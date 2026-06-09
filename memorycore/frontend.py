"""Same-port frontend control service routes for memorycore."""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import time
import yaml
from dataclasses import dataclass, field
from ipaddress import ip_address
from typing import Any
from urllib.parse import parse_qs

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from memorycore.models import MEMORY_TYPES, STATUSES, VALID_RELATION_TYPES, load_config, config_path
from memorycore.storage.db import _managed_query
from memorycore.storage import (
    add_feedback,
    add_link,
    add_memory_record,
    agent_capability_register,
    agent_capability_search,
    agent_handoff_create,
    agent_handoff_update,
    atomize_report,
    build_context_pack,
    cleanup_expired_messages,
    curator_report,
    dashboard_payload,
    get_active_warnings,
    get_agent_inbox,
    get_audit_log,
    get_context_quality_stats,
    get_memory_stats,
    get_record,
    entity_search,
    list_agent_presence,
    list_recent,
    memory_lineage,
    memory_backup,
    memory_export,
    memory_import,
    memory_rebuild_vectors,
    memory_vector_audit,
    query_links,
    search_memory_records,
    send_agent_message,
    timeline,
    update_agent_presence,
    update_memory_content,
    update_status,
)

logger = logging.getLogger(__name__)
_START_TIME = time.time()
_MUTATING_METHODS = {"POST", "PATCH", "PUT", "DELETE"}

# ---------------------------------------------------------------------------
# LLM Curator background job registry
# ---------------------------------------------------------------------------
import threading
import uuid

_llm_curator_jobs: dict[str, dict] = {}  # job_id -> {status, result, error}
_llm_curator_lock = threading.Lock()
_latest_llm_job_id: list[str] = []  # single-element list used as mutable container

_LLM_JOB_TTL_SECONDS = 1800  # 30 minutes


def _cleanup_stale_llm_jobs() -> None:
    """Remove succeeded/error jobs older than _LLM_JOB_TTL_SECONDS."""
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - _LLM_JOB_TTL_SECONDS))
    stale = [
        jid for jid, j in _llm_curator_jobs.items()
        if j.get("status") in ("done", "succeeded", "error")
        and j.get("updated_at", "9999") < cutoff
    ]
    for jid in stale:
        _llm_curator_jobs.pop(jid, None)


def _run_llm_curator_job(job_id: str, cfg: Any, limit: int, sim_threshold: float, apply: bool) -> None:
    """Runs in a daemon thread; updates _llm_curator_jobs on completion."""
    from memorycore.storage.curator_llm import run_llm_curator

    try:
        report = run_llm_curator(config=cfg, limit=limit, sim_threshold=sim_threshold, apply=apply)
        with _llm_curator_lock:
            _llm_curator_jobs[job_id] = {
                "status": "done", "result": report,
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
            }
        _clear_curator_status_cache()
    except Exception as exc:
        logger.warning("[llm-curator job %s] failed: %s", job_id, exc)
        with _llm_curator_lock:
            _llm_curator_jobs[job_id] = {
                "status": "error", "error": str(exc),
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
            }
        _clear_curator_status_cache()


@dataclass
class FrontendConfig:
    host: str = "127.0.0.1"
    port: int = 8318
    auth_token: str = ""
    allow_insecure_remote: bool = False
    max_body_bytes: int = 2_000_000
    enabled: bool = True


_CONFIG = FrontendConfig()


def configure_frontend(
    host: str = "127.0.0.1",
    port: int = 8318,
    auth_token: str = "",
    allow_insecure_remote: bool = False,
    enabled: bool = True,
) -> None:
    if enabled:
        validate_frontend_bind(host, auth_token, allow_insecure_remote)
    global _CONFIG
    _CONFIG = FrontendConfig(
        host=host, port=int(port), auth_token=auth_token or "",
        allow_insecure_remote=allow_insecure_remote, enabled=enabled,
    )


def validate_frontend_bind(host: str, auth_token: str = "", allow_insecure_remote: bool = False) -> None:
    if _is_loopback_host(host):
        return
    if auth_token or allow_insecure_remote:
        return
    raise ValueError("remote frontend bind requires --auth-token or --allow-insecure-remote")


def _is_loopback_host(host: str) -> bool:
    if host in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


async def frontend_index(request: Request) -> Response:
    if not _CONFIG.enabled:
        return Response("frontend disabled", status_code=404)
    return HTMLResponse(_FRONTEND_HTML)


