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

from memorycore.models import MEMORY_TYPES, STATUSES, VALID_RELATION_TYPES, load_config, config_path, row_to_dict
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

from memorycore.frontend import (
    _latest_llm_job_id,
    _llm_curator_jobs,
    _llm_curator_lock,
)
from memorycore.frontend_helpers import (
    _curator_status_cache,
    _curator_status_cache_ts,
    _systemctl_user_show,
)
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

    # For LLM Curator, we now use the jobs table directly instead of audit logs
    with _llm_curator_lock:
        latest_job_id = _latest_llm_job_id[0] if _latest_llm_job_id else None
        latest_job = dict(_llm_curator_jobs.get(latest_job_id, {})) if latest_job_id else {}

    if not latest_job:
        try:
            from memorycore.storage.llm_curator_jobs import get_latest_llm_curator_job
            job = get_latest_llm_curator_job()
            if job:
                latest_job = job
        except Exception:
            pass

    llm_errors = latest_job.get("errors", []) if isinstance(latest_job.get("errors"), list) else []

    llm_last_run_at = latest_job.get("started_at", "")
    if latest_job.get("status") == "succeeded":
        llm_last_result = "success"
    elif latest_job.get("status") == "failed":
        llm_last_result = "failed"
    elif latest_job.get("status") == "running":
        llm_last_result = "running"
    else:
        llm_last_result = "unknown"

    if "result" in latest_job:
        from memorycore.storage.governance import filter_applied_or_rejected_findings
        latest_job["result"] = filter_applied_or_rejected_findings(latest_job["result"])

    from memorycore.storage.governance import _CATEGORY_TO_DECISION_TYPE
    with _managed_query.__globals__["read_conn"]() as conn:
        rows = conn.execute(
            "SELECT decision_type, COUNT(*) as cnt FROM governance_decisions WHERE review_status IN ('needs_review', 'auto_approved') AND recommended_action != 'keep' GROUP BY decision_type"
        ).fetchall()
    active_counts = {row["decision_type"]: row["cnt"] for row in rows}

    llm_summary = latest_job.get("summary", {}) if isinstance(latest_job.get("summary"), dict) else {}
    for category, decision_type in _CATEGORY_TO_DECISION_TYPE.items():
        if category in llm_summary:
            llm_summary[category] = active_counts.get(decision_type, 0)

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
            "summary": llm_summary,
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


def _get_recall_metrics() -> dict:
    """召回效率指标：active 记忆的注入统计。"""
    from memorycore.storage.db import read_conn
    with read_conn() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*) as total_active,
                SUM(CASE WHEN injected_count = 0 THEN 1 ELSE 0 END) as never_injected,
                SUM(CASE WHEN injected_count > 0 THEN 1 ELSE 0 END) as injected,
                AVG(injected_count) as avg_injected_count,
                AVG(effectiveness_score) as avg_effectiveness
            FROM memories WHERE status = 'active'
        """).fetchone()
        total = row[0] or 1
        by_source = [
            {"source": r[0], "total": r[1], "never_injected": r[2],
             "never_injected_pct": round(r[2] * 100.0 / r[1], 1) if r[1] else 0}
            for r in conn.execute("""
                SELECT source, COUNT(*) as total,
                       SUM(CASE WHEN injected_count = 0 THEN 1 ELSE 0 END) as never
                FROM memories WHERE status = 'active'
                GROUP BY source ORDER BY total DESC LIMIT 10
            """).fetchall()
        ]
    return {
        "total_active": row[0],
        "never_injected": row[1],
        "injected": row[2],
        "never_injected_pct": round((row[1] or 0) * 100.0 / total, 1),
        "avg_injected_count": round(row[3] or 0, 2),
        "avg_effectiveness": round(row[4] or 0, 3),
        "by_source": by_source,
    }

def _get_governance_metrics() -> dict:
    """治理系统健康指标：决策状态分布与积压趋势。"""
    from memorycore.storage.db import read_conn
    with read_conn() as conn:
        status_rows = conn.execute("""
            SELECT review_status, COUNT(*) as cnt
            FROM governance_decisions
            GROUP BY review_status ORDER BY cnt DESC
        """).fetchall()
        total = sum(r[1] for r in status_rows)
        status_dist = {r[0]: r[1] for r in status_rows}

        recent_7d = conn.execute("""
            SELECT
                SUM(CASE WHEN review_status = 'applied' THEN 1 ELSE 0 END) as applied,
                SUM(CASE WHEN review_status = 'needs_review' THEN 1 ELSE 0 END) as needs_review,
                SUM(CASE WHEN review_status = 'rolled_back' THEN 1 ELSE 0 END) as rolled_back
            FROM governance_decisions
            WHERE created_at > datetime('now', '-7 days')
        """).fetchone()

    needs_review = status_dist.get("needs_review", 0)
    return {
        "total_decisions": total,
        "status_distribution": status_dist,
        "needs_review": needs_review,
        "needs_review_pct": round(needs_review * 100.0 / total, 1) if total else 0,
        "recent_7d": {
            "applied": recent_7d[0] or 0,
            "needs_review": recent_7d[1] or 0,
            "rolled_back": recent_7d[2] or 0,
        },
    }


def _get_curator_metrics() -> dict:
    """LLM Curator 运行状态指标。"""
    import os
    from pathlib import Path

    reports_dir = Path(os.environ.get("LOCAL_MEMORY_ROOT", ".")) / "reports"
    llm_reports = sorted(reports_dir.glob("llm-curator-*.json"), reverse=True) if reports_dir.exists() else []

    latest_report = None
    latest_size = 0
    if llm_reports:
        latest_report = llm_reports[0].name
        latest_size = llm_reports[0].stat().st_size

    total_reports = len(llm_reports)
    total_size_mb = round(sum(f.stat().st_size for f in llm_reports) / (1024 * 1024), 1) if llm_reports else 0

    from memorycore.storage.db import read_conn
    with read_conn() as conn:
        llm_source_count = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE source = 'llm_curator'"
        ).fetchone()[0]

    return {
        "latest_report": latest_report,
        "latest_report_size_kb": round(latest_size / 1024, 1),
        "total_reports": total_reports,
        "total_reports_size_mb": total_size_mb,
        "memories_produced": llm_source_count,
    }
