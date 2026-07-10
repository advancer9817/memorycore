"""MCP server and CLI entry point for MemoryCore.

Contains the FastMCP instance, all @mcp.tool() registrations, the main()
CLI argument parser, and the standard if-__main__ entry point.

This module is the THIN entry layer. Business logic lives in storage.py
and models.py so that dedup.py can import from those modules directly
without hitting a circular import.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from memorycore.frontend import (
    configure_frontend,
    frontend_api,
    frontend_health,
    frontend_index,
    frontend_metrics,
)

from memorycore.models import DEFAULT_ROOT, load_config, validate_config
from memorycore.storage import (
    add_memory_record,
    add_feedback,
    add_link,
    agent_capability_register as register_agent_capability,
    agent_capability_search as search_agent_capabilities,
    agent_handoff_create as create_agent_handoff,
    agent_handoff_update as update_agent_handoff,
    build_context_pack,
    curator_report,
    export_html,
    get_active_warnings,
    get_audit_log,
    get_context_quality_stats,
    get_memory_stats,
    get_record,
    entity_search,
    list_recent,
    list_governance_decisions,
    apply_governance_decision,
    memory_backup as create_memory_backup,
    memory_export as export_memory_payload,
    memory_import as import_memory_payload,
    memory_rebuild_vectors as rebuild_memory_vectors,
    memory_vector_audit as audit_memory_vectors,
    memory_lineage as get_memory_lineage,
    query_links,
    rollup_report,
    supersede_memory_record,
    search_memory_records,
    send_agent_message,
    timeline,
    update_agent_presence,
    update_memory_content,
    update_status,
)

import functools


__all__ = ["mcp", "main"]

logger = logging.getLogger(__name__)

mcp = FastMCP(
    "mcore",
)


@mcp.custom_route("/", methods=["GET"], include_in_schema=False)
async def _frontend_index_route(request):
    return await frontend_index(request)


@mcp.custom_route("/api/{path:path}", methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"], include_in_schema=False)
async def _frontend_api_route(request):
    return await frontend_api(request)


@mcp.custom_route("/health", methods=["GET"], include_in_schema=False)
async def _frontend_health_route(request):
    return await frontend_health(request)


@mcp.custom_route("/metrics", methods=["GET"], include_in_schema=False)
async def _frontend_metrics_route(request):
    return await frontend_metrics(request)


@mcp.custom_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD"], include_in_schema=False)
async def _frontend_proxy_route(request):
    return await frontend_index(request)

SQLITE_VEC_AVAILABLE = False  # removed; vector search now via vector_store.py (Qdrant)


def _safe_tool(fn):
    """Wrap an MCP tool so unhandled exceptions return {"error": ...} instead of crashing."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            logger.error("MCP tool %s failed: %s", fn.__name__, exc, exc_info=True)
            return {"error": f"{type(exc).__name__}: {exc}"}
    return wrapper


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


@mcp.tool()
@_safe_tool
def memory_add(
    type: str,
    title: str,
    content: str,
    scope: str = "global",
    tags: list[str] | str | None = None,
    source: str = "manual",
    source_agent: str = "agent",
    project_path: str = "",
    confidence: float = 0.70,
    importance: float = 0.50,
    status: str = "active",
    decay_policy: str = "review",
    related_ids: list[str] | str | None = None,
    metadata: dict[str, Any] | None = None,
    valid_from: str | None = None,
    valid_until: str | None = None,
    atomize: str | bool = "auto",
) -> dict[str, Any]:
    """Add a structured memory record to local SQLite memory."""
    return add_memory_record(
        type, title, content, scope, tags, source, source_agent,
        project_path, confidence, importance, status, decay_policy,
        related_ids, metadata, valid_from=valid_from, valid_until=valid_until,
        atomize=atomize,
    )


