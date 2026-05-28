"""Core CRUD operations for memory records."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from local_memory_mcp.models import (
    as_json,
    finite_float,
    load_config,
    normalize_list,
    now,
    row_to_dict,
    validate_status,
    validate_type,
)
from local_memory_mcp.privacy import redact_record_fields
from local_memory_mcp.storage.db import _managed_query, managed_conn
from local_memory_mcp.storage.audit import log_audit_event
from local_memory_mcp.storage.permissions import check_agent_permission

logger = logging.getLogger(__name__)


def _validate_iso(value: str | None, field: str) -> None:
    if value is None:
        return
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"{field} must be ISO-8601, got: {value!r}")
    if dt.tzinfo is None:
        raise ValueError(f"{field} must include timezone info (e.g. '+00:00'), got: {value!r}")

try:
    from local_memory_mcp.vector_store import get_vector_store as _get_vector_store
except Exception:
    _get_vector_store = None  # type: ignore[assignment]


def _sync_to_vector(record: dict[str, Any]) -> None:
    """Fire-and-forget Qdrant upsert after SQLite write. Never raises."""
    try:
        if _get_vector_store is None:
            return
        text = f"{record.get('title', '')} {record.get('content', '')}".strip()
        payload = {
            "type": record.get("type", ""),
            "scope": record.get("scope", ""),
            "status": record.get("status", "active"),
            "source_agent": record.get("source_agent", ""),
            "tags": record.get("tags", []),
        }
        vs = _get_vector_store(load_config())
        vs.upsert(record["id"], text, payload)
    except Exception as exc:
        logger.warning("_sync_to_vector: failed for id=%s: %s", record.get("id"), exc)


def add_memory_record(
    memory_type: str,
    title: str,
    content: str,
    scope: str = "global",
    tags: Any = None,
    source: str = "manual",
    source_agent: str = "agent",
    project_path: str = "",
    confidence: float = 0.70,
    importance: float = 0.50,
    status: str = "active",
    decay_policy: str = "review",
    related_ids: Any = None,
    metadata: Any = None,
    memory_id: str | None = None,
    valid_from: str | None = None,
    valid_until: str | None = None,
) -> dict[str, Any]:
    validate_type(memory_type)
    validate_status(status)
    if not title.strip() or not content.strip():
        raise ValueError("title and content are required")
    _validate_iso(valid_from, "valid_from")
    _validate_iso(valid_until, "valid_until")
    permission = check_agent_permission(source_agent or "unknown", "memory.write", scope or "global", memory_type, tags)
    if not permission["allowed"]:
        return {"error": "permission_denied", "decision": permission}
    title, content, _, _ = redact_record_fields(title, content)
    confidence_value = finite_float(confidence, "confidence", 0.0, 1.0)
    importance_value = finite_float(importance, "importance", 0.0, 1.0)
    memory_id = memory_id or str(uuid.uuid4())
    ts = now()
    with managed_conn() as conn:
        conn.execute(
            """
            INSERT INTO memories (
              id,type,scope,title,content,tags_json,source,source_agent,project_path,
              created_at,updated_at,confidence,importance,status,decay_policy,
              related_ids_json,metadata_json,valid_from,valid_until
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                memory_id, memory_type, scope or "global", title.strip(), content.strip(),
                as_json(normalize_list(tags)), source or "manual", source_agent or "unknown",
                project_path or "", ts, ts, confidence_value, importance_value, status,
                decay_policy or "review", as_json(normalize_list(related_ids)), as_json(metadata or {}),
                valid_from, valid_until,
            ),
        )
        row = conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
    result = row_to_dict(row)
    log_audit_event("memory_add", memory_id=memory_id, agent=source_agent, detail={"type": memory_type})
    _sync_to_vector(result)
    return result


def update_memory_content(
    memory_id: str,
    new_content: str | None = None,
    new_title: str | None = None,
    new_status: str | None = None,
    new_confidence: float | None = None,
    new_importance: float | None = None,
) -> dict[str, Any]:
    rows = _managed_query("SELECT id FROM memories WHERE id=? LIMIT 1", (memory_id,))
    if not rows:
        raise ValueError(f"Memory not found: {memory_id}")
    ts = now()
    updates: list[str] = ["updated_at=?"]
    params: list[Any] = [ts]
    if new_content is not None or new_title is not None:
        _t, _c, _, _ = redact_record_fields(new_title or "", new_content or "")
        if new_title is not None:
            new_title = _t
        if new_content is not None:
            new_content = _c
    if new_content is not None:
        updates.append("content=?")
        params.append(new_content.strip())
    if new_title is not None:
        updates.append("title=?")
        params.append(new_title.strip())
    if new_status is not None:
        validate_status(new_status)
        updates.append("status=?")
        params.append(new_status)
    if new_confidence is not None:
        updates.append("confidence=?")
        params.append(finite_float(new_confidence, "confidence", 0.0, 1.0))
    if new_importance is not None:
        updates.append("importance=?")
        params.append(finite_float(new_importance, "importance", 0.0, 1.0))
    params.append(memory_id)
    with managed_conn() as conn:
        conn.execute(f"UPDATE memories SET {', '.join(updates)} WHERE id=?", params)
        row = conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
    result = row_to_dict(row)
    log_audit_event("memory_update", memory_id=memory_id, detail={"fields": updates[1:]})
    _sync_to_vector(result)
    return result


