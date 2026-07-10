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

PRECIOUS_TYPES = {"user_profile", "decision", "project_memory"}
HIGH_IMPORTANCE_THRESHOLD = 0.85
AUTO_CONFIDENCE_THRESHOLD = 0.65
REVIEW_CONFIDENCE_THRESHOLD = 0.45
POLICY_VERSION = "2026-07-07"
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
MERGE_ACTIONS: set[str] = set()
MANUAL_ONLY_ACTIONS = {"split"}
DELETE_ACTIONS = {"delete", "hard_delete"}
ACTIONABLE_REVIEW_STATUSES = {"needs_review", "auto_approved"}


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


def filter_applied_or_rejected_findings(report: dict[str, Any]) -> dict[str, Any]:
    """Filter out findings that have already been applied, rejected, or rolled back."""
    if not report:
        return report

    with read_conn() as conn:
        rows = conn.execute(
            "SELECT candidate_hash FROM governance_decisions WHERE review_status IN ('applied', 'rejected', 'rolled_back')"
        ).fetchall()
    inactive_hashes = {row["candidate_hash"] for row in rows if row["candidate_hash"]}

    filtered_report = dict(report)
    summary = dict(report.get("summary", {}))
    filtered_report["summary"] = summary

    for category, decision_type in _CATEGORY_TO_DECISION_TYPE.items():
        if category not in report:
            continue
        filtered_findings = []
        for finding in report[category] or []:
            action = str(finding.get("action") or "keep")
            if action == "keep":
                continue
            source_ids = _source_ids_for_finding(finding)
            h = _stable_candidate_hash(decision_type, action, source_ids, finding)
            if h not in inactive_hashes:
                filtered_findings.append(finding)
        filtered_report[category] = filtered_findings
        if category in summary:
            summary[category] = len(filtered_findings)

    return filtered_report

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
            f"SELECT id, title, content, type, importance, feedback_score, scope, project_path, status, created_at, updated_at FROM memories WHERE id IN ({placeholders})",
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
    """Classify a governance recommendation as auto-approved or rejected.

    Policy v2026-07-07: no human review — all decisions are either
    auto-approved (confidence >= 0.75) or rejected.
      - < 0.45: hard rejected
      - 0.45..0.75: rejected (confidence too low)
      - >= 0.75: auto-approved
      - split: always rejected (requires manual action)
      - delete: always rejected
    """
    memories = memories or []

    # --- Hard rejections ---
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
    if action in MANUAL_ONLY_ACTIONS:
        return {
            "review_status": "rejected",
            "policy_reason": "split requires manual action",
            "policy_reasons": ["split_requires_manual_action"],
            "policy_version": POLICY_VERSION,
        }
    if confidence < REVIEW_CONFIDENCE_THRESHOLD:
        return {
            "review_status": "rejected",
            "policy_reason": "LLM confidence below review threshold",
            "policy_reasons": ["confidence_below_review_threshold"],
            "policy_version": POLICY_VERSION,
        }

    # --- "keep" is a no-op ---
    if action == "keep":
        return {
            "review_status": "auto_approved",
            "policy_reason": "keep is a no-op",
            "policy_reasons": [],
            "policy_version": POLICY_VERSION,
        }

    # --- Confidence threshold ---
    required_conf = 0.75
    if confidence < required_conf:
        return {
            "review_status": "rejected",
            "policy_reason": f"confidence {confidence} below required auto-approval threshold ({required_conf})",
            "policy_reasons": ["confidence_below_auto_threshold"],
            "policy_version": POLICY_VERSION,
        }

    # --- Auto-approve ---
    return {
        "review_status": "auto_approved",
        "policy_reason": f"auto-approved by policy v{POLICY_VERSION}",
        "policy_reasons": [],
        "policy_version": POLICY_VERSION,
    }


def _memory_snapshot_by_id(memory_ids: list[str]) -> dict[str, dict[str, Any]]:
    return {str(row.get("id")): row for row in _fetch_memory_summaries(memory_ids)}


def _decision_memories_for_policy(decision: dict[str, Any]) -> list[dict[str, Any]]:
    source_ids = [str(item) for item in decision.get("source_ids", []) if item]
    by_id = _memory_snapshot_by_id(source_ids)
    finding = decision.get("finding") or {}
    action = decision.get("recommended_action")
    if action in {"archive_duplicate", "archive_and_merge_duplicate"}:
        drop_id = str(finding.get("drop_id") or "")
        if drop_id and drop_id in by_id:
            return [by_id[drop_id]]
    if action == "supersede":
        older_id = str(finding.get("older_id") or finding.get("old_id") or "")
        if older_id and older_id in by_id:
            return [by_id[older_id]]
    if action in {"promote", "downgrade", "archive", "split", "mark_contradicted"}:
        primary_id = str(finding.get("id") or finding.get("older_id") or "")
        if primary_id and primary_id in by_id:
            return [by_id[primary_id]]
    return [by_id[item] for item in source_ids if item in by_id]


