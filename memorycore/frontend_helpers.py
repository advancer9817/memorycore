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
    timeline,
    update_memory_content,
    update_status,
)
def _context_lab_test(body: dict[str, Any]) -> dict[str, Any]:
    query = body.get("query", "")
    if not query:
        raise ValueError("'query' is required")
    token_budget = int(body.get("token_budget", 2000))
    result = build_context_pack(
        query,
        agent="context-lab",
        project_path=body.get("project_path", ""),
        scope=body.get("scope", "global"),
        token_budget=token_budget,
        retrieval_mode=body.get("retrieval_mode", "strict"),
        prefer_atomic=bool(body.get("prefer_atomic", True)),
        include_parent=bool(body.get("include_parent", False)),
        verbose=True,
    )
    records = result.get("records", [])
    items = []
    for rank, record in enumerate(records, 1):
        content = ""
        if record.get("id"):
            full = get_record(record["id"])
            if full:
                content = (full.get("content") or "")[:200]
        telemetry = result.get("telemetry", {})
        items.append({
            "rank": rank,
            "id": record.get("id", ""),
            "title": record.get("title", ""),
            "content": content,
            "type": record.get("type", ""),
            "importance": float(full.get("importance", 0.0)) if full else 0.0,
            "rank_score": 0.0,
            "retrieval_sources": full.get("tags", []) if full else [],
            "vector_score": 0.0,
        })
    return {
        "items": items,
        "trace": {
            "total_candidates": telemetry.get("total_candidates", 0),
            "used_count": telemetry.get("used_count", 0),
            "filtered_count": telemetry.get("filtered_count", 0),
            "vector_hits": telemetry.get("vector_hits", 0),
            "entity_hits": telemetry.get("entity_hits", 0),
            "vector_avg_score": telemetry.get("vector_avg_score", 0),
            "retrieval_mode": telemetry.get("retrieval_mode", "strict"),
            "hit_rate": telemetry.get("hit_rate", 0),
            "cross_retrieval_rate": telemetry.get("cross_retrieval_rate", 0),
        },
    }


def _mask_secret(value: str) -> str:
    """Return a masked view of a secret; empty stays empty.

    Used so the unauthenticated /api/v1/config endpoint never leaks the full
    API key (e.g. 'sk-****abcd'). Values containing the mask are rejected on
    write so a GET→PUT round-trip cannot overwrite the real key.
    """
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:3]}****{value[-4:]}"


