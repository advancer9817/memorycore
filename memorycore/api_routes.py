"""API route dispatch for memorycore frontend."""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from memorycore.models import MEMORY_TYPES, STATUSES, VALID_RELATION_TYPES, load_config, config_path, row_to_dict
from memorycore.storage.db import _managed_query
from memorycore.storage import (
    add_feedback, add_link, add_memory_record, atomize_report,
    build_context_pack, curator_report, dashboard_payload,
    get_audit_log, get_record, entity_search,
    list_recent, memory_lineage, memory_backup, memory_export, memory_import,
    memory_rebuild_vectors, memory_vector_audit, query_links,
    search_memory_records, timeline, update_memory_content, update_status,
)
from memorycore.storage.crud import update_status_batch
from memorycore.storage.db import managed_conn
from memorycore.storage.search import get_context_quality_stats
from memorycore.api_helpers import (
    _read_memorycore_config, _write_memorycore_config,
    _memory_item, _simple_memory, _memory_categories,
    _app_id_for_source_agent, _source_agents_for_app_id,
    _apps_list, _app_details, _delete_app_memories,
    _systemctl_user_show, _clear_curator_status_cache,
    _latest_audit_event, _curator_status_payload,
    _get_recall_metrics, _get_governance_metrics, _get_curator_metrics,
)

def _graph_payload(*a, **kw):
    from memorycore.frontend import _graph_payload as _gp
    return _gp(*a, **kw)

def _int_q(*a, **kw):
    from memorycore.frontend import _int_q as _iq
    return _iq(*a, **kw)

def _str_q(*a, **kw):
    from memorycore.frontend import _str_q as _sq
    return _sq(*a, **kw)

def _bool_q(*a, **kw):
    from memorycore.frontend import _bool_q as _bq
    return _bq(*a, **kw)

def _list_q(*a, **kw):
    from memorycore.frontend import _list_q as _lq
    return _lq(*a, **kw)

logger = logging.getLogger(__name__)

