"""Apply LLM curator actions through the governance mutation executor."""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from memorycore.models import row_to_dict
from memorycore.storage.mutation_executor import execute_batch, query_ledger
from memorycore.storage.mutations import MutationContext, MutationRequest

from .core import _llm_split_fact_hash

logger = logging.getLogger(__name__)


def apply_llm_curator(report: dict[str, Any], dry_run: bool = True) -> dict[str, Any]:
    """Apply LLM curator actions through the governance mutation executor."""
    if dry_run:
        return {"dry_run": True, "planned": report.get("summary", {})}

    applied: dict[str, int] = {
        "archived": 0,
        "contradicted": 0,
        "importance_updated": 0,
        "duplicate_merge_audits": 0,
        "split_links_created": 0,
        "split_links_skipped": 0,
        "duplicate_atomic_facts_archived": 0,
        "split": 0,
        "split_children_created": 0,
        "split_children_skipped": 0,
        "links_created": 0,
    }
    duplicate_merge_audits: list[dict[str, Any]] = []
    duplicate_atomic_fact_audits: list[dict[str, Any]] = []
    requests: list[MutationRequest] = []

    _append_duplicate_requests(report, requests, applied, duplicate_merge_audits)
    _append_contradiction_requests(report, requests)
    _append_importance_requests(report, requests)
    _append_link_discovery_requests(report, requests)
    _append_split_requests(report, requests, applied)
    _append_duplicate_atomic_fact_requests(requests, duplicate_atomic_fact_audits)

    execution = None
    if requests:
        execution = execute_batch(
            requests,
            MutationContext(
                actor="llm_curator",
                origin="llm_curator",
                approval_kind="auto_policy",
                correlation_id=f"llm-curator-{uuid.uuid4()}",
            ),
            idempotency_key=f"llm-curator:{uuid.uuid4()}",
        )
        _count_applied_results(execution, applied)

    from memorycore.storage.audit import log_audit_event
    log_audit_event(
        "llm_curator_apply",
        agent="llm_curator",
        detail={
            **applied,
            "dry_run": False,
            "execution_id": execution.get("execution_id") if execution else "",
            "execution_status": execution.get("status") if execution else "no_op",
            "duplicate_merge_audits": duplicate_merge_audits,
            "duplicate_atomic_fact_audits": duplicate_atomic_fact_audits,
        },
    )
    return {"dry_run": False, "applied": applied, "execution": execution}


def _append_duplicate_requests(
    report: dict[str, Any],
    requests: list[MutationRequest],
    applied: dict[str, int],
    duplicate_merge_audits: list[dict[str, Any]],
) -> None:
    for dup in report.get("semantic_duplicates", []) or []:
        drop_id = dup.get("drop_id")
        keep_id = dup.get("keep_id")
        if drop_id:
            requests.append(_memory_archive_request(str(drop_id), "semantic_duplicate", "low", dup.get("confidence", dup.get("score", 0.95))))
        if keep_id and drop_id and (dup.get("merge_info") or dup.get("action") == "archive_and_merge_duplicate"):
            duplicate_merge_audits.append({
                "keep_id": keep_id,
                "drop_id": drop_id,
                "keep_title": dup.get("keep_title", ""),
                "drop_title": dup.get("drop_title", ""),
                "merge_info": dup.get("merge_info", ""),
                "reason": dup.get("reason", "semantic duplicate"),
            })
            applied["duplicate_merge_audits"] += 1


def _append_contradiction_requests(report: dict[str, Any], requests: list[MutationRequest]) -> None:
    for contra in report.get("contradictions", []) or []:
        older_id = contra.get("older_id")
        if older_id:
            requests.append(MutationRequest(
                action_type="memory_status_update",
                target_type="memory",
                target_id=str(older_id),
                payload={"status": "contradicted"},
                risk_level="medium",
                confidence=float(contra.get("confidence", contra.get("score", 0.9)) or 0.9),
                idempotency_key=f"llm-curator:contradiction:{older_id}",
            ))