async def frontend_health(request: Request) -> Response:
    try:
        stats = get_memory_stats()
        return _json_ok({"status": "ok", "total_memories": stats["total"]})
    except Exception as exc:
        logger.exception("frontend health failed")
        return _json_error("unavailable", str(exc), 503)


async def frontend_metrics(request: Request) -> Response:
    try:
        return _json_ok({**get_memory_stats(), "uptime_s": round(time.time() - _START_TIME, 1)})
    except Exception as exc:
        logger.exception("frontend metrics failed")
        return _json_error("unavailable", str(exc), 503)


async def frontend_api(request: Request) -> Response:
    if not _CONFIG.enabled:
        return _json_error("not_found", "frontend disabled", 404)
    if request.method.upper() == "OPTIONS":
        return _with_cors(Response(status_code=204))
    auth_error = _check_auth(request)
    if auth_error is not None:
        return _with_cors(auth_error)
    path = (request.path_params.get("path") or "").strip("/")
    parts = [part for part in path.split("/") if part]
    if parts[:1] != ["v1"]:
        origin_error = _check_origin(request)
        if origin_error is not None:
            return _with_cors(origin_error)
    query = parse_qs(request.url.query)
    try:
        data = await _dispatch_api(request, parts, query)
        if isinstance(data, Response):
            return _with_cors(data)
        if parts[:1] == ["v1"]:
            return _with_cors(JSONResponse(data))
        return _with_cors(_json_ok(data))
    except json.JSONDecodeError:
        return _with_cors(_json_error("bad_json", "request body must be valid JSON", 400))
    except ValueError as exc:
        return _with_cors(_json_error("bad_request", str(exc), 400))
    except LookupError as exc:
        return _with_cors(_json_error("not_found", str(exc), 404))
    except Exception as exc:
        logger.exception("frontend api failed: /api/%s", path)
        return _with_cors(_json_error("internal_error", f"{type(exc).__name__}: request failed", 500))


async def _dispatch_api(request: Request, parts: list[str], query: dict[str, list[str]]) -> Any:
    method = request.method.upper()
    body = await _json_body(request) if method in _MUTATING_METHODS else {}
    return await asyncio.to_thread(_dispatch_api_sync, method, parts, query, body)


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
        return update_memory_content(parts[1], body.get("content"), body.get("title"), body.get("status"), body.get("confidence"), body.get("importance"))
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
        cfg = load_config()
        apply = not body.get("dry_run", True)
        job_id = str(uuid.uuid4())
        with _llm_curator_lock:
            _cleanup_stale_llm_jobs()
            _llm_curator_jobs[job_id] = {"status": "running", "job_id": job_id}
            _latest_llm_job_id[:] = [job_id]
        t = threading.Thread(
            target=_run_llm_curator_job,
            args=(job_id, cfg, int(body.get("limit", 10000)), float(body.get("sim_threshold", 0.72)), apply),
            daemon=True,
            name=f"llm-curator-{job_id[:8]}",
        )
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
        return apply_governance_decision(decision["id"], source_agent="frontend")
    if parts == ["curator", "llm", "latest"] and method == "GET":
        with _llm_curator_lock:
            job_id = _latest_llm_job_id[0] if _latest_llm_job_id else None
            job = _llm_curator_jobs.get(job_id) if job_id else None
        if job is None:
            return {"status": "idle", "job_id": None}
        return {**job, "job_id": job_id}
    if len(parts) == 3 and parts[:2] == ["curator", "llm"] and method == "GET":
        job_id = parts[2]
        with _llm_curator_lock:
            job = _llm_curator_jobs.get(job_id)
        if job is None:
            raise LookupError(f"job {job_id} not found")
        return job
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
        return list_governance_decisions(_str_q(query, "review_status", None), _int_q(query, "limit", 100))
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
        archived = [update_status(str(memory_id), "archived") for memory_id in ids]
        return {"archived": [item["id"] for item in archived], "count": len(archived)}
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
        updated = [update_status(str(memory_id), status) for memory_id in ids]
        return {"updated": [item["id"] for item in updated], "state": state}
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
        rows = search_memory_records(status="active", limit=max(page * page_size, 1000))
        rows = [row for row in rows if (row.get("source_agent") or "manual") == parts[1]]
        return {"memories": [_memory_item(row) for row in rows], "total": len(rows), "page": page, "page_size": page_size}
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