def _dispatch_api_sync(method: str, parts: list[str], query: dict[str, list[str]], body: dict[str, Any]) -> Any:
    if parts == ["dashboard"] and method == "GET":
        return dashboard_payload(_int_q(query, "limit", 1000))
    if parts == ["schema", "enums"] and method == "GET":
        return {"memory_types": sorted(MEMORY_TYPES), "statuses": sorted(STATUSES), "relation_types": sorted(VALID_RELATION_TYPES)}

    if parts[:1] == ["v1"]:
        return _dispatch_v1_compat(method, parts[1:], query, body)

    if parts == ["memories"] and method == "GET":
        return search_memory_records(
            query=_str_q(query, "query", _str_q(query, "q", "")),
            types=_list_q(query, "type") or _list_q(query, "types"),
            scope=_str_q(query, "scope", ""),
            project_path=_str_q(query, "project_path", ""),
            tags=_list_q(query, "tag") or _list_q(query, "tags"),
            status=_str_q(query, "status", "active"),
            limit=_int_q(query, "limit", 50),
            date_from=_str_q(query, "date_from", ""),
            date_to=_str_q(query, "date_to", ""),
        )
    if parts == ["memories", "recent"] and method == "GET":
        return list_recent(_int_q(query, "limit", 50), cap=500)
    if parts == ["memories", "timeline"] and method == "GET":
        return timeline(_str_q(query, "query", _str_q(query, "q", "")), _str_q(query, "scope", ""), _int_q(query, "limit", 50))
    if len(parts) == 2 and parts[0] == "memories" and method == "GET":
        record = get_record(parts[1])
        if record is None:
            raise LookupError(f"memory not found: {parts[1]}")
        return record
    if parts == ["memories"] and method == "POST":
        return add_memory_record(
            body.get("type", "project_memory"), body.get("title", ""), body.get("content", ""),
            scope=body.get("scope", "global"), tags=body.get("tags"), source=body.get("source", "manual"),
            source_agent=body.get("source_agent", "frontend"), project_path=body.get("project_path", ""),
            confidence=body.get("confidence", 0.7), importance=body.get("importance", 0.5),
            status=body.get("status", "active"), decay_policy=body.get("decay_policy", "review"),
            related_ids=body.get("related_ids"), metadata=body.get("metadata"),
            atomize=body.get("atomize", "auto"),
        )
    if len(parts) == 2 and parts[0] == "memories" and method == "PATCH":
        return update_memory_content(parts[1], body.get("content"), body.get("title"), body.get("status"), body.get("confidence"), body.get("importance"), body.get("valid_from"), body.get("valid_until"))
    if len(parts) == 3 and parts[0] == "memories" and parts[2] == "status" and method == "PATCH":
        return update_status(parts[1], body.get("status", ""))
    if len(parts) == 3 and parts[0] == "memories" and parts[2] == "feedback" and method == "POST":
        return add_feedback(parts[1], body.get("score", 0), body.get("note", ""), body.get("source_agent", "frontend"))

    if parts == ["context"] and method == "POST":
        return build_context_pack(
            body.get("task", ""),
            body.get("agent", "frontend"),
            body.get("project_path", ""),
            body.get("scope", "global"),
            body.get("token_budget", 2000),
            retrieval_mode=body.get("retrieval_mode", "strict"),
            prefer_atomic=bool(body.get("prefer_atomic", True)),
            include_parent=bool(body.get("include_parent", False)),
        )
    if parts == ["context", "stats"] and method == "GET":
        return get_context_quality_stats(_int_q(query, "limit", 500))
    if parts == ["curator"] and method == "GET":
        return curator_report(
            dry_run=_bool_q(query, "dry_run", True), limit=_int_q(query, "limit", 500),
            stale_after_days=_int_q(query, "stale_after_days", 60), archive_after_days=_int_q(query, "archive_after_days", 120),
            allow_actions=_list_q(query, "allow_actions"), deny_actions=_list_q(query, "deny_actions"),
        )
    if parts == ["curator", "status"] and method == "GET":
        return _curator_status_payload(limit=_int_q(query, "limit", 10000))
    if parts == ["curator", "apply"] and method == "POST":
        result = curator_report(
            dry_run=False, limit=int(body.get("limit", 500)),
            stale_after_days=int(body.get("stale_after_days", 60)), archive_after_days=int(body.get("archive_after_days", 120)),
            allow_actions=body.get("allow_actions"), deny_actions=body.get("deny_actions"),
        )
        _clear_curator_status_cache()
        return result
    if parts == ["curator", "llm"] and method == "POST":
        from memorycore.storage.llm_curator_jobs import create_llm_curator_job
        cfg = load_config()
        apply = not body.get("dry_run", True)
        job_id = str(uuid.uuid4())
        create_llm_curator_job(
            job_id,
            params={
                "limit": int(body.get("limit", 10000)),
                "sim_threshold": float(body.get("sim_threshold", 0.55)),
                "apply": apply,
                "dry_run": not apply,
            },
            created_by=body.get("source_agent", "frontend"),
        )
        with _llm_curator_lock:
            _cleanup_stale_llm_jobs()
            _llm_curator_jobs[job_id] = {"status": "running", "job_id": job_id}
            _latest_llm_job_id[:] = [job_id]
        global _llm_curator_thread
        t = threading.Thread(
            target=_run_llm_curator_job,
            args=(job_id, cfg, int(body.get("limit", 10000)), float(body.get("sim_threshold", 0.55)), apply),
            daemon=False,
            name=f"llm-curator-{job_id[:8]}",
        )
        _llm_curator_thread = t
        t.start()
        return {"job_id": job_id, "status": "running"}
    if parts == ["curator", "llm", "apply-single"] and method == "POST":
        from memorycore.storage.governance import apply_governance_decision, convert_llm_findings_to_decisions
        category = body.get("category", "")
        finding = body.get("finding", {})
        if not category or not finding:
            raise ValueError("'category' and 'finding' are required")
        single_report: dict = {
            "semantic_duplicates": [],
            "contradictions": [],
            "importance_reassessments": [],
            "split_candidates": [],
        }
        if category not in single_report:
            raise ValueError(f"Unknown category: {category!r}")
        single_report[category] = [finding]
        decision_result = convert_llm_findings_to_decisions(single_report, auto_apply=False)
        decisions = decision_result.get("decisions", [])
        if not decisions:
            return decision_result
        decision = decisions[0]
        if decision.get("review_status") == "rejected":
            return {"decision": decision, "applied": None}
        if decision.get("review_status") == "applied":
            return {"decision": decision, "applied": {"already_applied": True}}
        return apply_governance_decision(decision["id"], source_agent="frontend")
    if parts == ["curator", "llm", "latest"] and method == "GET":
        from memorycore.storage.llm_curator_jobs import get_latest_llm_curator_job
        job = get_latest_llm_curator_job()
        if job is None:
            return {"status": "idle", "job_id": None}
        return {**job, "job_id": job["id"]}
    if len(parts) == 4 and parts[:2] == ["curator", "llm"] and parts[3] == "decisions" and method == "GET":
        from memorycore.storage.llm_curator_jobs import get_llm_curator_job, list_llm_curator_decisions
        job_id = parts[2]
        job = get_llm_curator_job(job_id)
        if job is None:
            raise LookupError(f"job {job_id} not found")
        return {
            **list_llm_curator_decisions(
                job_id,
                after=_str_q(query, "after", None),
                limit=_int_q(query, "limit", 50),
                review_status=_str_q(query, "review_status", "actionable"),
                decision_type=_str_q(query, "decision_type", None),
            ),
            "job": {**job, "job_id": job["id"]},
        }
    if len(parts) == 4 and parts[:2] == ["curator", "llm"] and parts[3] == "batches" and method == "GET":
        from memorycore.storage.llm_curator_jobs import get_llm_curator_job, list_llm_curator_batches
        job_id = parts[2]
        job = get_llm_curator_job(job_id)
        if job is None:
            raise LookupError(f"job {job_id} not found")
        return {**list_llm_curator_batches(job_id, after=_str_q(query, "after", None), limit=_int_q(query, "limit", 50)), "job": {**job, "job_id": job["id"]}}
    if len(parts) == 3 and parts[:2] == ["curator", "llm"] and method == "GET":
        from memorycore.storage.llm_curator_jobs import get_llm_curator_job
        job_id = parts[2]
        job = get_llm_curator_job(job_id)
        if job is None:
            with _llm_curator_lock:
                legacy_job = _llm_curator_jobs.get(job_id)
            if legacy_job is None:
                raise LookupError(f"job {job_id} not found")
            filtered_job = dict(legacy_job)
            if "result" in filtered_job:
                from memorycore.storage.governance import filter_applied_or_rejected_findings
                filtered_job["result"] = filter_applied_or_rejected_findings(filtered_job["result"])
            return filtered_job
        return {**job, "job_id": job["id"]}
    if parts == ["links"] and method == "POST":
        return add_link(body.get("source_id", ""), body.get("target_id", ""), body.get("relation_type", "related_to"), body.get("weight", 1.0), body.get("note", ""), body.get("source_agent", "frontend"))
    if len(parts) == 2 and parts[0] == "links" and method == "GET":
        return query_links(parts[1], _str_q(query, "direction", "both"), _str_q(query, "relation_type", ""), _int_q(query, "limit", 50))
    if parts == ["warnings"] and method == "POST":
        return get_active_warnings(body.get("memory_ids", []), body.get("min_weight", 0.4), body.get("max_warnings", 5))

    if parts == ["agents", "presence"] and method == "GET":
        return list_agent_presence(_str_q(query, "status", ""), _int_q(query, "limit", 100))
    if parts == ["agents", "presence"] and method == "POST":
        return update_agent_presence(body.get("agent_id", ""), body.get("status", "online"), body.get("metadata"))
    if len(parts) == 3 and parts[0] == "agents" and parts[2] == "inbox" and method == "GET":
        return get_agent_inbox(parts[1], _str_q(query, "status", ""), _bool_q(query, "mark_read", False), _int_q(query, "limit", 50))
    if parts == ["agents", "messages"] and method == "POST":
        return send_agent_message(body.get("from_agent", "frontend"), body.get("to_agent", ""), body.get("subject", ""), body.get("body", ""), body.get("priority", "normal"), body.get("metadata"), body.get("ttl_seconds"))
    if parts == ["agents", "messages", "cleanup"] and method == "POST":
        return {"deleted": cleanup_expired_messages()}
    if len(parts) == 3 and parts[0] == "agents" and parts[2] == "capabilities" and method == "POST":
        return agent_capability_register(parts[1], body.get("capabilities", []), body.get("namespace", "default"), body.get("metadata"))
    if parts == ["agents", "capabilities"] and method == "GET":
        return agent_capability_search(_str_q(query, "capability", ""), _str_q(query, "namespace", ""), _int_q(query, "limit", 50))
    if parts == ["handoffs"] and method == "POST":
        return agent_handoff_create(body.get("from_agent", "frontend"), body.get("to_agent", ""), body.get("task", ""), body.get("payload"), body.get("correlation_id"), body.get("priority", "normal"), body.get("ttl_seconds"))
    if len(parts) == 2 and parts[0] == "handoffs" and method == "PATCH":
        return agent_handoff_update(parts[1], body.get("from_agent", "frontend"), body.get("status", ""), body.get("result"), body.get("error", ""))

    if parts == ["governance", "decisions"] and method == "GET":
        from memorycore.storage.governance import list_governance_decisions
        return list_governance_decisions(_str_q(query, "review_status", None), _str_q(query, "decision_type", None), _int_q(query, "limit", None))
    if len(parts) == 2 and parts[0] == "governance" and parts[1] not in ("decisions", "metrics", "counts") and method == "GET":
        from memorycore.storage.governance import get_governance_decision
        decision = get_governance_decision(parts[1])
        if decision is None:
            raise LookupError(f"governance decision not found: {parts[1]}")
        return decision
    if parts == ["governance", "batch", "apply"] and method == "POST":
        from memorycore.storage.governance import apply_governance_decisions_batch
        return apply_governance_decisions_batch(body.get("decision_ids", []), source_agent=body.get("source_agent", "frontend"))
    if parts == ["governance", "recalibrate"] and method == "POST":
        from memorycore.storage.governance import recalibrate_governance_review_queue
        return recalibrate_governance_review_queue(
            limit=body.get("limit"),
            dry_run=bool(body.get("dry_run", True)),
            source_agent=body.get("source_agent", "frontend"),
        )
    if len(parts) == 3 and parts[0] == "governance" and parts[2] == "apply" and method == "POST":
        from memorycore.storage.governance import apply_governance_decision
        return apply_governance_decision(parts[1], source_agent=body.get("source_agent", "frontend"))
    if len(parts) == 3 and parts[0] == "governance" and parts[2] == "reject" and method == "POST":
        from memorycore.storage.governance import reject_governance_decision
        return reject_governance_decision(parts[1], source_agent=body.get("source_agent", "frontend"), reason=body.get("reason", ""))
    if len(parts) == 3 and parts[0] == "governance" and parts[2] == "rollback" and method == "POST":
        from memorycore.storage.governance import rollback_governance_decision
        return rollback_governance_decision(parts[1], source_agent=body.get("source_agent", "frontend"))
    if parts == ["governance", "metrics"] and method == "GET":
        from memorycore.storage.governance import get_governance_metrics
        return get_governance_metrics()
    if parts == ["governance", "counts"] and method == "GET":
        from memorycore.storage.db import read_conn
        with read_conn() as conn:
            rows = conn.execute(
                "SELECT decision_type, COUNT(*) as cnt FROM governance_decisions"
                " WHERE review_status IN ('needs_review', 'auto_approved') AND recommended_action != 'keep'"
                " GROUP BY decision_type"
            ).fetchall()
        counts: dict[str, int] = {row["decision_type"]: row["cnt"] for row in rows}
        return {
            "contradiction": counts.get("contradiction", 0),
            "semantic_duplicate": counts.get("semantic_duplicate", 0),
            "importance_reassessment": counts.get("importance_reassessment", 0),
            "split_candidate": counts.get("split_candidate", 0),
            "total": sum(counts.values()),
        }
    if len(parts) == 2 and parts[0] == "lineage" and method == "GET":
        return memory_lineage(parts[1], _int_q(query, "limit", 100))
    if parts == ["audit"] and method == "GET":
        return get_audit_log(_str_q(query, "memory_id", None), _str_q(query, "event_type", None), _int_q(query, "limit", 50))
    if parts == ["export"] and method == "GET":
        return memory_export(_bool_q(query, "include_audit", False))
    if parts == ["import"] and method == "POST":
        return memory_import(body.get("payload", body), body.get("dry_run", True), body.get("conflict_policy", "skip"))
    if parts == ["backup"] and method == "POST":
        return memory_backup(body.get("path"))
    if parts == ["vector", "status"] and method == "GET":
        from memorycore.vector_store import get_vector_store
        return get_vector_store(load_config()).status()
    if parts == ["vector", "search"] and method == "GET":
        from memorycore.vector_store import get_vector_store
        results = get_vector_store(load_config()).search(
            _str_q(query, "query", _str_q(query, "q", "")),
            top_k=_int_q(query, "top_k", 10),
            score_threshold=float(_str_q(query, "score_threshold", "0") or 0),
        )
        return [{"id": r.id, "score": round(r.score, 4), "text": r.text, "payload": r.payload} for r in results]
    if parts == ["vector", "rebuild"] and method == "POST":
        return memory_rebuild_vectors(body.get("dry_run", True), body.get("limit", 5000))
    if parts == ["vector", "audit"] and method == "GET":
        return memory_vector_audit(_bool_q(query, "dry_run", True), _int_q(query, "limit", 100))
    if parts == ["atomize"] and method == "GET":
        return atomize_report(
            record_id=_str_q(query, "record_id", "") or "",
            dry_run=_bool_q(query, "dry_run", True),
            limit=_int_q(query, "limit", 100),
            min_chars=_int_q(query, "min_chars", 600),
        )
    if parts == ["entities"] and method == "GET":
        return entity_search(_str_q(query, "query", _str_q(query, "q", "")) or "", _int_q(query, "limit", 20))

    if parts == ["metrics", "recall"] and method == "GET":
        return _get_recall_metrics()
    if parts == ["metrics", "governance"] and method == "GET":
        return _get_governance_metrics()
    if parts == ["metrics", "curator"] and method == "GET":
        return _get_curator_metrics()

    if parts == ["graph"] and method == "GET":
        status = _str_q(query, "status", "active,candidate") or "active,candidate"
        default_limit = 2000 if status == "all" else 500
        requested_limit = _int_q(query, "limit", default_limit)
        return _graph_payload(
            limit=max(1, min(requested_limit, 10000)),
            status=status,
        )
    raise LookupError(f"route not found: /api/{'/'.join(parts)}")