def recalibrate_governance_review_queue(limit: int | None = None, dry_run: bool = True, source_agent: str = "maintenance") -> dict[str, Any]:
    """Reclassify existing needs_review decisions under the current policy.

    Moves decisions that now pass the policy gate from needs_review to
    auto_approved.  'keep' actions are reclassified to auto_approved as well
    since they are no-ops.
    """
    cap = max(1, int(limit)) if limit is not None else None
    params: list[Any] = []
    limit_clause = ""
    if cap is not None:
        params.append(cap)
        limit_clause = " LIMIT ?"
    with read_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM governance_decisions
            WHERE review_status='needs_review'
            ORDER BY created_at DESC
            {limit_clause}
            """,
            tuple(params),
        ).fetchall()

    candidates: list[dict[str, Any]] = []
    reject_candidates: list[dict[str, Any]] = []
    unchanged = 0
    for row in rows:
        decision = _decision_row_to_dict(row)
        gate = policy_gate(
            decision["recommended_action"],
            float(decision.get("llm_confidence") or 0.0),
            str(decision.get("risk_level") or "medium"),
            memories=_decision_memories_for_policy(decision),
        )
        if gate["review_status"] == "auto_approved":
            candidates.append({**decision, "_gate": gate})
        elif gate["review_status"] == "rejected":
            reject_candidates.append({**decision, "_gate": gate})
        else:
            unchanged += 1

    changed_ids = [item["id"] for item in candidates]
    rejected_ids = [item["id"] for item in reject_candidates]
    if not dry_run:
        ts = now()
        with managed_conn() as conn:
            for item in candidates:
                gate = item["_gate"]
                conn.execute(
                    """
                    UPDATE governance_decisions
                    SET review_status='auto_approved', policy_reason=?, policy_reasons_json=?,
                        policy_version=?, updated_at=?
                    WHERE id=? AND review_status='needs_review'
                    """,
                    (
                        gate["policy_reason"],
                        as_json(gate.get("policy_reasons", [])),
                        gate.get("policy_version", POLICY_VERSION),
                        ts,
                        item["id"],
                    ),
                )
            for item in reject_candidates:
                gate = item["_gate"]
                conn.execute(
                    """
                    UPDATE governance_decisions
                    SET review_status='rejected', policy_reason=?, policy_reasons_json=?,
                        policy_version=?, updated_at=?
                    WHERE id=? AND review_status='needs_review'
                    """,
                    (
                        gate["policy_reason"],
                        as_json(gate.get("policy_reasons", [])),
                        gate.get("policy_version", POLICY_VERSION),
                        ts,
                        item["id"],
                    ),
                )
        for item in candidates:
            try:
                apply_governance_decision(item["id"], source_agent=source_agent)
            except Exception as exc:
                logger.error("recalibrate: failed to apply decision %s: %s", item["id"], exc)
            _audit.log_audit_event(
                "governance_decision_recalibrate",
                memory_id=(item["source_ids"][0] if item["source_ids"] else None),
                agent=source_agent,
                detail={
                    "decision_id": item["id"],
                    "from": "needs_review",
                    "to": "auto_approved",
                    "policy_version": item["_gate"].get("policy_version", POLICY_VERSION),
                },
            )

    by_type: dict[str, int] = {}
    for item in candidates:
        decision_type = str(item.get("decision_type") or "unknown")
        by_type[decision_type] = by_type.get(decision_type, 0) + 1
    return {
        "dry_run": dry_run,
        "checked": len(rows),
        "would_reclassify": len(candidates),
        "reclassified": 0 if dry_run else len(candidates),
        "unchanged": unchanged,
        "would_reject": len(reject_candidates),
        "rejected": 0 if dry_run else len(reject_candidates),
        "by_type": by_type,
        "decision_ids": changed_ids,
        "rejected_ids": rejected_ids,
    }


# Low-risk actions eligible for auto-expiry after stale period
_AUTO_EXPIRE_ACTIONS = {"archive", "downgrade", "archive_duplicate", "archive_and_merge_duplicate", "keep"}


def auto_expire_stale_reviews(stale_days: int = 14, dry_run: bool = True, source_agent: str = "maintenance") -> dict[str, Any]:
    """Auto-approve low-risk needs_review decisions older than stale_days.

    High-risk actions (split, supersede on precious types) are never auto-expired.
    """
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(days=stale_days)).isoformat()
    with read_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM governance_decisions
            WHERE review_status='needs_review'
              AND created_at < ?
            ORDER BY created_at ASC
            """,
            (cutoff,),
        ).fetchall()

    expired: list[dict[str, Any]] = []
    skipped = 0
    for row in rows:
        decision = _decision_row_to_dict(row)
        action = decision.get("recommended_action", "")
        if action not in _AUTO_EXPIRE_ACTIONS:
            skipped += 1
            continue
        expired.append(decision)

    if expired and not dry_run:
        ts = now()
        with managed_conn() as conn:
            for item in expired:
                conn.execute(
                    """
                    UPDATE governance_decisions
                    SET review_status='auto_approved', policy_reason=?, updated_at=?
                    WHERE id=? AND review_status='needs_review'
                    """,
                    (f"auto_expired_after_{stale_days}_days", ts, item["id"]),
                )
        for item in expired:
            try:
                apply_governance_decision(item["id"], source_agent=source_agent)
            except Exception as exc:
                logger.error("auto_expire: failed to apply decision %s: %s", item["id"], exc)
            _audit.log_audit_event(
                "governance_decision_auto_expire",
                memory_id=(item["source_ids"][0] if item.get("source_ids") else None),
                agent=source_agent,
                detail={"decision_id": item["id"], "stale_days": stale_days, "action": item.get("recommended_action")},
            )

    return {
        "dry_run": dry_run,
        "checked": len(rows),
        "would_expire": len(expired),
        "expired": 0 if dry_run else len(expired),
        "skipped_high_risk": skipped,
        "cutoff": cutoff,
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
    curator_job_id: str = "",
    curator_batch_id: str = "",
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
            if curator_job_id or curator_batch_id:
                conn.execute(
                    """
                    UPDATE governance_decisions
                    SET curator_job_id=?, curator_batch_id=?, updated_at=?
                    WHERE id=?
                    """,
                    (curator_job_id or existing["curator_job_id"], curator_batch_id or existing["curator_batch_id"], ts, existing["id"]),
                )
                existing = conn.execute("SELECT * FROM governance_decisions WHERE id=?", (existing["id"],)).fetchone()
            return _decision_row_to_dict(existing)
        conn.execute(
            """
            INSERT INTO governance_decisions (
              id, decision_type, source_ids_json, recommended_action, llm_confidence,
              risk_level, review_status, policy_reason, finding_json, llm_trace_json, raw_response_ref,
              before_state_json, after_state_json, created_at, updated_at, applied_at, rolled_back_at, source_agent,
              candidate_hash, policy_reasons_json, policy_version, judge_model, judge_schema_version,
              decision_version, execution_id, applied_by, rolled_back_by, approval_kind, curator_job_id, curator_batch_id
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                decision_id, decision_type, as_json(source_ids), recommended_action, confidence,
                risk_level or "medium", gate["review_status"], gate["policy_reason"],
                as_json(finding), as_json(llm_trace), raw_response_ref or "", "[]", "[]",
                ts, ts, None, None, source_agent or "llm_curator",
                candidate_hash, as_json(gate.get("policy_reasons", [])), gate.get("policy_version", POLICY_VERSION),
                JUDGE_MODEL, JUDGE_SCHEMA_VERSION, DECISION_VERSION, "", "", "", "",
                curator_job_id or "", curator_batch_id or "",
            ),
        )
        row = conn.execute("SELECT * FROM governance_decisions WHERE id=?", (decision_id,)).fetchone()

    decision_dict = _decision_row_to_dict(row)
    if gate["review_status"] == "auto_approved":
        try:
            apply_res = apply_governance_decision(decision_id, source_agent=source_agent)
            if apply_res.get("decision"):
                decision_dict = apply_res["decision"]
        except Exception as exc:
            logger.error("Failed to automatically apply auto-approved decision %s: %s", decision_id, exc, exc_info=True)
            try:
                with managed_conn() as conn:
                    conn.execute(
                        "UPDATE governance_decisions SET review_status='rejected', policy_reason=?, updated_at=? WHERE id=? AND review_status='auto_approved'",
                        (f"auto-apply failed: {exc}", now(), decision_id),
                    )
                    updated_row = conn.execute("SELECT * FROM governance_decisions WHERE id=?", (decision_id,)).fetchone()
                if updated_row:
                    decision_dict = _decision_row_to_dict(updated_row)
            except Exception as reject_exc:
                logger.error("Failed to reject broken decision %s: %s", decision_id, reject_exc)

    _audit.log_audit_event("governance_decision_create", memory_id=source_ids[0] if source_ids else None, agent=source_agent, detail={"decision_id": decision_id, "review_status": gate["review_status"], "action": recommended_action, "policy_reasons": gate.get("policy_reasons", []), "policy_version": gate.get("policy_version", POLICY_VERSION)})
    return decision_dict


from memorycore.storage.governance_ops import (  # noqa: E402,F401
    _decision_row_to_dict,
    apply_governance_decision,
    apply_governance_decisions_batch,
    convert_llm_findings_to_decisions,
    get_governance_decision,
    list_governance_decisions,
    reject_governance_decision,
    rollback_governance_decision,
)
from memorycore.storage.governance_mutations import get_governance_metrics  # noqa: E402,F401