def update_status(memory_id: str, status: str) -> dict[str, Any]:
    validate_status(status)
    with managed_conn() as conn:
        conn.execute("UPDATE memories SET status=?, updated_at=? WHERE id=?", (status, now(), memory_id))
        row = conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
    if row is None:
        raise ValueError(f"memory not found: {memory_id}")
    result = row_to_dict(row)
    log_audit_event("memory_status_change", memory_id=memory_id, detail={"status": status})
    _sync_to_vector(result)
    return result


def update_status_batch(conn, updates: list[tuple[str, str]]) -> None:
    """Execute multiple status updates inside a caller-owned connection/transaction.

    Each item in updates is (memory_id, new_status). Caller is responsible for
    committing/rolling back the connection. No audit events are emitted here —
    caller should log a single bulk audit event instead.
    """
    ts = now()
    for memory_id, status in updates:
        validate_status(status)
        conn.execute("UPDATE memories SET status=?, updated_at=? WHERE id=?", (status, ts, memory_id))


def add_feedback(
    memory_id: str, score: float, note: str = "", source_agent: str = "agent"
) -> dict[str, Any]:
    score_value = finite_float(score, "score", -10.0, 10.0)
    event_id = str(uuid.uuid4())
    ts = now()
    with managed_conn() as conn:
        if conn.execute("SELECT 1 FROM memories WHERE id=?", (memory_id,)).fetchone() is None:
            raise ValueError(f"memory not found: {memory_id}")
        conn.execute(
            "INSERT INTO feedback_events(id,memory_id,score,note,source_agent,created_at) VALUES (?,?,?,?,?,?)",
            (event_id, memory_id, score_value, note or "", source_agent or "unknown", ts),
        )
        avg = conn.execute(
            "SELECT AVG(score) FROM feedback_events WHERE memory_id=?", (memory_id,)
        ).fetchone()[0] or 0
        cur = conn.execute(
            "SELECT injected_count, ineffective_count, effectiveness_score FROM memories WHERE id=?",
            (memory_id,),
        ).fetchone()
        inj, ineff, eff = int(cur[0] or 0), int(cur[1] or 0), float(cur[2] or 0.5)
        if score_value > 0:
            inj += 1
            eff = min(1.0, eff + 0.05 * score_value)
        elif score_value < 0:
            ineff += 1
            eff = max(0.0, eff + 0.05 * score_value)
        conn.execute(
            """UPDATE memories SET feedback_score=?, injected_count=?, ineffective_count=?,
               effectiveness_score=?, updated_at=? WHERE id=?""",
            (float(avg), inj, ineff, round(eff, 4), ts, memory_id),
        )
        row = conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
    return {"feedback_id": event_id, "memory": row_to_dict(row)}


def list_recent(limit: int = 10, cap: int | None = None) -> list[dict[str, Any]]:
    limit_value = max(1, int(limit))
    if cap is not None:
        limit_value = min(limit_value, int(cap))
    with managed_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM memories ORDER BY updated_at DESC LIMIT ?", (limit_value,)
        ).fetchall()
    return [row_to_dict(r) for r in rows]


def get_record(memory_id: str) -> dict[str, Any] | None:
    with managed_conn() as conn:
        row = conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
    return row_to_dict(row) if row else None


def timeline(query: str = "", scope: str = "", limit: int = 20) -> list[dict[str, Any]]:
    from local_memory_mcp.storage.search import search_memory_records
    rows = search_memory_records(
        query, types=["timeline_event", "decision", "feedback"],
        scope=scope, status="active", limit=limit,
    )
    return sorted(rows, key=lambda r: r.get("created_at", ""))


def get_memory_stats() -> dict[str, Any]:
    with managed_conn() as conn:
        type_dist = {r["type"]: r["cnt"] for r in conn.execute(
            "SELECT type, COUNT(*) as cnt FROM memories GROUP BY type"
        ).fetchall()}
        status_dist = {r["status"]: r["cnt"] for r in conn.execute(
            "SELECT status, COUNT(*) as cnt FROM memories GROUP BY status"
        ).fetchall()}
        agent_dist = {r["source_agent"]: r["cnt"] for r in conn.execute(
            "SELECT source_agent, COUNT(*) as cnt FROM memories GROUP BY source_agent"
        ).fetchall()}
        agg = conn.execute(
            "SELECT AVG(confidence) as avg_conf, AVG(importance) as avg_imp, "
            "AVG(feedback_score) as avg_fb, COUNT(*) as total FROM memories"
        ).fetchone()
        never_accessed = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE last_accessed_at IS NULL"
        ).fetchone()[0]
        link_count = conn.execute("SELECT COUNT(*) FROM memory_links").fetchone()[0]
    return {
        "total": agg["total"],
        "by_type": type_dist,
        "by_status": status_dist,
        "by_agent": agent_dist,
        "avg_confidence": round(float(agg["avg_conf"] or 0), 3),
        "avg_importance": round(float(agg["avg_imp"] or 0), 3),
        "avg_feedback_score": round(float(agg["avg_fb"] or 0), 3),
        "never_accessed_count": never_accessed,
        "link_count": link_count,
    }
