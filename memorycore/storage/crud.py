"""Core CRUD operations for memory records."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from memorycore.models import (
    as_json,
    finite_float,
    load_config,
    normalize_list,
    now,
    row_to_dict,
    validate_status,
    validate_type,
)
from memorycore.privacy import redact_record_fields
from memorycore.storage.db import _managed_query, managed_conn, read_conn
from memorycore.storage.audit import log_audit_event
from memorycore.storage.atomization import atomize_record, should_atomize
from memorycore.storage.entities import sync_memory_entities

_LINEAGE_RELEVANT_STATUSES = {"active", "stale", "contradicted", "superseded"}

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
    from memorycore.vector_store import get_vector_store as _get_vector_store
except Exception:
    _get_vector_store = None  # type: ignore[assignment]


def _sync_to_vector(record: dict[str, Any]) -> None:
    """Async fire-and-forget Qdrant sync. Never raises."""
    import threading as _threading
    def _run():
        try:
            if _get_vector_store is None:
                return
            vs = _get_vector_store(load_config())
            status = record.get("status", "active")
            if status != "active":
                vs.delete(record["id"])
                return
            text = f"{record.get('title', '')} {record.get('content', '')}".strip()
            metadata = record.get("metadata") or {}
            payload = {
                "type": record.get("type", ""),
                "scope": record.get("scope", ""),
                "status": status,
                "source_agent": record.get("source_agent", ""),
                "tags": record.get("tags", []),
                "kind": metadata.get("kind", ""),
                "parent_id": metadata.get("parent_id", ""),
            }
            vs.upsert(record["id"], text, payload)
        except Exception as exc:
            logger.warning("_sync_to_vector: failed for id=%s: %s", record.get("id"), exc)
    _threading.Thread(target=_run, daemon=True).start()


def _sync_entities(record: dict[str, Any], conn: Any | None = None) -> None:
    """Best-effort entity index sync after SQLite writes."""
    try:
        sync_memory_entities(record, conn=conn)
    except Exception as exc:
        logger.warning("_sync_entities: failed for id=%s: %s", record.get("id"), exc)


def _sync_record_indexes(record: dict[str, Any], conn: Any | None = None) -> None:
    _sync_to_vector(record)
    _sync_entities(record, conn=conn)


def _cascade_child_status(parent_id: str, status: str, conn: Any | None = None) -> list[dict[str, Any]]:
    if status == "active":
        return []
    ts = now()
    def _run(target_conn: Any) -> list[dict[str, Any]]:
        target_conn.execute(
            """
            UPDATE memories
            SET status=?, updated_at=?
            WHERE json_extract(metadata_json, '$.parent_id') = ?
              AND json_extract(metadata_json, '$.kind') = 'atomic_fact'
              AND status != ?
            """,
            (status, ts, parent_id, status),
        )
        rows = target_conn.execute(
            """
            SELECT * FROM memories
            WHERE json_extract(metadata_json, '$.parent_id') = ?
              AND json_extract(metadata_json, '$.kind') = 'atomic_fact'
            """,
            (parent_id,),
        ).fetchall()
        return [row_to_dict(row) for row in rows]
    if conn is not None:
        return _run(conn)
    with managed_conn() as managed:
        return _run(managed)


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
    atomize: str | bool = "auto",
) -> dict[str, Any]:
    validate_type(memory_type)
    validate_status(status)
    if not title.strip() or not content.strip():
        raise ValueError("title and content are required")
    _validate_iso(valid_from, "valid_from")
    _validate_iso(valid_until, "valid_until")
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
    _sync_record_indexes(result)
    try:
        from memorycore.storage.temporal_governance import process_auto_supersession

        process_auto_supersession(result, source_agent=source_agent)
    except Exception as exc:
        logger.warning("process_auto_supersession: failed for id=%s: %s", result.get("id"), exc)
    if should_atomize(result, atomize):
        try:
            atomize_record(
                result["id"],
                dry_run=False,
                atomize=atomize,
                add_memory_fn=add_memory_record,
            )
        except Exception as exc:
            logger.warning("atomize_record: failed for id=%s: %s", result.get("id"), exc)
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
    changed_records = [result]
    if new_status is not None:
        changed_records.extend(_cascade_child_status(memory_id, new_status))
    for record in changed_records:
        _sync_record_indexes(record)
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
    changed_records = [result, *_cascade_child_status(memory_id, status)]
    for record in changed_records:
        _sync_record_indexes(record)
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
    # Sync changed records to Qdrant after the batch (fire-and-forget per record)
    for memory_id, status in updates:
        row = conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
        if row:
            result = row_to_dict(row)
            changed_records = [result]
            changed_records.extend(_cascade_child_status(memory_id, status, conn=conn))
            for record in changed_records:
                _sync_record_indexes(record, conn=conn)


def supersede_memory_record(
    old_id: str,
    new_id: str,
    source_agent: str = "agent",
    note: str = "",
) -> dict[str, Any]:
    """Mark an older memory as superseded by a newer memory and link the pair."""
    if old_id == new_id:
        raise ValueError("old_id and new_id must be different")
    ts = now()
    with managed_conn() as conn:
        old_row = conn.execute("SELECT * FROM memories WHERE id=?", (old_id,)).fetchone()
        new_row = conn.execute("SELECT * FROM memories WHERE id=?", (new_id,)).fetchone()
        if old_row is None:
            raise ValueError(f"old memory not found: {old_id}")
        if new_row is None:
            raise ValueError(f"new memory not found: {new_id}")
        old_record = row_to_dict(old_row)
        new_record = row_to_dict(new_row)
        root_id = new_record.get("fact_lineage_root") or old_record.get("fact_lineage_root") or old_id
        conn.execute(
            """
            UPDATE memories
            SET status='superseded', superseded_by=?, fact_lineage_root=?, updated_at=?
            WHERE id=?
            """,
            (new_id, root_id, ts, old_id),
        )
        conn.execute(
            """
            UPDATE memories
            SET fact_lineage_root=COALESCE(fact_lineage_root, ?), updated_at=?
            WHERE id=?
            """,
            (root_id, ts, new_id),
        )
        import uuid as _uuid
        link_id = str(_uuid.uuid4())
        link_note = note or "newer memory supersedes older fact"
        conn.execute(
            """
            INSERT INTO memory_links(id, source_id, target_id, relation_type, weight, note, created_at, source_agent)
            VALUES (?, ?, ?, 'supersedes', 1.0, ?, ?, ?)
            ON CONFLICT(source_id, target_id, relation_type) DO UPDATE SET
              weight=excluded.weight, note=excluded.note, source_agent=excluded.source_agent
            """,
            (link_id, new_id, old_id, link_note, ts, source_agent or "agent"),
        )
        old_after = row_to_dict(conn.execute("SELECT * FROM memories WHERE id=?", (old_id,)).fetchone())
        new_after = row_to_dict(conn.execute("SELECT * FROM memories WHERE id=?", (new_id,)).fetchone())
    log_audit_event(
        "memory_supersede",
        memory_id=old_id,
        agent=source_agent,
        detail={"old_id": old_id, "new_id": new_id, "note": note, "root_id": root_id},
    )
    _sync_record_indexes(old_after)
    _sync_record_indexes(new_after)
    return {"old": old_after, "new": new_after, "root_id": root_id}


def memory_lineage(memory_id: str, limit: int = 100) -> dict[str, Any]:
    """Return a compact fact-lineage view for a memory and its supersession links."""
    cap = max(1, min(int(limit), 500))
    with read_conn() as conn:
        base_row = conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
        if base_row is None:
            raise ValueError(f"memory not found: {memory_id}")
        base = row_to_dict(base_row)
        root_id = base.get("fact_lineage_root") or memory_id
        rows = conn.execute(
            """
            SELECT * FROM memories
            WHERE id = ? OR fact_lineage_root = ? OR superseded_by = ?
            ORDER BY created_at ASC, updated_at ASC
            LIMIT ?
            """,
            (root_id, root_id, memory_id, cap),
        ).fetchall()
        records = [row_to_dict(row) for row in rows]
        known_ids = {record["id"] for record in records}
        if memory_id not in known_ids:
            records.append(base)
            known_ids.add(memory_id)
        placeholders = ",".join("?" for _ in known_ids)
        links = []
        if placeholders:
            link_rows = conn.execute(
                f"""
                SELECT * FROM memory_links
                WHERE relation_type='supersedes'
                  AND (source_id IN ({placeholders}) OR target_id IN ({placeholders}))
                ORDER BY created_at ASC
                LIMIT ?
                """,
                [*known_ids, *known_ids, cap],
            ).fetchall()
            links = [dict(row) for row in link_rows]
    return {"memory_id": memory_id, "root_id": root_id, "records": records, "links": links}


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
    with read_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM memories ORDER BY updated_at DESC LIMIT ?", (limit_value,)
        ).fetchall()
    return [row_to_dict(r) for r in rows]


def get_record(memory_id: str) -> dict[str, Any] | None:
    with read_conn() as conn:
        row = conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
    return row_to_dict(row) if row else None


def timeline(query: str = "", scope: str = "", limit: int = 20) -> list[dict[str, Any]]:
    from memorycore.storage.search import search_memory_records
    rows = search_memory_records(
        query, types=["timeline_event", "decision", "feedback"],
        scope=scope, status="active", limit=limit,
    )
    return sorted(rows, key=lambda r: r.get("created_at", ""))


_stats_cache: dict[str, Any] = {}
_stats_cache_ts: float = 0.0
_STATS_TTL = 10.0  # seconds


def get_memory_stats() -> dict[str, Any]:
    import time as _time
    global _stats_cache, _stats_cache_ts
    if _stats_cache and (_time.monotonic() - _stats_cache_ts) < _STATS_TTL:
        return _stats_cache
    with read_conn() as conn:
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
    result = {
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
    import time as _time
    _stats_cache = result
    _stats_cache_ts = _time.monotonic()
    return result