def _read_memorycore_config() -> dict[str, Any]:
    cfg = load_config()
    extraction = cfg.get("extraction", {})
    embedding = cfg.get("embedding", {})
    return {
        "settings": {
            "custom_instructions": None,
        },
        "llm": {
            "extraction": {
                "base_url": extraction.get("base_url", ""),
                "api_key": extraction.get("api_key", ""),
                "model": extraction.get("model", ""),
                "temperature": extraction.get("temperature", 0.1),
                "max_tokens": extraction.get("max_tokens", 2000),
                "timeout": extraction.get("timeout", 180),
            },
            "embedding": {
                "provider": embedding.get("provider", "auto"),
                "model": embedding.get("model", "nomic-embed-text"),
                "ollama_url": embedding.get("ollama_url", "http://127.0.0.1:11434"),
                "api_url": embedding.get("api_url", ""),
                "api_key": embedding.get("api_key", ""),
                "dim": embedding.get("dim", 768),
                "timeout": embedding.get("timeout", 30),
            },
        },
    }


def _write_memorycore_config(body: dict[str, Any]) -> dict[str, Any]:
    path = config_path()
    existing: dict[str, Any] = {}
    if path.exists():
        existing = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    llm_body = body.get("llm", {})
    extraction_patch = llm_body.get("extraction", {})
    embedding_patch = llm_body.get("embedding", {})

    if extraction_patch:
        existing.setdefault("extraction", {}).update({
            k: v for k, v in extraction_patch.items() if v is not None and v != ""
        })
    if embedding_patch:
        existing.setdefault("embedding", {}).update({
            k: v for k, v in embedding_patch.items() if v is not None and v != ""
        })

    path.write_text(yaml.safe_dump(existing, allow_unicode=True, default_flow_style=False), encoding="utf-8")
    return _read_memorycore_config()


def _memory_item(record: dict[str, Any]) -> dict[str, Any]:
    tags = [str(tag) for tag in record.get("tags", [])]
    state = "archived" if record.get("status") == "archived" else "active"
    return {
        "id": record["id"],
        "content": record.get("content", ""),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "state": state,
        "app_id": record.get("source_agent") or "manual",
        "app_name": record.get("source_agent") or "manual",
        "categories": tags,
        "metadata_": record.get("metadata") or {},
    }


def _simple_memory(record: dict[str, Any]) -> dict[str, Any]:
    item = _memory_item(record)
    return {
        "id": item["id"],
        "text": item["content"],
        "content": item["content"],
        "created_at": item["created_at"],
        "state": item["state"],
        "categories": item["categories"],
        "app_name": item["app_name"],
        "metadata_": item["metadata_"],
    }


def _memory_categories() -> dict[str, Any]:
    from memorycore.storage.db import read_conn as _rc
    import json as _json
    with _rc() as conn:
        rows = conn.execute(
            "SELECT tags_json FROM memories WHERE status='active' AND tags_json IS NOT NULL AND tags_json != '[]'"
        ).fetchall()
    names: set[str] = set()
    for row in rows:
        try:
            tags = _json.loads(row[0])
            if isinstance(tags, list):
                names.update(str(t) for t in tags if t)
        except Exception:
            pass
    sorted_names = sorted(names)
    categories = [
        {"id": name, "name": name, "description": f"{name} memories", "created_at": "", "updated_at": ""}
        for name in sorted_names
    ]
    return {"categories": categories, "total": len(categories)}


_KNOWN_AGENTS = {
    "agent", "claude", "claude-code",
    "codex",
    "hermes", "hermes-cli", "hermes-default", "hermes-default-router", "hermes-research",
    "gemini",
    "opencode",
    "gpt-5.5", "gpt-5.5-router",
    "memory-rollup",
    "default-router",
    "memorycore-ui",
}

_AGENT_DISPLAY_NAME: dict[str, str] = {
    "agent": "claude",
    "claude-code": "claude",
    "hermes-cli": "hermes",
    "hermes-default": "hermes",
    "hermes-default-router": "hermes",
    "hermes-research": "hermes",
    "gpt-5.5-router": "gpt-5.5",
    "default-router": "hermes",
}

