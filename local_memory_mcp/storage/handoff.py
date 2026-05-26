"""Agent handoff workflow and capability registry."""
from __future__ import annotations

import uuid
from typing import Any

from local_memory_mcp.models import as_json, from_json, normalize_list, now
from local_memory_mcp.storage.agents import send_agent_message
from local_memory_mcp.storage.audit import log_audit_event
from local_memory_mcp.storage.db import managed_conn

_HANDOFF_STATUSES = {"ack", "done", "failed"}


def agent_handoff_create(
    from_agent: str,
    to_agent: str,
    task: str,
    payload: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    priority: str = "normal",
    ttl_seconds: int | None = None,
) -> dict[str, Any]:
    correlation = correlation_id or str(uuid.uuid4())
    metadata = {
        "workflow": "handoff",
        "handoff_status": "requested",
        "correlation_id": correlation,
        "payload": payload or {},
    }
    message = send_agent_message(
        from_agent,
        to_agent,
        f"handoff: {task}",
        body=task,
        priority=priority,
        metadata=metadata,
        ttl_seconds=ttl_seconds,
    )
    if "error" in message:
        return message
    result = {**message, "workflow": "handoff", "handoff_status": "requested", "correlation_id": correlation}
    log_audit_event("agent_handoff_create", memory_id=message["id"], agent=from_agent, detail={"to": to_agent, "correlation_id": correlation})
    return result


def agent_handoff_update(
    message_id: str,
    from_agent: str,
    status: str,
    result: dict[str, Any] | None = None,
    error: str = "",
) -> dict[str, Any]:
    if status not in _HANDOFF_STATUSES:
        return {"error": f"invalid handoff status '{status}', must be one of {sorted(_HANDOFF_STATUSES)}"}
    with managed_conn() as conn:
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
    with managed_conn() as conn:
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