@mcp.tool()
@_safe_tool
def memory_search(
    query: str = "",
    types: list[str] | str | None = None,
    scope: str = "",
    project_path: str = "",
    tags: list[str] | str | None = None,
    status: str = "active",
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Search structured memory with SQLite FTS5 plus filters."""
    return search_memory_records(query, types, scope, project_path, tags, status, limit)


@mcp.tool()
@_safe_tool
def memory_context(
    task: str,
    agent: str = "agent",
    project_path: str = "",
    scope: str = "global",
    token_budget: int = 2000,
    retrieval_mode: str = "strict",
    prefer_atomic: bool = True,
    include_parent: bool = False,
) -> dict[str, Any]:
    """Return a compact context pack for a task, grouped by memory class."""
    return build_context_pack(
        task,
        agent,
        project_path,
        scope,
        token_budget,
        retrieval_mode=retrieval_mode,
        prefer_atomic=prefer_atomic,
        include_parent=include_parent,
    )


@mcp.tool()
@_safe_tool
def memory_context_stats(limit: int = 500) -> dict[str, Any]:
    """Return context pack quality trend metrics."""
    return get_context_quality_stats(limit=limit)


@mcp.tool()
@_safe_tool
def memory_get(id: str) -> dict[str, Any] | None:
    """Get one memory record by id."""
    return get_record(id)


@mcp.tool()
@_safe_tool
def memory_list_recent(limit: int = 10) -> list[dict[str, Any]]:
    """List recently updated memory records."""
    return list_recent(limit, cap=100)


@mcp.tool()
@_safe_tool
def memory_feedback(
    id: str, score: float, note: str = "", source_agent: str = "agent"
) -> dict[str, Any]:
    """Record whether a retrieved memory helped. Score can be negative or positive."""
    return add_feedback(id, score, note, source_agent)


@mcp.tool()
@_safe_tool
def memory_timeline(query: str = "", scope: str = "", limit: int = 20) -> list[dict[str, Any]]:
    """Return decision/timeline/feedback memories in chronological order."""
    return timeline(query, scope, limit)


@mcp.tool()
@_safe_tool
def memory_entity_search(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Search active memories by deterministic entity and alias index."""
    return entity_search(query, limit=limit)


@mcp.tool()
@_safe_tool
def memory_ingest(
    messages: list[dict[str, str]],
    user_id: str = "default",
    agent_id: str = "agent",
    timeout_s: int = 120,
) -> dict[str, Any]:
    """Extract facts from a conversation and write deduplicated candidates to SQLite.

    Full pipeline: DeepSeek LLM extraction -> Qdrant dedup -> SQLite candidate.

    Args:
        messages: Conversation as [{"role": "user"|"assistant", "content": "..."}]
        user_id: User scope for vector search filters
        agent_id: Which agent produced the conversation
        timeout_s: Hard timeout in seconds (default 120)

    Returns:
        {"added": int, "updated": int, "skipped": int, "errors": int, "elapsed_s": float}
    """
    import threading
    from memorycore.dedup import ingest

    result_box: list = []
    exc_box: list = []

    def _run():
        try:
            result_box.append(ingest(
                messages,
                user_id=user_id,
                agent_id=agent_id,
                cfg=load_config(),
                _add_memory_fn=add_memory_record,
                _update_memory_fn=update_memory_content,
            ))
        except Exception as exc:
            exc_box.append(exc)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=float(timeout_s))

    if t.is_alive():
        return {
            "added": 0, "updated": 0, "skipped": len(messages), "errors": 1,
            "elapsed_s": float(timeout_s), "extraction_elapsed_s": 0.0,
            "degraded": True, "reason": f"ingest timed out after {timeout_s}s",
        }
    if exc_box:
        exc = exc_box[0]
        return {
            "added": 0, "updated": 0, "skipped": len(messages), "errors": 1,
            "elapsed_s": 0.0, "extraction_elapsed_s": 0.0,
            "degraded": True,
            "reason": f"ingest pipeline unavailable: {type(exc).__name__}: {exc}",
        }
    result = result_box[0]
    cfg = load_config()
    ext_api_key = (
        cfg.get("extraction", {}).get("api_key", "")
        or cfg.get("llm", {}).get("api_key", "")
        or ""
    )
    warning = None
    if result.added == 0 and result.updated == 0 and result.errors == 0 and not ext_api_key:
        warning = "extraction skipped: no LLM API key configured (set extraction.api_key in config.yaml)"
    return {
        "added": result.added,
        "updated": result.updated,
        "skipped": result.skipped,
        "errors": result.errors,
        "elapsed_s": result.elapsed_s,
        "extraction_elapsed_s": result.extraction_elapsed_s,
        "degraded": False,
        **({"warning": warning} if warning else {}),
    }


