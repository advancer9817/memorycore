"""local-memory-mcp — Structured agent memory with SQLite/FTS5 + Qdrant.

Re-exports all public symbols for backward compatibility with existing
code that does ``import local_memory_mcp as lm``.
"""
from __future__ import annotations

# Keep pyright quiet about re-exports
from typing import Any

# ── Models (constants + helpers) ──────────────────────────────────────────────
from local_memory_mcp.models import (
    DEFAULT_ROOT,
    _INITIALIZED_DB_PATHS,
    config_path,
    load_config,
    normalize_list,
)

SQLITE_VEC_AVAILABLE: bool = False  # removed; vector search now via vector_store.py

# ── Storage (SQLite operations) ────────────────────────────────────────────────
from local_memory_mcp.storage import (
    add_feedback,
    add_link,
    add_memory_record,
    build_context_pack,
    consolidate,
    curator_report,
    export_html,
    get_active_warnings,
    get_memory_stats,
    get_record,
    list_recent,
    managed_conn,
    query_links,
    search_memory_records,
    timeline,
    update_memory_content,
    update_status,
)

# ── Server (MCP tools + CLI) ──────────────────────────────────────────────────
from local_memory_mcp.server import main, memory_link_add, memory_link_query

__all__ = [
    "DEFAULT_ROOT",
    "_INITIALIZED_DB_PATHS",
    "SQLITE_VEC_AVAILABLE",
    "add_feedback",
    "add_link",
    "add_memory_record",
    "build_context_pack",
    "config_path",
    "consolidate",
    "curator_report",
    "export_html",
    "get_active_warnings",
    "get_memory_stats",
    "get_record",
    "list_recent",
    "load_config",
    "main",
    "managed_conn",
    "memory_link_add",
    "memory_link_query",
    "normalize_list",
    "query_links",
    "search_memory_records",
    "timeline",
    "update_memory_content",
    "update_status",
]
