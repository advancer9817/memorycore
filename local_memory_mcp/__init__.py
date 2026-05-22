"""local-memory-mcp — Structured agent memory with SQLite/FTS5 + Qdrant.

Re-exports all public symbols for backward compatibility with existing
code that does ``import local_memory_mcp as lm``.
"""
from __future__ import annotations

# Keep pyright quiet about re-exports
from typing import Any

from local_memory_mcp.injection_guard import (
    BOUNDARY_NOTICE,
    check_memory_for_injection,
    warning_for_filtered_memory,
)
from local_memory_mcp.privacy import redact_record_fields, redact_secrets

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
    cleanup_expired_messages,
    consolidate,
    curator_report,
    export_html,
    get_active_warnings,
    get_agent_inbox,
    get_audit_log,
    get_memory_stats,
    get_record,
    list_agent_presence,
    list_recent,
    log_audit_event,
    managed_conn,
    query_links,
    search_memory_records,
    send_agent_message,
    timeline,
    update_agent_presence,
    update_memory_content,
    update_status,
)

# ── Server (MCP tools + CLI) ──────────────────────────────────────────────────
from local_memory_mcp.server import main, memory_link_add, memory_link_query

__all__ = [
    "BOUNDARY_NOTICE",
    "DEFAULT_ROOT",
    "_INITIALIZED_DB_PATHS",
    "SQLITE_VEC_AVAILABLE",
    "add_feedback",
    "add_link",
    "add_memory_record",
    "build_context_pack",
    "check_memory_for_injection",
    "cleanup_expired_messages",
    "config_path",
    "consolidate",
    "curator_report",
    "export_html",
    "get_active_warnings",
    "get_agent_inbox",
    "get_audit_log",
    "get_memory_stats",
    "get_record",
    "list_agent_presence",
    "list_recent",
    "load_config",
    "log_audit_event",
    "main",
    "managed_conn",
    "memory_link_add",
    "memory_link_query",
    "normalize_list",
    "query_links",
    "redact_record_fields",
    "redact_secrets",
    "search_memory_records",
    "send_agent_message",
    "timeline",
    "update_agent_presence",
    "update_memory_content",
    "update_status",
    "warning_for_filtered_memory",
]
