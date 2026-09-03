"""Audit event logging and retrieval."""
from __future__ import annotations

import threading
import uuid
from typing import Any

from memorycore.models import as_json, now
from memorycore.storage.db import _managed_query, managed_conn, read_conn


def log_audit_event(
    event_type: str,
    memory_id: str | None = None,
    agent: str = "unknown",
    detail: dict[str, Any] | None = None,
) -> threading.Thread:
    """Write one row to audit_events. Fire-and-forget; never raises. Returns the thread."""
    params = (str(uuid.uuid4()), event_type, memory_id, agent, as_json(detail or {}), now())

    def _write():
        try:
            with managed_conn() as conn:
                conn.execute(
                    "INSERT INTO audit_events (id, event_type, memory_id, agent, detail_json, created_at) VALUES (?,?,?,?,?,?)",
                    params,
                )
        except Exception:
            pass

    t = threading.Thread(target=_write, daemon=True)
    t.start()
    return t


def get_audit_log(
    memory_id: str | None = None,
    event_type: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return audit events, optionally filtered by memory_id or event_type."""
    clauses: list[str] = []
    params: list[Any] = []
    if memory_id:
        clauses.append("memory_id = ?")
        params.append(memory_id)
    if event_type:
        clauses.append("event_type = ?")
        params.append(event_type)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    limit = max(1, min(int(limit), 500))
    params.append(limit)
    with read_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM audit_events {where} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def cleanup_stale_audit_events(retention_days: int = 90) -> int:
    """Delete audit events older than retention_days. Returns deleted count."""
    import datetime
    from memorycore.models import local_now
    cutoff = (local_now() - datetime.timedelta(days=retention_days)).isoformat(timespec="seconds")
    with managed_conn() as conn:
        cursor = conn.execute("DELETE FROM audit_events WHERE created_at < ?", (cutoff,))
        return cursor.rowcount if cursor is not None else 0

