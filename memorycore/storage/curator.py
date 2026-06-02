"""Curator: duplicate detection, stale/archive lifecycle management.

Memory retention philosophy (v3 — evidence-driven lifecycle):
  - Entry status is determined by the write path, not the caller:
      memory_add → active, memory_ingest → candidate, rollup output → active.
  - High-value types (user_profile, environment_fact, decision, project_memory,
    skill_candidate) are NEVER auto-staled unless feedback < -2.0 AND importance < 0.3.
  - candidate windows are tiered by type:
      episodic_memory: 7 days (aligned with rollup 30-record threshold pace)
      precious types:  30 days (importance < 0.4 AND feedback < 0)
      other types:      7 days (importance < 0.5)
  - Promotion from candidate to active:
      importance >= 0.75 AND feedback >= 0, OR injected_count >= 3 (evidence of utility)
  - stale → active revival: record injected in last 7 days AND effective AND no neg feedback.
  - contradicted auto-archive: 90 days without access.
  - decay_policy semantics:
      review  — slow confidence decay when truly forgotten (injected, then abandoned)
      stable  — no decay; stale threshold requires feedback < -2.0 AND importance < 0.3
      freeze  — curator skips entirely; manual management only
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from memorycore.models import local_now, normalize_list, normalize_title_key, now
from memorycore.storage.db import _managed_query, managed_conn
from memorycore.storage.audit import log_audit_event

# Decay: records that were used and then forgotten
_DECAY_STEP = 0.05
_DECAY_INTERVAL_DAYS = 30
_DECAY_MIN_CONFIDENCE = 0.15

# Per-type candidate timeout windows
_CANDIDATE_TTL_EPISODIC_DAYS = 7
_CANDIDATE_TTL_PRECIOUS_DAYS = 30
_CANDIDATE_TTL_DEFAULT_DAYS = 7

# Per-type stale/archive thresholds (days since updated_at)
_STALE_DAYS_EPISODIC = 14
_ARCHIVE_DAYS_EPISODIC = 30
_STALE_DAYS_DEFAULT = 365
_ARCHIVE_DAYS_DEFAULT = 730

# contradicted auto-archive after no access
_CONTRADICTED_ARCHIVE_DAYS = 90

# Never-accessed candidate auto-archive
_NEVER_ACCESSED_CANDIDATE_DAYS = 14

# High-value types — immune to auto-stale unless feedback very negative
_PRECIOUS_TYPES = {"user_profile", "environment_fact", "decision", "project_memory", "skill_candidate"}

# Auto-promote candidates
_PROMOTE_IMPORTANCE_THRESHOLD = 0.75
_PROMOTE_INJECTED_THRESHOLD = 3


def curator_report(
    dry_run: bool = True,
    limit: int = 500,
    stale_after_days: int = _STALE_DAYS_DEFAULT,
    archive_after_days: int = _ARCHIVE_DAYS_DEFAULT,
    allow_actions: Any = None,
    deny_actions: Any = None,
) -> dict[str, Any]:
    now_dt = local_now()
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
        " AND decay_policy != 'freeze'"
        " LIMIT ?",
        (cap,),
    )

    # Decay: only truly forgotten records that were once used
    decay_cutoff = (now_dt - timedelta(days=_DECAY_INTERVAL_DAYS)).isoformat()
    auto_decay_candidates = _managed_query(
        """SELECT * FROM memories WHERE status = 'active'
             AND decay_policy = 'review'
             AND (last_accessed_at IS NULL OR last_accessed_at < ?)
             AND effectiveness_score < 0.3
             AND importance < 0.5
             AND injected_count > 0
             AND confidence > ?
           ORDER BY confidence DESC LIMIT ?""",
        (decay_cutoff, _DECAY_MIN_CONFIDENCE, cap),
    )

    # ── Episodic stale/archive ────────────────────────────────────────────────
    episodic_stale_cutoff = (now_dt - timedelta(days=_STALE_DAYS_EPISODIC)).isoformat()
    episodic_archive_cutoff = (now_dt - timedelta(days=_ARCHIVE_DAYS_EPISODIC)).isoformat()
    episodic_stale_candidates = _managed_query(
        """SELECT * FROM memories WHERE type = 'episodic_memory'
             AND status = 'active'
             AND datetime(updated_at) < datetime(?)
             AND importance < 0.65
             AND decay_policy != 'freeze'
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

    # ── Candidate timeouts (tiered by type) ──────────────────────────────────
    episodic_candidate_cutoff = (now_dt - timedelta(days=_CANDIDATE_TTL_EPISODIC_DAYS)).isoformat()
    precious_candidate_cutoff = (now_dt - timedelta(days=_CANDIDATE_TTL_PRECIOUS_DAYS)).isoformat()
    default_candidate_cutoff = (now_dt - timedelta(days=_CANDIDATE_TTL_DEFAULT_DAYS)).isoformat()

    # episodic candidates: 7-day window
    dead_candidates_episodic = _managed_query(
        """SELECT * FROM memories WHERE status = 'candidate'
             AND type = 'episodic_memory'
             AND datetime(updated_at) < datetime(?)
             AND importance < 0.65
             AND decay_policy != 'freeze'
           ORDER BY updated_at ASC LIMIT ?""",
        (episodic_candidate_cutoff, cap),
    )
    # precious type candidates: 30-day window, only if importance and feedback both low
    dead_candidates_precious = _managed_query(
        """SELECT * FROM memories WHERE status = 'candidate'
             AND type IN ('user_profile','environment_fact','decision','project_memory','skill_candidate')
             AND datetime(updated_at) < datetime(?)
             AND importance < 0.4
             AND feedback_score < 0
             AND decay_policy != 'freeze'
           ORDER BY updated_at ASC LIMIT ?""",
        (precious_candidate_cutoff, cap),
    )
    # other candidate types: 7-day window
    dead_candidates_default = _managed_query(
        """SELECT * FROM memories WHERE status = 'candidate'
             AND type NOT IN ('episodic_memory','user_profile','environment_fact',
                              'decision','project_memory','skill_candidate')
             AND datetime(updated_at) < datetime(?)
             AND importance < 0.5
             AND decay_policy != 'freeze'
           ORDER BY updated_at ASC LIMIT ?""",
        (default_candidate_cutoff, cap),
    )
    dead_candidates = dead_candidates_episodic + dead_candidates_precious + dead_candidates_default

    # ── Never-accessed candidate auto-archive ─────────────────────────────
    never_accessed_cutoff = (now_dt - timedelta(days=_NEVER_ACCESSED_CANDIDATE_DAYS)).isoformat()
    never_accessed_candidates = _managed_query(
        """SELECT * FROM memories WHERE status = 'candidate'
             AND last_accessed_at IS NULL
             AND injected_count = 0
             AND datetime(updated_at) < datetime(?)
             AND type NOT IN ('user_profile','environment_fact','decision','project_memory','skill_candidate')
             AND decay_policy != 'freeze'
           ORDER BY updated_at ASC LIMIT ?""",
        (never_accessed_cutoff, cap),
    )

    # ── Default stale: non-precious, non-episodic, long-lived active ──────────
    stale_cutoff = (now_dt - timedelta(days=max(1, int(stale_after_days)))).isoformat()
    stale_candidates = _managed_query(
        """SELECT * FROM memories WHERE status = 'active'
             AND type NOT IN ('user_profile','environment_fact','decision','project_memory','skill_candidate','episodic_memory')
             AND datetime(updated_at) < datetime(?)
             AND importance < 0.45
             AND feedback_score <= -0.5
             AND decay_policy NOT IN ('freeze', 'stable')
           ORDER BY updated_at ASC LIMIT ?""",
        (stale_cutoff, cap),
    )

    # precious type stale: only when feedback very negative (stable/freeze immune)
    precious_stale_candidates = _managed_query(
        """SELECT * FROM memories WHERE status = 'active'
             AND type IN ('user_profile','environment_fact','decision','project_memory','skill_candidate')
             AND feedback_score < -2.0
             AND importance < 0.3
             AND decay_policy NOT IN ('freeze', 'stable')
           ORDER BY feedback_score ASC LIMIT ?""",
        (cap,),
    )

    # ── Default archive: stale past archive threshold ─────────────────────────
    archive_cutoff = (now_dt - timedelta(days=max(1, int(archive_after_days)))).isoformat()
    archive_candidates = _managed_query(
        """SELECT * FROM memories WHERE status = 'stale'
             AND type NOT IN ('episodic_memory')
             AND updated_at < ?
           ORDER BY updated_at ASC LIMIT ?""",
        (archive_cutoff, cap),
    )

    # ── contradicted auto-archive ─────────────────────────────────────────────
    contradicted_cutoff = (now_dt - timedelta(days=_CONTRADICTED_ARCHIVE_DAYS)).isoformat()
    contradicted_archive_candidates = _managed_query(
        """SELECT * FROM memories WHERE status = 'contradicted'
             AND (last_accessed_at IS NULL OR last_accessed_at < ?)
           ORDER BY last_accessed_at ASC LIMIT ?""",
        (contradicted_cutoff, cap),
    )

    # ── stale → active revival ────────────────────────────────────────────────
    revival_cutoff = (now_dt - timedelta(days=7)).isoformat()
    revival_candidates = _managed_query(
        """SELECT * FROM memories WHERE status = 'stale'
             AND type != 'episodic_memory'
             AND last_injected_at >= ?
             AND effectiveness_score >= 0.5
             AND feedback_score >= 0
           ORDER BY effectiveness_score DESC LIMIT ?""",
        (revival_cutoff, cap),
    )

    # ── Auto-promote: high-importance candidates or frequently used ───────────
    promote_candidates = _managed_query(
        """SELECT * FROM memories WHERE status = 'candidate'
             AND (
               (importance >= ? AND feedback_score >= 0)
               OR injected_count >= ?
             )
           ORDER BY importance DESC LIMIT ?""",
        (_PROMOTE_IMPORTANCE_THRESHOLD, _PROMOTE_INJECTED_THRESHOLD, cap),
    )

    # ── Skill promotions ──────────────────────────────────────────────────────
    skill_promotion_candidates = _managed_query(
        """SELECT * FROM memories WHERE type = 'skill_candidate'
             AND status IN ('active','candidate') AND importance >= 0.65 AND feedback_score >= 0
           LIMIT ?""",
        (cap,),
    )

    # ── Contradiction detection ───────────────────────────────────────────────
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

    # ── Build action plan ─────────────────────────────────────────────────────
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

    # Revival first — takes priority over other stale rules
    for r in revival_candidates:
        _plan(r, "revive", "stale_revival", "active")
    for r in promote_candidates:
        _plan(r, "promote", "high_importance_candidate", "active")
    for r in low_feedback_candidates:
        _plan(r, "mark_stale", "low_feedback", "stale")
    for r in precious_stale_candidates:
        _plan(r, "mark_stale", "precious_negative_feedback", "stale")
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
    for r in never_accessed_candidates:
        _plan(r, "archive", "never_accessed_candidate", "archived")
    for r in contradicted_archive_candidates:
        _plan(r, "archive", "contradicted_expired", "archived")

    actions: list[dict[str, Any]] = []

    if not dry_run:
        from memorycore.storage.crud import update_status_batch
        decay_applied = 0
        with managed_conn() as conn:
            if auto_decay_candidates:
                now_ts = now()
                decay_rows = [
                    (max(_DECAY_MIN_CONFIDENCE, round(float(r["confidence"]) - _DECAY_STEP, 3)), now_ts, r["id"])
                    for r in auto_decay_candidates
                ]
                conn.executemany(
                    "UPDATE memories SET confidence=?, updated_at=? WHERE id=?",
                    decay_rows,
                )
                decay_applied = len(decay_rows)
            conn.execute(
                "DELETE FROM context_quality_events WHERE created_at < datetime('now', '-90 days')"
            )
            conn.execute(
                "DELETE FROM audit_events WHERE created_at < datetime('now', '-180 days')"
            )
            # Apply all status transitions in a single transaction (S-2 fix)
            batch_updates = [
                (planned["id"], "active" if planned["action"] in ("promote", "revive") else planned["target_status"])
                for planned in action_plan
            ]
            update_status_batch(conn, batch_updates)

        if decay_applied:
            from memorycore.storage.db import connect as _connect
            _connect().execute("PRAGMA wal_checkpoint(TRUNCATE)")

        for planned in action_plan:
            actions.append({
                "id": planned["id"],
                "action": planned["action"],
                "title": planned.get("title"),
            })

        stale_count = sum(1 for a in actions if a["action"] == "mark_stale")
        archive_count = sum(1 for a in actions if a["action"] == "archive")
        promote_count = sum(1 for a in actions if a["action"] == "promote")
        revive_count = sum(1 for a in actions if a["action"] == "revive")
        log_audit_event(
            "curator_apply",
            detail={
                "stale": stale_count,
                "archived": archive_count,
                "promoted": promote_count,
                "revived": revive_count,
                "auto_decay": decay_applied,
                "total_actions": len(actions),
                "actions": action_plan,
            },
        )

    total_scanned = _managed_query("SELECT COUNT(*) as cnt FROM memories", ())[0]["cnt"]
    all_stale = stale_candidates + episodic_stale_candidates + precious_stale_candidates
    all_archive = archive_candidates + episodic_archive_candidates + list(contradicted_archive_candidates)
    return {
        "dry_run": dry_run,
        "generated_at": now(),
        "scanned": total_scanned,
        "duplicate_title_groups": duplicate_title_groups,
        "low_feedback_candidates": low_feedback_candidates,
        "stale_candidates": all_stale,
        "archive_candidates": all_archive,
        "never_accessed_candidates": never_accessed_candidates,
        "contradiction_candidates": contradiction_candidates,
        "skill_promotion_candidates": skill_promotion_candidates,
        "auto_decay_candidates": auto_decay_candidates,
        "promote_candidates": promote_candidates,
        "revival_candidates": revival_candidates,
        "action_plan": action_plan,
        "actions": actions,
        "summary": {
            "duplicates": len(duplicate_title_groups),
            "low_feedback": len(low_feedback_candidates),
            "stale": len(all_stale),
            "archive": len(all_archive) + len(dead_candidates) + len(never_accessed_candidates),
            "contradictions": len(contradiction_candidates),
            "skill_promotions": len(skill_promotion_candidates),
            "auto_decay_candidates": len(auto_decay_candidates),
            "promote_candidates": len(promote_candidates),
            "revival_candidates": len(revival_candidates),
            "planned_actions": len(action_plan),
            "actions": len(actions),
        },
    }