def _is_masked_secret(value: Any) -> bool:
    return isinstance(value, str) and "****" in value


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
                "api_key": _mask_secret(str(extraction.get("api_key", ""))),
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
                "api_key": _mask_secret(str(embedding.get("api_key", ""))),
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
            k: v for k, v in extraction_patch.items() if v is not None and v != "" and not _is_masked_secret(v)
        })
    if embedding_patch:
        existing.setdefault("embedding", {}).update({
            k: v for k, v in embedding_patch.items() if v is not None and v != "" and not _is_masked_secret(v)
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
    "llm_curator", "frontend", "memorycore-smoke-test",
}

# Raw source_agent → display/app id. Alias groups collapse onto one canonical
# name; entries below cover every distinct source_agent seen in production
# (17 raw names as of 2026-08-25). Anything else displays verbatim.
_AGENT_DISPLAY_NAME: dict[str, str] = {
    # Alias groups — Claude / Hermes families.
    "agent": "claude",
    "claude-code": "claude",
    "hermes-cli": "hermes",
    "hermes-default": "hermes",
    "hermes-default-router": "hermes",
    "hermes-research": "hermes",
    "default-router": "hermes",
    # gpt-5.5 family.
    "gpt-5.5-router": "gpt-5.5",
    # All mcore internal subsystems collapse onto 'mcore'
    "frontend": "mcore",
    "memory-rollup": "mcore",
    "llm_curator": "mcore",
    "llm-curator": "mcore",
    "curator": "mcore",
    "memorycore-ui": "mcore",
}

_DEFAULT_APP_METADATA: dict[str, dict[str, str]] = {
    "claude": {
        "display_name": "Claude Code",
        "description": "Anthropic Claude Code 命令行交互智能体",
        "category": "agent",
    },
    "hermes": {
        "display_name": "Hermes Agent",
        "description": "Hermes 个人全能 Agent 与长期记忆中心",
        "category": "agent",
    },
    "codex": {
        "display_name": "Codex CLI",
        "description": "代码编写与执行辅助 Agent",
        "category": "agent",
    },
    "mcore": {
        "display_name": "MemoryCore",
        "description": "mcore 核心记忆中枢自省、治理与控制台",
        "category": "system",
    },
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
        accessed_rows = conn.execute(
            "SELECT source_agent, COUNT(*) as cnt FROM memories"
            " WHERE last_accessed_at IS NOT NULL GROUP BY source_agent"
        ).fetchall()

    accessed_by_agent = {str(row["source_agent"] or "manual"): int(row["cnt"]) for row in accessed_rows}

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
                "display_name": _DEFAULT_APP_METADATA.get(app, {}).get("display_name", app.capitalize()),
                "description": _DEFAULT_APP_METADATA.get(app, {}).get("description", ""),
                "category": _DEFAULT_APP_METADATA.get(app, {}).get("category", "agent"),
                "total_memories_created": int(row["cnt"]),
                "total_memories_accessed": accessed_by_agent.get(agent_raw, 0),
                "is_active": False,
                "status": "offline",
                "last_activity_at": str(row["last_at"] or ""),
                "last_seen_at": "",
            }
        else:
            existing["total_memories_created"] += int(row["cnt"])
            existing["total_memories_accessed"] += accessed_by_agent.get(agent_raw, 0)
            last = str(row["last_at"] or "")
            if last > str(existing.get("last_activity_at") or ""):
                existing["last_activity_at"] = last

    presence_by_id = {item["agent_id"]: item for item in list_agent_presence(limit=500)}
    now = datetime.now(timezone.utc)
    for app, item in apps_by_id.items():
        presence = presence_by_id.get(app)
        if presence:
            import json
            try:
                meta = json.loads(presence.get("metadata_json") or "{}")
                if meta.get("display_name"):
                    item["display_name"] = meta["display_name"]
                if meta.get("description"):
                    item["description"] = meta["description"]
                if "is_active" in meta:
                    item["is_active"] = bool(meta["is_active"])
            except Exception:
                pass
            if presence.get("status"):
                item["status"] = presence["status"]
                item["last_seen_at"] = presence.get("last_seen_at") or ""
                if "is_active" not in item:
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
        "display_name": lambda item: str(item["display_name"]).lower(),
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
    import json
    from memorycore.storage.db import read_conn as _rc
    source_agents = _source_agents_for_app_id(app_id)
    placeholders = ", ".join("?" for _ in source_agents)
    with _rc() as conn:
        row = conn.execute(
            f"SELECT COUNT(*) as cnt FROM memories WHERE status='active' AND source_agent IN ({placeholders})",
            tuple(source_agents),
        ).fetchone()
        accessed = conn.execute(
            f"SELECT COUNT(*) as cnt, MIN(last_accessed_at) as first_ts, MAX(last_accessed_at) as last_ts "
            f"FROM memories WHERE source_agent IN ({placeholders}) AND last_accessed_at IS NOT NULL",
            tuple(source_agents),
        ).fetchone()
        p_row = conn.execute("SELECT * FROM agent_presence WHERE agent_id=?", (app_id,)).fetchone()

    total = int(row["cnt"]) if row else 0
    accessed_count = int(accessed["cnt"]) if accessed else 0

    meta = {}
    status = "idle"
    is_active = True
    if p_row:
        status = p_row["status"]
        try:
            meta = json.loads(p_row["metadata_json"] or "{}")
            if "is_active" in meta:
                is_active = bool(meta["is_active"])
        except Exception:
            pass

    default_meta = _DEFAULT_APP_METADATA.get(app_id, {})
    return {
        "id": app_id,
        "name": app_id,
        "display_name": meta.get("display_name") or default_meta.get("display_name", app_id.capitalize()),
        "description": meta.get("description") or default_meta.get("description", ""),
        "category": default_meta.get("category", "agent"),
        "is_active": is_active,
        "status": status,
        "total_memories_created": total,
        "total_memories_accessed": accessed_count,
        "first_accessed": str(accessed["first_ts"] or "") or None,
        "last_accessed": str(accessed["last_ts"] or "") or None,
    }


def _update_app_details(app_id: str, body: dict[str, Any]) -> dict[str, Any]:
    import json
    from memorycore.storage.db import read_conn as _rc, managed_conn as _mc
    from memorycore.models import now as _now

    with _rc() as conn:
        row = conn.execute("SELECT * FROM agent_presence WHERE agent_id=?", (app_id,)).fetchone()

    meta = {}
    status = "idle"
    if row:
        status = row["status"]
        try:
            meta = json.loads(row["metadata_json"] or "{}")
        except Exception:
            meta = {}

    if "display_name" in body:
        meta["display_name"] = str(body["display_name"]).strip()
    if "description" in body:
        meta["description"] = str(body["description"]).strip()
    if "is_active" in body:
        meta["is_active"] = bool(body["is_active"])
        status = "idle" if body["is_active"] else "paused"

    ts = _now()
    with _mc() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO agent_presence (agent_id, status, last_seen_at, metadata_json)
               VALUES (?, ?, ?, ?)""",
            (app_id, status, ts, json.dumps(meta, ensure_ascii=False)),
        )

    return _app_details(app_id)


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
        archived_rows = conn.execute(
            f"SELECT * FROM memories WHERE id IN ({placeholders})", target_ids
        ).fetchall()
    # Archive must remove the vectors too, otherwise stale points leak into
    # Qdrant (the curator's rebuild is a dry-run and never cleans them up).
    from memorycore.storage.crud import _sync_record_indexes
    for archived_row in archived_rows:
        try:
            _sync_record_indexes(row_to_dict(archived_row))
        except Exception:
            pass
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


def dashboard_v1_payload(limit: int = 200) -> dict[str, Any]:
    """Aggregated Dashboard payload (single v1 request).

    Combines stats + apps + curator status + governance metrics + maintenance
    latest + profile attribute count so the frontend Dashboard issues ONE
    request instead of several parallel fetches. Each section is best-effort:
    a failing section degrades to its empty value, never failing the request.
    """
    from memorycore.storage.crud import get_memory_stats
    from memorycore.storage.governance import get_governance_metrics
    from memorycore.storage.maintenance import get_latest_maintenance_job

    stats: dict[str, Any] = {}
    apps: list[Any] = []
    curator: dict[str, Any] = {}
    governance: dict[str, Any] = {}
    maintenance = None
    profile_attrs = 0
    try:
        stats = get_memory_stats()
    except Exception:
        pass
    try:
        apps = _apps_list(limit=1000)["apps"]
    except Exception:
        pass
    try:
        from memorycore.frontend_metrics import _curator_status_payload as _curator_payload
        curator = _curator_payload(limit=limit)
    except Exception:
        pass
    try:
        governance = get_governance_metrics()
    except Exception:
        pass
    try:
        maintenance = get_latest_maintenance_job()
    except Exception:
        pass
    try:
        from memorycore.storage.db import read_conn
        with read_conn() as conn:
            row = conn.execute("SELECT COUNT(*) FROM user_profile_attrs").fetchone()
            profile_attrs = int(row[0]) if row else 0
    except Exception:
        pass
    return {
        "total_memories": stats.get("total", 0),
        "stats": stats,
        "apps": apps,
        "curator": curator,
        "governance": governance,
        "maintenance": maintenance,
        "profile_attrs": profile_attrs,
    }


def health_score_v1_payload() -> dict[str, Any]:
    """Backend health-quality scoring (single source of truth).

    Mirrors `MemoryIntelligenceCenter` weighted scoring as of the 2026-08-24
    B1-B5 caliber fixes: reuse coverage over the ACTIVE pool, linked coverage
    from real memory_links, non-archived ratio = pending-cleanup share of the
    usable pool, neutral LLM governance when never run. Frontend renders this
    payload instead of computing scores locally.
    """
    from memorycore.storage.crud import get_memory_stats
    from memorycore.frontend_metrics import _curator_status_payload
    from memorycore.storage.db import read_conn

    stats = get_memory_stats()
    by_status = stats.get("by_status") or {}
    active = int(by_status.get("active", 0))
    stale = int(by_status.get("stale", 0))
    superseded = int(by_status.get("superseded", 0))
    contradicted = int(by_status.get("contradicted", 0))
    active_never = int(stats.get("active_never_accessed_count", 0))
    unique_linked = int(stats.get("unique_linked_memories", 0))
    link_total = int(stats.get("link_count", 0))
    pending_cleanup = stale + superseded + contradicted
    usable_pool = active + stale + contradicted + superseded

    def _pct(num: float, den: float) -> float:
        return min(100.0, round(num / den * 100)) if den > 0 else 0.0

    def _clamp(value: float) -> float:
        return max(0.0, min(100.0, round(value)))

    active_reuse = _pct(active - active_never, active)
    linked_coverage = _pct(unique_linked, active)
    pending_share = _pct(pending_cleanup, usable_pool)

    contra_actionable = 0
    dup_actionable = 0
    try:
        with read_conn() as conn:
            rows = conn.execute(
                "SELECT decision_type, COUNT(*) as cnt FROM governance_decisions"
                " WHERE review_status IN ('needs_review','auto_approved') AND recommended_action != 'keep'"
                " GROUP BY decision_type"
            ).fetchall()
        dist = {row["decision_type"]: int(row["cnt"]) for row in rows}
        contra_actionable = int(dist.get("contradiction", 0))
        dup_actionable = int(dist.get("semantic_duplicate", 0))
    except Exception:
        pass
    # Backend approximation of the frontend "high-severity attention items".
    high_risk_count = contra_actionable + dup_actionable

    risk_score = _clamp(
        100
        - high_risk_count * 18
        - min(dup_actionable, 100) * 0.28
        - min(contra_actionable, 20) * 2
    )

    llm_score = 50.0
    llm_status = "unknown"
    try:
        curator = _curator_status_payload(limit=50)
        llm = curator.get("llm_curator") or {}
        llm_status = str(
            llm.get("last_result") or (llm.get("latest_job") or {}).get("status") or "unknown"
        )
        if llm_status in ("success", "succeeded"):
            llm_score = 100.0
        elif llm_status == "running":
            llm_score = 62.0
    except Exception:
        pass

    weights = {
        "risk": 0.34,
        "pending": 0.16,
        "linked": 0.08,
        "reuse": 0.24,
        "llm": 0.14,
    }
    total_weight = sum(weights.values())
    quality = _clamp(
        (
            _clamp(risk_score) * weights["risk"]
            + _clamp(100 - pending_share) * weights["pending"]
            + _clamp(linked_coverage) * weights["linked"]
            + _clamp(active_reuse) * weights["reuse"]
            + _clamp(llm_score) * weights["llm"]
        )
        / total_weight
    )

    return {
        "quality": quality,
        "risk": risk_score,
        "llmGovernance": llm_score,
        "llmStatus": llm_status,
        "metrics": {
            "active": active,
            "stale": stale,
            "superseded": superseded,
            "contradicted": contradicted,
            "active_never_accessed": active_never,
            "active_reuse_coverage": active_reuse,
            "linked_coverage": linked_coverage,
            "link_count": link_total,
            "unique_linked_memories": unique_linked,
            "pending_cleanup_share": pending_share,
            "pending_cleanup": pending_cleanup,
            "usable_pool": usable_pool,
        },
        "signals": {
            "high_risk_count": high_risk_count,
            "contradiction_actionable": contra_actionable,
            "duplicate_actionable": dup_actionable,
        },
    }
