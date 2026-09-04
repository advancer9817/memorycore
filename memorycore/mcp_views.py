"""MCP Dedicated Presentation Layer (Agent DTO / View Adapter).

Provides strictly isolated, lightweight presentation models for MCP tools.
Ensures that full database internal entities (with 27+ internal columns, metrics,
and operational metadata) are NOT leaked to LLM Agent context, while keeping
the underlying storage layer and HTTP REST API (for Web UI / dashboard) completely
unaffected.
"""
from __future__ import annotations

from typing import Any


def to_mcp_memory(record: dict[str, Any] | None) -> dict[str, Any] | None:
    """Project a 27-column SQLite memory row into a clean, concise MCP Agent view.

    Retains only semantic knowledge fields: id, title, content, type, tags,
    date (YYYY-MM-DD), and optional project_path. Strips all internal governance,
    status, and tracking metrics.
    """
    if not record or not isinstance(record, dict):
        return None

    updated_ts = record.get("updated_at") or record.get("created_at") or ""
    date_str = str(updated_ts)[:10] if updated_ts else ""

    item: dict[str, Any] = {
        "id": str(record.get("id") or ""),
        "title": str(record.get("title") or ""),
        "content": str(record.get("content") or ""),
        "type": str(record.get("type") or "project_memory"),
        "tags": list(record.get("tags") or []),
        "updated_at": date_str,
    }

    project_path = record.get("project_path")
    if project_path:
        item["project_path"] = str(project_path)

    return item


def to_mcp_memories(records: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Project a list of SQLite memory records to MCP Agent views."""
    if not records:
        return []
    result = []
    for r in records:
        item = to_mcp_memory(r)
        if item is not None:
            result.append(item)
    return result


def to_mcp_vector_hit(hit: Any) -> dict[str, Any]:
    """Project a Qdrant search result into a flat MCP vector hit.

    Eliminates duplicated `text` inside `payload` and removes nested payload dict.
    """
    payload = getattr(hit, "payload", None) or {}
    score = getattr(hit, "score", 0.0)
    try:
        score_val = round(float(score), 4)
    except (TypeError, ValueError):
        score_val = 0.0

    item: dict[str, Any] = {
        "id": str(getattr(hit, "id", "")),
        "score": score_val,
        "text": str(getattr(hit, "text", "")),
        "type": str(payload.get("type") or "episodic_memory"),
        "tags": list(payload.get("tags") or []),
    }

    project_path = payload.get("project_path")
    if project_path:
        item["project_path"] = str(project_path)

    return item


def to_mcp_vector_hits(hits: list[Any] | None) -> list[dict[str, Any]]:
    """Project a list of Qdrant search results to flat MCP vector hits."""
    if not hits:
        return []
    return [to_mcp_vector_hit(h) for h in hits]


def to_mcp_entity_hit(hit: dict[str, Any] | None) -> dict[str, Any] | None:
    """Project an entity search result, replacing the nested 32-column memory with McpMemory."""
    if not hit or not isinstance(hit, dict):
        return None

    raw_mem = hit.get("memory")
    try:
        boost_val = round(float(hit.get("boost", 0.0)), 3)
    except (TypeError, ValueError):
        boost_val = 0.0

    return {
        "memory_id": str(hit.get("memory_id") or ""),
        "entity": str(hit.get("entity") or ""),
        "normalized_entity": str(hit.get("normalized_entity") or ""),
        "entity_type": str(hit.get("entity_type") or ""),
        "weight": hit.get("weight", 1.0),
        "boost": boost_val,
        "memory": to_mcp_memory(raw_mem) if raw_mem else None,
    }


def to_mcp_entity_hits(hits: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Project a list of entity search hits to lightweight MCP entity hits."""
    if not hits:
        return []
    result = []
    for h in hits:
        item = to_mcp_entity_hit(h)
        if item is not None:
            result.append(item)
    return result


def to_mcp_add_result(record: dict[str, Any] | None) -> dict[str, Any]:
    """Return a lightweight receipt for memory_add instead of echoing 27 columns."""
    if not record or not isinstance(record, dict):
        return {"error": "Failed to create memory"}

    res: dict[str, Any] = {
        "id": str(record.get("id") or ""),
        "status": str(record.get("status") or "active"),
        "title": str(record.get("title") or ""),
        "type": str(record.get("type") or ""),
    }
    if record.get("source_agent"):
        res["source_agent"] = str(record["source_agent"])
    if record.get("project_path"):
        res["project_path"] = str(record["project_path"])
    if record.get("sub_ids"):
        res["sub_ids"] = record["sub_ids"]
    return res


def to_mcp_update_result(record: dict[str, Any] | None) -> dict[str, Any]:
    """Return a lightweight confirmation for memory_update."""
    if not record or not isinstance(record, dict):
        return {"error": "Failed to update memory"}
    if "error" in record:
        return {"error": str(record["error"])}

    return {
        "id": str(record.get("id") or ""),
        "updated": True,
        "title": str(record.get("title") or ""),
        "type": str(record.get("type") or ""),
    }


def to_mcp_feedback_result(raw_result: dict[str, Any] | None, memory_id: str, score: float) -> dict[str, Any]:
    """Return a concise confirmation for memory_feedback instead of echoing the entire memory record."""
    if not raw_result or not isinstance(raw_result, dict):
        return {"error": "Failed to record feedback"}

    return {
        "id": memory_id,
        "feedback_id": str(raw_result.get("feedback_id") or ""),
        "recorded": True,
        "score": score,
    }
