"""storage package — re-exports the full public API for backward compatibility.

All imports of ``memorycore.storage`` continue to work unchanged.
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
from memorycore.storage.db import connect, managed_conn, init_db
from memorycore.storage.audit import log_audit_event, get_audit_log
from memorycore.storage.crud import (
    add_memory_record,
    update_memory_content,
    update_status,
    update_status_batch,
    add_feedback,
    list_recent,
    get_record,
    timeline,
    get_memory_stats,
    supersede_memory_record,
    memory_lineage,
)
from memorycore.storage.search import (
    search_memory_records,
    build_context_pack,
    get_active_warnings,
    get_context_quality_stats,
)
from memorycore.storage.atomization import atomize_record, atomize_report
from memorycore.storage.entities import entity_search
from memorycore.storage.links import add_link, query_links
from memorycore.storage.curator import curator_report
from memorycore.storage.rollup import rollup_report
from memorycore.storage.agents import (
    send_agent_message,
    get_agent_inbox,
    update_agent_presence,
    list_agent_presence,
    cleanup_expired_messages,
)
from memorycore.storage.transfer import (
    memory_backup,
    memory_export,
    memory_import,
    memory_rebuild_vectors,
    memory_vector_audit,
)
from memorycore.storage.handoff import (
    agent_capability_register,
    agent_capability_search,
    agent_handoff_create,
    agent_handoff_update,
)
from memorycore.storage.dashboard import dashboard_payload, export_html
from memorycore.storage.governance import (
    policy_gate,
    create_governance_decision,
    convert_llm_findings_to_decisions,
    get_governance_decision,
    get_governance_metrics,
    list_governance_decisions,
    recalibrate_governance_review_queue,
    apply_governance_decision,
    apply_governance_decisions_batch,
    reject_governance_decision,
    rollback_governance_decision,
)
from memorycore.storage.mutation_executor import query_ledger as query_governance_ledger

__all__ = [
    "connect",
    "managed_conn",
    "init_db",
    "add_memory_record",
    "update_memory_content",
    "search_memory_records",
    "build_context_pack",
    "atomize_record",
    "atomize_report",
    "entity_search",
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
    "memory_vector_audit",
    "agent_capability_register",
    "agent_capability_search",
    "agent_handoff_create",
    "agent_handoff_update",
    "get_active_warnings",
    "get_context_quality_stats",
    "supersede_memory_record",
    "memory_lineage",
    "policy_gate",
    "create_governance_decision",
    "convert_llm_findings_to_decisions",
    "list_governance_decisions",
    "recalibrate_governance_review_queue",
    "apply_governance_decision",
    "apply_governance_decisions_batch",
    "reject_governance_decision",
    "rollback_governance_decision",
    "query_governance_ledger",
]
