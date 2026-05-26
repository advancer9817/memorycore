"""Agent permission policy helpers."""
from __future__ import annotations

import uuid
from typing import Any

from local_memory_mcp.models import as_json, from_json, normalize_list, now
from local_memory_mcp.storage.audit import log_audit_event
from local_memory_mcp.storage.db import _managed_query, managed_conn


def grant_agent_permission(
    agent_id: str,
    namespace: str = "default",
    can_read: bool = True,
    can_write: bool = True,
    can_broadcast: bool = True,
    scopes: Any = None,
    types: Any = None,
    tags: Any = None,
) -> dict[str, Any]:
    ts = now()
    record_id = str(uuid.uuid4())
    with managed_conn() as conn:
        conn.execute(
            """
            INSERT INTO agent_permissions (
              id, agent_id, namespace, can_read, can_write, can_broadcast,
              scopes_json, types_json, tags_json, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(agent_id) DO UPDATE SET
              namespace=excluded.namespace,
              can_read=excluded.can_read,
              can_write=excluded.can_write,
              can_broadcast=excluded.can_broadcast,
              scopes_json=excluded.scopes_json,
              types_json=excluded.types_json,
              tags_json=excluded.tags_json,
              updated_at=excluded.updated_at
            """,
            (
                record_id,
                agent_id,
                namespace or "default",
                int(bool(can_read)),
                int(bool(can_write)),
                int(bool(can_broadcast)),
                as_json(normalize_list(scopes)),
                as_json(normalize_list(types)),
                as_json(normalize_list(tags)),
                ts,
                ts,
            ),
        )
    log_audit_event("agent_permission_upsert", agent=agent_id, detail={"namespace": namespace or "default"})
    return get_agent_permission(agent_id) or {}


def get_agent_permission(agent_id: str) -> dict[str, Any] | None:
    rows = _managed_query("SELECT * FROM agent_permissions WHERE agent_id=? LIMIT 1", (agent_id,))
    if not rows:
        return None
    row = dict(rows[0])
    row["can_read"] = bool(row["can_read"])
    row["can_write"] = bool(row["can_write"])
    row["can_broadcast"] = bool(row["can_broadcast"])
    row["scopes"] = from_json(row.pop("scopes_json", "[]"), [])
    row["types"] = from_json(row.pop("types_json", "[]"), [])
    row["tags"] = from_json(row.pop("tags_json", "[]"), [])
    return row


def get_agent_namespace(agent_id: str) -> str:
    policy = get_agent_permission(agent_id)
    if policy:
        return str(policy.get("namespace") or "default")
    return ""


def check_agent_permission(
    agent_id: str,
    operation: str,
    scope: str = "",
    memory_type: str = "",
    tags: Any = None,
) -> dict[str, Any]:
    policy = get_agent_permission(agent_id)
    if policy is None:
        return {"allowed": True, "configured": False, "namespace": ""}

    reasons: list[str] = []
    if operation.endswith(".read") and not policy["can_read"]:
        reasons.append("read_disabled")
    if operation.endswith(".write") and not policy["can_write"]:
        reasons.append("write_disabled")
    if operation == "agent.broadcast" and not policy["can_broadcast"]:
        reasons.append("broadcast_disabled")

    allowed_scopes = set(policy["scopes"])
    if scope and allowed_scopes and scope not in allowed_scopes:
        reasons.append("scope_denied")

    allowed_types = set(policy["types"])
    if memory_type and allowed_types and memory_type not in allowed_types:
        reasons.append("type_denied")

    allowed_tags = set(policy["tags"])
    requested_tags = set(normalize_list(tags))
    if requested_tags and allowed_tags and requested_tags.isdisjoint(allowed_tags):
        reasons.append("tag_denied")

    allowed = not reasons
    result = {
        "allowed": allowed,
        "configured": True,
        "namespace": policy.get("namespace", "default"),
        "reasons": reasons,
    }
    if not allowed:
        log_permission_denied(agent_id, operation, result, scope=scope, memory_type=memory_type, tags=normalize_list(tags))
    return result


def log_permission_denied(
    agent_id: str,
    operation: str,
    decision: dict[str, Any] | None = None,
    **detail: Any,
) -> None:
    payload = {"agent_id": agent_id, "operation": operation}
    if decision:
        payload.update({"namespace": decision.get("namespace"), "reasons": decision.get("reasons", [])})
    payload.update(detail)
    log_audit_event("permission_denied", agent=agent_id, detail=payload)
