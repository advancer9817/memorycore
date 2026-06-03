"""Episodic memory rollup into durable memory records."""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable

from memorycore.extraction import extraction_config_from_dict, _call_llm
from memorycore.models import finite_float, load_config, local_now, normalize_list, now, parse_ts, validate_type
from memorycore.storage.audit import log_audit_event
from memorycore.storage.crud import add_memory_record, update_status, update_status_batch as _usb
from memorycore.storage.db import _managed_query, managed_conn as _managed_conn, read_conn

logger = logging.getLogger(__name__)

_DEFAULT_MIN_COUNT = 30
_DEFAULT_MIN_AGE_COUNT = 5
_DEFAULT_MAX_AGE_HOURS = 24
_DEFAULT_LIMIT = 250
_ALLOWED_ROLLUP_TYPES = {
    "user_profile",
    "environment_fact",
    "agent_architecture",
    "project_memory",
    "timeline_event",
    "decision",
    "feedback",
    "skill_candidate",
}

_ROLLUP_SYSTEM_PROMPT = """\
You condense noisy episodic memory fragments into durable long-term memory.
Use only the provided records. Preserve stable user preferences, project facts,
decisions, environment/tooling facts, feedback rules, and skill candidates.
Do not preserve secrets, tokens, passwords, private account identifiers, or raw
one-off task chatter. Merge duplicates and contradictions conservatively.

Return only JSON:
{
  "memories": [
    {
      "type": "user_profile|environment_fact|agent_architecture|project_memory|timeline_event|decision|feedback|skill_candidate",
      "title": "short specific title",
      "content": "self-contained durable memory",
      "importance": 0.0,
      "confidence": 0.0,
      "tags": ["optional"],
      "source_ids": ["episodic-memory-id"]
    }
  ]
}
"""


def _parse_llm_json(raw: str) -> dict[str, Any]:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(raw[start:end])
        raise


def _candidate_age_hours(row: dict[str, Any]) -> float:
    ts = parse_ts(row.get("created_at") or row.get("updated_at"))
    return max(0.0, (local_now() - ts).total_seconds() / 3600.0)


def _select_rollup_group(
    rows: list[dict[str, Any]],
    *,
    min_count: int,
    min_age_count: int,
    max_age_hours: float,
    force: bool,
) -> tuple[list[dict[str, Any]], str]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = (row.get("scope") or "global", row.get("source_agent") or "", row.get("project_path") or "")
        groups.setdefault(key, []).append(row)

    ordered = sorted(
        groups.values(),
        key=lambda group: parse_ts(group[0].get("created_at") or group[0].get("updated_at")),
    )
    for group in ordered:
        oldest_age = _candidate_age_hours(group[0]) if group else 0.0
        if force:
            return group, "force"
        if len(group) >= min_count:
            return group, "count"
        if len(group) >= min_age_count and oldest_age >= max_age_hours:
            return group, "age"
    return [], "threshold_not_met"


