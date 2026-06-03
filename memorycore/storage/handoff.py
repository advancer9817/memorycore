"""Agent handoff workflow and capability registry."""
from __future__ import annotations

import uuid
from typing import Any

from memorycore.models import as_json, from_json, normalize_list, now
from memorycore.storage.agents import send_agent_message
from memorycore.storage.audit import log_audit_event
from memorycore.storage.db import managed_conn, read_conn

_HANDOFF_STATUSES = {"ack", "done", "failed"}

# Default TTL for handoff requests — auto-expire if not acknowledged
_DEFAULT_HANDOFF_TTL_SECONDS = 3600  # 1 hour


def cleanup_expired_handoffs() -> dict[str, Any]:
    """Archive agent_messages that are handoff requests and have expired.

    Called by the auto-curator thread each run. Returns count of cleaned records.
    """
    ts = now()
    with managed_conn() as conn:
        rows = conn.execute(
            """SELECT id FROM agent_messages
               WHERE expires_at IS NOT NULL AND expires_at < ?
                 AND metadata_json LIKE '%"workflow": "handoff"%'
                 AND metadata_json LIKE '%"handoff_status": "requested"%'""",
            (ts,),
        ).fetchall()
        ids = [r[0] for r in rows]
        if ids:
            conn.executemany(
                "UPDATE agent_messages SET status='read' WHERE id=?",
                [(mid,) for mid in ids],
            )
    if ids:
        log_audit_event(
            "handoff_timeout_cleanup",
            detail={"cleaned": len(ids), "message_ids": ids},
        )
    return {"cleaned": len(ids)}


def agent_handoff_create(
    from_agent: str,
    to_agent: str,
    task: str,
    payload: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    priority: str = "normal",
    ttl_seconds: int | None = _DEFAULT_HANDOFF_TTL_SECONDS,
    auto_route: bool = False,
) -> dict[str, Any]:
    """Create a structured agent handoff request message.

    Parameters
    ----------
    auto_route:
        When True and to_agent is empty or '*', automatically select the best
        available online/idle agent whose registered capabilities overlap with
        the task keywords.  Falls back to to_agent as-is if no match found.
    """
    resolved_to = to_agent

    if auto_route:
        candidate = _auto_route_agent(task, exclude=from_agent)
        if candidate:
            resolved_to = candidate

    correlation = correlation_id or str(uuid.uuid4())
    metadata = {
        "workflow": "handoff",
        "handoff_status": "requested",
        "correlation_id": correlation,
        "payload": payload or {},
    }
    message = send_agent_message(
        from_agent,
        resolved_to,
        f"handoff: {task}",
        body=task,
        priority=priority,
        metadata=metadata,
        ttl_seconds=ttl_seconds,
    )
    if "error" in message:
        return message
    result = {
        **message,
        "workflow": "handoff",
        "handoff_status": "requested",
        "correlation_id": correlation,
        "routed_to": resolved_to,
    }
    log_audit_event(
        "agent_handoff_create",
        memory_id=message["id"],
        agent=from_agent,
        detail={"to": resolved_to, "correlation_id": correlation, "auto_route": auto_route},
    )
    return result


def _auto_route_agent(task: str, exclude: str = "") -> str:
    """Find the best online/idle agent whose capabilities match the task.

    Scores agents by counting how many of their capability keywords appear in
    the task string (case-insensitive). Returns the agent_id with the highest
    score, or empty string if none found.
    """
    task_lower = task.lower()
    with read_conn() as conn:
        presence_rows = conn.execute(
            "SELECT agent_id FROM agent_presence WHERE status IN ('online', 'idle') AND agent_id != ?",
            (exclude,),
        ).fetchall()
        online_ids = {r[0] for r in presence_rows}
        if not online_ids:
            return ""
        cap_rows = conn.execute(
            "SELECT agent_id, capabilities_json FROM agent_capabilities WHERE agent_id IN ({})".format(
                ",".join("?" * len(online_ids))
            ),
            list(online_ids),
        ).fetchall()

    best_agent = ""
    best_score = 0
    for row in cap_rows:
        caps = from_json(row["capabilities_json"], [])
        score = sum(1 for cap in caps if cap.lower() in task_lower)
        if score > best_score:
            best_score = score
            best_agent = row["agent_id"]
    return best_agent


def agent_handoff_update(
    message_id: str,
    from_agent: str,
    status: str,
    result: dict[str, Any] | None = None,
    error: str = "",
) -> dict[str, Any]:
    if status not in _HANDOFF_STATUSES:
        return {"error": f"invalid handoff status '{status}', must be one of {sorted(_HANDOFF_STATUSES)}"}
    with read_conn() as conn:
        row = conn.execute("SELECT * FROM agent_messages WHERE id=?", (message_id,)).fetchone()
    if row is None:
        return {"error": f"message not found: {message_id}"}
    original = dict(row)
    metadata = from_json(original.get("metadata_json"), {})
    if metadata.get("workflow") != "handoff":
        return {"error": "message is not a handoff"}
    correlation_id = metadata.get("correlation_id") or str(uuid.uuid4())
    response_meta = {
        "workflow": "handoff",
        "handoff_status": status,
        "correlation_id": correlation_id,
        "response_to": message_id,
        "result": result or {},
        "error": error,
    }
    response = send_agent_message(
        from_agent,
        original["from_agent"],
        f"handoff {status}: {original['subject']}",
        body=error or "",
        priority=original.get("priority") or "normal",
        metadata=response_meta,
    )
    if "error" in response:
        return response
    with managed_conn() as conn:
        original_meta = {**metadata, "handoff_status": status, "last_response_id": response["id"]}
        conn.execute(
            "UPDATE agent_messages SET metadata_json=? WHERE id=?",
            (as_json(original_meta), message_id),
        )
    log_audit_event("agent_handoff_update", memory_id=message_id, agent=from_agent, detail={"status": status, "correlation_id": correlation_id})
    return {**response, "workflow": "handoff", "handoff_status": status, "correlation_id": correlation_id}


def agent_capability_register(
    agent_id: str,
    capabilities: Any,
    namespace: str = "default",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    caps = normalize_list(capabilities)
    ts = now()
    with managed_conn() as conn:
        conn.execute(
            """
            INSERT INTO agent_capabilities(agent_id, namespace, capabilities_json, metadata_json, updated_at)
            VALUES (?,?,?,?,?)
            ON CONFLICT(agent_id) DO UPDATE SET namespace=excluded.namespace,
              capabilities_json=excluded.capabilities_json, metadata_json=excluded.metadata_json,
              updated_at=excluded.updated_at
            """,
            (agent_id, namespace or "default", as_json(caps), as_json(metadata or {}), ts),
        )
    log_audit_event("agent_capability_register", agent=agent_id, detail={"namespace": namespace or "default", "capabilities": caps})
    return {"agent_id": agent_id, "namespace": namespace or "default", "capabilities": caps, "metadata": metadata or {}, "updated_at": ts}


def agent_capability_search(
    capability: str = "",
    namespace: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    cap = max(1, min(int(limit), 500))
    clauses: list[str] = []
    params: list[Any] = []
    if namespace:
        clauses.append("namespace = ?")
        params.append(namespace)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(cap)
    with read_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM agent_capabilities {where} ORDER BY updated_at DESC LIMIT ?",
            params,
        ).fetchall()
    results = []
    for row in rows:
        item = dict(row)
        item["capabilities"] = from_json(item.pop("capabilities_json", "[]"), [])
        item["metadata"] = from_json(item.pop("metadata_json", "{}"), {})
        if capability and capability not in item["capabilities"]:
            continue
        results.append(item)
    return results