@mcp.tool()
@_safe_tool
def memory_vector_search(
    query: str,
    top_k: int = 10,
    score_threshold: float = 0.0,
) -> list[dict[str, Any]]:
    """Semantic search via Qdrant vector store (nomic-embed-text embeddings).

    Args:
        query: Natural language search query
        top_k: Maximum results to return
        score_threshold: Minimum cosine similarity (0.0 = no filter)

    Returns:
        List of {"id", "score", "text", "payload"} dicts, sorted by score desc.
    """
    from memorycore.vector_store import get_vector_store

    try:
        vs = get_vector_store(load_config())
        results = vs.search(query, top_k=top_k, score_threshold=score_threshold)
        return [
            {"id": r.id, "score": round(r.score, 4), "text": r.text, "payload": r.payload}
            for r in results
        ]
    except Exception as exc:
        return [{"degraded": True, "reason": f"vector store unavailable: {type(exc).__name__}: {exc}"}]


@mcp.tool()
@_safe_tool
def memory_vector_status() -> dict[str, Any]:
    """Return Qdrant vector store status (availability, collection, count)."""
    from memorycore.vector_store import get_vector_store

    try:
        vs = get_vector_store(load_config())
        return vs.status()
    except Exception as exc:
        return {"available": False, "degraded": True, "reason": f"{type(exc).__name__}: {exc}"}


@_safe_tool
def memory_vector_audit(dry_run: bool = True, limit: int = 100) -> dict[str, Any]:
    """Audit SQLite active memories against Qdrant points and optionally rebuild missing vectors."""
    return audit_memory_vectors(dry_run=dry_run, limit=limit)


@mcp.tool()
@_safe_tool
def memory_link_add(
    source_id: str,
    target_id: str,
    relation_type: str = "related_to",
    weight: float = 1.0,
    note: str = "",
    source_agent: str = "agent",
) -> dict[str, Any]:
    """Create a directed link between two memories.

    Relation types:
      related_to  - general association (default)
      supersedes  - source replaces/updates target (newer fact)
      contradicts - source conflicts with target
      supports    - source provides evidence for target
      part_of     - source is a component of target

    Upserts on (source_id, target_id, relation_type) - safe to call repeatedly.

    Args:
        source_id: ID of the source memory
        target_id: ID of the target memory
        relation_type: One of the 5 valid types above
        weight: Link strength 0.0-1.0 (default 1.0)
        note: Optional human-readable annotation
        source_agent: Agent creating the link

    Returns:
        The created/updated link record.
    """
    try:
        return add_link(source_id, target_id, relation_type, weight, note, source_agent)
    except ValueError as exc:
        return {"error": str(exc)}


