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

from memorycore.storage.governance import POLICY_VERSION

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
    # Quality gate: limit fragment count and enforce minimum length
    max_splits = 5
    min_content_len = 50
    min_title_len = 10
    qualified_subs = [
        sub for sub in sub_memories
        if len(str(sub.get("content") or "").strip()) >= min_content_len
        and len(str(sub.get("title") or "").strip()) >= min_title_len
    ][:max_splits]
    requests = [_memory_request("memory_archive", orig_id, {"status": "archived"}, risk, confidence, decision_id)]
    for index, sub in enumerate(qualified_subs):
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
        or review_queue_age_hours > 72.0
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
