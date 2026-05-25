"""FTS5 search, context pack, and active-warning helpers."""
from __future__ import annotations

import re
from typing import Any

from local_memory_mcp.injection_guard import (
    BOUNDARY_NOTICE,
    check_memory_for_injection,
    warning_for_filtered_memory,
)
from local_memory_mcp.models import fts_phrase, normalize_list, now, row_to_dict
from local_memory_mcp.storage.db import _managed_query, managed_conn

_GREETINGS = {"hi", "hello", "hey", "你好", "嗯", "好", "继续", "ok", "okay", "yes", "no"}


def _is_greeting(task: str) -> bool:
    return task.strip().lower() in _GREETINGS


def search_memory_records(
    query: str = "",
    types: Any = None,
    scope: str = "",
    project_path: str = "",
    tags: Any = None,
    status: str = "active",
    limit: int = 10,
) -> list[dict[str, Any]]:
    types_list = normalize_list(types)
    tags_list = [t.lower() for t in normalize_list(tags)]
    clauses = []
    params: list[Any] = []
    base = "SELECT m.* FROM memories m"
    if query.strip():
        terms = re.findall(r"[\w一-鿿]+", query, flags=re.UNICODE)
        if not terms:
            return []
        base += " JOIN memories_fts f ON f.id = m.id"
        fts_query = " OR ".join(fts_phrase(term) for term in terms)
        clauses.append("memories_fts MATCH ?")
        params.append(fts_query)
    if types_list:
        clauses.append("m.type IN (%s)" % ",".join("?" for _ in types_list))
        params.extend(types_list)
    if scope:
        clauses.append("(m.scope = ? OR m.scope = 'global')")
        params.append(scope)
    if project_path:
        clauses.append("(m.project_path = ? OR m.project_path = '')")
        params.append(project_path)
    if tags_list:
        clauses.append(
            "EXISTS (SELECT 1 FROM json_each(m.tags_json) WHERE lower(json_each.value) IN (%s))"
            % ",".join("?" for _ in tags_list)
        )
        params.extend(tags_list)
    if status:
        clauses.append("m.status = ?")
        params.append(status)
    sql = base
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY m.importance DESC, m.effectiveness_score DESC, m.feedback_score DESC, m.updated_at DESC LIMIT ?"
    params.append(max(1, min(int(limit), 100)))
    with managed_conn() as conn:
        rows = [row_to_dict(r) for r in conn.execute(sql, params).fetchall()]
        if rows:
            conn.executemany(
                "UPDATE memories SET last_accessed_at=? WHERE id=?",
                [(now(), r["id"]) for r in rows],
            )
    return rows


def get_active_warnings(
    memory_ids: list[str],
    min_weight: float = 0.4,
    max_warnings: int = 5,
) -> list[dict[str, Any]]:
    if not memory_ids:
        return []
    placeholders = ",".join("?" for _ in memory_ids)
    sql = f"""
        SELECT
            ml.source_id, ml.target_id, ml.relation_type, ml.weight, ml.note,
            ms.title AS source_title, ms.feedback_score AS source_fb,
            mt.title AS target_title, mt.feedback_score AS target_fb
        FROM memory_links ml
        JOIN memories ms ON ms.id = ml.source_id
        JOIN memories mt ON mt.id = ml.target_id
        WHERE (ml.source_id IN ({placeholders}) OR ml.target_id IN ({placeholders}))
          AND ml.relation_type IN ('contradicts', 'supersedes', 'causes', 'failure_pattern')
          AND ml.weight >= ?
          AND ms.status = 'active'
          AND mt.status = 'active'
        ORDER BY ml.weight DESC
        LIMIT ?
    """
    params = memory_ids + memory_ids + [min_weight, max_warnings * 2]
    rows = _managed_query(sql, params)

    warnings: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        sig = f"{row['source_id']}→{row['target_id']}→{row['relation_type']}"
        if sig in seen:
            continue
        seen.add(sig)
        rel_type = row["relation_type"]
        if rel_type in ("causes", "failure_pattern"):
            severity = "medium"
        else:
            severity = "high" if float(row.get("weight") or 0) >= 0.7 else "medium"
            if float(row.get("target_fb") or 0) < -0.5:
                severity = "high"
        note_part = f" — {row['note']}" if row.get("note") else ""
        warnings.append({
            "source_id": row["source_id"],
            "target_id": row["target_id"],
            "relation_type": row["relation_type"],
            "severity": severity,
            "weight": row["weight"],
            "reason": (
                f"'{row['source_title']}' {row['relation_type']} "
                f"'{row['target_title']}'{note_part}"
            ),
        })
    warnings.sort(key=lambda w: (0 if w["severity"] == "high" else 1, -float(w["weight"])))
    return warnings[:max_warnings]


