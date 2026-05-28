"""Tests for the v3 state machine: tiered candidate TTL, stale revival,
contradicted auto-archive, freeze/stable policy, precious-type protection,
and injected_count-based promotion."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import local_memory_mcp as lm


def _set_field(memory_id: str, **kwargs) -> None:
    sets = ", ".join(f"{k}=?" for k in kwargs)
    values = list(kwargs.values()) + [memory_id]
    with lm.managed_conn() as conn:
        conn.execute(f"UPDATE memories SET {sets} WHERE id=?", values)


# ─── candidate tiered TTL ────────────────────────────────────────────────────

def test_episodic_candidate_archived_after_7_days():
    """episodic candidate older than 7 days with low importance → dead_candidate."""
    old = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat(timespec="seconds")
    lm.add_memory_record(
        "episodic_memory", "Old episodic", "content",
        status="candidate", importance=0.5, source="manual", memory_id="ep-cand-old",
    )
    _set_field("ep-cand-old", updated_at=old)

    report = lm.curator_report(dry_run=False)
    assert lm.get_record("ep-cand-old")["status"] == "archived"


def test_episodic_candidate_kept_within_7_days():
    """episodic candidate younger than 7 days is NOT touched."""
    lm.add_memory_record(
        "episodic_memory", "Fresh episodic", "content",
        status="candidate", importance=0.5, source="manual", memory_id="ep-cand-fresh",
    )

    report = lm.curator_report(dry_run=False)
    assert lm.get_record("ep-cand-fresh")["status"] == "candidate"


def test_precious_candidate_kept_30_days():
    """project_memory candidate within 30 days is NOT archived even with low importance."""
    recent = (datetime.now(timezone.utc) - timedelta(days=15)).isoformat(timespec="seconds")
    lm.add_memory_record(
        "project_memory", "Mid-age project candidate", "content",
        status="candidate", importance=0.35, memory_id="proj-cand-mid",
    )
    _set_field("proj-cand-mid", updated_at=recent, feedback_score=-0.5)

    report = lm.curator_report(dry_run=False)
    assert lm.get_record("proj-cand-mid")["status"] == "candidate"


def test_precious_candidate_archived_after_30_days_if_bad():
    """project_memory candidate older than 30 days with low importance AND negative feedback → archived."""
    old = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat(timespec="seconds")
    lm.add_memory_record(
        "project_memory", "Old bad project candidate", "content",
        status="candidate", importance=0.35, memory_id="proj-cand-old-bad",
    )
    _set_field("proj-cand-old-bad", updated_at=old, feedback_score=-0.5)

    report = lm.curator_report(dry_run=False)
    assert lm.get_record("proj-cand-old-bad")["status"] == "archived"


def test_precious_candidate_survives_if_feedback_ok():
    """project_memory candidate older than 30 days but feedback >= 0 → NOT archived."""
    old = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat(timespec="seconds")
    lm.add_memory_record(
        "project_memory", "Old ok project candidate", "content",
        status="candidate", importance=0.35, memory_id="proj-cand-old-ok",
    )
    _set_field("proj-cand-old-ok", updated_at=old, feedback_score=0.0)

    report = lm.curator_report(dry_run=False)
    assert lm.get_record("proj-cand-old-ok")["status"] == "candidate"


# ─── candidate → active promotion via injected_count ─────────────────────────

def test_candidate_promoted_by_injected_count():
    """candidate with injected_count >= 3 is promoted to active regardless of importance."""
    lm.add_memory_record(
        "feedback", "Frequently used candidate", "content",
        status="candidate", importance=0.4, memory_id="inj-promote",
    )
    _set_field("inj-promote", injected_count=3, feedback_score=0.0)

    report = lm.curator_report(dry_run=False)
    assert lm.get_record("inj-promote")["status"] == "active"
    actions = {a["id"]: a["action"] for a in report["actions"]}
    assert actions.get("inj-promote") == "promote"


def test_candidate_not_promoted_below_injected_threshold():
    """candidate with injected_count < 3 and low importance is NOT promoted."""
    lm.add_memory_record(
        "feedback", "Rarely used candidate", "content",
        status="candidate", importance=0.4, memory_id="inj-no-promote",
    )
    _set_field("inj-no-promote", injected_count=1, feedback_score=0.0)

    report = lm.curator_report(dry_run=False)
    # Should remain candidate (not yet timed out)
    assert lm.get_record("inj-no-promote")["status"] == "candidate"


# ─── stale → active revival ──────────────────────────────────────────────────

def test_stale_record_revived_when_recently_injected():
    """stale record injected in last 7 days with good effectiveness → revived to active."""
    recent_injected = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(timespec="seconds")
    lm.add_memory_record(
        "environment_fact", "Revivable env fact", "content",
        status="stale", importance=0.6, memory_id="revive-me",
    )
    _set_field(
        "revive-me",
        last_injected_at=recent_injected,
        effectiveness_score=0.7,
        feedback_score=0.0,
    )

    report = lm.curator_report(dry_run=False)
    assert lm.get_record("revive-me")["status"] == "active"
    actions = {a["id"]: a["action"] for a in report["actions"]}
    assert actions.get("revive-me") == "revive"


def test_stale_not_revived_without_recent_injection():
    """stale record with old last_injected_at is NOT revived."""
    old_injected = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(timespec="seconds")
    lm.add_memory_record(
        "environment_fact", "Old stale env fact", "content",
        status="stale", importance=0.6, memory_id="no-revive",
    )
    _set_field(
        "no-revive",
        last_injected_at=old_injected,
        effectiveness_score=0.7,
        feedback_score=0.0,
    )

    report = lm.curator_report(dry_run=False)
    assert lm.get_record("no-revive")["status"] == "stale"


def test_stale_not_revived_with_negative_feedback():
    """stale record with negative feedback is NOT revived even if recently injected."""
    recent_injected = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(timespec="seconds")
    lm.add_memory_record(
        "environment_fact", "Bad stale record", "content",
        status="stale", importance=0.6, memory_id="no-revive-bad",
    )
    _set_field(
        "no-revive-bad",
        last_injected_at=recent_injected,
        effectiveness_score=0.7,
        feedback_score=-0.5,
    )

    report = lm.curator_report(dry_run=False)
    assert lm.get_record("no-revive-bad")["status"] == "stale"


def test_episodic_stale_not_revived():
    """episodic_memory stale is never revived (ephemeral by design)."""
    recent_injected = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
    lm.add_memory_record(
        "episodic_memory", "Old episodic stale", "content",
        status="stale", memory_id="ep-stale-no-revive",
    )
    _set_field(
        "ep-stale-no-revive",
        last_injected_at=recent_injected,
        effectiveness_score=0.8,
        feedback_score=0.0,
    )

    report = lm.curator_report(dry_run=False)
    assert lm.get_record("ep-stale-no-revive")["status"] == "stale"


# ─── contradicted auto-archive ────────────────────────────────────────────────

def test_contradicted_archived_after_90_days_no_access():
    """contradicted record with no access in 90 days → archived."""
    old_access = (datetime.now(timezone.utc) - timedelta(days=91)).isoformat(timespec="seconds")
    lm.add_memory_record(
        "feedback", "Old contradiction", "content",
        status="contradicted", memory_id="contra-old",
    )
    _set_field("contra-old", last_accessed_at=old_access)

    report = lm.curator_report(dry_run=False)
    assert lm.get_record("contra-old")["status"] == "archived"
    actions = {a["id"]: a["action"] for a in report["actions"]}
    assert actions.get("contra-old") == "archive"


def test_contradicted_kept_if_recently_accessed():
    """contradicted record accessed within 90 days is NOT archived."""
    recent_access = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(timespec="seconds")
    lm.add_memory_record(
        "feedback", "Recent contradiction", "content",
        status="contradicted", memory_id="contra-recent",
    )
    _set_field("contra-recent", last_accessed_at=recent_access)

    report = lm.curator_report(dry_run=False)
    assert lm.get_record("contra-recent")["status"] == "contradicted"


def test_contradicted_archived_if_never_accessed():
    """contradicted record with NULL last_accessed_at → archived."""
    old = (datetime.now(timezone.utc) - timedelta(days=91)).isoformat(timespec="seconds")
    lm.add_memory_record(
        "feedback", "Never accessed contradiction", "content",
        status="contradicted", memory_id="contra-never",
    )
    _set_field("contra-never", updated_at=old)

    report = lm.curator_report(dry_run=False)
    # last_accessed_at is NULL → should be archived
    assert lm.get_record("contra-never")["status"] == "archived"


# ─── decay_policy: freeze and stable ─────────────────────────────────────────

def test_freeze_policy_skips_all_curator_rules():
    """A record with decay_policy='freeze' is skipped by all auto curator rules."""
    lm.add_memory_record(
        "feedback", "Frozen record", "content",
        status="active", importance=0.1, decay_policy="freeze",
        memory_id="freeze-record",
    )
    lm.add_feedback("freeze-record", -3)
    old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat(timespec="seconds")
    _set_field("freeze-record", updated_at=old, feedback_score=-3.0)

    report = lm.curator_report(dry_run=False, stale_after_days=5, archive_after_days=10)
    assert lm.get_record("freeze-record")["status"] == "active"
    action_ids = {a["id"] for a in report["actions"]}
    assert "freeze-record" not in action_ids


def test_stable_policy_requires_very_negative_feedback_to_stale():
    """A non-precious record with decay_policy='stable' only stales with feedback < -2.0 AND importance < 0.3."""
    lm.add_memory_record(
        "timeline_event", "Stable record mild bad", "content",
        status="active", importance=0.4, decay_policy="stable",
        memory_id="stable-mild",
    )
    old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat(timespec="seconds")
    _set_field("stable-mild", updated_at=old, feedback_score=-0.6)

    report = lm.curator_report(dry_run=False, stale_after_days=5)
    assert lm.get_record("stable-mild")["status"] == "active"


# ─── precious type protection ─────────────────────────────────────────────────

def test_precious_type_not_staled_by_default_rule():
    """user_profile active with low importance but moderate feedback is NOT staled."""
    old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat(timespec="seconds")
    lm.add_memory_record(
        "user_profile", "Precious user pref", "likes dark mode",
        status="active", importance=0.4, memory_id="precious-pref",
    )
    _set_field("precious-pref", updated_at=old, feedback_score=-0.4)

    report = lm.curator_report(dry_run=False, stale_after_days=5)
    assert lm.get_record("precious-pref")["status"] == "active"


def test_precious_type_staled_only_with_very_negative_feedback():
    """user_profile with feedback < -2.0 AND importance < 0.3 IS staled."""
    lm.add_memory_record(
        "user_profile", "Bad user pref", "wrong value",
        status="active", importance=0.2, memory_id="precious-bad",
    )
    _set_field("precious-bad", feedback_score=-2.5)

    report = lm.curator_report(dry_run=False)
    assert lm.get_record("precious-bad")["status"] == "stale"


# ─── rollup: manual source episodic ──────────────────────────────────────────

def test_rollup_processes_manual_source_episodic():
    """episodic_memory with source='manual' is included in rollup scan."""
    from local_memory_mcp.storage.rollup import rollup_report
    lm.add_memory_record(
        "episodic_memory", "Hermes manual episodic", "user said X",
        status="candidate", source="manual", source_agent="hermes",
        memory_id="hermes-ep-manual",
    )

    result = rollup_report(dry_run=True, force=True)
    assert result["triggered"] is True
    assert "hermes-ep-manual" in result["source_ids"]


def test_rollup_still_processes_extraction_source():
    """episodic_memory with source='extraction' is still included in rollup scan."""
    from local_memory_mcp.storage.rollup import rollup_report
    lm.add_memory_record(
        "episodic_memory", "Extraction episodic", "extracted from session",
        status="candidate", source="extraction", source_agent="claude",
        memory_id="claude-ep-extraction",
    )

    result = rollup_report(dry_run=True, force=True)
    assert result["triggered"] is True
    assert "claude-ep-extraction" in result["source_ids"]
