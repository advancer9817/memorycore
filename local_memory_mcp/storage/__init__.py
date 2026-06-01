"""storage package — re-exports the full public API for backward compatibility.

All imports of ``local_memory_mcp.storage`` continue to work unchanged.
The implementation is split across submodules:
  db.py        — connection, init_db, managed_conn
  audit.py     — log_audit_event, get_audit_log
  crud.py      — add/update/get/list memory records, feedback, stats
  search.py    — FTS search, context pack, warnings
  links.py     — add_link, query_links
  curator.py   — curator_report
  agents.py    — mailbox, presence
  transfer.py  — export/import/backup/vector rebuild
  handoff.py   — agent handoff workflow and capabilities
  dashboard.py — export_html
"""
from local_memory_mcp.storage.db import connect, managed_conn, init_db
from local_memory_mcp.storage.audit import log_audit_event, get_audit_log
from local_memory_mcp.storage.crud import (
    add_memory_record,
    update_memory_content,
    update_status,
    update_status_batch,
    add_feedback,
    list_recent,
    get_record,
    timeline,
    get_memory_stats,
)
from local_memory_mcp.storage.search import (
    search_memory_records,
    build_context_pack,
    get_active_warnings,
    get_context_quality_stats,
)
from local_memory_mcp.storage.links import add_link, query_links
from local_memory_mcp.storage.curator import curator_report
from local_memory_mcp.storage.rollup import rollup_report
from local_memory_mcp.storage.agents import (
    send_agent_message,
    get_agent_inbox,
    update_agent_presence,
    list_agent_presence,
    cleanup_expired_messages,
)
from local_memory_mcp.storage.transfer import (
    memory_backup,
    memory_export,
    memory_import,
    memory_rebuild_vectors,
)
from local_memory_mcp.storage.handoff import (
    agent_capability_register,
    agent_capability_search,
    agent_handoff_create,
    agent_handoff_update,
)
from local_memory_mcp.storage.dashboard import dashboard_payload, export_html

__all__ = [
    "connect",
    "managed_conn",
    "init_db",
    "add_memory_record",
    "update_memory_content",
    "search_memory_records",
    "build_context_pack",
    "update_status",
    "add_feedback",
    "list_recent",
    "get_record",
    "timeline",
    "add_link",
    "query_links",
    "curator_report",
    "rollup_report",
    "get_memory_stats",
    "dashboard_payload",
    "export_html",
    "log_audit_event",
    "get_audit_log",
    "send_agent_message",
    "get_agent_inbox",
    "update_agent_presence",
    "list_agent_presence",
    "cleanup_expired_messages",
    "memory_backup",
    "memory_export",
    "memory_import",
    "memory_rebuild_vectors",
    "agent_capability_register",
    "agent_capability_search",
    "agent_handoff_create",
    "agent_handoff_update",
    "get_active_warnings",
    "get_context_quality_stats",
]
