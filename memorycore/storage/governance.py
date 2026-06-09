"""Governance decisions for LLM-assisted memory curation.

LLMs may recommend actions, but this module persists decisions and applies a
small deterministic policy gate before any database mutation occurs.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any

from memorycore.models import as_json, now, row_to_dict
from memorycore.storage import audit as _audit
from memorycore.storage.crud import supersede_memory_record, update_memory_content
from memorycore.storage.db import managed_conn, read_conn

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

    before = _snapshot_memories(decision["source_ids"])
    applied = _apply_finding(decision)
    ts = now()
    execution_id = str(uuid.uuid4())
    approval_kind = "auto" if decision["review_status"] == "auto_approved" else "human_accept"
    after = _snapshot_memories(decision["source_ids"])
    rollback = {"before": before, "after": after}
    with managed_conn() as conn:
        conn.execute(
            """
            UPDATE governance_decisions
            SET review_status='applied', applied_at=?, updated_at=?, rollback_json=?,
                before_state_json=?, after_state_json=?, execution_id=?, applied_by=?, approval_kind=?
            WHERE id=?
            """,
            (ts, ts, as_json(rollback), as_json(before), as_json(after), execution_id, source_agent or "agent", approval_kind, decision_id),
        )
        updated = conn.execute("SELECT * FROM governance_decisions WHERE id=?", (decision_id,)).fetchone()
    updated_decision = _decision_row_to_dict(updated)
    _audit.log_audit_event("governance_decision_apply", memory_id=(decision["source_ids"][0] if decision["source_ids"] else None), agent=source_agent, detail={"decision_id": decision_id, "execution_id": execution_id, "applied": applied, "before_state": before, "after_state": after, "approval_kind": approval_kind})
    return {"decision": updated_decision, "applied": applied}


def rollback_governance_decision(decision_id: str, source_agent: str = "agent") -> dict[str, Any]:
    with read_conn() as conn:
        row = conn.execute("SELECT * FROM governance_decisions WHERE id=?", (decision_id,)).fetchone()
    if row is None:
        raise ValueError(f"governance decision not found: {decision_id}")
    decision = _decision_row_to_dict(row)
    if decision.get("rolled_back_at"):
        return {"decision": decision, "already_rolled_back": True, "restored": []}
    rollback_data = json.loads(decision.get("rollback_json") or "{}")
    before = rollback_data.get("before") or []
    if not before:
        raise ValueError("decision has no rollback snapshot")
    ts = now()
    restored_records: list[dict[str, Any]] = []
    with managed_conn() as conn:
        for memory in before:
            conn.execute(
                """
                UPDATE memories
                SET title=?, content=?, confidence=?, importance=?, status=?, superseded_by=?,
                    fact_lineage_root=?, updated_at=?
                WHERE id=?
                """,
                (
                    memory.get("title"), memory.get("content"), memory.get("confidence"),
                    memory.get("importance"), memory.get("status"), memory.get("superseded_by"),
                    memory.get("fact_lineage_root"), ts, memory.get("id"),
                ),
            )
            restored = conn.execute("SELECT * FROM memories WHERE id=?", (memory.get("id"),)).fetchone()
            if restored is not None:
                restored_records.append(row_to_dict(restored))
        conn.execute(
            "UPDATE governance_decisions SET review_status='rolled_back', rolled_back_at=?, updated_at=?, rolled_back_by=? WHERE id=?",
            (ts, ts, source_agent or "agent", decision_id),
        )
        updated = conn.execute("SELECT * FROM governance_decisions WHERE id=?", (decision_id,)).fetchone()
    from memorycore.storage.crud import _sync_record_indexes

    for record in restored_records:
        _sync_record_indexes(record)
    _audit.log_audit_event("governance_decision_rollback", memory_id=(decision["source_ids"][0] if decision["source_ids"] else None), agent=source_agent, detail={"decision_id": decision_id, "restored": [m.get("id") for m in before]})
    return {"decision": _decision_row_to_dict(updated), "restored": before, "already_rolled_back": False}


def _snapshot_memories(memory_ids: list[str]) -> list[dict[str, Any]]:
    if not memory_ids:
        return []
    placeholders = ",".join("?" for _ in memory_ids)
    with read_conn() as conn:
        rows = conn.execute(f"SELECT * FROM memories WHERE id IN ({placeholders})", tuple(memory_ids)).fetchall()
    return [row_to_dict(row) for row in rows]


def _apply_finding(decision: dict[str, Any]) -> dict[str, Any]:
    finding = decision.get("finding") or {}
    action = decision.get("recommended_action")
    if decision["decision_type"] == "importance_reassessment" and action in {"promote", "downgrade", "archive"}:
        mem_id = finding.get("id")
        if action == "archive":
            return _update_memory_fields(mem_id, status="archived")
        kwargs: dict[str, Any] = {"new_importance": finding.get("new_importance")}
        if action == "promote":
            kwargs["new_status"] = "active"
        return update_memory_content(mem_id, **kwargs)
    if decision["decision_type"] == "semantic_duplicate" and action in {"archive_duplicate", "archive_and_merge_duplicate"}:
        return _update_memory_fields(finding.get("drop_id"), status="archived")
    if decision["decision_type"] == "contradiction" and action == "mark_contradicted":
        return _update_memory_fields(finding.get("older_id"), status="contradicted")
    if decision["decision_type"] == "supersession" and action == "supersede":
        old_id = finding.get("old_id") or finding.get("older_id")
        new_id = finding.get("new_id") or finding.get("newer_id")
        return supersede_memory_record(old_id, new_id, source_agent=decision.get("source_agent", "governance"), note="auto-supersession governance decision")
    raise ValueError(f"governance apply does not support action {action!r}")


def _update_memory_fields(memory_id: str, status: str) -> dict[str, Any]:
    if not memory_id:
        raise ValueError("memory id is required")
    return update_memory_content(memory_id, new_status=status)
