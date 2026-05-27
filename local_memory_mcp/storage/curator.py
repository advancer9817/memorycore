"""Curator: duplicate detection, stale/archive lifecycle management."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from local_memory_mcp.models import normalize_list, normalize_title_key, now
from local_memory_mcp.storage.db import _managed_query, managed_conn
from local_memory_mcp.storage.audit import log_audit_event

_DECAY_STEP = 0.05
_DECAY_INTERVAL_DAYS = 30
_DECAY_MIN_CONFIDENCE = 0.10


def consolidate(dry_run: bool = True, limit: int = 50) -> dict[str, Any]:
    from local_memory_mcp.storage.crud import list_recent
    rows = list_recent(limit)
    seen: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        key = normalize_title_key(r.get("title", ""))
        seen.setdefault(key, []).append(r)
    duplicates = [v for v in seen.values() if len(v) > 1]
    low_feedback = [r for r in rows if float(r.get("feedback_score", 0)) < -0.5]
    return {
        "dry_run": dry_run,
        "applied": False,
        "reason": "v0 consolidate is report-only; use memory_curator_report(dry_run=False) for low-risk lifecycle status changes",
        "duplicate_title_groups": duplicates,
        "low_feedback_candidates": low_feedback,
    }


def curator_report(
    dry_run: bool = True,
    limit: int = 500,
    stale_after_days: int = 60,
    archive_after_days: int = 120,
    allow_actions: Any = None,
    deny_actions: Any = None,
) -> dict[str, Any]:
    from local_memory_mcp.storage.crud import update_status
    now_dt = datetime.now(timezone.utc)
    stale_cutoff = now_dt - timedelta(days=max(1, int(stale_after_days)))
    archive_cutoff = now_dt - timedelta(days=max(1, int(archive_after_days)))
    cap = max(1, min(int(limit), 5000))

    all_rows = _managed_query("SELECT * FROM memories ORDER BY updated_at DESC LIMIT ?", (cap,))
    by_title: dict[str, list[dict[str, Any]]] = {}
    for r in all_rows:
        by_title.setdefault(normalize_title_key(r.get("title", "")), []).append(r)
    duplicate_title_groups = [v for k, v in by_title.items() if k and len(v) > 1]

    low_feedback_candidates = _managed_query(
        "SELECT * FROM memories WHERE status IN ('active','candidate') AND feedback_score < -0.5 LIMIT ?",
        (cap,),
    )
    decay_candidates = _managed_query(
        """SELECT * FROM memories WHERE status = 'active'
             AND (last_accessed_at IS NULL OR last_accessed_at < datetime('now', '-90 days'))
             AND effectiveness_score < 0.4 AND importance < 0.6
           ORDER BY effectiveness_score ASC, last_accessed_at ASC LIMIT ?""",
        (cap,),
    )
    evolution_candidates = _managed_query(
        """SELECT * FROM memories WHERE status IN ('active','candidate')
             AND (LENGTH(content) < 50 OR feedback_score < -1.0)
           ORDER BY feedback_score ASC LIMIT ?""",
        (min(cap, 50),),
    )
    stale_candidates = _managed_query(
        """SELECT * FROM memories WHERE (
               status = 'active' AND datetime(updated_at) < datetime(?)
               AND importance < 0.45 AND feedback_score <= 0
             ) OR (
               status = 'candidate' AND datetime(updated_at) < datetime('now', '-12 hours')
               AND importance < 0.65 AND feedback_score <= 0
             )
           ORDER BY updated_at ASC LIMIT ?""",
        (stale_cutoff.isoformat(), cap),
    )
    archive_candidates = _managed_query(
        "SELECT * FROM memories WHERE status = 'stale' AND updated_at < ? ORDER BY updated_at ASC LIMIT ?",
        (archive_cutoff.isoformat(), cap),
    )
    skill_promotion_candidates = _managed_query(
        """SELECT * FROM memories WHERE type = 'skill_candidate'
             AND status IN ('active','candidate') AND importance >= 0.65 AND feedback_score >= 0
           LIMIT ?""",
        (cap,),
    )

    decay_cutoff = (now_dt - timedelta(days=_DECAY_INTERVAL_DAYS)).isoformat()
    auto_decay_candidates = _managed_query(
        """SELECT * FROM memories WHERE status = 'active'
             AND decay_policy = 'review'
             AND (last_accessed_at IS NULL OR last_accessed_at < ?)
             AND confidence > ?
           ORDER BY confidence DESC LIMIT ?""",
        (decay_cutoff, _DECAY_MIN_CONFIDENCE, cap),
    )

    contradiction_candidates: list[dict[str, Any]] = []
    active_by_key: dict[str, list[dict[str, Any]]] = {}
    contradicted_by_key: dict[str, list[dict[str, Any]]] = {}
    for r in all_rows:
        key = normalize_title_key(r.get("title", ""))
        if not key:
            continue
        if r.get("status") == "active":
            active_by_key.setdefault(key, []).append(r)
        elif r.get("status") == "contradicted":
            contradicted_by_key.setdefault(key, []).append(r)
    for key, active_items in active_by_key.items():
        if key in contradicted_by_key:
            contradiction_candidates.append({
                "title_key": key,
                "active": active_items,
                "contradicted": contradicted_by_key[key],
            })

    actions: list[dict[str, Any]] = []
    allow_set = set(normalize_list(allow_actions))
    deny_set = set(normalize_list(deny_actions))
    action_plan: list[dict[str, Any]] = []
    planned_ids: set[str] = set()

    def _plan(row: dict[str, Any], action: str, reason: str, target_status: str) -> None:
        if row["id"] in planned_ids:
            return
        if allow_set and action not in allow_set:
            return
        if action in deny_set:
            return
        planned_ids.add(row["id"])
        action_plan.append({
            "id": row["id"],
            "action": action,
            "title": row.get("title"),
            "reason": reason,
            "target_status": target_status,
            "rollback": {"status": row.get("status")},
        })

    for r in low_feedback_candidates:
        if r.get("status") != "stale":
            _plan(r, "mark_stale", "low_feedback", "stale")
    for r in stale_candidates:
        if r.get("status") != "stale":
            _plan(r, "mark_stale", "stale_candidate", "stale")
    for r in archive_candidates:
        _plan(r, "archive", "archive_candidate", "archived")

    if not dry_run:
        decay_applied = 0
        if auto_decay_candidates:
            now_ts = now()
            decay_rows = [
                (max(_DECAY_MIN_CONFIDENCE, round(float(r["confidence"]) - _DECAY_STEP, 3)), now_ts, r["id"])
                for r in auto_decay_candidates
            ]
            with managed_conn() as conn:
                conn.executemany(
                    "UPDATE memories SET confidence=?, updated_at=? WHERE id=?",
                    decay_rows,
                )
                conn.execute(
                    "DELETE FROM context_quality_events WHERE created_at < datetime('now', '-90 days')"
                )
                conn.execute(
                    "DELETE FROM audit_events WHERE created_at < datetime('now', '-180 days')"
                )
            decay_applied = len(decay_rows)
            # WAL checkpoint must run outside any transaction
            from local_memory_mcp.storage.db import connect as _connect
            _connect().execute("PRAGMA wal_checkpoint(TRUNCATE)")
        for planned in action_plan:
            update_status(planned["id"], planned["target_status"])
            actions.append({
                "id": planned["id"],
                "action": planned["action"],
                "title": planned.get("title"),
            })
        stale_count = sum(1 for a in actions if a["action"] == "mark_stale")
        archive_count = sum(1 for a in actions if a["action"] == "archive")
        log_audit_event(
            "curator_apply",
            detail={
                "stale": stale_count,
                "archived": archive_count,
                "auto_decay": decay_applied,
                "total_actions": len(actions),
                "actions": action_plan,
            },
        )

    total_scanned = _managed_query("SELECT COUNT(*) as cnt FROM memories", ())[0]["cnt"]
    return {
        "dry_run": dry_run,
        "generated_at": now(),
        "scanned": total_scanned,
        "duplicate_title_groups": duplicate_title_groups,
        "low_feedback_candidates": low_feedback_candidates,
        "stale_candidates": stale_candidates,
        "archive_candidates": archive_candidates,
        "contradiction_candidates": contradiction_candidates,
        "skill_promotion_candidates": skill_promotion_candidates,
        "auto_decay_candidates": auto_decay_candidates,
        "action_plan": action_plan,
        "actions": actions,
        "summary": {
            "duplicates": len(duplicate_title_groups),
            "low_feedback": len(low_feedback_candidates),
            "stale": len(stale_candidates),
            "archive": len(archive_candidates),
            "contradictions": len(contradiction_candidates),
            "skill_promotions": len(skill_promotion_candidates),
            "auto_decay_candidates": len(auto_decay_candidates),
            "planned_actions": len(action_plan),
            "actions": len(actions),
        },
    }