def _append_importance_requests(report: dict[str, Any], requests: list[MutationRequest]) -> None:
    for reassess in report.get("importance_reassessments", []) or []:
        action = reassess.get("action", "keep")
        mem_id = reassess.get("id")
        new_imp = reassess.get("new_importance")
        if not mem_id:
            continue
        confidence = float(reassess.get("confidence", 0.95) or 0.95)
        if action == "archive":
            requests.append(_memory_archive_request(str(mem_id), "importance_archive", "low", confidence))
        elif action in ("promote", "downgrade") and new_imp is not None:
            payload: dict[str, Any] = {"importance": float(new_imp)}
            if action == "promote":
                payload["status"] = "active"
            requests.append(MutationRequest(
                action_type="memory_importance_update",
                target_type="memory",
                target_id=str(mem_id),
                payload=payload,
                risk_level="low",
                confidence=confidence,
                idempotency_key=f"llm-curator:importance:{mem_id}:{action}",
            ))


def _append_link_discovery_requests(report: dict[str, Any], requests: list[MutationRequest]) -> None:
    for link in report.get("link_discoveries", []) or []:
        source_id = link.get("source_id")
        target_id = link.get("target_id")
        relation = link.get("relation_type", "related_to")
        if not source_id or not target_id:
            continue
        requests.append(MutationRequest(
            action_type="memory_link_insert",
            target_type="memory_link",
            payload={
                "source_id": source_id,
                "target_id": target_id,
                "relation_type": relation,
                "weight": 0.8,
                "note": f"LLM curator link discovery: {link.get('reason', '')}",
            },
            risk_level="low",
            confidence=0.85,
            idempotency_key=f"llm-curator:link-discovery:{source_id}:{target_id}:{relation}",
        ))


def _append_split_requests(report: dict[str, Any], requests: list[MutationRequest], applied: dict[str, int]) -> None:
    from memorycore.storage.db import read_conn

    for split in report.get("split_candidates", []) or []:
        orig_id = split.get("id")
        sub_memories = split.get("sub_memories", []) or []
        if not orig_id or not sub_memories:
            continue
        with read_conn() as conn:
            orig_row = conn.execute("SELECT * FROM memories WHERE id=?", (orig_id,)).fetchone()
            if not orig_row:
                continue
            orig = row_to_dict(orig_row)
        requests.append(_memory_archive_request(str(orig_id), "llm_split_parent", "medium", split.get("confidence", 0.95)))
        created_for_parent = 0
        for sub in sub_memories:
            sub_title = str(sub.get("title") or "")[:120].strip()
            sub_content = str(sub.get("content") or "").strip()
            if not sub_title or not sub_content:
                continue
            fact_hash = _llm_split_fact_hash(str(orig_id), sub_content)
            existing_id = _existing_split_child_id(str(orig_id), fact_hash)
            child_id = existing_id or str(uuid.uuid5(uuid.NAMESPACE_URL, f"llm-curator:{orig_id}:{fact_hash}"))
            if existing_id:
                applied["split_children_skipped"] += 1
            else:
                raw_imp = sub.get("importance")
                sub_importance = float(max(0.0, min(1.0, raw_imp))) if raw_imp is not None else float(orig.get("importance", 0.5))
                requests.append(MutationRequest(
                    action_type="memory_insert",
                    target_type="memory",
                    target_id=child_id,
                    payload={
                        "id": child_id,
                        "type": orig.get("type", "project_memory"),
                        "scope": orig.get("scope", "global"),
                        "title": sub_title,
                        "content": sub_content,
                        "tags": json.loads(orig.get("tags_json") or "[]"),
                        "source": "llm_curator",
                        "project_path": orig.get("project_path", ""),
                        "confidence": float(orig.get("confidence", 0.7)),
                        "importance": sub_importance,
                        "status": "active",
                        "decay_policy": orig.get("decay_policy", "review"),
                        "metadata": {
                            "kind": "atomic_fact",
                            "parent_id": orig_id,
                            "fact_hash": fact_hash,
                            "atomizer_version": "llm-curator-v1",
                            "source_type": "llm_split",
                        },
                    },
                    risk_level="low",
                    confidence=float(split.get("confidence", 0.95) or 0.95),
                    idempotency_key=f"llm-curator:split-child:{orig_id}:{fact_hash}",
                ))
                created_for_parent += 1
            _append_split_link_requests(requests, str(orig_id), child_id)
        if created_for_parent:
            applied["split"] += 1


def _append_split_link_requests(requests: list[MutationRequest], orig_id: str, child_id: str) -> None:
    for source_id, target_id, relation_type, note in (
        (child_id, orig_id, "part_of", "LLM curator split child fact"),
        (orig_id, child_id, "supports", "LLM curator split generated child fact"),
    ):
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
            confidence=0.95,
            idempotency_key=f"llm-curator:split-link:{source_id}:{target_id}:{relation_type}",
        ))


