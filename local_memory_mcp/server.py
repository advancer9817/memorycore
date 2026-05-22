"""MCP server and CLI entry point for local-memory-mcp.

Contains the FastMCP instance, all @mcp.tool() registrations, the main()
CLI argument parser, and the standard if-__main__ entry point.

This module is the THIN entry layer. Business logic lives in storage.py
and models.py so that dedup.py can import from those modules directly
without hitting a circular import.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from local_memory_mcp.models import DEFAULT_ROOT, load_config
from local_memory_mcp.storage import (
    add_memory_record,
    add_feedback,
    add_link,
    build_context_pack,
    consolidate,
    curator_report,
    export_html,
    get_active_warnings,
    get_audit_log,
    get_memory_stats,
    get_record,
    list_recent,
    query_links,
    search_memory_records,
    timeline,
    update_memory_content,
    update_status,
)

__all__ = ["mcp", "main"]

mcp = FastMCP(
    "local-memory-mcp",
    instructions="Author: advancer9817-crypto <advancer9817-crypto@users.noreply.github.com>",
)

SQLITE_VEC_AVAILABLE = False  # removed; vector search now via vector_store.py (Qdrant)


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


@mcp.tool()
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
) -> dict[str, Any]:
    """Add a structured memory record to local SQLite memory."""
    return add_memory_record(
        type, title, content, scope, tags, source, source_agent,
        project_path, confidence, importance, status, decay_policy,
        related_ids, metadata,
    )


@mcp.tool()
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
def memory_context(
    task: str,
    agent: str = "agent",
    project_path: str = "",
    scope: str = "global",
    token_budget: int = 2000,
) -> dict[str, Any]:
    """Return a compact context pack for a task, grouped by memory class."""
    return build_context_pack(task, agent, project_path, scope, token_budget)


@mcp.tool()
def memory_get(id: str) -> dict[str, Any] | None:
    """Get one memory record by id."""
    return get_record(id)


@mcp.tool()
def memory_list_recent(limit: int = 10) -> list[dict[str, Any]]:
    """List recently updated memory records."""
    return list_recent(limit, cap=100)


@mcp.tool()
def memory_update_status(id: str, status: str) -> dict[str, Any]:
    """Mark a memory active/stale/archived/contradicted/promoted/candidate."""
    return update_status(id, status)


@mcp.tool()
def memory_feedback(
    id: str, score: float, note: str = "", source_agent: str = "agent"
) -> dict[str, Any]:
    """Record whether a retrieved memory helped. Score can be negative or positive."""
    return add_feedback(id, score, note, source_agent)


@mcp.tool()
def memory_timeline(query: str = "", scope: str = "", limit: int = 20) -> list[dict[str, Any]]:
    """Return decision/timeline/feedback memories in chronological order."""
    return timeline(query, scope, limit)


@mcp.tool()
def memory_consolidate(dry_run: bool = True, limit: int = 50) -> dict[str, Any]:
    """Curator helper: detect duplicate/stale candidates. v0 is dry-run oriented."""
    return consolidate(dry_run, limit)


@mcp.tool()
def memory_curator_report(
    dry_run: bool = True,
    limit: int = 500,
    stale_after_days: int = 60,
    archive_after_days: int = 120,
) -> dict[str, Any]:
    """Return memory curator candidates; optionally mark stale/archive records without deleting."""
    return curator_report(dry_run, limit, stale_after_days, archive_after_days)


@mcp.tool()
def memory_ingest(
    messages: list[dict[str, str]],
    user_id: str = "advancer",
    agent_id: str = "agent",
) -> dict[str, Any]:
    """Extract facts from a conversation and write deduplicated candidates to SQLite.

    Full pipeline: DeepSeek LLM extraction -> Qdrant dedup -> SQLite candidate.

    Args:
        messages: Conversation as [{"role": "user"|"assistant", "content": "..."}]
        user_id: User scope for vector search filters
        agent_id: Which agent produced the conversation

    Returns:
        {"added": int, "updated": int, "skipped": int, "errors": int, "elapsed_s": float}
    """
    from dedup import ingest

    try:
        result = ingest(
            messages,
            user_id=user_id,
            agent_id=agent_id,
            cfg=load_config(),
            _add_memory_fn=add_memory_record,
            _update_memory_fn=update_memory_content,
        )
        return {
            "added": result.added,
            "updated": result.updated,
            "skipped": result.skipped,
            "errors": result.errors,
            "elapsed_s": result.elapsed_s,
            "extraction_elapsed_s": result.extraction_elapsed_s,
            "degraded": False,
        }
    except Exception as exc:
        return {
            "added": 0,
            "updated": 0,
            "skipped": len(messages),
            "errors": 1,
            "elapsed_s": 0.0,
            "extraction_elapsed_s": 0.0,
            "degraded": True,
            "reason": f"ingest pipeline unavailable: {type(exc).__name__}: {exc}",
        }


@mcp.tool()
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
    from vector_store import get_vector_store

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
def memory_vector_status() -> dict[str, Any]:
    """Return Qdrant vector store status (availability, collection, count)."""
    from vector_store import get_vector_store

    try:
        vs = get_vector_store(load_config())
        return vs.status()
    except Exception as exc:
        return {"available": False, "degraded": True, "reason": f"{type(exc).__name__}: {exc}"}


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
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


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="local-memory-mcp server and CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    p_add = sub.add_parser("add")
    p_add.add_argument("type")
    p_add.add_argument("title")
    p_add.add_argument("content")
    p_add.add_argument("--scope", default="global")
    p_add.add_argument("--tags", default="")
    p_add.add_argument("--source", default="manual")
    p_add.add_argument("--source-agent", default="agent")
    p_add.add_argument("--importance", type=float, default=0.5)
    p_search = sub.add_parser("search")
    p_search.add_argument("query", nargs="?", default="")
    p_search.add_argument("--type", dest="types", action="append")
    p_search.add_argument("--limit", type=int, default=10)
    p_ctx = sub.add_parser("context")
    p_ctx.add_argument("task")
    p_ctx.add_argument("--agent", default="agent")
    p_ctx.add_argument("--scope", default="global")
    p_ctx.add_argument("--project-path", default="")
    p_ctx.add_argument("--budget", type=int, default=2000)
    p_curator = sub.add_parser("curator")
    p_curator.add_argument("--apply", action="store_true", help="mark low-risk stale/archive transitions")
    p_curator.add_argument("--limit", type=int, default=500)
    p_curator.add_argument("--stale-after-days", type=int, default=60)
    p_curator.add_argument("--archive-after-days", type=int, default=120)
    p_curator.add_argument("--summary-only", action="store_true")
    p_sem_index = sub.add_parser("semantic-index")
    p_sem_index.add_argument("--limit", type=int, default=1000)
    p_sem_index.add_argument("--force", action="store_true")
    p_sem_search = sub.add_parser("semantic-search")
    p_sem_search.add_argument("query")
    p_sem_search.add_argument("--limit", type=int, default=10)
    p_sem_search.add_argument("--status", default="active")
    sub.add_parser("semantic-status")
    p_html = sub.add_parser("html")
    p_html.add_argument("out", nargs="?", default=str(DEFAULT_ROOT / "dashboard.html"))
    p_serve = sub.add_parser("serve")
    p_serve.add_argument("--host", default="127.0.0.1", help="HTTP bind address (SSE mode)")
    p_serve.add_argument("--port", type=int, default=0, help="HTTP port (SSE mode; default=0 = stdio)")
    args = parser.parse_args(argv)
    if args.cmd == "init":
        from local_memory_mcp.storage import managed_conn

        with managed_conn():
            pass
        from local_memory_mcp.models import db_path

        print(db_path())
    elif args.cmd == "add":
        print(
            json.dumps(
                add_memory_record(
                    args.type,
                    args.title,
                    args.content,
                    scope=args.scope,
                    tags=args.tags,
                    source=args.source,
                    source_agent=args.source_agent,
                    importance=args.importance,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
    elif args.cmd == "search":
        print(
            json.dumps(
                search_memory_records(args.query, types=args.types, limit=args.limit),
                ensure_ascii=False,
                indent=2,
            )
        )
    elif args.cmd == "context":
        print(
            build_context_pack(
                args.task, args.agent, project_path=args.project_path,
                scope=args.scope, token_budget=args.budget,
            )["context"]
        )
    elif args.cmd == "curator":
        report = curator_report(
            dry_run=not args.apply,
            limit=args.limit,
            stale_after_days=args.stale_after_days,
            archive_after_days=args.archive_after_days,
        )
        payload = report["summary"] if args.summary_only else report
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.cmd in ("semantic-status", "semantic-index", "semantic-search"):
        print(
            json.dumps(
                {"error": "sqlite-vec removed; use memory_vector_search / memory_vector_status MCP tools"},
                indent=2,
            )
        )
    elif args.cmd == "html":
        export_html(Path(args.out))
    elif args.cmd == "serve":
        if args.port:
            mcp.settings.host = args.host
            mcp.settings.port = args.port
            print(f"Starting MCP server on http://{args.host}:{args.port}/mcp", file=sys.stderr)
            mcp.run(transport="streamable-http")
        else:
            mcp.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