def _apps_list(
    limit: int = 50,
    name: str = "",
    is_active: str | None = "",
    sort_by: str = "name",
    sort_direction: str = "asc",
) -> dict[str, Any]:
    from datetime import datetime, timezone, timedelta
    from memorycore.storage.db import read_conn as _rc

    with _rc() as conn:
        agg_rows = conn.execute(
            "SELECT source_agent, COUNT(*) as cnt, MAX(COALESCE(updated_at, created_at)) as last_at"
            " FROM memories WHERE status='active' GROUP BY source_agent"
        ).fetchall()

    apps_by_id: dict[str, dict[str, Any]] = {}
    for row in agg_rows:
        agent_raw = str(row["source_agent"] or "manual")
        if agent_raw not in _KNOWN_AGENTS:
            continue
        app = _AGENT_DISPLAY_NAME.get(agent_raw, agent_raw)
        if name and name.lower() not in app.lower():
            continue
        existing = apps_by_id.get(app)
        if existing is None:
            apps_by_id[app] = {
                "id": app,
                "name": app,
                "total_memories_created": int(row["cnt"]),
                "total_memories_accessed": 0,
                "is_active": False,
                "status": "offline",
                "last_activity_at": str(row["last_at"] or ""),
                "last_seen_at": "",
            }
        else:
            existing["total_memories_created"] += int(row["cnt"])
            last = str(row["last_at"] or "")
            if last > str(existing.get("last_activity_at") or ""):
                existing["last_activity_at"] = last

    presence_by_id = {item["agent_id"]: item for item in list_agent_presence(limit=500)}
    now = datetime.now(timezone.utc)
    for app, item in apps_by_id.items():
        presence = presence_by_id.get(app)
        if presence and presence.get("status"):
            item["status"] = presence["status"]
            item["last_seen_at"] = presence.get("last_seen_at") or ""
            item["is_active"] = item["status"] in {"online", "idle", "busy"}
            if str(item["last_seen_at"]) > str(item.get("last_activity_at") or ""):
                item["last_activity_at"] = item["last_seen_at"]
        else:
            # Derive status from last memory activity when no live presence record
            last_ts = item.get("last_activity_at") or ""
            if last_ts:
                try:
                    ts = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    age = now - ts
                    if age < timedelta(hours=24):
                        item["status"] = "idle"
                        item["is_active"] = True
                    else:
                        item["status"] = "offline"
                except Exception:
                    item["status"] = "offline"

    if is_active in {"true", "false"}:
        expected = is_active == "true"
        apps_by_id = {key: item for key, item in apps_by_id.items() if bool(item["is_active"]) is expected}

    sort_map = {
        "name": lambda item: str(item["name"]).lower(),
        "memories": lambda item: int(item["total_memories_created"]),
        "memories_accessed": lambda item: int(item["total_memories_accessed"]),
        "last_activity": lambda item: str(item.get("last_activity_at") or ""),
        "status": lambda item: str(item.get("status") or ""),
    }
    apps = sorted(
        apps_by_id.values(),
        key=sort_map.get(sort_by, sort_map["name"]),
        reverse=sort_direction == "desc",
    )[:limit]
    return {"apps": apps, "total": len(apps), "page": 1, "page_size": limit}


def _app_details(app_id: str) -> dict[str, Any]:
    from memorycore.storage.db import read_conn as _rc
    with _rc() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM memories WHERE status='active' AND source_agent=?",
            (app_id,),
        ).fetchone()
    total = int(row["cnt"]) if row else 0
    return {
        "is_active": True,
        "total_memories_created": total,
        "total_memories_accessed": 0,
        "first_accessed": None,
        "last_accessed": None,
    }


def _delete_app_memories(app_id: str) -> dict[str, Any]:
    from memorycore.storage.db import read_conn as _rc, managed_conn as _mc
    from memorycore.models import now as _now
    with _rc() as conn:
        rows = conn.execute(
            "SELECT id FROM memories WHERE status='active' AND source_agent=?",
            (app_id,),
        ).fetchall()
    target_ids = [str(row["id"]) for row in rows]
    if not target_ids:
        return {"app_id": app_id, "archived_count": 0, "archived_ids": []}
    ts = _now()
    placeholders = ",".join("?" * len(target_ids))
    with _mc() as conn:
        conn.execute(
            f"UPDATE memories SET status='archived', updated_at=? WHERE id IN ({placeholders})",
            [ts, *target_ids],
        )
    return {"app_id": app_id, "archived_count": len(target_ids), "archived_ids": target_ids}


