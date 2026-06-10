"""Governance decisions for LLM-assisted memory curation.

LLMs may recommend actions, but this module persists decisions and applies a
small deterministic policy gate before any database mutation occurs.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from memorycore.models import as_json, now, row_to_dict
from memorycore.storage import audit as _audit
from memorycore.storage.db import managed_conn, read_conn
from memorycore.storage.mutation_executor import execute_batch, query_ledger, rollback_execution
from memorycore.storage.mutations import MutationContext, MutationRequest

PRECIOUS_TYPES = {"user_profile", "decision", "project_memory"}
HIGH_IMPORTANCE_THRESHOLD = 0.85
AUTO_CONFIDENCE_THRESHOLD = 0.90
REVIEW_CONFIDENCE_THRESHOLD = 0.55
POLICY_VERSION = "2026-06-09.1"
JUDGE_SCHEMA_VERSION = "1"
DECISION_VERSION = "1"
JUDGE_MODEL = "deterministic"
MUTATING_ACTIONS = {
    "archive_duplicate",
    "archive_and_merge_duplicate",
    "mark_contradicted",
    "archive",
    "promote",
    "downgrade",
    "split",
    "supersede",
}
DESTRUCTIVE_ACTIONS = {"archive_duplicate", "archive_and_merge_duplicate", "archive", "split", "supersede"}
MERGE_ACTIONS = {"archive_and_merge_duplicate"}
MANUAL_ONLY_ACTIONS = {"split"}
DELETE_ACTIONS = {"delete", "hard_delete"}


_CATEGORY_TO_DECISION_TYPE = {
    "semantic_duplicates": "semantic_duplicate",
    "contradictions": "contradiction",
    "importance_reassessments": "importance_reassessment",
    "split_candidates": "split_candidate",
}


def _clamp_confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return 0.0


def _llm_trace_from_finding(finding: dict[str, Any]) -> dict[str, Any]:
    return {
        "prompt": finding.get("llm_prompt", ""),
        "response": finding.get("llm_raw", ""),
        "thinking": finding.get("llm_thinking", ""),
        "rationale": finding.get("reason", ""),
    }


def _source_ids_for_finding(finding: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for key in ("id", "keep_id", "drop_id", "older_id", "newer_id"):
        value = finding.get(key)
        if value and value not in ids:
            ids.append(str(value))
    return ids


def _stable_candidate_hash(
    decision_type: str,
    recommended_action: str,
    source_ids: list[str],
    finding: dict[str, Any],
) -> str:
    payload = {
        "decision_type": decision_type,
        "recommended_action": recommended_action,
        "source_ids": sorted(str(x) for x in source_ids),
        "finding": finding,
        "policy_version": POLICY_VERSION,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


_SQL_PATTERN = re.compile(
    r"\b(SELECT|UPDATE|INSERT|DELETE|DROP|ALTER|CREATE|TRUNCATE|EXEC|EXECUTE)\b",
    re.IGNORECASE,
)
_TOOL_CALL_PATTERN = re.compile(r"\b\w+\s*\(.*\)", re.DOTALL)


def _contains_llm_instruction_injection(text: str) -> bool:
    """Return True if text looks like embedded SQL or a tool-call instruction."""
    if _SQL_PATTERN.search(text):
        return True
    if _TOOL_CALL_PATTERN.search(text) and any(
        kw in text.lower() for kw in ("execute", "call", "invoke", "run", "query")
    ):
        return True
    return False


def _fetch_memory_summaries(memory_ids: list[str]) -> list[dict[str, Any]]:
    if not memory_ids:
        return []
    placeholders = ",".join("?" for _ in memory_ids)
    with read_conn() as conn:
        rows = conn.execute(
            f"SELECT id, type, importance, feedback_score, scope, project_path, status FROM memories WHERE id IN ({placeholders})",
            tuple(memory_ids),
        ).fetchall()
    return [dict(row) for row in rows]


def policy_gate(
    action: str,
    confidence: float,
    risk_level: str = "medium",
    memories: list[dict[str, Any]] | None = None,
    scope: str = "global",
    project_path: str = "",
) -> dict[str, Any]:
    """Classify a governance recommendation as auto-approved, review, or rejected."""
    memories = memories or []
    reasons: list[str] = []
    normalized_risk = (risk_level or "medium").lower()

    if _contains_llm_instruction_injection(action):
        return {
            "review_status": "rejected",
            "policy_reason": "LLM action contains SQL or tool-call instruction",
            "policy_reasons": ["llm_instruction_injection_in_action"],
            "policy_version": POLICY_VERSION,
        }
    if action in DELETE_ACTIONS or "delete" in action:
        return {
            "review_status": "rejected",
            "policy_reason": "delete actions are never auto-governed",
            "policy_reasons": ["delete_action_not_allowed"],
            "policy_version": POLICY_VERSION,
        }
    if action not in MUTATING_ACTIONS and action != "keep":
        return {
            "review_status": "rejected",
            "policy_reason": f"unsupported action: {action}",
            "policy_reasons": ["unsupported_action"],
            "policy_version": POLICY_VERSION,
        }
    if confidence < REVIEW_CONFIDENCE_THRESHOLD:
        return {
            "review_status": "rejected",
            "policy_reason": "LLM confidence below review threshold",
            "policy_reasons": ["confidence_below_review_threshold"],
            "policy_version": POLICY_VERSION,
        }
    if normalized_risk == "high":
        reasons.append("high_risk_action")

    is_precious = any(m.get("type") in PRECIOUS_TYPES for m in memories)
    is_high_importance = any(float(m.get("importance") or 0.0) >= HIGH_IMPORTANCE_THRESHOLD for m in memories)
    has_positive_feedback = any(float(m.get("feedback_score") or 0.0) > 0 for m in memories)
    is_destructive = action in DESTRUCTIVE_ACTIONS or "delete" in action or "merge" in action

    if is_precious:
        reasons.append("precious_memory_type")
    if is_high_importance:
        reasons.append("high_importance_memory")
    if action in MERGE_ACTIONS:
        reasons.append("merge_requires_review")
    if action in MANUAL_ONLY_ACTIONS:
        reasons.append("split_requires_manual_action")
    if has_positive_feedback and is_destructive:
        reasons.append("positive_feedback_requires_review")
    if is_destructive and normalized_risk != "low":
        reasons.append("destructive_action_not_low_risk")
    if confidence < AUTO_CONFIDENCE_THRESHOLD:
        reasons.append("confidence_below_auto_threshold")

    if reasons:
        return {
            "review_status": "needs_review",
            "policy_reason": "; ".join(reasons),
            "policy_reasons": reasons,
            "policy_version": POLICY_VERSION,
        }
    return {
        "review_status": "auto_approved",
        "policy_reason": "low-risk high-confidence recommendation",
        "policy_reasons": [],
        "policy_version": POLICY_VERSION,
    }


def create_governance_decision(
    decision_type: str,
    recommended_action: str,
    source_ids: list[str],
    llm_confidence: float,
    risk_level: str = "medium",
    finding: dict[str, Any] | None = None,
    raw_response_ref: str = "",
    source_agent: str = "llm_curator",
    llm_trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    finding = finding or {}
    llm_trace = llm_trace or _llm_trace_from_finding(finding)
    confidence = _clamp_confidence(llm_confidence)
    source_ids = [str(x) for x in source_ids if x]
    memories = _fetch_memory_summaries(source_ids)
    gate = policy_gate(
        recommended_action,
        confidence,
        risk_level,
        memories=memories,
        scope=(memories[0].get("scope") if memories else "global"),
        project_path=(memories[0].get("project_path") if memories else ""),
    )
    candidate_hash = _stable_candidate_hash(decision_type, recommended_action, source_ids, finding)
    decision_id = str(uuid.uuid4())
    ts = now()
    with managed_conn() as conn:
        existing = conn.execute(
            """
            SELECT * FROM governance_decisions
            WHERE candidate_hash=?
              AND review_status IN ('needs_review', 'auto_approved', 'applied')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (candidate_hash,),
        ).fetchone()
        if existing is not None:
            return _decision_row_to_dict(existing)
        conn.execute(
            """
            INSERT INTO governance_decisions (
              id, decision_type, source_ids_json, recommended_action, llm_confidence,
              risk_level, review_status, policy_reason, finding_json, llm_trace_json, raw_response_ref,
              before_state_json, after_state_json, created_at, updated_at, applied_at, rolled_back_at, source_agent,
              candidate_hash, policy_reasons_json, policy_version, judge_model, judge_schema_version,
              decision_version, execution_id, applied_by, rolled_back_by, approval_kind
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                decision_id, decision_type, as_json(source_ids), recommended_action, confidence,
                risk_level or "medium", gate["review_status"], gate["policy_reason"],
                as_json(finding), as_json(llm_trace), raw_response_ref or "", "[]", "[]",
                ts, ts, None, None, source_agent or "llm_curator",
                candidate_hash, as_json(gate.get("policy_reasons", [])), gate.get("policy_version", POLICY_VERSION),
                JUDGE_MODEL, JUDGE_SCHEMA_VERSION, DECISION_VERSION, "", "", "", "",
            ),
        )
        row = conn.execute("SELECT * FROM governance_decisions WHERE id=?", (decision_id,)).fetchone()
    _audit.log_audit_event("governance_decision_create", memory_id=source_ids[0] if source_ids else None, agent=source_agent, detail={"decision_id": decision_id, "review_status": gate["review_status"], "action": recommended_action, "policy_reasons": gate.get("policy_reasons", []), "policy_version": gate.get("policy_version", POLICY_VERSION)})
    return _decision_row_to_dict(row)


def _decision_row_to_dict(row: Any) -> dict[str, Any]:
    data = dict(row)
    data["source_ids"] = json.loads(data.pop("source_ids_json") or "[]")
    data["finding"] = json.loads(data.pop("finding_json") or "{}")
    data["llm_trace"] = json.loads(data.pop("llm_trace_json", "{}") or "{}")
    data["before_state"] = json.loads(data.pop("before_state_json", "[]") or "[]")
    data["after_state"] = json.loads(data.pop("after_state_json", "[]") or "[]")
    data["policy_reasons"] = json.loads(data.pop("policy_reasons_json", "[]") or "[]")
    return data


def list_governance_decisions(review_status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    cap = max(1, min(int(limit), 500))
    where = ""
    params: list[Any] = []
    if review_status:
        where = "WHERE review_status=?"
        params.append(review_status)
    params.append(cap)
    with read_conn() as conn:
        rows = conn.execute(f"SELECT * FROM governance_decisions {where} ORDER BY created_at DESC LIMIT ?", tuple(params)).fetchall()
    return [_decision_row_to_dict(row) for row in rows]


def convert_llm_findings_to_decisions(report: dict[str, Any], auto_apply: bool = False) -> dict[str, Any]:
    decisions: list[dict[str, Any]] = []
    applied: list[dict[str, Any]] = []
    for category, decision_type in _CATEGORY_TO_DECISION_TYPE.items():
        for finding in report.get(category, []) or []:
            action = str(finding.get("action") or "keep")
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
            )
            decisions.append(decision)
            if auto_apply and decision["review_status"] == "auto_approved":
                applied.append(apply_governance_decision(decision["id"], source_agent="llm_curator"))
    return {"decisions_created": len(decisions), "decisions": decisions, "auto_applied": applied}


def _risk_for_action(action: str) -> str:
    if action in {"promote", "downgrade"}:
        return "low"
    if action in {"archive_duplicate", "supersede"}:
        return "low"
    return "high" if action in {"archive_and_merge_duplicate", "split", "mark_contradicted"} else "medium"


def reject_governance_decision(decision_id: str, source_agent: str = "agent", reason: str = "") -> dict[str, Any]:
    ts = now()
    with managed_conn() as conn:
        conn.execute("UPDATE governance_decisions SET review_status='rejected', updated_at=? WHERE id=?", (ts, decision_id))
        row = conn.execute("SELECT * FROM governance_decisions WHERE id=?", (decision_id,)).fetchone()
    if row is None:
        raise ValueError(f"governance decision not found: {decision_id}")
    decision = _decision_row_to_dict(row)
    _audit.log_audit_event("governance_decision_reject", memory_id=(decision["source_ids"][0] if decision["source_ids"] else None), agent=source_agent, detail={"decision_id": decision_id, "reason": reason})
    return decision


def apply_governance_decision(decision_id: str, source_agent: str = "agent") -> dict[str, Any]:
    with read_conn() as conn:
        row = conn.execute("SELECT * FROM governance_decisions WHERE id=?", (decision_id,)).fetchone()
    if row is None:
        raise ValueError(f"governance decision not found: {decision_id}")
    decision = _decision_row_to_dict(row)
    if decision["review_status"] not in {"auto_approved", "needs_review"}:
        raise ValueError(f"decision cannot be applied from status {decision['review_status']!r}")
    if decision.get("applied_at"):
        return {"decision": decision, "applied": {"already_applied": True}}

    approval_kind = "auto_policy" if decision["review_status"] == "auto_approved" else "human_accept"
    context = MutationContext(
        actor=source_agent or "agent",
        origin="governance",
        approval_kind=approval_kind,
        decision_id=decision_id,
        correlation_id=decision_id,
    )
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


def _execution_key(decision: dict[str, Any]) -> str:
    return f"governance:{decision['id']}:{decision.get('candidate_hash') or decision.get('updated_at') or ''}"


def _mutation_requests_for_decision(decision: dict[str, Any]) -> list[MutationRequest]:
    finding = decision.get("finding") or {}
    action = decision.get("recommended_action")
    confidence = float(decision.get("llm_confidence") or 1.0)
    risk = str(decision.get("risk_level") or "medium")
    decision_id = str(decision.get("id"))

    if decision["decision_type"] == "importance_reassessment" and action in {"promote", "downgrade", "archive"}:
        mem_id = str(finding.get("id") or "")
        if action == "archive":
            return [_memory_request("memory_archive", mem_id, {"status": "archived"}, risk, confidence, decision_id)]
        payload: dict[str, Any] = {"importance": finding.get("new_importance")}
        if action == "promote":
            payload["status"] = "active"
        return [_memory_request("memory_importance_update", mem_id, payload, risk, confidence, decision_id)]
    if decision["decision_type"] == "semantic_duplicate" and action in {"archive_duplicate", "archive_and_merge_duplicate"}:
        mem_id = str(finding.get("drop_id") or "")
        return [_memory_request("memory_archive", mem_id, {"status": "archived"}, risk, confidence, decision_id)]
    if decision["decision_type"] == "contradiction" and action == "mark_contradicted":
        mem_id = str(finding.get("older_id") or "")
        return [_memory_request("memory_status_update", mem_id, {"status": "contradicted"}, risk, confidence, decision_id)]
    if decision["decision_type"] == "supersession" and action == "supersede":
        return _supersede_requests(decision, finding, confidence, risk)
    if decision["decision_type"] == "split_candidate" and action == "split":
        return _split_requests(decision, finding, confidence, risk)
    raise ValueError(f"governance apply does not support action {action!r}")


def _memory_request(action_type: str, memory_id: str, payload: dict[str, Any], risk: str, confidence: float, decision_id: str) -> MutationRequest:
    if not memory_id:
        raise ValueError("memory id is required")
    return MutationRequest(
        action_type=action_type,
        target_type="memory",
        target_id=memory_id,
        payload=payload,
        risk_level=risk,
        confidence=confidence,
        idempotency_key=f"{decision_id}:{action_type}:{memory_id}",
    )


def _supersede_requests(decision: dict[str, Any], finding: dict[str, Any], confidence: float, risk: str) -> list[MutationRequest]:
    old_id = str(finding.get("old_id") or finding.get("older_id") or "")
    new_id = str(finding.get("new_id") or finding.get("newer_id") or "")
    if not old_id or not new_id or old_id == new_id:
        raise ValueError("supersession finding requires distinct old/new memory ids")
    with read_conn() as conn:
        old_row = conn.execute("SELECT * FROM memories WHERE id=?", (old_id,)).fetchone()
        new_row = conn.execute("SELECT * FROM memories WHERE id=?", (new_id,)).fetchone()
    if old_row is None:
        raise ValueError(f"old memory not found: {old_id}")
    if new_row is None:
        raise ValueError(f"new memory not found: {new_id}")
    old_record = row_to_dict(old_row)
    new_record = row_to_dict(new_row)
    old_root = old_record.get("fact_lineage_root") or old_id
    new_root = new_record.get("fact_lineage_root") or new_id
    if new_root != new_id and new_root != old_root:
        raise ValueError("lineage merge requires human review")
    root_id = old_root
    decision_id = str(decision.get("id"))
    return [
        _memory_request(
            "memory_supersede",
            old_id,
            {"status": "superseded", "superseded_by": new_id, "fact_lineage_root": root_id},
            risk,
            confidence,
            decision_id,
        ),
        _memory_request(
            "memory_update",
            new_id,
            {"fact_lineage_root": root_id},
            "low",
            confidence,
            decision_id,
        ),
        MutationRequest(
            action_type="memory_link_insert",
            target_type="memory_link",
            payload={
                "source_id": new_id,
                "target_id": old_id,
                "relation_type": "supersedes",
                "weight": 1.0,
                "note": "auto-supersession governance decision",
            },
            risk_level="low",
            confidence=confidence,
            idempotency_key=f"{decision_id}:supersedes-link:{new_id}:{old_id}",
        ),
    ]


def _split_requests(decision: dict[str, Any], finding: dict[str, Any], confidence: float, risk: str) -> list[MutationRequest]:
    orig_id = str(finding.get("id") or "")
    sub_memories = finding.get("sub_memories") or []
    if not orig_id or not sub_memories:
        raise ValueError("split finding requires 'id' and 'sub_memories'")
    with read_conn() as conn:
        orig_row = conn.execute("SELECT * FROM memories WHERE id=?", (orig_id,)).fetchone()
    if orig_row is None:
        raise ValueError(f"split source memory {orig_id!r} not found")
    orig = row_to_dict(orig_row)
    decision_id = str(decision.get("id"))
    requests = [_memory_request("memory_archive", orig_id, {"status": "archived"}, risk, confidence, decision_id)]
    for index, sub in enumerate(sub_memories):
        sub_title = str(sub.get("title") or "")[:120].strip()
        sub_content = str(sub.get("content") or "").strip()
        if not sub_title or not sub_content:
            continue
        normalized = " ".join(sub_content.lower().split())
        fact_hash = hashlib.sha256(f"{orig_id}:{normalized}".encode()).hexdigest()[:16]
        child_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{decision_id}:{orig_id}:{fact_hash}"))
        child_payload = {
            "id": child_id,
            "type": orig.get("type", "episodic_memory"),
            "title": sub_title,
            "content": sub_content,
            "scope": orig.get("scope") or "global",
            "project_path": orig.get("project_path") or "",
            "importance": max(0.0, min(1.0, float(sub.get("importance") or orig.get("importance") or 0.5))),
            "confidence": float(orig.get("confidence") or 0.7),
            "status": "active",
            "source": "governance_split",
            "metadata": {"parent_id": orig_id, "fact_hash": fact_hash},
        }
        requests.append(MutationRequest(
            action_type="memory_insert",
            target_type="memory",
            target_id=child_id,
            payload=child_payload,
            risk_level="low",
            confidence=confidence,
            idempotency_key=f"{decision_id}:split-child:{index}:{child_id}",
        ))
        for rel_index, (source_id, target_id, relation_type, note) in enumerate((
            (child_id, orig_id, "part_of", "governance split child fact"),
            (orig_id, child_id, "supports", "governance split generated child"),
        )):
            requests.append(MutationRequest(
                action_type="memory_link_insert",
                target_type="memory_link",
                payload={
                    "source_id": source_id,
                    "target_id": target_id,
                    "relation_type": relation_type,
                    "weight": 1.0,
                    "note": note,
                },
                risk_level="low",
                confidence=confidence,
                idempotency_key=f"{decision_id}:split-link:{index}:{rel_index}:{child_id}",
            ))
    return requests


def _snapshots_for_execution(execution_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = query_ledger(correlation_id=execution_id, limit=500)
    before = [json.loads(row["before_json"]) for row in rows if row.get("before_json") and row.get("entity_type") == "memory"]
    after = [json.loads(row["after_json"]) for row in rows if row.get("after_json") and row.get("entity_type") == "memory"]
    return before, after


def _applied_payload(decision: dict[str, Any], execution: dict[str, Any]) -> dict[str, Any]:
    if decision.get("decision_type") == "split_candidate":
        child_ids = [
            result["entity_id"]
            for result in execution.get("results", [])
            if result.get("mutation_type") == "memory_insert" and result.get("entity_id")
        ]
        return {"original_id": (decision.get("finding") or {}).get("id"), "children_created": len(child_ids), "child_ids": child_ids}
    return {"mutations_applied": len(execution.get("results", [])), "execution_id": execution.get("execution_id")}


def get_governance_metrics() -> dict[str, Any]:
    """Compute operational governance health metrics.

    Returns:
        Dict with rollback_rate, revival_rate, review_queue stats,
        rejection_rate_by_type, and degraded_warning flag.
    """
    from memorycore.models import load_config

    with read_conn() as conn:
        rows = conn.execute(
            "SELECT review_status, decision_type, created_at FROM governance_decisions"
        ).fetchall()

    counts: dict[str, int] = {}
    type_total: dict[str, int] = {}
    type_rejected: dict[str, int] = {}
    review_ages_hours: list[float] = []

    now_dt = datetime.now(timezone.utc)

    for row in rows:
        status = row["review_status"]
        dtype = row["decision_type"]
        counts[status] = counts.get(status, 0) + 1
        type_total[dtype] = type_total.get(dtype, 0) + 1
        if status == "rejected":
            type_rejected[dtype] = type_rejected.get(dtype, 0) + 1
        if status == "needs_review" and row["created_at"]:
            try:
                created = datetime.fromisoformat(row["created_at"].rstrip("Z"))
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                age_hours = (now_dt - created).total_seconds() / 3600.0
                review_ages_hours.append(age_hours)
            except ValueError:
                pass

    applied = counts.get("applied", 0)
    rolled_back = counts.get("rolled_back", 0)
    needs_review = counts.get("needs_review", 0)
    rejected = counts.get("rejected", 0)
    total_decided = applied + rolled_back

    rollback_rate = rolled_back / total_decided if total_decided > 0 else 0.0

    # Revival rate: auto-supersessions that were rolled back
    with read_conn() as conn:
        supersession_applied = conn.execute(
            "SELECT COUNT(*) FROM governance_decisions WHERE decision_type='supersession' AND review_status IN ('applied', 'rolled_back')"
        ).fetchone()[0]
        supersession_rolled_back = conn.execute(
            "SELECT COUNT(*) FROM governance_decisions WHERE decision_type='supersession' AND review_status='rolled_back'"
        ).fetchone()[0]

    revival_rate = (
        supersession_rolled_back / supersession_applied if supersession_applied > 0 else 0.0
    )

    review_queue_age_hours = (
        sum(review_ages_hours) / len(review_ages_hours) if review_ages_hours else 0.0
    )

    rejection_rate_by_type = {
        dtype: round(type_rejected.get(dtype, 0) / total, 3)
        for dtype, total in type_total.items()
        if total > 0
    }

    cfg = load_config()
    temporal_cfg = cfg.get("temporal") or {}
    auto_supersede_enabled = bool(temporal_cfg.get("auto_supersede_enabled", False))

    degraded_warning = (
        revival_rate > 0.05
        or rollback_rate > 0.10
        or (auto_supersede_enabled is False and needs_review > 20)
    )

    return {
        "applied_count": applied,
        "rolled_back_count": rolled_back,
        "needs_review_count": needs_review,
        "rejected_count": rejected,
        "rollback_rate": round(rollback_rate, 4),
        "revival_rate": round(revival_rate, 4),
        "review_queue_age_hours": round(review_queue_age_hours, 2),
        "rejection_rate_by_type": rejection_rate_by_type,
        "auto_supersede_enabled": auto_supersede_enabled,
        "degraded_warning": degraded_warning,
        "policy_version": POLICY_VERSION,
    }
