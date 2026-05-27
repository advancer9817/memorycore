"""Curator: duplicate detection, stale/archive lifecycle management.

Memory retention philosophy (v2 — maximum memory strength):
  - High-value types (user_profile, environment_fact, decision, project_memory,
    skill_candidate) are preserved aggressively: stale only after 365 days of
    non-update with low importance AND negative feedback.
  - episodic_memory is treated as ephemeral: candidates auto-promote after 24 h
    if importance >= 0.7, otherwise stale after 14 days and archive after 30 days.
  - Candidates older than 48 h with no activity are cleaned up fast.
  - Decay runs on truly forgotten memories only (not accessed in 90 days AND
    effectiveness < 0.3), at a smaller step so confidence fades slowly.
  - Auto-promotion: active candidates with importance >= 0.75 are promoted to
    active status automatically.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from local_memory_mcp.models import normalize_list, normalize_title_key, now
from local_memory_mcp.storage.db import _managed_query, managed_conn
from local_memory_mcp.storage.audit import log_audit_event

# Decay: very slow — only truly forgotten memories fade
_DECAY_STEP = 0.02            # was 0.05 — much gentler fade
_DECAY_INTERVAL_DAYS = 90     # was 30 — only decay if not accessed in 90 days
_DECAY_MIN_CONFIDENCE = 0.15  # floor stays higher

# Per-type stale/archive thresholds (days since updated_at)
_STALE_DAYS_EPISODIC = 14
_ARCHIVE_DAYS_EPISODIC = 30
_STALE_DAYS_DEFAULT = 365     # was 60 — preserve everything else for a year
_ARCHIVE_DAYS_DEFAULT = 730   # was 120 — 2 years before archiving

# High-value types — never auto-stale regardless of importance
_PRECIOUS_TYPES = {"user_profile", "environment_fact", "decision", "project_memory", "skill_candidate"}

# Auto-promote candidates with high importance
_PROMOTE_IMPORTANCE_THRESHOLD = 0.75


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
    stale_after_days: int = _STALE_DAYS_DEFAULT,
    archive_after_days: int = _ARCHIVE_DAYS_DEFAULT,
    allow_actions: Any = None,
    deny_actions: Any = None,
) -> dict[str, Any]:
    from local_memory_mcp.storage.crud import update_status
    now_dt = datetime.now(timezone.utc)
    cap = max(1, min(int(limit), 5000))

    all_rows = _managed_query("SELECT * FROM memories ORDER BY updated_at DESC LIMIT ?", (cap,))
    by_title: dict[str, list[dict[str, Any]]] = {}
    for r in all_rows:
        by_title.setdefault(normalize_title_key(r.get("title", "")), []).append(r)
    duplicate_title_groups = [v for k, v in by_title.items() if k and len(v) > 1]

    # Low-feedback: only mark stale if score is truly bad AND not a precious type
    low_feedback_candidates = _managed_query(
        "SELECT * FROM memories WHERE status IN ('active','candidate')"
        " AND feedback_score < -1.0"
        " AND type NOT IN ('user_profile','environment_fact','decision','project_memory','skill_candidate')"
        " LIMIT ?",
        (cap,),
    )

    # Decay: only truly forgotten, low-effectiveness memories
    decay_cutoff = (now_dt - timedelta(days=_DECAY_INTERVAL_DAYS)).isoformat()
    auto_decay_candidates = _managed_query(
        """SELECT * FROM memories WHERE status = 'active'
             AND decay_policy = 'review'
             AND (last_accessed_at IS NULL OR last_accessed_at < ?)
             AND effectiveness_score < 0.3
             AND importance < 0.5
             AND confidence > ?
           ORDER BY confidence DESC LIMIT ?""",
        (decay_cutoff, _DECAY_MIN_CONFIDENCE, cap),
    )

    # Episodic stale: fast turnover for ephemeral memories
    episodic_stale_cutoff = (now_dt - timedelta(days=_STALE_DAYS_EPISODIC)).isoformat()
    episodic_archive_cutoff = (now_dt - timedelta(days=_ARCHIVE_DAYS_EPISODIC)).isoformat()
    episodic_stale_candidates = _managed_query(
        """SELECT * FROM memories WHERE type = 'episodic_memory'
             AND status = 'active'
             AND datetime(updated_at) < datetime(?)
             AND importance < 0.65
           ORDER BY updated_at ASC LIMIT ?""",
        (episodic_stale_cutoff, cap),
    )
    episodic_archive_candidates = _managed_query(
        """SELECT * FROM memories WHERE type = 'episodic_memory'
             AND status = 'stale'
             AND datetime(updated_at) < datetime(?)
           ORDER BY updated_at ASC LIMIT ?""",
        (episodic_archive_cutoff, cap),
    )

    # Old candidates (not episodic): keep for 48h, then archive if still candidate
    dead_candidate_cutoff = (now_dt - timedelta(hours=48)).isoformat()
    dead_candidates = _managed_query(
        """SELECT * FROM memories WHERE status = 'candidate'
             AND type != 'episodic_memory'
             AND datetime(updated_at) < datetime(?)
             AND importance < 0.5
           ORDER BY updated_at ASC LIMIT ?""",
        (dead_candidate_cutoff, cap),
    )

    # Default stale: precious types immune; everything else after stale_after_days
    stale_cutoff = (now_dt - timedelta(days=max(1, int(stale_after_days)))).isoformat()
    stale_candidates = _managed_query(
        """SELECT * FROM memories WHERE status = 'active'
             AND type NOT IN ('user_profile','environment_fact','decision','project_memory','skill_candidate','episodic_memory')
             AND datetime(updated_at) < datetime(?)
             AND importance < 0.45
             AND feedback_score <= -0.5
           ORDER BY updated_at ASC LIMIT ?""",
        (stale_cutoff, cap),
    )

    # Default archive: stale memories past archive_after_days
    archive_cutoff = (now_dt - timedelta(days=max(1, int(archive_after_days)))).isoformat()
    archive_candidates = _managed_query(
        """SELECT * FROM memories WHERE status = 'stale'
             AND type NOT IN ('episodic_memory')
             AND updated_at < ?
           ORDER BY updated_at ASC LIMIT ?""",
        (archive_cutoff, cap),
    )

    # Auto-promote: high-importance candidates → active
    promote_candidates = _managed_query(
        """SELECT * FROM memories WHERE status = 'candidate'
             AND importance >= ?
             AND feedback_score >= 0
           ORDER BY importance DESC LIMIT ?""",
        (_PROMOTE_IMPORTANCE_THRESHOLD, cap),
    )

    # Skill promotions
    skill_promotion_candidates = _managed_query(
        """SELECT * FROM memories WHERE type = 'skill_candidate'
             AND status IN ('active','candidate') AND importance >= 0.65 AND feedback_score >= 0
           LIMIT ?""",
        (cap,),
    )

    # Contradiction detection
    evolution_candidates = _managed_query(
        """SELECT * FROM memories WHERE status IN ('active','candidate')
             AND (LENGTH(content) < 50 OR feedback_score < -1.5)
           ORDER BY feedback_score ASC LIMIT ?""",
        (min(cap, 50),),
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

    # Build action plan
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
        _plan(r, "mark_stale", "low_feedback", "stale")
    for r in episodic_stale_candidates:
        _plan(r, "mark_stale", "episodic_aged", "stale")
    for r in stale_candidates:
        _plan(r, "mark_stale", "stale_candidate", "stale")
    for r in episodic_archive_candidates:
        _plan(r, "archive", "episodic_archive", "archived")
    for r in archive_candidates:
        _plan(r, "archive", "archive_candidate", "archived")
    for r in dead_candidates:
        _plan(r, "archive", "dead_candidate", "archived")
    for r in promote_candidates:
        _plan(r, "promote", "high_importance_candidate", "active")

    actions: list[dict[str, Any]] = []

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
            from local_memory_mcp.storage.db import connect as _connect
            _connect().execute("PRAGMA wal_checkpoint(TRUNCATE)")
        for planned in action_plan:
            if planned["action"] == "promote":
                update_status(planned["id"], "active")
            else:
                update_status(planned["id"], planned["target_status"])
            actions.append({
                "id": planned["id"],
                "action": planned["action"],
                "title": planned.get("title"),
            })
        stale_count = sum(1 for a in actions if a["action"] == "mark_stale")
        archive_count = sum(1 for a in actions if a["action"] == "archive")
        promote_count = sum(1 for a in actions if a["action"] == "promote")
        log_audit_event(
            "curator_apply",
            detail={
                "stale": stale_count,
                "archived": archive_count,
                "promoted": promote_count,
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
        "stale_candidates": stale_candidates + episodic_stale_candidates,
        "archive_candidates": archive_candidates + episodic_archive_candidates,
        "contradiction_candidates": contradiction_candidates,
        "skill_promotion_candidates": skill_promotion_candidates,
        "auto_decay_candidates": auto_decay_candidates,
        "promote_candidates": promote_candidates,
        "action_plan": action_plan,
        "actions": actions,
        "summary": {
            "duplicates": len(duplicate_title_groups),
            "low_feedback": len(low_feedback_candidates),
            "stale": len(stale_candidates) + len(episodic_stale_candidates),
            "archive": len(archive_candidates) + len(episodic_archive_candidates) + len(dead_candidates),
            "contradictions": len(contradiction_candidates),
            "skill_promotions": len(skill_promotion_candidates),
            "auto_decay_candidates": len(auto_decay_candidates),
            "promote_candidates": len(promote_candidates),
            "planned_actions": len(action_plan),
            "actions": len(actions),
        },
    }
