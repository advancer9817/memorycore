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

from memorycore.models import MEMORY_TYPES, STATUSES, VALID_RELATION_TYPES, load_config, config_path, row_to_dict, now
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
    memory_rebuild_vectors,
    memory_vector_audit,
    query_links,
    search_memory_records,
    timeline,
    update_memory_content,
    update_status,
)

logger = logging.getLogger(__name__)
try:
    from memorycore.storage.llm_curator_jobs import mark_stale_running_jobs_failed, _diag as _curator_diag
    _curator_diag(f"SERVICE_START: frontend.py loaded, pid={__import__('os').getpid()}")
    marked = mark_stale_running_jobs_failed()
    if marked:
        _curator_diag(f"SERVICE_START: marked {marked} stale job(s) as failed on startup")
except Exception:
    logger.debug("failed to mark stale llm curator jobs", exc_info=True)

_START_TIME = time.time()
_MUTATING_METHODS = {"POST", "PATCH", "PUT", "DELETE"}

# ---------------------------------------------------------------------------
# LLM Curator background job registry
# ---------------------------------------------------------------------------
import threading
import uuid
import signal
import atexit

_llm_curator_jobs: dict[str, dict] = {}  # job_id -> {status, result, error}
_llm_curator_lock = threading.Lock()
_latest_llm_job_id: list[str] = []  # single-element list used as mutable container
_llm_curator_thread: threading.Thread | None = None

_LLM_JOB_TTL_SECONDS = 1800  # 30 minutes


def _wait_for_curator_thread() -> None:
    """Wait for the LLM curator thread on shutdown so it can finish gracefully."""
    global _llm_curator_thread
    t = _llm_curator_thread
    if t is not None and t.is_alive():
        logger.info("Waiting for LLM curator thread to finish (up to 120s)...")
        t.join(timeout=120)
        if t.is_alive():
            logger.warning("LLM curator thread did not finish in time")

atexit.register(_wait_for_curator_thread)


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
    """Runs in a background thread; persists incremental job state to SQLite."""
    from memorycore.storage.curator_llm import run_llm_curator_incremental
    from memorycore.storage.llm_curator_jobs import update_llm_curator_job, _diag
    import threading

    _diag(f"THREAD_START: job={job_id} thread={threading.current_thread().name} pid={__import__('os').getpid()} daemon={threading.current_thread().daemon}")

    try:
        report = run_llm_curator_incremental(
            job_id=job_id,
            config=cfg,
            limit=limit,
            sim_threshold=sim_threshold,
            apply=apply,
        )
        _diag(f"THREAD_DONE: job={job_id} status={report.get('status', 'done')} errors={len(report.get('errors', []))}")
        with _llm_curator_lock:
            existing = _llm_curator_jobs.get(job_id, {})
            _llm_curator_jobs[job_id] = {
                **existing,
                "status": report.get("status", "done"),
                "summary": report.get("summary", {}),
                "errors": report.get("errors", []),
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
            }
        _clear_curator_status_cache()
    except Exception as exc:
        _diag(f"THREAD_EXCEPTION: job={job_id} error={exc!r}")
        logger.warning("[llm-curator job %s] failed: %s", job_id, exc)
        update_llm_curator_job(job_id, status="failed", errors=[str(exc)], finished=True)
        with _llm_curator_lock:
            existing = _llm_curator_jobs.get(job_id, {})
            _llm_curator_jobs[job_id] = {
                **existing,
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
    _CONFIG.host = host
    _CONFIG.port = int(port)
    _CONFIG.auth_token = auth_token or ""
    _CONFIG.allow_insecure_remote = allow_insecure_remote
    _CONFIG.enabled = enabled


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
    return Response("8318 embedded frontend has been removed. Active UI is on http://127.0.0.1:18318/", status_code=404, media_type="text/plain")


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

    # /api/v1/* — native v1 routes first; legacy-only namespaces (curator,
    # governance, lineage, graph) delegate to the legacy handler below so the
    # v1 surface is a complete superset for future frontend migration.
    if parts[:1] == ["v1"]:
        _V1_LEGACY_FALLBACK = {"curator", "governance", "lineage", "graph"}
        if parts[1:2] and parts[1] in _V1_LEGACY_FALLBACK:
            parts = parts[1:]
        else:
            return _dispatch_v1_compat(method, parts[1:], query, body)

    if parts == ["curator", "last-digest"] and method == "GET":
        from pathlib import Path
        digest_file = Path.home() / ".agent-memory" / "last_curator_digest.json"
        if digest_file.exists():
            try:
                import json
                return json.loads(digest_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"changed": False, "status": "no_digest"}

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
            verbose=bool(body.get("verbose", True)),
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
        return _curator_status_payload(limit=_int_q(query, "limit", 200))
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
        ts = now()
        with _llm_curator_lock:
            _cleanup_stale_llm_jobs()
            _llm_curator_jobs[job_id] = {
                "status": "running",
                "job_id": job_id,
                "started_at": ts,
            }
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
        from memorycore.storage.llm_curator_jobs import get_latest_llm_curator_job, list_llm_curator_decisions
        job = get_latest_llm_curator_job()
        if job is None:
            return {"status": "idle", "job_id": None, "decisions": [], "total_decisions": 0}
        dec_res = list_llm_curator_decisions(job["id"], limit=200, review_status="all")
        return {
            **job,
            "job_id": job["id"],
            "decisions": dec_res.get("items", []),
            "total_decisions": dec_res.get("total", 0),
        }
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
        from memorycore.storage.llm_curator_jobs import get_llm_curator_job, list_llm_curator_decisions
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
        dec_res = list_llm_curator_decisions(job_id, limit=200, review_status="all")
        return {
            **job,
            "job_id": job["id"],
            "decisions": dec_res.get("items", []),
            "total_decisions": dec_res.get("total", 0),
        }
    if parts == ["links"] and method == "POST":
        return add_link(body.get("source_id", ""), body.get("target_id", ""), body.get("relation_type", "related_to"), body.get("weight", 1.0), body.get("note", ""), body.get("source_agent", "frontend"))
    if len(parts) == 2 and parts[0] == "links" and method == "GET":
        return query_links(parts[1], _str_q(query, "direction", "both"), _str_q(query, "relation_type", ""), _int_q(query, "limit", 50))
    if parts == ["warnings"] and method == "POST":
        return get_active_warnings(body.get("memory_ids", []), body.get("min_weight", 0.4), body.get("max_warnings", 5))

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


from memorycore.frontend_helpers import (  # noqa: E402,F401
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
from memorycore.frontend_metrics import (  # noqa: E402,F401
    _clear_curator_status_cache,
    _curator_status_payload,
    _get_curator_metrics,
    _get_governance_metrics,
    _get_recall_metrics,
)
from memorycore.frontend_http import (  # noqa: E402,F401
    _bool_q,
    _check_auth,
    _check_origin,
    _graph_payload,
    _int_q,
    _json_body,
    _json_error,
    _json_ok,
    _list_q,
    _str_q,
    _with_cors,
)
from memorycore.frontend_v1 import _dispatch_v1_compat  # noqa: E402,F401