def _systemctl_user_show(unit: str, properties: list[str]) -> dict[str, str]:
    try:
        result = subprocess.run(
            ["systemctl", "--user", "show", unit, *[f"--property={prop}" for prop in properties]],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception as exc:
        return {"error": str(exc)}
    if result.returncode != 0:
        return {"error": (result.stderr or result.stdout or f"systemctl exited {result.returncode}").strip()}
    parsed: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            parsed[key] = value
    return parsed


_curator_status_cache: dict[str, Any] = {}
_curator_status_cache_ts: float = 0.0
_CURATOR_STATUS_TTL = 60.0  # seconds


def _clear_curator_status_cache() -> None:
    global _curator_status_cache, _curator_status_cache_ts
    _curator_status_cache = {}
    _curator_status_cache_ts = 0.0


def _latest_audit_event(event_type: str) -> dict[str, Any]:
    try:
        rows = get_audit_log(event_type=event_type, limit=1)
    except Exception:
        return {}
    if not rows:
        return {}
    row = rows[0]
    try:
        detail = json.loads(row.get("detail_json") or "{}")
    except Exception:
        detail = {}
    return {**row, "detail": detail}


def _curator_status_payload(limit: int = 200) -> dict[str, Any]:
    import time as _time
    global _curator_status_cache, _curator_status_cache_ts
    if _curator_status_cache and (_time.monotonic() - _curator_status_cache_ts) < _CURATOR_STATUS_TTL:
        return _curator_status_cache
    stats = get_memory_stats()
    report = curator_report(dry_run=True, limit=limit)
    timer = _systemctl_user_show("mcore-curator.timer", [
        "ActiveState",
        "SubState",
        "NextElapseUSecRealtime",
        "LastTriggerUSec",
    ])
    service = _systemctl_user_show("mcore-curator.service", [
        "ActiveState",
        "SubState",
        "Result",
        "ExecMainStatus",
        "ExecMainStartTimestamp",
        "ExecMainExitTimestamp",
    ])
    # Fall back to audit log when systemd timer has no history
    last_run_at = (
        service.get("ExecMainExitTimestamp")
        or timer.get("LastTriggerUSec")
        or ""
    )
    if not last_run_at:
        try:
            row = _managed_query(
                "SELECT created_at FROM audit_events WHERE event_type='curator_apply'"
                " ORDER BY created_at DESC LIMIT 1",
                (),
            )
            if row:
                last_run_at = row[0].get("created_at", "")
        except Exception:
            pass

    # Compute next run when timer is inactive (hourly schedule)
    next_run_at = timer.get("NextElapseUSecRealtime") or ""
    if not next_run_at:
        from datetime import datetime, timezone, timedelta
        now_dt = datetime.now(timezone.utc)
        next_hour = (now_dt + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        next_run_at = next_hour.isoformat()

    llm_run = _latest_audit_event("llm_curator_run")
    llm_detail = llm_run.get("detail", {})
    llm_last_run_at = llm_run.get("created_at", "")
    llm_errors = llm_detail.get("errors", []) if isinstance(llm_detail, dict) else []
    llm_last_result = "failed" if llm_errors else ("success" if llm_last_run_at else "unknown")
    with _llm_curator_lock:
        latest_job_id = _latest_llm_job_id[0] if _latest_llm_job_id else None
        latest_job = dict(_llm_curator_jobs.get(latest_job_id, {})) if latest_job_id else {}

    schedule = {
        "timer": "mcore-curator.timer",
        "service": "mcore-curator.service",
        "active_state": timer.get("ActiveState", "unknown"),
        "last_run_at": last_run_at,
        "next_run_at": next_run_at,
        "result": service.get("Result", "unknown"),
    }
    result = {
        "stats": stats,
        "curator": {
            "generated_at": report.get("generated_at"),
            "scanned": report.get("scanned", 0),
            "summary": report.get("summary", {}),
            "planned_actions": report.get("action_plan", [])[:10],
        },
        "llm_curator": {
            "last_run_at": llm_last_run_at,
            "last_result": llm_last_result,
            "summary": llm_detail.get("summary", {}) if isinstance(llm_detail, dict) else {},
            "errors": llm_errors if isinstance(llm_errors, list) else [],
            "latest_job": {**latest_job, "job_id": latest_job_id} if latest_job_id else {"status": "idle", "job_id": None},
        },
        "timer": {**timer, "LastTriggerUSec": last_run_at, "NextElapseUSecRealtime": next_run_at},
        "service": service,
        "schedules": {
            "rule_curator": schedule,
            "llm_curator": {**schedule, "last_run_at": llm_last_run_at, "result": llm_last_result},
        },
    }
    import time as _time
    _curator_status_cache = result
    _curator_status_cache_ts = _time.monotonic()
    return result


async def _json_body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if len(raw) > _CONFIG.max_body_bytes:
        raise ValueError("request body too large")
    if not raw:
        return {}
    parsed = json.loads(raw.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("request body must be a JSON object")
    return parsed


def _check_auth(request: Request) -> Response | None:
    token = _CONFIG.auth_token
    if not token:
        return None
    auth = request.headers.get("authorization", "")
    if auth != f"Bearer {token}":
        return _json_error("unauthorized", "valid bearer token required", 401)
    return None


def _check_origin(request: Request) -> Response | None:
    if request.method.upper() not in _MUTATING_METHODS:
        return None
    origin = request.headers.get("origin") or ""
    if not origin:
        return None
    host = request.headers.get("host") or ""
    if not host:
        return None
    # Compare hostnames only (strip port) so that the UI on a different port
    # (e.g. localhost:3000) can still POST to the API (e.g. localhost:8318).
    origin_host = origin.split("://")[-1].split(":")[0].split("/")[0]
    server_host = host.split(":")[0]
    # Treat localhost and 127.0.0.1 as equivalent
    loopback_aliases = {"localhost", "127.0.0.1", "::1"}
    origin_is_loopback = origin_host in loopback_aliases
    server_is_loopback = server_host in loopback_aliases
    if origin_is_loopback and server_is_loopback:
        return None
    if origin_host and server_host and origin_host != server_host:
        return _json_error("bad_origin", "mutating requests must use same origin", 403)
    return None


def _graph_payload(limit: int = 500, status: str = "active,candidate") -> dict[str, Any]:
    from memorycore.storage.db import read_conn

    status_values = [item.strip() for item in status.split(",") if item.strip()]
    include_all_statuses = not status_values or "all" in status_values

    # Prioritize nodes with higher utility: importance DESC, then feedback_score DESC,
    # then injected_count DESC — deterministic ordering that surfaces useful nodes first.
    order_clause = (
        "ORDER BY COALESCE(importance, 0.5) DESC, "
        "COALESCE(feedback_score, 0.0) DESC, "
        "COALESCE(injected_count, 0) DESC"
    )

    with read_conn() as conn:
        if include_all_statuses:
            rows = conn.execute(
                f"SELECT id, title, type, status, importance, feedback_score, injected_count, content"
                f" FROM memories {order_clause} LIMIT ?",
                (limit,),
            ).fetchall()
        else:
            placeholders = ",".join("?" * len(status_values))
            rows = conn.execute(
                f"SELECT id, title, type, status, importance, feedback_score, injected_count, content"
                f" FROM memories WHERE status IN ({placeholders}) {order_clause} LIMIT ?",
                (*status_values, limit),
            ).fetchall()

        nodes: list[dict[str, Any]] = [
            {
                "id": row[0],
                "title": (row[1] or "")[:80],
                "type": row[2] or "unknown",
                "status": row[3] or "active",
                "importance": round(float(row[4] or 0.5), 2),
                "feedback_score": round(float(row[5] or 0.0), 2),
                "injected_count": int(row[6] or 0),
                "content": (row[7] or "")[:500],
            }
            for row in rows
        ]

        node_ids = {n["id"] for n in nodes}

        # Fetch links connected to the selected node set. Chunk ids to avoid SQLite
        # parameter-limit issues when the UI requests a high graph limit, then keep
        # only links whose endpoints are both present in the returned node set.
        edges: list[dict[str, Any]] = []
        if node_ids:
            link_rows = []
            seen_links = set()
            id_list = list(node_ids)
            chunk_size = 400
            for start in range(0, len(id_list), chunk_size):
                chunk = id_list[start:start + chunk_size]
                placeholders_n = ",".join("?" * len(chunk))
                rows_for_chunk = conn.execute(
                    f"SELECT source_id, target_id, relation_type, weight"
                    f" FROM memory_links"
                    f" WHERE source_id IN ({placeholders_n}) OR target_id IN ({placeholders_n})",
                    (*chunk, *chunk),
                ).fetchall()
                for lrow in rows_for_chunk:
                    link_key = (lrow[0], lrow[1], lrow[2])
                    if link_key not in seen_links:
                        seen_links.add(link_key)
                        link_rows.append(lrow)
            edges = [
                {
                    "source": lrow[0],
                    "target": lrow[1],
                    "relation_type": lrow[2] or "related_to",
                    "weight": lrow[3] if lrow[3] is not None else 1.0,
                }
                for lrow in link_rows
                if lrow[0] in node_ids and lrow[1] in node_ids
            ]

    return {
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "status": "all" if include_all_statuses else ",".join(status_values),
            "dropped_edges": 0,
        },
    }


def _json_ok(data: Any) -> JSONResponse:
    return JSONResponse({"ok": True, "data": data})


def _json_error(code: str, message: str, status: int, detail: Any = None) -> JSONResponse:
    error: dict[str, Any] = {"code": code, "message": message}
    if detail is not None:
        error["detail"] = detail
    return JSONResponse({"ok": False, "error": error}, status_code=status)


def _with_cors(response: Response) -> Response:
    response.headers.setdefault("Access-Control-Allow-Origin", "*")
    response.headers.setdefault("Access-Control-Allow-Methods", "GET,POST,PATCH,PUT,DELETE,OPTIONS")
    response.headers.setdefault("Access-Control-Allow-Headers", "authorization,content-type")
    return response


def _str_q(query: dict[str, list[str]], key: str, default: str | None = "") -> str | None:
    values = query.get(key)
    if not values:
        return default
    return values[-1]


def _int_q(query: dict[str, list[str]], key: str, default: int) -> int:
    value = _str_q(query, key, str(default))
    return int(value or default)


def _bool_q(query: dict[str, list[str]], key: str, default: bool) -> bool:
    value = _str_q(query, key, "true" if default else "false")
    return str(value).lower() in {"1", "true", "yes", "on"}


def _list_q(query: dict[str, list[str]], key: str) -> list[str]:
    values = query.get(key) or []
    items: list[str] = []
    for value in values:
        items.extend(part.strip() for part in value.split(",") if part.strip())
    return items


_FRONTEND_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Local Memory MCP Control</title>
<style>
:root{--paper:#f7f1e8;--panel:#fffaf1;--ink:#2b2118;--muted:#7c6b5a;--line:#dfcfb8;--accent:#d97757;--bad:#a94735;--good:#6f8068}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font-family:Inter,system-ui,sans-serif}.shell{display:grid;grid-template-columns:260px 1fr;min-height:100vh}.side{border-right:1px solid var(--line);padding:20px;background:#f3eadc}.brand{font-family:Georgia,serif;font-size:28px;font-weight:700;letter-spacing:-.04em}.muted{color:var(--muted)}button,input,textarea,select{font:inherit}button{border:1px solid var(--line);border-radius:12px;background:var(--panel);padding:9px 12px;cursor:pointer}button.primary{background:var(--accent);border-color:var(--accent);color:white}nav{display:grid;gap:8px;margin-top:22px}nav button{text-align:left}nav button.active{outline:2px solid rgba(217,119,87,.35)}main{padding:24px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px}.card{border:1px solid var(--line);border-radius:18px;background:var(--panel);padding:16px}.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}.stack{display:grid;gap:10px}input,textarea,select{width:100%;border:1px solid var(--line);border-radius:12px;background:white;padding:10px}textarea{min-height:110px}.pill{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:3px 8px;color:var(--muted);font-size:12px}.err{color:var(--bad)}.ok{color:var(--good)}pre{white-space:pre-wrap;word-break:break-word;background:#f3eadc;border-radius:12px;padding:12px;max-height:420px;overflow:auto}.records{display:grid;gap:10px}.record{border:1px solid var(--line);border-radius:14px;padding:12px;background:white}.record h3{margin:0 0 8px}.hidden{display:none}@media(max-width:850px){.shell{grid-template-columns:1fr}.side{border-right:0;border-bottom:1px solid var(--line)}}
</style>
</head>
<body>
<div class="shell">
  <aside class="side">
    <div class="brand">Local Memory</div>
    <p class="muted">同端口控制台 · <code>/mcp</code> 保持可用</p>
    <label class="stack">API Token <input id="token" type="password" placeholder="Bearer token（如启用）"></label>
    <nav id="nav"></nav>
  </aside>
  <main>
    <div class="row"><h1 id="title">Overview</h1><button onclick="refresh()">刷新</button><span id="status" class="muted"></span></div>
    <section id="overview" class="view"></section>
    <section id="records" class="view hidden"></section>
    <section id="curator" class="view hidden"></section>
    <section id="agents" class="view hidden"></section>
    <section id="ops" class="view hidden"></section>
    <section id="raw" class="view hidden"><pre id="rawOut"></pre></section>
  </main>
</div>
<script>
const views = {overview:'Overview',records:'Records',curator:'Curator',agents:'Agents',ops:'Ops',raw:'Raw JSON'};
let current = 'overview';
let state = {};
const $ = id => document.getElementById(id);
function headers(){ const h={'Content-Type':'application/json'}; const t=$('token').value.trim(); if(t) h.Authorization='Bearer '+t; return h; }
async function api(path, opts={}){ const r=await fetch(path,{...opts,headers:{...headers(),...(opts.headers||{})}}); const j=await r.json(); if(!j.ok) throw new Error(j.error?.message || 'request failed'); return j.data; }
function setStatus(msg, cls='muted'){ $('status').className=cls; $('status').textContent=msg; }
function esc(s){ return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function mountNav(){ $('nav').innerHTML=Object.entries(views).map(([k,v])=>`<button class="${k===current?'active':''}" onclick="show('${k}')">${v}</button>`).join(''); }
function show(v){ current=v; mountNav(); Object.keys(views).forEach(k=>$(k).classList.toggle('hidden',k!==v)); $('title').textContent=views[v]; render(); }
async function refresh(){ try{ setStatus('加载中...'); state.dashboard=await api('/api/dashboard'); state.metrics=await api('/metrics'); setStatus('已更新','ok'); render(); }catch(e){ setStatus(e.message,'err'); } }
function render(){ if(!state.dashboard) return; const d=state.dashboard; $('overview').innerHTML=`<div class="grid"><div class="card"><h2>${d.rows.length}</h2><p>records</p></div><div class="card"><h2>${Object.keys(d.type_counts||{}).length}</h2><p>types</p></div><div class="card"><h2>${d.mailbox.length}</h2><p>messages</p></div><div class="card"><h2>${d.presence.length}</h2><p>agents</p></div></div>`; $('records').innerHTML=`<div class="grid"><div class="card stack"><h2>Create memory</h2><input id="mTitle" placeholder="title"><textarea id="mContent" placeholder="content"></textarea><select id="mType"><option>project_memory</option><option>feedback</option><option>decision</option><option>user_profile</option></select><button class="primary" onclick="createMemory()">创建</button></div><div class="card stack"><h2>Search</h2><input id="q" placeholder="query"><button onclick="searchMemories()">搜索</button></div></div><div id="recordList" class="records">${recordHtml(d.rows)}</div>`; $('curator').innerHTML=`<div class="grid"><div class="card"><h2>Action plan</h2>${(d.report.action_plan||[]).map(a=>`<p><span class="pill">${esc(a.action)}</span> ${esc(a.title||a.id)} · ${esc(a.reason)}</p>`).join('')||'<p class="muted">无计划动作</p>'}</div><div class="card stack"><h2>Apply curator</h2><p class="muted">会执行当前低风险 status transition。</p><button class="primary" onclick="applyCurator()">执行 apply</button></div></div>`; $('agents').innerHTML=`<div class="grid"><div class="card"><h2>Presence</h2>${d.presence.map(a=>`<p><b>${esc(a.agent_id)}</b> <span class="pill">${esc(a.status)}</span></p>`).join('')||'<p class="muted">无</p>'}</div><div class="card"><h2>Mailbox</h2>${d.mailbox.map(m=>`<p><b>${esc(m.subject)}</b><br><span class="muted">${esc(m.from_agent)} → ${esc(m.to_agent)}</span></p>`).join('')||'<p class="muted">无</p>'}</div></div>`; $('ops').innerHTML=`<div class="grid"><div class="card stack"><h2>Export</h2><button onclick="downloadExport()">下载 JSON</button></div><div class="card stack"><h2>Backup</h2><button onclick="backup()">创建默认备份</button></div><div class="card stack"><h2>Vector rebuild</h2><button onclick="vectorDryRun()">Dry-run</button></div></div>`; $('rawOut').textContent=JSON.stringify(d,null,2); }
function recordHtml(rows){ return rows.slice(0,80).map(r=>`<article class="record"><h3>${esc(r.title)}</h3><p>${esc(r.content)}</p><span class="pill">${esc(r.type)}</span> <span class="pill">${esc(r.status)}</span><br><code>${esc(r.id)}</code></article>`).join(''); }
async function createMemory(){ await api('/api/memories',{method:'POST',body:JSON.stringify({title:$('mTitle').value,content:$('mContent').value,type:$('mType').value,source_agent:'frontend'})}); await refresh(); }
async function searchMemories(){ const rows=await api('/api/memories?query='+encodeURIComponent($('q').value)); $('recordList').innerHTML=recordHtml(rows); }
async function applyCurator(){ await api('/api/curator/apply',{method:'POST',body:JSON.stringify({})}); await refresh(); }
async function downloadExport(){ const data=await api('/api/export'); const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'}); const a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download='mcore-export.json'; a.click(); }
async function backup(){ alert(JSON.stringify(await api('/api/backup',{method:'POST',body:'{}'}),null,2)); }
async function vectorDryRun(){ alert(JSON.stringify(await api('/api/vector/rebuild',{method:'POST',body:JSON.stringify({dry_run:true})}),null,2)); }
mountNav(); refresh();
</script>
</body>
</html>"""
