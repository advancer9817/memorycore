"""Same-port frontend control service routes for memorycore."""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import threading
import time
import yaml
from dataclasses import dataclass, field
from ipaddress import ip_address
from typing import Any
from urllib.parse import parse_qs

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from memorycore.models import MEMORY_TYPES, STATUSES, VALID_RELATION_TYPES, load_config, config_path, row_to_dict
from memorycore.storage.db import _managed_query
from memorycore.storage import (
    add_feedback,
    add_link,
    add_memory_record,
    atomize_report,
    build_context_pack,
    curator_report,
    dashboard_payload,
    get_active_warnings,
    get_audit_log,
    get_context_quality_stats,
    get_memory_stats,
    get_record,
    entity_search,
    list_recent,
    memory_lineage,
    memory_backup,
    memory_export,
    memory_import,
    query_links,
    search_memory_records,
    timeline,
    update_memory_content,
    update_status,
)

from memorycore.frontend_helpers import (
    _app_details,
    _apps_list,
    _context_lab_test,
    _delete_app_memories,
    _memory_categories,
    _memory_item,
    _read_memorycore_config,
    _simple_memory,
    _source_agents_for_app_id,
    _write_memorycore_config,
)
from memorycore.frontend_http import _bool_q, _int_q, _list_q, _str_q

# In-process mirror of maintenance job results (thread → GET {job_id} polling).
_maintenance_jobs: dict[str, dict[str, Any]] = {}
_maintenance_jobs_lock = threading.Lock()


