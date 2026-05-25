"""Audit event logging and retrieval."""
from __future__ import annotations

import uuid
from typing import Any

from local_memory_mcp.models import as_json, now
from local_memory_mcp.storage.db import _managed_query, managed_conn


def log_audit_event(
    event_type: str,
    memory_id: str | None = None,
    agent: str = "unknown",
    detail: dict[str, Any] | None = None,
) -> None:
    """Write one row to audit_events. Fire-and-forget; never raises."""
    try:
        with managed_conn() as conn:
            conn.execute(
                "INSERT INTO audit_events (id, event_type, memory_id, agent, detail_json, created_at) VALUES (?,?,?,?,?,?)",
                (str(uuid.uuid4()), event_type, memory_id, agent, as_json(detail or {}), now()),
            )
    except Exception:
        pass  # audit must never block the main write path


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
    rows = _managed_query(
        f"SELECT * FROM audit_events {where} ORDER BY created_at DESC LIMIT ?",
        params,
    )
    return [dict(r) for r in rows]