def _call_rollup_llm(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cfg = extraction_config_from_dict(load_config())
    if not cfg.api_key:
        raise RuntimeError("no extraction API key configured")
    payload = [
        {
            "id": row["id"],
            "title": row.get("title", ""),
            "content": row.get("content", ""),
            "tags": row.get("tags", []),
            "source_agent": row.get("source_agent", ""),
            "project_path": row.get("project_path", ""),
            "created_at": row.get("created_at", ""),
        }
        for row in rows
    ]
    user_prompt = "## Episodic records to roll up\n" + json.dumps(payload, ensure_ascii=False)
    raw = _call_llm(_ROLLUP_SYSTEM_PROMPT, user_prompt, cfg)
    data = _parse_llm_json(raw)
    memories = data.get("memories", data.get("memory", []))
    return memories if isinstance(memories, list) else []


def _sanitize_proposals(proposals: Any, source_ids: list[str]) -> list[dict[str, Any]]:
    if not isinstance(proposals, list):
        return []
    allowed_ids = set(source_ids)
    sanitized: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in proposals:
        if not isinstance(item, dict):
            continue
        memory_type = str(item.get("type", "")).strip()
        if memory_type not in _ALLOWED_ROLLUP_TYPES:
            continue
        validate_type(memory_type)
        title = str(item.get("title", "")).strip()[:160]
        content = str(item.get("content", "")).strip()
        if not title or not content:
            continue
        key = (memory_type, title.lower())
        if key in seen:
            continue
        seen.add(key)
        item_source_ids = [sid for sid in normalize_list(item.get("source_ids")) if sid in allowed_ids]
        if not item_source_ids:
            item_source_ids = source_ids
        tags = ["rollup"]
        for tag in normalize_list(item.get("tags")):
            if tag not in tags:
                tags.append(tag)
        sanitized.append({
            "type": memory_type,
            "title": title,
            "content": content[:6000],
            "importance": finite_float(item.get("importance", 0.75), "importance", 0.0, 1.0),
            "confidence": finite_float(item.get("confidence", 0.75), "confidence", 0.0, 1.0),
            "tags": tags,
            "source_ids": item_source_ids,
        })
    return sanitized


def rollup_report(
    dry_run: bool = True,
    limit: int = _DEFAULT_LIMIT,
    min_count: int = _DEFAULT_MIN_COUNT,
    max_age_hours: float = _DEFAULT_MAX_AGE_HOURS,
    min_age_count: int = _DEFAULT_MIN_AGE_COUNT,
    source_agent: str = "",
    project_path: str = "",
    force: bool = False,
    _summarize_fn: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Plan or apply an episodic-memory rollup pass."""
    cap = max(1, min(int(limit), 5000))
    min_count = max(1, int(min_count))
    min_age_count = max(1, int(min_age_count))
    max_age_hours = max(0.0, float(max_age_hours))

    clauses = ["type = 'episodic_memory'", "status IN ('candidate','active')"]
    params: list[Any] = []
    if source_agent:
        clauses.append("source_agent = ?")
        params.append(source_agent)
    if project_path:
        clauses.append("project_path = ?")
        params.append(project_path)
    params.append(cap)
    rows = _managed_query(
        f"SELECT * FROM memories WHERE {' AND '.join(clauses)} ORDER BY created_at ASC LIMIT ?",
        tuple(params),
    )
    group, trigger_reason = _select_rollup_group(
        rows,
        min_count=min_count,
        min_age_count=min_age_count,
        max_age_hours=max_age_hours,
        force=force,
    )
    source_ids = [row["id"] for row in group]
    triggered = bool(group) and trigger_reason != "threshold_not_met"
    base: dict[str, Any] = {
        "dry_run": dry_run,
        "generated_at": now(),
        "scanned": len(rows),
        "eligible": len(group),
        "triggered": triggered,
        "trigger_reason": trigger_reason,
        "source_ids": source_ids,
        "proposed_records": [],
        "created_records": [],
        "archived_source_ids": [],
        "errors": [],
        "summary": {
            "scanned": len(rows),
            "eligible": len(group),
            "proposed": 0,
            "created": 0,
            "archived_sources": 0,
            "triggered": triggered,
        },
    }
    if not triggered:
        return base

    t0 = time.time()
    try:
        raw_proposals = _summarize_fn(group) if _summarize_fn else _call_rollup_llm(group)
        proposals = _sanitize_proposals(raw_proposals, source_ids)
    except Exception as exc:
        base["degraded"] = True
        base["reason"] = f"rollup summarizer unavailable: {type(exc).__name__}: {exc}"
        base["elapsed_s"] = round(time.time() - t0, 3)
        return base

    base["proposed_records"] = proposals
    base["summary"]["proposed"] = len(proposals)
    base["elapsed_s"] = round(time.time() - t0, 3)
    if dry_run or not proposals:
        return base

    scope = group[0].get("scope") or "global"
    group_project_path = group[0].get("project_path") or ""
    created: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for proposal in proposals:
        record = add_memory_record(
            proposal["type"],
            proposal["title"],
            proposal["content"],
            scope=scope,
            tags=proposal["tags"],
            source="rollup",
            source_agent="memory-rollup",
            project_path=group_project_path,
            confidence=proposal["confidence"],
            importance=proposal["importance"],
            status="active",
            decay_policy="review",
            related_ids=proposal["source_ids"],
            metadata={"rollup_source_ids": proposal["source_ids"], "rollup_generated_at": base["generated_at"]},
        )
        if "error" in record:
            errors.append({"title": proposal["title"], "error": record["error"]})
        else:
            created.append(record)
    if errors:
        base["created_records"] = created
        base["errors"] = errors
        base["summary"]["created"] = len(created)
        return base

    with _managed_conn() as _bc:
        _usb(_bc, [(sid, "archived") for sid in source_ids])
    archived: list[str] = list(source_ids)
    base["created_records"] = created
    base["archived_source_ids"] = archived
    base["summary"]["created"] = len(created)
    base["summary"]["archived_sources"] = len(archived)
    log_audit_event(
        "memory_rollup_apply",
        detail={
            "source_ids": source_ids,
            "created_ids": [record["id"] for record in created],
            "trigger_reason": trigger_reason,
            "proposed": len(proposals),
        },
    )
    return base