def _append_duplicate_atomic_fact_requests(
    requests: list[MutationRequest],
    duplicate_atomic_fact_audits: list[dict[str, Any]],
) -> None:
    from memorycore.storage.db import read_conn

    with read_conn() as conn:
        duplicate_fact_rows = conn.execute(
            """
            SELECT parent_id, fact_hash, GROUP_CONCAT(id) AS memory_ids
            FROM (
                SELECT id,
                       json_extract(metadata_json, '$.parent_id') AS parent_id,
                       json_extract(metadata_json, '$.fact_hash') AS fact_hash
                FROM memories
                WHERE status NOT IN ('archived')
                  AND json_extract(metadata_json, '$.parent_id') IS NOT NULL
                  AND json_extract(metadata_json, '$.fact_hash') IS NOT NULL
                ORDER BY created_at ASC, id ASC
            )
            GROUP BY parent_id, fact_hash
            HAVING COUNT(*) > 1
            """
        ).fetchall()
    for row in duplicate_fact_rows:
        memory_ids = [mid for mid in str(row["memory_ids"] or "").split(",") if mid]
        if len(memory_ids) < 2:
            continue
        keep_id = memory_ids[0]
        drop_ids = memory_ids[1:]
        for drop_id in drop_ids:
            requests.append(_memory_archive_request(drop_id, "duplicate_atomic_fact", "low", 0.95))
        if drop_ids:
            duplicate_atomic_fact_audits.append({
                "parent_id": row["parent_id"],
                "fact_hash": row["fact_hash"],
                "keep_id": keep_id,
                "archived_ids": drop_ids,
                "reason": "duplicate atomic facts with same parent_id and fact_hash",
            })


def _memory_archive_request(memory_id: str, reason: str, risk_level: str, confidence: Any) -> MutationRequest:
    return MutationRequest(
        action_type="memory_archive",
        target_type="memory",
        target_id=memory_id,
        payload={"status": "archived", "reason": reason},
        risk_level=risk_level,
        confidence=float(confidence or 0.95),
        idempotency_key=f"llm-curator:archive:{reason}:{memory_id}",
    )


def _existing_split_child_id(parent_id: str, fact_hash: str) -> str | None:
    from memorycore.storage.db import read_conn

    with read_conn() as conn:
        row = conn.execute(
            """
            SELECT id FROM memories
            WHERE json_extract(metadata_json, '$.parent_id') = ?
              AND json_extract(metadata_json, '$.fact_hash') = ?
            LIMIT 1
            """,
            (parent_id, fact_hash),
        ).fetchone()
    return str(row["id"]) if row else None


def _count_applied_results(execution: dict[str, Any], applied: dict[str, int]) -> None:
    if execution.get("status") != "applied":
        return
    for result in execution.get("results", []) or []:
        mutation_type = result.get("mutation_type")
        before = result.get("before") or {}
        after = result.get("after") or {}
        if mutation_type == "memory_archive" and before.get("status") != "archived" and after.get("status") == "archived":
            request = _request_from_result(result)
            reason = (request.get("payload") or {}).get("reason", "")
            if reason == "duplicate_atomic_fact":
                applied["duplicate_atomic_facts_archived"] += 1
            else:
                applied["archived"] += 1
        elif mutation_type == "memory_status_update" and after.get("status") == "contradicted":
            applied["contradicted"] += 1
        elif mutation_type == "memory_importance_update":
            applied["importance_updated"] += 1
        elif mutation_type == "memory_insert":
            applied["split_children_created"] += 1
        elif mutation_type == "memory_link_insert":
            if result.get("before") is None:
                applied["split_links_created"] += 1
            else:
                applied["split_links_skipped"] += 1


def _request_from_result(result: dict[str, Any]) -> dict[str, Any]:
    log_id = result.get("log_id")
    if not log_id:
        return {}
    from memorycore.storage.db import read_conn
    with read_conn() as conn:
        row = conn.execute(
            "SELECT request_json FROM governance_mutation_log WHERE id = ? LIMIT 1",
            (log_id,),
        ).fetchone()
    if row:
        try:
            return json.loads(row["request_json"] or "{}")
        except Exception:
            return {}
    return {}