@mcp.tool()
@_safe_tool
def memory_link_query(
    memory_id: str,
    direction: str = "both",
    relation_type: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    """Return all links connected to a memory.

    Args:
        memory_id: The memory to query links for
        direction: 'outgoing' (links from this memory), 'incoming' (links to this memory), 'both'
        relation_type: Filter by relation type (empty = all types)
        limit: Max links per direction (default 50)

    Returns:
        {"memory_id": str, "outgoing": [...], "incoming": [...], "total": int}
    """
    try:
        return query_links(memory_id, direction, relation_type, limit)
    except ValueError as exc:
        return {"error": str(exc)}


@_safe_tool
def memory_lineage(memory_id: str, limit: int = 100) -> dict[str, Any]:
    """Return the supersession lineage for a memory without mutating records."""
    return get_memory_lineage(memory_id, limit=limit)


@mcp.tool()
@_safe_tool
def memory_supersede(
    old_id: str,
    new_id: str,
    source_agent: str = "agent",
    note: str = "",
) -> dict[str, Any]:
    """Mark an older memory as superseded by a newer memory and write an audit event."""
    return supersede_memory_record(old_id, new_id, source_agent=source_agent, note=note)


@mcp.tool()
@_safe_tool
def memory_warnings(
    memory_ids: list[str],
    min_weight: float = 0.4,
    max_warnings: int = 5,
) -> list[dict[str, Any]]:
    """Return active contradicts/supersedes warnings for a set of memory IDs.

    Args:
        memory_ids: List of memory IDs to check for conflicts
        min_weight: Minimum link weight to include (default 0.4)
        max_warnings: Maximum warnings to return (default 5)

    Returns:
        List of {"source_id", "target_id", "relation_type", "severity", "weight", "reason"} dicts,
        sorted by severity (high first) then weight descending.
    """
    return get_active_warnings(memory_ids, min_weight=min_weight, max_warnings=max_warnings)


def governance_decisions(review_status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    """Return governance decisions ordered by newest first."""
    return list_governance_decisions(review_status=review_status, limit=limit)


@mcp.tool()
@_safe_tool
def memory_audit_log(
    memory_id: str | None = None,
    event_type: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return audit events for memory writes, updates, and status changes.

    Args:
        memory_id: Filter by a specific memory record ID (optional)
        event_type: Filter by event type, e.g. memory_add, memory_update, memory_status_change (optional)
        limit: Maximum number of events to return (default 50, max 500)

    Returns:
        List of audit event dicts ordered by created_at desc.
    """
    return get_audit_log(memory_id=memory_id, event_type=event_type, limit=limit)


@mcp.tool()
@_safe_tool
def memory_update(
    id: str,
    content: str | None = None,
    title: str | None = None,
    status: str | None = None,
    confidence: float | None = None,
    importance: float | None = None,
) -> dict[str, Any]:
    """Update an existing memory record's fields.

    Only provided (non-None) fields are updated. Returns the updated record.

    Args:
        id: Memory record ID
        content: New content text (optional)
        title: New title (optional)
        status: New status — active/stale/archived/contradicted/promoted/candidate (optional)
        confidence: New confidence 0.0-1.0 (optional)
        importance: New importance 0.0-1.0 (optional)

    Returns:
        The updated memory record dict.
    """
    try:
        return update_memory_content(id, content, title, status, confidence, importance)
    except ValueError as exc:
        return {"error": str(exc)}


@mcp.tool()
@_safe_tool
def memory_export(
    include_audit: bool = False,
    memories_only: bool = False,
) -> dict[str, Any]:
    """Export memory data as a schema-versioned JSON-compatible payload.

    Set memories_only=True to export only durable cross-device knowledge
    (memories, feedback_events, memory_links) — suitable for git-based sync.
    """
    return export_memory_payload(include_audit=include_audit, memories_only=memories_only)


@mcp.tool()
@_safe_tool
def memory_import(
    payload: dict[str, Any],
    dry_run: bool = True,
    conflict_policy: str = "skip",
) -> dict[str, Any]:
    """Import a schema-versioned memory payload with dry-run conflict reporting.

    conflict_policy: skip | replace | newer
      newer = keep whichever row has the later updated_at (best for multi-device sync)
    """
    return import_memory_payload(payload, dry_run=dry_run, conflict_policy=conflict_policy)


@mcp.tool()
@_safe_tool
def memory_backup(path: str | None = None) -> dict[str, Any]:
    """Create a SQLite backup using the SQLite backup API."""
    return create_memory_backup(path)


@_safe_tool
def memory_rebuild_vectors(dry_run: bool = True, limit: int = 5000) -> dict[str, Any]:
    """Rebuild Qdrant vectors from SQLite memory rows."""
    return rebuild_memory_vectors(dry_run=dry_run, limit=limit)


@mcp.tool()
@_safe_tool
def memory_stats() -> dict[str, Any]:
    """Return memory statistics grouped by type, status, and agent, with aggregate scores."""
    return get_memory_stats()


def agent_handoff_create(
    from_agent: str,
    to_agent: str,
    task: str,
    payload: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    priority: str = "normal",
    ttl_seconds: int | None = 3600,
    auto_route: bool = False,
) -> dict[str, Any]:
    """Create a structured agent handoff request message.

    Set auto_route=True to automatically select the best online agent whose
    capabilities match the task keywords, ignoring the to_agent value.
    ttl_seconds defaults to 3600 (1 hour); set to None to disable expiry.
    """
    return create_agent_handoff(from_agent, to_agent, task, payload, correlation_id, priority, ttl_seconds, auto_route)


def agent_handoff_update(
    message_id: str,
    from_agent: str,
    status: str,
    result: dict[str, Any] | None = None,
    error: str = "",
) -> dict[str, Any]:
    """Acknowledge, complete, or fail an agent handoff request."""
    return update_agent_handoff(message_id, from_agent, status, result, error)


def agent_capability_register(
    agent_id: str,
    capabilities: list[str] | str,
    namespace: str = "default",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Register an agent's capabilities for handoff routing."""
    return register_agent_capability(agent_id, capabilities, namespace, metadata)


def agent_capability_search(
    capability: str = "",
    namespace: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Find agents by capability and optional namespace."""
    return search_agent_capabilities(capability, namespace, limit)


def agent_presence_update(
    agent_id: str,
    status: str = "online",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Update an agent's presence status (heartbeat).

    Args:
        agent_id: The agent identifier
        status: online, idle, busy, or offline
        metadata: Optional key-value metadata (e.g. current task)

    Returns:
        The updated presence record.
    """
    return update_agent_presence(agent_id, status=status, metadata=metadata)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

from memorycore.server_runtime import main  # noqa: E402,F401