def _dispatch_v1_compat(
    method: str,
    parts: list[str],
    query: dict[str, list[str]],
    body: dict[str, Any],
) -> Any:
    """MemoryCore v1 REST compatibility API for external clients."""
    if (
        (parts == ["memories"] and method == "GET")
        or (parts == ["memories", "filter"] and method in {"GET", "POST"})
    ):
        page = int(body.get("page", _int_q(query, "page", 1)) or 1)
        size = int(body.get("size", _int_q(query, "size", _int_q(query, "page_size", 20))) or 20)
        search_query = body.get("search_query") if method == "POST" else None
        search_query = search_query if search_query is not None else _str_q(query, "query", _str_q(query, "q", ""))
        show_archived = bool(body.get("show_archived", False)) if method == "POST" else _bool_q(query, "show_archived", False)
        status = "" if show_archived else _str_q(query, "status", "active")
        app_ids = body.get("app_ids") or []
        category_ids = body.get("category_ids") or []
        sort_column = str(body.get("sort_column") or "created_at")
        sort_direction = str(body.get("sort_direction") or "desc").lower()

        # Fetch enough rows to paginate correctly: if no filters, get true total from DB
        has_filters = bool(search_query or app_ids or category_ids)
        if has_filters:
            # With filters: fetch all matching, paginate in Python
            fetch_limit = 5000
        else:
            # No filters: get true total count first, then only fetch the page we need
            from memorycore.storage.db import read_conn as _rc
            import sqlite3 as _sqlite3
            _status_clause = "AND status = 'active'" if status == "active" else ("AND status != 'archived'" if not show_archived else "")
            with _rc() as _conn:
                true_total = _conn.execute(
                    f"SELECT COUNT(*) FROM memories WHERE 1=1 {_status_clause}"
                ).fetchone()[0]
            fetch_limit = size  # only fetch the page we need

        if search_query:
            rows = search_memory_records(
                query=str(search_query),
                status=status,
                limit=fetch_limit if has_filters else max(size * page, 50),
            )
        elif has_filters:
            rows = search_memory_records(
                query="",
                types=_list_q(query, "type") or _list_q(query, "types"),
                scope=_str_q(query, "scope", ""),
                project_path=_str_q(query, "project_path", ""),
                tags=_list_q(query, "tag") or _list_q(query, "tags"),
                status=status,
                limit=fetch_limit,
            )
        else:
            rows = []  # no-filter path: use direct SQL below
        if app_ids:
            app_set = {str(item) for item in app_ids}
            rows = [row for row in rows if str(row.get("source_agent") or "manual") in app_set]
        if category_ids:
            cat_set = {str(item) for item in category_ids}
            rows = [row for row in rows if cat_set.intersection({str(tag) for tag in row.get("tags", [])})]
        rows.sort(key=lambda row: str(row.get(sort_column) or row.get("created_at") or ""), reverse=sort_direction != "asc")

        if has_filters:
            total = len(rows)
        else:
            total = true_total  # type: ignore[possibly-undefined]
        start = max(page - 1, 0) * size
        page_rows = rows[start:start + size] if has_filters else rows[:size]
        if not has_filters:
            # For no-filter case, fetch just the page from DB directly
            from memorycore.storage.db import read_conn as _rc2
            _status_clause2 = "AND status = 'active'" if status == "active" else ("AND status != 'archived'" if not show_archived else "")
            _sort_col = sort_column if sort_column in ("created_at", "updated_at", "importance", "feedback_score") else "created_at"
            _sort_dir = "ASC" if sort_direction == "asc" else "DESC"
            from memorycore.models import row_to_dict as _rtd
            with _rc2() as _conn:
                _rows = _conn.execute(
                    f"SELECT * FROM memories WHERE 1=1 {_status_clause2} ORDER BY {_sort_col} {_sort_dir} LIMIT ? OFFSET ?",
                    (size, start),
                ).fetchall()
            page_rows = [_rtd(r) for r in _rows]
        return {
            "items": [_memory_item(row) for row in page_rows],
            "total": total,
            "page": page,
            "size": size,
            "pages": max(1, (total + size - 1) // max(size, 1)),
        }
    if parts == ["memories"] and method == "POST":
        content = body.get("content") or body.get("text") or ""
        title = body.get("title") or str(content).strip().splitlines()[0][:88] or "MemoryCore memory"
        return add_memory_record(
            body.get("type", "project_memory"), title, content,
            scope=body.get("scope", "global"), tags=body.get("tags"), source=body.get("source", "v1-compat"),
            source_agent=body.get("source_agent", "memorycore-ui"), project_path=body.get("project_path", ""),
            confidence=body.get("confidence", 0.7), importance=body.get("importance", 0.5),
            status=body.get("status", "active"), decay_policy=body.get("decay_policy", "review"),
            related_ids=body.get("related_ids"), metadata=body.get("metadata"),
            atomize=body.get("atomize", "auto"),
        )
    if parts == ["memories"] and method == "DELETE":
        ids = body.get("memory_ids") or []
        with managed_conn() as conn:
            update_status_batch(conn, [(str(mid), "archived") for mid in ids])
        return {"archived": [str(mid) for mid in ids], "count": len(ids)}
    if parts == ["memories", "categories"] and method == "GET":
        return _memory_categories()
    if len(parts) == 2 and parts[0] == "memories" and method == "GET":
        record = get_record(parts[1])
        if record is None:
            raise LookupError(f"memory not found: {parts[1]}")
        return _simple_memory(record)
    if len(parts) == 2 and parts[0] == "memories" and method in {"PATCH", "PUT"}:
        content = body.get("content") or body.get("memory_content")
        return _memory_item(update_memory_content(parts[1], content, body.get("title"), body.get("status"), body.get("confidence"), body.get("importance")))
    if len(parts) == 2 and parts[0] == "memories" and method == "DELETE":
        return update_status(parts[1], body.get("status", "archived"))
    if len(parts) == 3 and parts[0] == "memories" and parts[2] == "access-log" and method == "GET":
        record = get_record(parts[1])
        if record is None:
            raise LookupError(f"memory not found: {parts[1]}")
        return {"total": 1, "page": _int_q(query, "page", 1), "page_size": _int_q(query, "page_size", 10), "logs": [{
            "id": record["id"],
            "app_name": record.get("source_agent") or "manual",
            "accessed_at": record.get("last_accessed_at") or record.get("updated_at"),
        }]}
    if len(parts) == 3 and parts[0] == "memories" and parts[2] == "related" and method == "GET":
        links = query_links(parts[1], direction="both", limit=20)
        ids = [link["target_id"] for link in links.get("outgoing", [])] + [link["source_id"] for link in links.get("incoming", [])]
        ids = list(dict.fromkeys(ids))  # deduplicate preserving order
        items = []
        if ids:
            from memorycore.storage.db import read_conn as _rc2
            from memorycore.models import row_to_dict as _rtd2
            placeholders = ",".join("?" * len(ids))
            with _rc2() as conn:
                rows = conn.execute(
                    f"SELECT * FROM memories WHERE id IN ({placeholders})",
                    ids,
                ).fetchall()
            record_map = {row["id"]: _rtd2(row) for row in rows}
            items = [_memory_item(record_map[mid]) for mid in ids if mid in record_map]
        return {"items": items, "total": len(items), "page": 1, "size": len(items) or 10, "pages": 1}
    if parts == ["memories", "actions", "pause"] and method == "POST":
        state = str(body.get("state") or "archived")
        status = "active" if state == "active" else "archived"
        ids = body.get("memory_ids") or []
        with managed_conn() as conn:
            update_status_batch(conn, [(str(mid), status) for mid in ids])
        return {"updated": [str(mid) for mid in ids], "state": state}
    if parts == ["stats"] and method == "GET":
        stats = get_memory_stats()
        apps = _apps_list(limit=1000)["apps"]
        return {"total_memories": stats["total"], "total_apps": len(apps), "apps": apps}
    if parts == ["entities"] and method == "GET":
        return entity_search(
            _str_q(query, "query", _str_q(query, "q", "")) or "",
            _int_q(query, "limit", 20),
            scope=_str_q(query, "scope", "") or "",
            project_path=_str_q(query, "project_path", "") or "",
        )
    if parts == ["context-traces"] and method == "GET":
        return get_context_quality_stats(_int_q(query, "limit", 500))
    if len(parts) == 1 and parts[0] == "apps" and method == "GET":
        return _apps_list(
            limit=_int_q(query, "page_size", 50),
            name=_str_q(query, "name", "") or "",
            is_active=_str_q(query, "is_active", ""),
            sort_by=_str_q(query, "sort_by", "name") or "name",
            sort_direction=_str_q(query, "sort_direction", "asc") or "asc",
        )
    if len(parts) == 2 and parts[0] == "apps" and method == "GET":
        return _app_details(parts[1])
    if len(parts) == 3 and parts[0] == "apps" and parts[2] == "memories" and method == "GET":
        page = _int_q(query, "page", 1)
        page_size = _int_q(query, "page_size", 50)
        source_agents = set(_source_agents_for_app_id(parts[1]))
        placeholders = ",".join("?" for _ in source_agents)
        offset = max(0, page - 1) * page_size
        from memorycore.storage.db import read_conn as _rc_apps
        with _rc_apps() as conn:
            total_row = conn.execute(
                f"SELECT COUNT(*) as cnt FROM memories WHERE status='active' AND source_agent IN ({placeholders})",
                tuple(source_agents),
            ).fetchone()
            rows = conn.execute(
                f"""
                SELECT * FROM memories
                WHERE status='active' AND source_agent IN ({placeholders})
                ORDER BY COALESCE(updated_at, created_at) DESC
                LIMIT ? OFFSET ?
                """,
                (*source_agents, page_size, offset),
            ).fetchall()
        return {
            "memories": [_memory_item(row_to_dict(row)) for row in rows],
            "total": int(total_row["cnt"] if total_row else 0),
            "page": page,
            "page_size": page_size,
        }
    if len(parts) == 3 and parts[0] == "apps" and parts[2] == "accessed" and method == "GET":
        return {"memories": [], "total": 0, "page": _int_q(query, "page", 1), "page_size": _int_q(query, "page_size", 50)}
    if len(parts) == 2 and parts[0] == "apps" and method == "DELETE":
        return _delete_app_memories(parts[1])
    if len(parts) == 2 and parts[0] == "apps" and method == "PUT":
        return _app_details(parts[1])
    if parts == ["config"] and method == "GET":
        return _read_memorycore_config()
    if parts == ["config"] and method in {"PUT", "POST"}:
        return _write_memorycore_config(body)
    if len(parts) >= 2 and parts[0] == "config" and method in {"PUT", "POST"}:
        return body
    raise LookupError(f"route not found: /api/v1/{'/'.join(parts)}")


