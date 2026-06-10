"""Deterministic executor for governance-originated storage mutations."""
from __future__ import annotations

import json
import uuid
from typing import Any

from memorycore.models import as_json, now, row_to_dict
from memorycore.storage.db import managed_conn, read_conn
from memorycore.storage.mutations import (
    MutationContext,
    MutationRequest,
    evaluate_mutation_policy,
    validate_execution_transition,
)


def _json_load(value: str | None, default: Any) -> Any:
    try:
        return json.loads(value or "")
    except Exception:
        return default


def _snapshot_memory(conn: Any, memory_id: str | None) -> dict[str, Any] | None:
    if not memory_id:
        return None
    row = conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
    return row_to_dict(row) if row is not None else None


def _snapshot_links_for_memory(conn: Any, memory_id: str | None) -> list[dict[str, Any]]:
    if not memory_id:
        return []
    rows = conn.execute(
        "SELECT * FROM memory_links WHERE source_id=? OR target_id=? ORDER BY created_at, id",
        (memory_id, memory_id),
    ).fetchall()
    return [row_to_dict(row) for row in rows]


def ensure_governance_run(context: MutationContext, conn: Any) -> str:
    run_id = context.run_id or context.correlation_id or f"run-{uuid.uuid4()}"
    existing = conn.execute("SELECT id FROM governance_runs WHERE id=?", (run_id,)).fetchone()
    if existing is not None:
        return run_id
    conn.execute(
        """
        INSERT INTO governance_runs (
          id, source, mode, policy_version, status, started_at, created_by, metadata_json
        ) VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            run_id,
            context.origin,
            "auto_apply" if context.approval_kind == "auto_policy" else "review_only",
            "2026-06-10.1",
            "running",
            now(),
            context.actor,
            as_json(context.metadata),
        ),
    )
    return run_id


def create_execution(
    context: MutationContext,
    highest_risk: str,
    policy_snapshot: dict[str, Any],
    conn: Any,
    execution_id: str | None = None,
    idempotency_key: str | None = None,
) -> str:
    run_id = ensure_governance_run(context, conn)
    resolved_execution_id = execution_id or str(uuid.uuid4())
    resolved_key = idempotency_key or f"{context.decision_id or 'batch'}:{context.approval_kind}:{resolved_execution_id}"
    existing = conn.execute(
        """
        SELECT id FROM governance_executions
        WHERE run_id=? AND COALESCE(decision_id,'')=COALESCE(?, '')
          AND approval_kind=? AND idempotency_key=?
        LIMIT 1
        """,
        (run_id, context.decision_id, context.approval_kind, resolved_key),
    ).fetchone()
    if existing is not None:
        return existing["id"]
    applying = conn.execute(
        """
        SELECT id FROM governance_executions
        WHERE COALESCE(decision_id,'')=COALESCE(?, '') AND status='applying'
        LIMIT 1
        """,
        (context.decision_id,),
    ).fetchone()
    if applying is not None:
        raise ValueError("duplicate concurrent applying governance execution")
    conn.execute(
        """
        INSERT INTO governance_executions (
          id, run_id, decision_id, approval_kind, risk_level, status, idempotency_key,
          policy_snapshot_json, started_at, created_by, metadata_json
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            resolved_execution_id,
            run_id,
            context.decision_id or None,
            context.approval_kind,
            highest_risk,
            "planned",
            resolved_key,
            as_json(policy_snapshot),
            now(),
            context.actor,
            as_json(context.metadata),
        ),
    )
    return resolved_execution_id


def transition_execution(execution_id: str, next_status: str, conn: Any, error: dict[str, Any] | None = None) -> None:
    row = conn.execute("SELECT status FROM governance_executions WHERE id=?", (execution_id,)).fetchone()
    if row is None:
        raise ValueError(f"governance execution not found: {execution_id}")
    validate_execution_transition(row["status"], next_status)
    finished_at = now() if next_status in {"queued", "rejected", "applied", "apply_failed", "cancelled", "rolled_back", "rollback_failed"} else None
    conn.execute(
        "UPDATE governance_executions SET status=?, finished_at=COALESCE(?, finished_at), error_json=COALESCE(?, error_json) WHERE id=?",
        (next_status, finished_at, as_json(error) if error else None, execution_id),
    )


