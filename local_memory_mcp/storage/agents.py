"""Agent mailbox and presence operations."""
from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from local_memory_mcp.models import as_json, from_json, local_now, now
from local_memory_mcp.storage.db import managed_conn
from local_memory_mcp.storage.audit import log_audit_event

_MESSAGE_PRIORITIES = {"low", "normal", "high", "urgent"}
_PRESENCE_STATUSES = {"online", "idle", "busy", "offline"}


def send_agent_message(
    from_agent: str,
    to_agent: str,
    subject: str,
    body: str = "",
    priority: str = "normal",
    metadata: dict[str, Any] | None = None,
    ttl_seconds: int | None = None,
) -> dict[str, Any]:
    if priority not in _MESSAGE_PRIORITIES:
        return {"error": f"invalid priority '{priority}', must be one of {sorted(_MESSAGE_PRIORITIES)}"}

    expires_at: str | None = None
    if ttl_seconds is not None:
        expires_at = (local_now() + timedelta(seconds=int(ttl_seconds))).isoformat(timespec="seconds")

    if to_agent == "*":
        with managed_conn() as conn:
            rows = conn.execute(
                "SELECT agent_id FROM agent_presence WHERE status IN ('online', 'idle') AND agent_id != ?",
                (from_agent,),
            ).fetchall()
        recipients = [row["agent_id"] for row in rows]
        ts = now()
        meta_json = as_json(metadata or {})
        if recipients:
            rows_to_insert = [
                (str(uuid.uuid4()), from_agent, recipient, subject, body, priority, "unread", ts, meta_json, expires_at)
                for recipient in recipients
            ]
            with managed_conn() as conn:
                conn.executemany(
                    "INSERT INTO agent_messages "
                    "(id, from_agent, to_agent, subject, body, priority, status, created_at, metadata_json, expires_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    rows_to_insert,
                )
            for msg_id, _, recipient, *_ in rows_to_insert:
                log_audit_event("agent_message_send", memory_id=msg_id, agent=from_agent, detail={
                    "message_id": msg_id, "to": recipient, "subject": subject,
                    "priority": priority, "broadcast": True,
                })
        return {"broadcast": True, "sent_to": recipients, "count": len(recipients)}

    msg_id = str(uuid.uuid4())
    ts = now()
    meta_json = as_json(metadata or {})
    with managed_conn() as conn:
        conn.execute(
            "INSERT INTO agent_messages "
            "(id, from_agent, to_agent, subject, body, priority, status, created_at, metadata_json, expires_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (msg_id, from_agent, to_agent, subject, body, priority, "unread", ts, meta_json, expires_at),
        )
    log_audit_event("agent_message_send", memory_id=msg_id, agent=from_agent, detail={
        "message_id": msg_id, "to": to_agent, "subject": subject, "priority": priority,
    })
    return {
        "id": msg_id, "from_agent": from_agent, "to_agent": to_agent,
        "subject": subject, "body": body, "priority": priority,
        "status": "unread", "created_at": ts, "read_at": None,
        "expires_at": expires_at, "metadata": metadata or {},
    }


def get_agent_inbox(
    agent_id: str,
    status: str = "",
    mark_read: bool = False,
    limit: int = 50,
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 500))
    clauses = ["to_agent = ?"]
    params: list[Any] = [agent_id]
    if status:
        clauses.append("status = ?")
        params.append(status)
    clauses.append("(expires_at IS NULL OR expires_at > ?)")
    params.append(now())
    where = " AND ".join(clauses)
    params.append(limit)
    with managed_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM agent_messages WHERE {where} ORDER BY created_at DESC, rowid DESC LIMIT ?",
            params,
        ).fetchall()
        results = [dict(r) for r in rows]
        for r in results:
            r["metadata"] = from_json(r.pop("metadata_json", "{}"), {})
        if mark_read and results:
            ids = [r["id"] for r in results if r["status"] == "unread"]
            if ids:
                conn.execute(
                    f"UPDATE agent_messages SET status='read', read_at=? WHERE id IN ({','.join('?' * len(ids))})",
                    [now()] + ids,
                )
    return results


def update_agent_presence(
    agent_id: str,
    status: str = "online",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if status not in _PRESENCE_STATUSES:
        return {"error": f"invalid status '{status}', must be one of {sorted(_PRESENCE_STATUSES)}"}
    metadata = dict(metadata or {})
    ts = now()
    with managed_conn() as conn:
        conn.execute(
            "INSERT INTO agent_presence (agent_id, status, last_seen_at, metadata_json) "
            "VALUES (?,?,?,?) "
            "ON CONFLICT(agent_id) DO UPDATE SET status=excluded.status, "
            "last_seen_at=excluded.last_seen_at, metadata_json=excluded.metadata_json",
            (agent_id, status, ts, as_json(metadata or {})),
        )
    log_audit_event("agent_presence_update", agent=agent_id, detail={"agent_id": agent_id, "status": status})
    return {"agent_id": agent_id, "status": status, "last_seen_at": ts, "metadata": metadata or {}}


def list_agent_presence(status: str = "", limit: int = 100) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 500))
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    with managed_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM agent_presence {where} ORDER BY last_seen_at DESC, rowid DESC LIMIT ?",
            params,
        ).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        d["metadata"] = from_json(d.pop("metadata_json", "{}"), {})
        results.append(d)
    return results


def cleanup_expired_messages() -> int:
    """Delete all agent_messages where expires_at is set and in the past."""
    with managed_conn() as conn:
        cur = conn.execute(
            "DELETE FROM agent_messages WHERE expires_at IS NOT NULL AND expires_at <= ?",
            (now(),),
        )
        return cur.rowcount
