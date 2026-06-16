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

from memorycore.models import load_config, local_now, normalize_list, normalize_title_key, now
from memorycore.storage.db import _managed_query, managed_conn, read_conn
from memorycore.storage.audit import log_audit_event

def curator_report(
    dry_run: bool = True,
    limit: int = 500,
    stale_after_days: int = 365,
    archive_after_days: int = 730,
    allow_actions: Any = None,
    deny_actions: Any = None,
) -> dict[str, Any]:
    now_dt = local_now()
    cap = max(1, min(int(limit), 5000))

    cfg = load_config().get("rule_curator", {})
    _DECAY_STEP = cfg.get("decay_step", 0.05)
    _DECAY_INTERVAL_DAYS = cfg.get("decay_interval_days", 30)
    _DECAY_MIN_CONFIDENCE = cfg.get("decay_min_confidence", 0.15)
    _CANDIDATE_TTL_EPISODIC_DAYS = cfg.get("candidate_ttl_episodic_days", 7)
    _CANDIDATE_TTL_PRECIOUS_DAYS = cfg.get("candidate_ttl_precious_days", 30)
    _CANDIDATE_TTL_DEFAULT_DAYS = cfg.get("candidate_ttl_default_days", 7)
    _STALE_DAYS_EPISODIC = cfg.get("stale_days_episodic", 14)
    _ARCHIVE_DAYS_EPISODIC = cfg.get("archive_days_episodic", 30)
    _CONTRADICTED_ARCHIVE_DAYS = cfg.get("contradicted_archive_days", 90)
    _NEVER_ACCESSED_CANDIDATE_DAYS = cfg.get("never_accessed_candidate_days", 14)
    _PROMOTE_IMPORTANCE_THRESHOLD = cfg.get("promote_importance_threshold", 0.75)
    _PROMOTE_INJECTED_THRESHOLD = cfg.get("promote_injected_threshold", 3)
    _PRECIOUS_TYPES = set(cfg.get("precious_types", ["user_profile", "environment_fact", "decision", "project_memory", "skill_candidate"]))
    stale_importance = cfg.get("stale_importance_threshold", 0.45)
    stale_feedback = cfg.get("stale_feedback_threshold", -0.5)
    precious_stale_fb = cfg.get("precious_stale_feedback", -2.0)
    precious_stale_imp = cfg.get("precious_stale_importance", 0.3)
    revival_window = cfg.get("revival_window_days", 7)
    revival_eff_min = cfg.get("revival_effectiveness_min", 0.5)
    revival_fb_min = cfg.get("revival_feedback_min", 0.0)
    skill_imp = cfg.get("skill_promote_importance", 0.65)
    skill_fb_min = cfg.get("skill_promote_feedback_min", 0.0)

    # Single read — all subsequent categorisation is Python-side filtering.
    with read_conn() as conn:
        all_rows = [
            dict(r) for r in
            conn.execute("SELECT * FROM memories ORDER BY updated_at DESC LIMIT ?", (cap,)).fetchall()
        ]
    total_scanned_count = len(all_rows)

    # Pre-compute cutoffs
    decay_cutoff         = (now_dt - timedelta(days=_DECAY_INTERVAL_DAYS)).isoformat()
    episodic_stale_cutoff   = (now_dt - timedelta(days=_STALE_DAYS_EPISODIC)).isoformat()
    episodic_archive_cutoff = (now_dt - timedelta(days=_ARCHIVE_DAYS_EPISODIC)).isoformat()
    episodic_cand_cutoff    = (now_dt - timedelta(days=_CANDIDATE_TTL_EPISODIC_DAYS)).isoformat()
    precious_cand_cutoff    = (now_dt - timedelta(days=_CANDIDATE_TTL_PRECIOUS_DAYS)).isoformat()
    default_cand_cutoff     = (now_dt - timedelta(days=_CANDIDATE_TTL_DEFAULT_DAYS)).isoformat()
    never_accessed_cutoff   = (now_dt - timedelta(days=_NEVER_ACCESSED_CANDIDATE_DAYS)).isoformat()
    stale_cutoff            = (now_dt - timedelta(days=max(1, int(stale_after_days)))).isoformat()
    archive_cutoff          = (now_dt - timedelta(days=max(1, int(archive_after_days)))).isoformat()
    contradicted_cutoff     = (now_dt - timedelta(days=_CONTRADICTED_ARCHIVE_DAYS)).isoformat()
    revival_cutoff          = (now_dt - timedelta(days=revival_window)).isoformat()
    now_ts = now()

    _PRECIOUS = _PRECIOUS_TYPES

    def _s(r: dict, key: str, default: Any = None) -> Any:
        v = r.get(key)
        return default if v is None else v

    by_title: dict[str, list[dict[str, Any]]] = {}
    low_feedback_candidates: list[dict] = []
    auto_decay_candidates: list[dict] = []
    episodic_stale_candidates: list[dict] = []
    episodic_archive_candidates: list[dict] = []
    dead_candidates_episodic: list[dict] = []
    dead_candidates_precious: list[dict] = []
    dead_candidates_default: list[dict] = []
    never_accessed_candidates: list[dict] = []
    stale_candidates: list[dict] = []
    precious_stale_candidates: list[dict] = []
    archive_candidates: list[dict] = []
    contradicted_archive_candidates: list[dict] = []
    revival_candidates: list[dict] = []
    promote_candidates: list[dict] = []
    skill_promotion_candidates: list[dict] = []
    evolution_candidates: list[dict] = []
    supersession_candidates: list[dict[str, Any]] = []

    for r in all_rows:
        typ = _s(r, "type", "")
        status = _s(r, "status", "")
        importance = float(_s(r, "importance", 0.5))
        feedback = float(_s(r, "feedback_score", 0.0))
        confidence = float(_s(r, "confidence", 0.7))
        decay = _s(r, "decay_policy", "review")
        updated = _s(r, "updated_at", "")
        last_accessed = _s(r, "last_accessed_at")
        injected = int(_s(r, "injected_count", 0))
        effectiveness = float(_s(r, "effectiveness_score", 0.5))
        content_len = len(_s(r, "content", ""))
        last_injected = _s(r, "last_injected_at")

        # title dedup
        key = normalize_title_key(_s(r, "title", ""))
        if key:
            by_title.setdefault(key, []).append(r)

        if decay == "freeze":
            continue

        # low feedback → mark stale
        if status in ("active", "candidate") and feedback < -1.0 and typ not in _PRECIOUS:
            low_feedback_candidates.append(r)

        # auto decay
        if (status == "active" and decay == "review"
                and (last_accessed is None or last_accessed < decay_cutoff)
                and effectiveness < 0.3 and importance < 0.5
                and injected > 0 and confidence > _DECAY_MIN_CONFIDENCE):
            auto_decay_candidates.append(r)

        if typ == "episodic_memory":
            if status == "active" and updated < episodic_stale_cutoff and importance < 0.65:
                episodic_stale_candidates.append(r)
            if status == "stale" and updated < episodic_archive_cutoff:
                episodic_archive_candidates.append(r)
            if (status == "candidate" and updated < episodic_cand_cutoff and importance < 0.65):
                dead_candidates_episodic.append(r)

        if status == "candidate":
            if typ in _PRECIOUS:
                if updated < precious_cand_cutoff and importance < 0.4 and feedback < 0:
                    dead_candidates_precious.append(r)
            elif typ != "episodic_memory":
                if updated < default_cand_cutoff and importance < 0.5:
                    dead_candidates_default.append(r)
            # never-accessed candidate
            if (last_accessed is None and injected == 0
                    and updated < never_accessed_cutoff and typ not in _PRECIOUS):
                never_accessed_candidates.append(r)
            # promote
            if (importance >= _PROMOTE_IMPORTANCE_THRESHOLD and feedback >= 0) or injected >= _PROMOTE_INJECTED_THRESHOLD:
                promote_candidates.append(r)

        # default stale: non-precious, non-episodic
        if (status == "active" and typ not in _PRECIOUS and typ != "episodic_memory"
                and updated < stale_cutoff and importance < stale_importance
                and feedback <= stale_feedback and decay not in ("freeze", "stable")):
            stale_candidates.append(r)

        # precious stale
        if (status == "active" and typ in _PRECIOUS
                and feedback < precious_stale_fb and importance < precious_stale_imp and decay not in ("freeze", "stable")):
            precious_stale_candidates.append(r)

        # archive stale non-episodic
        if status == "stale" and typ != "episodic_memory" and updated < archive_cutoff:
            archive_candidates.append(r)

        # contradicted auto-archive
        if status == "contradicted" and (last_accessed is None or last_accessed < contradicted_cutoff):
            contradicted_archive_candidates.append(r)

        # stale revival
        if (status == "stale" and typ != "episodic_memory"
                and last_injected is not None and last_injected >= revival_cutoff
                and effectiveness >= revival_eff_min and feedback >= revival_fb_min):
            revival_candidates.append(r)

        # skill promotions
        if typ == "skill_candidate" and status in ("active", "candidate") and importance >= skill_imp and feedback >= skill_fb_min:
            skill_promotion_candidates.append(r)

        # evolution / contradiction detection
        if status in ("active", "candidate") and (content_len < 50 or feedback < -1.5):
            evolution_candidates.append(r)

    duplicate_title_groups = [v for k, v in by_title.items() if k and len(v) > 1]
    dead_candidates = dead_candidates_episodic + dead_candidates_precious + dead_candidates_default

    # Supersession candidates: same fact key/type/scope/project with newer active record.
    # Curator only reports these; applying supersession is handled by the explicit,
    # audited supersede operation so high-value memories never change silently.
    for group in duplicate_title_groups:
        active_group = [r for r in group if r.get("status") == "active"]
        if len(active_group) < 2:
            continue
        buckets: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for row in active_group:
            bucket_key = (
                str(row.get("type") or ""),
                str(row.get("scope") or "global"),
                str(row.get("project_path") or ""),
            )
            buckets.setdefault(bucket_key, []).append(row)
        for bucket_rows in buckets.values():
            if len(bucket_rows) < 2:
                continue
            ordered = sorted(bucket_rows, key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""), reverse=True)
            survivor = ordered[0]
            for old in ordered[1:]:
                is_precious = str(old.get("type") or "") in _PRECIOUS
                supersession_candidates.append({
                    "old_id": old["id"],
                    "new_id": survivor["id"],
                    "title": old.get("title"),
                    "type": old.get("type"),
                    "scope": old.get("scope"),
                    "project_path": old.get("project_path"),
                    "reason": "same_title_type_scope_project_newer_active_record",
                    "review_required": is_precious or float(old.get("importance") or 0) >= 0.7,
                    "action": "supersede_candidate",
                })

    # contradiction candidates (title-key overlap between active and contradicted)
    active_by_key: dict[str, list[dict]] = {}
    contradicted_by_key: dict[str, list[dict]] = {}
    for r in all_rows:
        k = normalize_title_key(_s(r, "title", ""))
        if not k:
            continue
        if r.get("status") == "active":
            active_by_key.setdefault(k, []).append(r)
        elif r.get("status") == "contradicted":
            contradicted_by_key.setdefault(k, []).append(r)
    contradiction_candidates: list[dict] = [
        {"title_key": k, "active": v, "contradicted": contradicted_by_key[k]}
        for k, v in active_by_key.items() if k in contradicted_by_key
    ]

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

    total_scanned = total_scanned_count
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
        "supersession_candidates": supersession_candidates,
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
            "supersession_candidates": len(supersession_candidates),
            "skill_promotions": len(skill_promotion_candidates),
            "auto_decay_candidates": len(auto_decay_candidates),
            "promote_candidates": len(promote_candidates),
            "revival_candidates": len(revival_candidates),
            "planned_actions": len(action_plan),
            "actions": len(actions),
        },
    }
