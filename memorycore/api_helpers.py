"""Helper functions for frontend API responses."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import yaml

from memorycore.models import MEMORY_TYPES, load_config, config_path, row_to_dict
from memorycore.storage.db import read_conn, _managed_query

logger = logging.getLogger(__name__)

def _read_memorycore_config() -> dict[str, Any]:
    cfg = load_config()
    extraction = cfg.get("extraction", {})
    embedding = cfg.get("embedding", {})
    return {
        "settings": {
            "custom_instructions": None,
            "output_language": cfg.get("output_language", "auto"),
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
        "strategy": {
            "rule_curator": cfg.get("rule_curator", {}),
            "llm_curator": cfg.get("llm_curator", {}),
            "governance": cfg.get("governance", {}),
            "extraction_strategy": cfg.get("extraction_strategy", {}),
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

    strategy_patch = body.get("strategy", {})

    settings_patch = body.get("settings", {})
    if "output_language" in settings_patch and settings_patch["output_language"] in ("zh", "en", "auto"):
        existing["output_language"] = settings_patch["output_language"]

    for section in ("rule_curator", "llm_curator", "governance", "extraction_strategy"):
        patch = strategy_patch.get(section, {})
        if patch:
            existing.setdefault(section, {}).update(
                {k: v for k, v in patch.items() if v is not None}
            )

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


def _app_id_for_source_agent(source_agent: str | None) -> str:
    agent_raw = str(source_agent or "manual")
    return _AGENT_DISPLAY_NAME.get(agent_raw, agent_raw)


def _source_agents_for_app_id(app_id: str) -> list[str]:
    aliases = [source for source, app in _AGENT_DISPLAY_NAME.items() if app == app_id]
    if app_id not in aliases:
        aliases.append(app_id)
    return aliases


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
        app = _app_id_for_source_agent(agent_raw)
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
    source_agents = _source_agents_for_app_id(app_id)
    placeholders = ",".join("?" for _ in source_agents)
    with _rc() as conn:
        row = conn.execute(
            f"SELECT COUNT(*) as cnt FROM memories WHERE status='active' AND source_agent IN ({placeholders})",
            tuple(source_agents),
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
    source_agents = _source_agents_for_app_id(app_id)
    source_placeholders = ",".join("?" for _ in source_agents)
    with _rc() as conn:
        rows = conn.execute(
            f"SELECT id FROM memories WHERE status='active' AND source_agent IN ({source_placeholders})",
            tuple(source_agents),
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