def _run_data_maintenance_job_thread(job_id: str, plan_token: str, action: str = "archive", limit: int = 0) -> None:
    from memorycore.storage.maintenance import run_data_maintenance_job
    try:
        result = run_data_maintenance_job(job_id, plan_token, limit=limit, action=action)
    except Exception as exc:  # run_* already records failures; keep a final fallback
        result = {
            "job_id": job_id,
            "plan_token": plan_token,
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
        }
    with _maintenance_jobs_lock:
        _maintenance_jobs[job_id] = result


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
        links = query_links(parts[1], direction="both", limit=50)
        # 过滤掉 supports/part_of 自动关系，只保留语义链接
        _NOISE_RELATIONS = {"supports", "part_of"}
        outgoing = [l for l in links.get("outgoing", []) if l.get("relation_type") not in _NOISE_RELATIONS]
        incoming = [l for l in links.get("incoming", []) if l.get("relation_type") not in _NOISE_RELATIONS]
        ids = [link["target_id"] for link in outgoing] + [link["source_id"] for link in incoming]
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
    if parts == ["dashboard"] and method == "GET":
        from memorycore.frontend_helpers import dashboard_v1_payload
        return dashboard_v1_payload(limit=_int_q(query, "limit", 200))
    if parts == ["health-score"] and method == "GET":
        from memorycore.frontend_helpers import health_score_v1_payload
        return health_score_v1_payload()
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
        page = _int_q(query, "page", 1)
        page_size = min(_int_q(query, "page_size", 50), 200)
        from memorycore.storage.db import read_conn as _rc2
        from memorycore.models import row_to_dict as _rtd2
        source_agents = _source_agents_for_app_id(parts[1])
        if not source_agents:
            return {"memories": [], "total": 0, "page": page, "page_size": page_size}
        sph = ", ".join("?" for _ in source_agents)
        offset = max(page - 1, 0) * page_size
        with _rc2() as conn:
            total_row = conn.execute(
                f"SELECT COUNT(*) as cnt FROM memories "
                f"WHERE source_agent IN ({sph}) AND last_accessed_at IS NOT NULL",
                tuple(source_agents),
            ).fetchone()
            rows = conn.execute(
                f"SELECT * FROM memories "
                f"WHERE source_agent IN ({sph}) AND last_accessed_at IS NOT NULL "
                f"ORDER BY last_accessed_at DESC LIMIT ? OFFSET ?",
                (*source_agents, page_size, offset),
            ).fetchall()
        return {
            "memories": [_memory_item(_rtd2(row)) for row in rows],
            "total": int(total_row["cnt"] if total_row else 0),
            "page": page,
            "page_size": page_size,
        }
    if len(parts) == 2 and parts[0] == "apps" and method == "DELETE":
        return _delete_app_memories(parts[1])
    if len(parts) == 2 and parts[0] == "apps" and method == "PUT":
        return _app_details(parts[1])
    if parts == ["context", "test"] and method == "POST":
        return _context_lab_test(body)
    if parts == ["config"] and method == "GET":
        return _read_memorycore_config()
    if parts == ["config"] and method in {"PUT", "POST"}:
        return _write_memorycore_config(body)
    if len(parts) >= 2 and parts[0] == "config" and method in {"PUT", "POST"}:
        return body
    if parts == ["profile"] and method == "GET":
        from memorycore.storage.profile import profile_detail
        return profile_detail(include_sources=True)
    if parts == ["profile", "extract"] and method == "POST":
        from memorycore.storage.profile import extract_profile, profile_detail
        apply = bool(body.get("apply", False))
        only_new = bool(body.get("only_new", False))
        result = extract_profile(apply=apply, only_new=only_new)
        if result.get("errors"):
            return result
        return {**result, "profile": profile_detail(include_sources=True)}
    if parts == ["profile", "extract"] and method == "GET":
        from memorycore.storage.profile import extract_profile
        # Dry-run preview without writing to the store.
        result = extract_profile(apply=False, only_new=(query.get("only_new") or ["false"])[0] == "true")
        return result
    if parts == ["maintenance", "plan"] and method == "GET":
        action = (query.get("action") or ["archive"])[0]
        # limit 默认 0 = 无条数上限（单次处理全部候选）；显式正整数仍可限制。
        if action == "merge":
            from memorycore.storage.maintenance import plan_data_maintenance_merge
            return plan_data_maintenance_merge(limit=_int_q(query, "limit", 0))
        if action == "clean":
            from memorycore.storage.maintenance import plan_data_maintenance_clean
            return plan_data_maintenance_clean(limit=_int_q(query, "limit", 0))
        from memorycore.storage.maintenance import plan_data_maintenance
        return plan_data_maintenance(limit=_int_q(query, "limit", 0))
    if parts == ["maintenance", "candidates"] and method == "GET":
        action = (query.get("action") or ["clean"])[0]
        if action != "clean":
            raise ValueError("unsupported maintenance candidate action: only clean is supported")
        from memorycore.storage.maintenance import list_data_maintenance_clean_candidates
        offset = max(0, _int_q(query, "offset", 0) or 0)
        limit = max(1, _int_q(query, "limit", 100) or 100)
        return list_data_maintenance_clean_candidates(offset=offset, limit=limit)
    if parts == ["maintenance", "latest"] and method == "GET":
        from memorycore.storage.maintenance import get_latest_maintenance_job
        return get_latest_maintenance_job() or {"job_id": None, "status": "none"}
    if parts == ["maintenance", "execute"] and method == "POST":
        plan_token = str(body.get("plan_token") or "").strip()
        if not plan_token:
            raise ValueError("plan_token is required (GET /api/v1/maintenance/plan first)")
        action = str(body.get("action") or "archive").strip() or "archive"
        if action not in ("archive", "merge", "clean"):
            raise ValueError(f"unsupported maintenance action: {action}")
        from memorycore.storage.maintenance import (
            create_maintenance_job,
            run_data_maintenance_job,
        )
        job = create_maintenance_job(plan_token, kind=action)
        # limit 与 plan 阶段保持一致（默认 0 = 无上限）；不一致会导致
        # plan_token 失配（stale），故 execute 显式透传同一 limit。
        limit = int(body.get("limit") or 0)
        thread = threading.Thread(
            target=_run_data_maintenance_job_thread,
            args=(job["job_id"], plan_token, action, limit),
            daemon=True,
        )
        thread.start()
        return job
    if len(parts) == 2 and parts[0] == "maintenance" and method == "GET":
        job_id = parts[1]
        with _maintenance_jobs_lock:
            memory_job = _maintenance_jobs.get(job_id)
        if memory_job is not None:
            return memory_job
        from memorycore.storage.maintenance import get_maintenance_job
        job = get_maintenance_job(job_id)
        if job is None:
            raise LookupError(f"maintenance job not found: {job_id}")
        return job
    raise LookupError(f"route not found: /api/v1/{'/'.join(parts)}")