def build_context_pack(
    task: str,
    agent: str = "agent",
    project_path: str = "",
    scope: str = "global",
    token_budget: int = 2000,
) -> dict[str, Any]:
    max_chars = max(800, int(token_budget) * 4)
    records = search_memory_records(task, scope=scope, project_path=project_path, status="active", limit=40)
    fallback_used = False
    if not records and len(task.strip()) > 10 and not _is_greeting(task):
        records = search_memory_records("", scope=scope, project_path=project_path, status="active", limit=20)
        fallback_used = bool(records)
    groups_order = [
        "skill_candidate", "user_profile", "environment_fact", "agent_architecture",
        "project_memory", "decision", "timeline_event", "episodic_memory", "feedback",
    ]
    grouped: dict[str, list[dict[str, Any]]] = {k: [] for k in groups_order}
    for r in records:
        grouped.setdefault(r["type"], []).append(r)
    lines = [
        f"# memory_context for {agent}",
        f"task: {task}",
        f"scope: {scope}",
        f"project_path: {project_path or '(none)'}",
        f"safety: {BOUNDARY_NOTICE}",
        "",
    ]
    used_ids: list[str] = []
    filtered_ids: list[str] = []
    injection_warnings: list[dict[str, Any]] = []
    for group in groups_order:
        items = grouped.get(group) or []
        if not items:
            continue
        if group == "episodic_memory":
            items = [i for i in items if float(i.get("feedback_score", 0)) >= 0][:2]
            if not items:
                continue
        section = [f"## {group}"]
        section_used_ids: list[str] = []
        for item in items[:6]:
            check = check_memory_for_injection(item)
            if check.is_high_risk:
                filtered_ids.append(item["id"])
                injection_warnings.append(warning_for_filtered_memory(item, check))
                continue
            snippet = item["content"].replace("\n", " ")
            if len(snippet) > 420:
                snippet = snippet[:417] + "..."
            section.append(f"- [{item['id']}] {item['title']}: {snippet}")
            section_used_ids.append(item["id"])
        if len(section) == 1:
            continue
        candidate = "\n".join(lines + section) + "\n"
        if len(candidate) > max_chars:
            break
        lines.extend(section + [""])
        used_ids.extend(section_used_ids)
    text = "\n".join(lines).strip()
    if used_ids:
        ts = now()
        with managed_conn() as conn:
            for mid in used_ids:
                conn.execute(
                    """UPDATE memories SET injected_count = injected_count + 1,
                           last_injected_at = ?, last_accessed_at = ? WHERE id = ?""",
                    (ts, ts, mid),
                )
    active_count = sum(1 for r in records if r["status"] == "active")
    warnings = (get_active_warnings(used_ids) if used_ids else []) + injection_warnings
    used_id_set = set(used_ids)
    sections: list[dict[str, Any]] = []
    for group in groups_order:
        group_records = [r for r in grouped.get(group, []) if r["id"] in used_id_set]
        if group_records:
            sections.append({"type": group, "records": group_records})
    return {
        "context": text,
        "records": records,
        "used_ids": used_ids,
        "filtered_ids": filtered_ids,
        "warnings": warnings,
        "budget_chars": max_chars,
        "quality": {
            "total_candidates": len(records),
            "used_count": len(used_ids),
            "filtered_count": len(filtered_ids),
            "active_ratio": round(active_count / max(len(records), 1), 3),
            "avg_importance": round(sum(r["importance"] for r in records) / max(len(records), 1), 3),
            "stale_in_results": sum(1 for r in records if r["status"] == "stale"),
            "estimated_tokens": len(text) // 4,
        },
        "sections": sections,
        "trace": {
            "total_candidates": len(records),
            "used_count": len(used_ids),
            "filtered_count": len(filtered_ids),
            "fallback_used": fallback_used,
        },
    }