def execute_batch(
    requests: list[MutationRequest],
    context: MutationContext,
    execution_id: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    if not requests:
        raise ValueError("execute_batch requires at least one mutation request")
    policy_results = [evaluate_mutation_policy(request, context) for request in requests]
    blocking = [result for result in policy_results if result["policy_decision"] in {"queued", "rejected"}]
    highest_risk = "high" if any(r.risk_level == "high" for r in requests) else "medium" if any(r.risk_level == "medium" for r in requests) else "low"
    with managed_conn() as conn:
        resolved_execution_id = create_execution(
            context,
            highest_risk,
            {"results": policy_results},
            conn,
            execution_id=execution_id,
            idempotency_key=idempotency_key,
        )
        transition_execution(resolved_execution_id, "policy_evaluated", conn)
        if blocking:
            status = "rejected" if any(r["policy_decision"] == "rejected" for r in blocking) else "queued"
            transition_execution(resolved_execution_id, status, conn)
            return {"execution_id": resolved_execution_id, "status": status, "policy_results": policy_results, "results": []}
        transition_execution(resolved_execution_id, "applying", conn)
        results = []
        for index, request in enumerate(requests, start=1):
            results.append(_apply_request(conn, resolved_execution_id, index, request, context, policy_results[index - 1]))
        transition_execution(resolved_execution_id, "applied", conn)
    _sync_results(results)
    return {"execution_id": resolved_execution_id, "status": "applied", "policy_results": policy_results, "results": results}


def _apply_request(conn: Any, execution_id: str, seq: int, request: MutationRequest, context: MutationContext, policy: dict[str, Any]) -> dict[str, Any]:
    ts = now()
    before: Any = None
    after: Any = None
    inverse: dict[str, Any] | None = None
    entity_id = request.target_id
    if request.action_type in {"memory_update", "memory_archive", "memory_status_update", "memory_importance_update", "memory_confidence_update", "memory_supersede"}:
        before = _snapshot_memory(conn, request.target_id)
        if before is None:
            raise ValueError(f"memory not found: {request.target_id}")
        updates = ["updated_at=?"]
        params: list[Any] = [ts]
        payload = request.payload
        field_map = {
            "title": "title",
            "content": "content",
            "status": "status",
            "importance": "importance",
            "confidence": "confidence",
            "metadata_json": "metadata_json",
            "superseded_by": "superseded_by",
            "fact_lineage_root": "fact_lineage_root",
        }
        if request.action_type == "memory_archive":
            payload = {**payload, "status": "archived"}
        for payload_key, column in field_map.items():
            if payload_key in payload:
                updates.append(f"{column}=?")
                params.append(as_json(payload[payload_key]) if payload_key == "metadata_json" and isinstance(payload[payload_key], dict) else payload[payload_key])
        params.append(request.target_id)
        conn.execute(f"UPDATE memories SET {', '.join(updates)} WHERE id=?", params)
        after = _snapshot_memory(conn, request.target_id)
        inverse = {"action_type": "memory_restore", "target_id": request.target_id, "before": before}
    elif request.action_type == "memory_insert":
        payload = request.payload
        entity_id = request.target_id or payload.get("id") or str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO memories (
              id,type,scope,title,content,tags_json,source,source_agent,project_path,
              created_at,updated_at,confidence,importance,status,decay_policy,
              related_ids_json,metadata_json,valid_from,valid_until
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                entity_id,
                payload["type"],
                payload.get("scope", "global"),
                payload["title"],
                payload["content"],
                as_json(payload.get("tags", [])),
                payload.get("source", "governance"),
                context.actor,
                payload.get("project_path", ""),
                ts,
                ts,
                float(payload.get("confidence", 0.7)),
                float(payload.get("importance", 0.5)),
                payload.get("status", "active"),
                payload.get("decay_policy", "review"),
                as_json(payload.get("related_ids", [])),
                as_json(payload.get("metadata", {})),
                payload.get("valid_from"),
                payload.get("valid_until"),
            ),
        )
        after = _snapshot_memory(conn, entity_id)
        inverse = {"action_type": "memory_delete_inserted", "target_id": entity_id}
    elif request.action_type == "memory_link_insert":
        payload = request.payload
        entity_id = payload.get("id") or str(uuid.uuid4())
        before = conn.execute(
            "SELECT * FROM memory_links WHERE source_id=? AND target_id=? AND relation_type=?",
            (payload["source_id"], payload["target_id"], payload["relation_type"]),
        ).fetchone()
        before_dict = row_to_dict(before) if before is not None else None
        conn.execute(
            """
            INSERT INTO memory_links(id, source_id, target_id, relation_type, weight, note, created_at, source_agent)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id, target_id, relation_type) DO UPDATE SET
              weight=excluded.weight, note=excluded.note, source_agent=excluded.source_agent
            """,
            (entity_id, payload["source_id"], payload["target_id"], payload["relation_type"], float(payload.get("weight", 1.0)), payload.get("note", ""), ts, context.actor),
        )
        row = conn.execute(
            "SELECT * FROM memory_links WHERE source_id=? AND target_id=? AND relation_type=?",
            (payload["source_id"], payload["target_id"], payload["relation_type"]),
        ).fetchone()
        after = row_to_dict(row)
        entity_id = after["id"]
        before = before_dict
        inverse = {"action_type": "memory_link_restore", "target_id": entity_id, "before": before_dict, "after": after}
    elif request.action_type == "memory_link_delete":
        before = _snapshot_links_for_memory(conn, request.target_id)
        conn.execute("DELETE FROM memory_links WHERE source_id=? OR target_id=?", (request.target_id, request.target_id))
        after = []
        inverse = {"action_type": "memory_links_restore", "target_id": request.target_id, "before": before}
    else:
        after = {"no_op": True}
        inverse = {"action_type": "no_op"}

    log_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO governance_mutation_log (
          id, execution_id, seq, mutation_type, entity_type, entity_id, operation,
          risk_level, policy_decision, policy_reason, request_json, before_json,
          after_json, inverse_json, index_effect_json, status, idempotency_key,
          created_at, applied_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            log_id,
            execution_id,
            seq,
            request.action_type,
            request.target_type,
            entity_id,
            _operation_for(request.action_type),
            request.risk_level,
            policy["policy_decision"],
            policy["policy_reason"],
            as_json(request.canonical()),
            as_json(before) if before is not None else None,
            as_json(after) if after is not None else None,
            as_json(inverse) if inverse is not None else None,
            as_json({"pending_sync": True}) if request.target_type in {"memory", "memory_link"} else None,
            "applied",
            request.idempotency_key or f"{execution_id}:{seq}:{request.action_type}:{entity_id or ''}",
            ts,
            ts,
        ),
    )
    return {"log_id": log_id, "entity_id": entity_id, "mutation_type": request.action_type, "before": before, "after": after}


