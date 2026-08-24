"""Governance decisions for LLM-assisted memory curation.

LLMs may recommend actions, but this module persists decisions and applies a
small deterministic policy gate before any database mutation occurs.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from memorycore.models import as_json, now, row_to_dict
from memorycore.storage import audit as _audit
from memorycore.storage.db import managed_conn, read_conn
from memorycore.storage.mutation_executor import execute_batch, query_ledger, rollback_execution
from memorycore.storage.mutations import MutationContext, MutationRequest

logger = logging.getLogger(__name__)

from memorycore.storage.governance import (
    ACTIONABLE_REVIEW_STATUSES,
    _CATEGORY_TO_DECISION_TYPE,
    _fetch_memory_summaries,
    _source_ids_for_finding,
    _stable_candidate_hash,
    create_governance_decision,
    policy_gate,
)
from memorycore.storage.governance_mutations import (
    _applied_payload,
    _execution_key,
    _mutation_requests_for_decision,
    _snapshots_for_execution,
)

def _decision_row_to_dict(row: Any) -> dict[str, Any]:
    data = dict(row)
    data["source_ids"] = json.loads(data.pop("source_ids_json") or "[]")
    data["finding"] = json.loads(data.pop("finding_json") or "{}")
    data["llm_trace"] = json.loads(data.pop("llm_trace_json", "{}") or "{}")
    data["before_state"] = json.loads(data.pop("before_state_json", "[]") or "[]")
    data["after_state"] = json.loads(data.pop("after_state_json", "[]") or "[]")
    data["policy_reasons"] = json.loads(data.pop("policy_reasons_json", "[]") or "[]")
    return data


def list_governance_decisions(review_status: str | None = None, decision_type: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    cap = max(1, int(limit)) if limit is not None else None
    conditions: list[str] = []
    params: list[Any] = []
    if review_status == "actionable":
        conditions.append("review_status IN ('needs_review', 'auto_approved') AND recommended_action != 'keep'")
    elif review_status == "auto_approved":
        conditions.append("review_status = 'applied' AND approval_kind = 'auto'")
    elif review_status and review_status != "all":
        conditions.append("review_status=?")
        params.append(review_status)
    if decision_type and decision_type.strip():
        conditions.append("decision_type=?")
        params.append(decision_type.strip())
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    order_by = """
        ORDER BY
          CASE risk_level WHEN 'high' THEN 0 WHEN 'medium' THEN 1 WHEN 'low' THEN 2 ELSE 1 END,
          CASE recommended_action
            WHEN 'mark_contradicted' THEN 0
            WHEN 'archive_and_merge_duplicate' THEN 1
            WHEN 'supersede' THEN 2
            WHEN 'archive_duplicate' THEN 3
            WHEN 'archive' THEN 4
            WHEN 'split' THEN 5
            WHEN 'downgrade' THEN 6
            WHEN 'promote' THEN 7
            ELSE 8
          END,
          llm_confidence DESC,
          created_at DESC
    """
    with read_conn() as conn:
        if cap is not None:
            params.append(cap)
            rows = conn.execute(f"SELECT * FROM governance_decisions {where} {order_by} LIMIT ?", tuple(params)).fetchall()
        else:
            rows = conn.execute(f"SELECT * FROM governance_decisions {where} {order_by}", tuple(params)).fetchall()
    decisions = [_decision_row_to_dict(row) for row in rows]
    all_ids: list[str] = []
    for d in decisions:
        if not d.get("before_state"):
            all_ids.extend(d.get("source_ids") or [])
    if all_ids:
        summaries_by_id = {s["id"]: s for s in _fetch_memory_summaries(list(set(all_ids)))}
        for d in decisions:
            if not d.get("before_state"):
                d["before_state"] = [summaries_by_id[sid] for sid in (d.get("source_ids") or []) if sid in summaries_by_id]
    return decisions


def get_governance_decision(decision_id: str) -> dict[str, Any] | None:
    with read_conn() as conn:
        row = conn.execute("SELECT * FROM governance_decisions WHERE id=?", (decision_id,)).fetchone()
    if row is None:
        return None
    decision = _decision_row_to_dict(row)
    if not decision.get("before_state"):
        source_ids = decision.get("source_ids") or []
        summaries = _fetch_memory_summaries(source_ids) if source_ids else []
        decision["before_state"] = summaries
    return decision


def convert_llm_findings_to_decisions(
    report: dict[str, Any],
    auto_apply: bool = False,
    curator_job_id: str = "",
    curator_batch_id: str = "",
) -> dict[str, Any]:
    decisions: list[dict[str, Any]] = []
    applied: list[dict[str, Any]] = []
    skipped_keep = 0
    for category, decision_type in _CATEGORY_TO_DECISION_TYPE.items():
        for finding in report.get(category, []) or []:
            action = str(finding.get("action") or "keep")
            if action == "keep":
                skipped_keep += 1
                continue
            confidence = finding.get("confidence", finding.get("score", 0.7))
            risk = _risk_for_action(action)
            decision = create_governance_decision(
                decision_type=decision_type,
                recommended_action=action,
                source_ids=_source_ids_for_finding(finding),
                llm_confidence=confidence,
                risk_level=risk,
                finding=finding,
                raw_response_ref="llm_raw" if finding.get("llm_raw") else "",
                curator_job_id=curator_job_id,
                curator_batch_id=curator_batch_id,
            )
            decisions.append(decision)
            if decision["review_status"] == "applied":
                applied.append(decision)
            elif auto_apply and decision["review_status"] == "auto_approved":
                try:
                    applied.append(apply_governance_decision(decision["id"], source_agent="llm_curator"))
                except Exception as exc:
                    logger.warning("convert_llm_findings: failed to apply decision %s: %s", decision["id"], exc)
    if not decisions and skipped_keep > 0:
        logger.warning(
            "[governance] All %d LLM findings were 'keep' — no governance decisions created. "
            "LLM may be too conservative or prompts need adjustment.", skipped_keep,
        )
    return {"decisions_created": len(decisions), "decisions": decisions, "auto_applied": applied, "skipped_keep": skipped_keep}


def _risk_for_action(action: str) -> str:
    if action in {"promote", "downgrade"}:
        return "low"
    if action in {"archive_duplicate", "supersede"}:
        return "low"
    return "high" if action in {"archive_and_merge_duplicate", "split", "mark_contradicted"} else "medium"


def reject_governance_decision(decision_id: str, source_agent: str = "agent", reason: str = "") -> dict[str, Any]:
    ts = now()
    with managed_conn() as conn:
        row = conn.execute("SELECT * FROM governance_decisions WHERE id=?", (decision_id,)).fetchone()
        if row is None:
            raise ValueError(f"governance decision not found: {decision_id}")
        if row["review_status"] not in ACTIONABLE_REVIEW_STATUSES:
            raise ValueError(f"decision cannot be rejected from status {row['review_status']!r}")
        conn.execute("UPDATE governance_decisions SET review_status='rejected', updated_at=? WHERE id=?", (ts, decision_id))
        row = conn.execute("SELECT * FROM governance_decisions WHERE id=?", (decision_id,)).fetchone()
    decision = _decision_row_to_dict(row)
    _audit.log_audit_event("governance_decision_reject", memory_id=(decision["source_ids"][0] if decision["source_ids"] else None), agent=source_agent, detail={"decision_id": decision_id, "reason": reason})
    return decision


def apply_governance_decision(decision_id: str, source_agent: str = "agent") -> dict[str, Any]:
    with read_conn() as conn:
        row = conn.execute("SELECT * FROM governance_decisions WHERE id=?", (decision_id,)).fetchone()
    if row is None:
        raise ValueError(f"governance decision not found: {decision_id}")
    decision = _decision_row_to_dict(row)
    if decision["review_status"] == "applied" or decision.get("applied_at"):
        return {"decision": decision, "applied": {"already_applied": True}}
    if decision["review_status"] not in {"auto_approved", "needs_review"}:
        raise ValueError(f"decision cannot be applied from status {decision['review_status']!r}")

    approval_kind = "auto_policy" if decision["review_status"] == "auto_approved" else "human_accept"
    context = MutationContext(
        actor=source_agent or "agent",
        origin="governance",
        approval_kind=approval_kind,
        decision_id=decision_id,
        correlation_id=decision_id,
    )

    if decision.get("recommended_action") == "keep":
        ts = now()
        legacy_approval_kind = "auto" if decision["review_status"] == "auto_approved" else "human_accept"
        with managed_conn() as conn:
            conn.execute(
                "UPDATE governance_decisions SET review_status='applied', applied_at=?, updated_at=?, applied_by=?, approval_kind=? WHERE id=?",
                (ts, ts, source_agent or "agent", legacy_approval_kind, decision_id),
            )
            updated = conn.execute("SELECT * FROM governance_decisions WHERE id=?", (decision_id,)).fetchone()
        updated_decision = _decision_row_to_dict(updated)
        _audit.log_audit_event("governance_decision_apply", memory_id=(decision["source_ids"][0] if decision["source_ids"] else None), agent=source_agent, detail={"decision_id": decision_id, "action": "keep", "approval_kind": legacy_approval_kind})
        return {"decision": updated_decision, "applied": {"action": "keep"}, "execution": None}

    requests = _mutation_requests_for_decision(decision)
    execution_id = str(uuid.uuid4())
    execution = execute_batch(
        requests,
        context,
        execution_id=execution_id,
        idempotency_key=_execution_key(decision),
    )
    if execution["status"] != "applied":
        return {"decision": decision, "applied": {"blocked": True, "status": execution["status"]}, "execution": execution}
    before, after = _snapshots_for_execution(execution["execution_id"])
    applied = _applied_payload(decision, execution)
    ts = now()
    legacy_approval_kind = "auto" if decision["review_status"] == "auto_approved" else "human_accept"
    rollback = {"execution_id": execution["execution_id"], "before": before, "after": after}
    with managed_conn() as conn:
        conn.execute(
            """
            UPDATE governance_decisions
            SET review_status='applied', applied_at=?, updated_at=?, rollback_json=?,
                before_state_json=?, after_state_json=?, execution_id=?, applied_by=?, approval_kind=?
            WHERE id=?
            """,
            (ts, ts, as_json(rollback), as_json(before), as_json(after), execution["execution_id"], source_agent or "agent", legacy_approval_kind, decision_id),
        )
        updated = conn.execute("SELECT * FROM governance_decisions WHERE id=?", (decision_id,)).fetchone()
    updated_decision = _decision_row_to_dict(updated)
    _audit.log_audit_event("governance_decision_apply", memory_id=(decision["source_ids"][0] if decision["source_ids"] else None), agent=source_agent, detail={"decision_id": decision_id, "execution_id": execution["execution_id"], "applied": applied, "before_state": before, "after_state": after, "approval_kind": legacy_approval_kind})
    return {"decision": updated_decision, "applied": applied, "execution": execution}


def apply_governance_decisions_batch(decision_ids: list[str], source_agent: str = "agent") -> dict[str, Any]:
    """Apply a batch of actionable governance decisions.

    Decisions in invalid review states still fail the whole batch before any mutation.
    Decisions blocked by the mutation policy are skipped and reported, while the
    remaining allowed decisions are applied in a single transaction.
    """
    if not decision_ids:
        return {"applied_count": 0, "decisions": [], "skipped_count": 0, "skipped": [], "already_applied": []}

    # Fetch decisions first
    with read_conn() as conn:
        placeholders = ",".join("?" for _ in decision_ids)
        rows = conn.execute(
            f"SELECT * FROM governance_decisions WHERE id IN ({placeholders})",
            tuple(decision_ids)
        ).fetchall()

    decisions = [_decision_row_to_dict(row) for row in rows]
    decisions_by_id = {d["id"]: d for d in decisions}

    missing_ids = set(decision_ids) - set(decisions_by_id.keys())
    if missing_ids:
        raise ValueError(f"governance decisions not found: {list(missing_ids)}")

    valid_decisions = []
    already_applied = []
    for d_id in decision_ids:
        d = decisions_by_id[d_id]
        if d["review_status"] == "applied" or d.get("applied_at"):
            already_applied.append(d)
        elif d["review_status"] not in {"auto_approved", "needs_review"}:
            raise ValueError(f"decision {d_id} cannot be applied from status {d['review_status']!r}")
        else:
            valid_decisions.append(d)

    skipped_decisions: list[dict] = []
    if not valid_decisions:
        return {
            "applied_count": 0,
            "decisions": [],
            "skipped_count": len(skipped_decisions),
            "skipped": skipped_decisions,
            "already_applied": [d["id"] for d in already_applied]
        }

    # Gather mutation requests and evaluate policies for all decisions beforehand
    from memorycore.storage.mutation_executor import evaluate_mutation_policy

    all_requests_with_decisions = []
    for d in valid_decisions:
        requests = _mutation_requests_for_decision(d)
        approval_kind = "human_accept"
        context = MutationContext(
            actor=source_agent or "agent",
            origin="governance",
            approval_kind=approval_kind,
            decision_id=d["id"],
            correlation_id=d["id"],
        )
        policy_results = [evaluate_mutation_policy(req, context) for req in requests]

        # Skip decisions blocked by policy (confidence_below_auto_threshold, etc.)
        # rather than failing the entire batch — collect them for reporting.
        blocking = [r for r in policy_results if r["policy_decision"] in {"queued", "rejected"}]
        if blocking:
            skipped_decisions.append({
                "id": d["id"],
                "reason": blocking[0]["policy_reason"],
                "decision_type": d.get("decision_type", ""),
            })
            continue
        all_requests_with_decisions.append((d, requests, context, policy_results))

    results = []
    applied_decisions = []
    run_id = f"batch-run-{uuid.uuid4()}"
    ts = now()

    # No decision survived policy evaluation — do not create an empty run row.
    if not all_requests_with_decisions:
        return {
            "applied_count": 0,
            "decisions": [],
            "skipped_count": len(skipped_decisions),
            "skipped": skipped_decisions,
            "already_applied": [d["id"] for d in already_applied],
            "skipped_run": True,
        }

    # Import mutation executor helper functions
    from memorycore.storage.mutation_executor import _apply_request, _sync_results

    # Run everything in a single database transaction
    with managed_conn() as conn:
        # Create a single run record for this batch execution
        conn.execute(
            """
            INSERT INTO governance_runs (
              id, source, mode, policy_version, status, started_at, created_by, metadata_json
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                "governance",
                "batch_apply",
                "2026-06-10.1",
                "running",
                ts,
                source_agent or "agent",
                as_json({"decision_ids": [d["id"] for d in valid_decisions]}),
            ),
        )

        for d, requests, context, policy_results in all_requests_with_decisions:
            execution_id = str(uuid.uuid4())
            highest_risk = "high" if any(r.risk_level == "high" for r in requests) else "medium" if any(r.risk_level == "medium" for r in requests) else "low"
            resolved_key = f"{d['id']}:{context.approval_kind}:{execution_id}"

            # Create a execution record for this decision
            conn.execute(
                """
                INSERT INTO governance_executions (
                  id, run_id, decision_id, approval_kind, risk_level, status, idempotency_key,
                  policy_snapshot_json, started_at, created_by, metadata_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    execution_id,
                    run_id,
                    d["id"],
                    context.approval_kind,
                    highest_risk,
                    "planned",
                    resolved_key,
                    as_json({"results": policy_results}),
                    ts,
                    context.actor,
                    as_json(context.metadata),
                ),
            )

            # Update statuses
            conn.execute("UPDATE governance_executions SET status='policy_evaluated' WHERE id=?", (execution_id,))
            conn.execute("UPDATE governance_executions SET status='applying' WHERE id=?", (execution_id,))

            # Execute mutations
            decision_results = []
            for index, request in enumerate(requests, start=1):
                res = _apply_request(conn, execution_id, index, request, context, policy_results[index - 1])
                decision_results.append(res)
                results.append(res)

            conn.execute("UPDATE governance_executions SET status='applied', finished_at=? WHERE id=?", (ts, execution_id))

            # Retrieve snapshots for rollback log directly from database using the connection (in-transaction)
            log_rows = conn.execute(
                """
                SELECT before_json, after_json, entity_type FROM governance_mutation_log
                WHERE execution_id=? AND status='applied'
                """,
                (execution_id,)
            ).fetchall()
            before = [json.loads(row["before_json"]) for row in log_rows if row["before_json"] and row["entity_type"] == "memory"]
            after = [json.loads(row["after_json"]) for row in log_rows if row["after_json"] and row["entity_type"] == "memory"]

            applied_payload = _applied_payload(d, {"results": decision_results, "execution_id": execution_id})
            rollback_payload = {"execution_id": execution_id, "before": before, "after": after}
            legacy_approval_kind = "auto" if d["review_status"] == "auto_approved" else "human_accept"

            # Update decision status
            conn.execute(
                """
                UPDATE governance_decisions
                SET review_status='applied', applied_at=?, updated_at=?, rollback_json=?,
                    before_state_json=?, after_state_json=?, execution_id=?, applied_by=?, approval_kind=?
                WHERE id=?
                """,
                (
                    ts, ts, as_json(rollback_payload), as_json(before), as_json(after),
                    execution_id, source_agent or "agent", legacy_approval_kind, d["id"]
                ),
            )

            # Retrieve updated row for the response
            updated_row = conn.execute("SELECT * FROM governance_decisions WHERE id=?", (d["id"],)).fetchone()
            applied_decisions.append(_decision_row_to_dict(updated_row))

        # Close the batch run
        conn.execute("UPDATE governance_runs SET status='finished', finished_at=? WHERE id=?", (ts, run_id))

    # Perform vector/FTS sync outside of transaction
    _sync_results(results)

    # Log audit events (async background threads or standard log)
    for d, _, _, _ in all_requests_with_decisions:
        updated_d = next(ud for ud in applied_decisions if ud["id"] == d["id"])
        legacy_approval_kind = "auto" if d["review_status"] == "auto_approved" else "human_accept"
        _audit.log_audit_event(
            "governance_decision_apply",
            memory_id=(d["source_ids"][0] if d["source_ids"] else None),
            agent=source_agent,
            detail={
                "decision_id": d["id"],
                "execution_id": updated_d["execution_id"],
                "applied": _applied_payload(d, {"results": [r for r in results if r["entity_id"] in d["source_ids"]], "execution_id": updated_d["execution_id"]}),
                "before_state": updated_d["before_state"],
                "after_state": updated_d["after_state"],
                "approval_kind": legacy_approval_kind
            }
        )

    return {
        "applied_count": len(applied_decisions),
        "decisions": applied_decisions,
        "already_applied": [d["id"] for d in already_applied],
        "skipped_count": len(skipped_decisions),
        "skipped": skipped_decisions,
        "run_id": run_id
    }


def rollback_governance_decision(decision_id: str, source_agent: str = "agent") -> dict[str, Any]:
    with read_conn() as conn:
        row = conn.execute("SELECT * FROM governance_decisions WHERE id=?", (decision_id,)).fetchone()
    if row is None:
        raise ValueError(f"governance decision not found: {decision_id}")
    decision = _decision_row_to_dict(row)
    if decision.get("rolled_back_at"):
        return {"decision": decision, "already_rolled_back": True, "restored": []}
    execution_id = decision.get("execution_id") or (json.loads(decision.get("rollback_json") or "{}").get("execution_id"))
    if not execution_id:
        raise ValueError("decision has no execution id for rollback")
    rollback = rollback_execution(
        execution_id,
        MutationContext(
            actor=source_agent or "agent",
            origin="governance",
            approval_kind="rollback",
            decision_id=decision_id,
            correlation_id=decision_id,
        ),
    )
    ts = now()
    with managed_conn() as conn:
        conn.execute(
            "UPDATE governance_decisions SET review_status='rolled_back', rolled_back_at=?, updated_at=?, rolled_back_by=? WHERE id=?",
            (ts, ts, source_agent or "agent", decision_id),
        )
        updated = conn.execute("SELECT * FROM governance_decisions WHERE id=?", (decision_id,)).fetchone()
    restored_ids = [item.get("entity_id") for item in rollback.get("restored", []) if item.get("entity_id")]
    _audit.log_audit_event("governance_decision_rollback", memory_id=(decision["source_ids"][0] if decision["source_ids"] else None), agent=source_agent, detail={"decision_id": decision_id, "execution_id": execution_id, "restored": restored_ids})
    return {"decision": _decision_row_to_dict(updated), "restored": rollback.get("restored", []), "already_rolled_back": False}