def _operation_for(action_type: str) -> str:
    if action_type == "memory_insert":
        return "insert"
    if action_type == "memory_archive":
        return "archive"
    if action_type == "memory_link_insert":
        return "link"
    if action_type == "memory_link_delete":
        return "unlink"
    if action_type == "maintenance_cleanup":
        return "cleanup"
    if action_type == "no_op":
        return "no_op"
    return "update"


def rollback_execution(execution_id: str, context: MutationContext) -> dict[str, Any]:
    with managed_conn() as conn:
        transition_execution(execution_id, "rolling_back", conn)
        rows = conn.execute(
            "SELECT * FROM governance_mutation_log WHERE execution_id=? AND status='applied' ORDER BY seq DESC",
            (execution_id,),
        ).fetchall()
        restored = []
        for row in rows:
            inverse = _json_load(row["inverse_json"], {})
            restored.append(_apply_inverse(conn, row_to_dict(row), inverse))
            conn.execute(
                "UPDATE governance_mutation_log SET status='rolled_back', rolled_back_at=? WHERE id=?",
                (now(), row["id"]),
            )
        transition_execution(execution_id, "rolled_back", conn)
    _sync_results(restored)
    return {"execution_id": execution_id, "restored": restored}


def _apply_inverse(conn: Any, log_row: dict[str, Any], inverse: dict[str, Any]) -> dict[str, Any]:
    action = inverse.get("action_type")
    target_id = inverse.get("target_id") or log_row.get("entity_id")
    if action == "memory_restore":
        before = inverse.get("before") or {}
        conn.execute(
            """
            UPDATE memories
            SET title=?, content=?, confidence=?, importance=?, status=?, superseded_by=?,
                fact_lineage_root=?, metadata_json=?, updated_at=?
            WHERE id=?
            """,
            (
                before.get("title"), before.get("content"), before.get("confidence"), before.get("importance"),
                before.get("status"), before.get("superseded_by"), before.get("fact_lineage_root"),
                as_json(before.get("metadata", _json_load(before.get("metadata_json"), {}))), now(), target_id,
            ),
        )
        return {"entity_id": target_id, "mutation_type": "memory_restore", "after": _snapshot_memory(conn, target_id)}
    if action == "memory_delete_inserted":
        conn.execute("UPDATE memories SET status='archived', updated_at=? WHERE id=?", (now(), target_id))
        return {"entity_id": target_id, "mutation_type": "memory_archive_inserted", "after": _snapshot_memory(conn, target_id)}
    if action == "memory_link_restore":
        before = inverse.get("before")
        after = inverse.get("after") or {}
        if before:
            conn.execute(
                """
                INSERT INTO memory_links(id, source_id, target_id, relation_type, weight, note, created_at, source_agent)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id, target_id, relation_type) DO UPDATE SET
                  weight=excluded.weight, note=excluded.note, source_agent=excluded.source_agent
                """,
                (before["id"], before["source_id"], before["target_id"], before["relation_type"], before["weight"], before.get("note", ""), before["created_at"], before.get("source_agent", "unknown")),
            )
        elif after:
            conn.execute("DELETE FROM memory_links WHERE id=?", (after.get("id"),))
        return {"entity_id": target_id, "mutation_type": "memory_link_restore"}
    return {"entity_id": target_id, "mutation_type": "no_op"}


def query_ledger(correlation_id: str = "", target_id: str = "", origin: str = "", status: str = "", limit: int = 100) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    if target_id:
        clauses.append("l.entity_id=?")
        params.append(target_id)
    if status:
        clauses.append("l.status=?")
        params.append(status)
    if origin:
        clauses.append("r.source=?")
        params.append(origin)
    if correlation_id:
        clauses.append("(r.id=? OR e.id=? OR e.decision_id=?)")
        params.extend([correlation_id, correlation_id, correlation_id])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(max(1, min(int(limit), 500)))
    with read_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT l.*, e.run_id, e.decision_id, r.source AS origin
            FROM governance_mutation_log l
            LEFT JOIN governance_executions e ON e.id = l.execution_id
            LEFT JOIN governance_runs r ON r.id = e.run_id
            {where}
            ORDER BY l.created_at DESC, l.seq DESC
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
    return [row_to_dict(row) for row in rows]


def _sync_results(results: list[dict[str, Any]]) -> None:
    try:
        from memorycore.storage.crud import _sync_record_indexes
    except Exception:
        return
    for result in results:
        after = result.get("after")
        if isinstance(after, dict) and after.get("id") and result.get("mutation_type", "").startswith("memory"):
            _sync_record_indexes(after)
