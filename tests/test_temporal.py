"""Tests for Temporal Memory Layer: valid_from/valid_until + auto_decay."""
from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone

import memorycore as lm
from memorycore.storage import add_memory_record, search_memory_records
from memorycore.storage.curator import curator_report, _DECAY_STEP, _DECAY_MIN_CONFIDENCE
from memorycore.storage.db import managed_conn


@pytest.fixture(autouse=True)
def _db(isolated_memory_db):
    pass


def _future(days: int = 1) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _past(days: int = 1) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


# ── valid_from / valid_until storage ─────────────────────────────────────────

def test_add_with_valid_until_stores_value():
    vt = _future(7)
    r = add_memory_record("feedback", "TempMem", "content", valid_until=vt)
    assert r["valid_until"] == vt


def test_add_with_valid_from_stores_value():
    vf = _past(3)
    r = add_memory_record("feedback", "TempMem2", "content", valid_from=vf)
    assert r["valid_from"] == vf


def test_add_without_temporal_fields_defaults_to_none():
    r = add_memory_record("feedback", "Plain", "content")
    assert r.get("valid_from") is None
    assert r.get("valid_until") is None


# ── valid_until filtering in search ──────────────────────────────────────────

def test_expired_memory_excluded_from_search():
    add_memory_record("feedback", "Expired", "this is expired", valid_until=_past(1))
    results = search_memory_records("expired")
    titles = [r["title"] for r in results]
    assert "Expired" not in titles


def test_future_valid_until_included_in_search():
    add_memory_record("feedback", "Valid", "still valid content", valid_until=_future(7))
    results = search_memory_records("still valid content")
    titles = [r["title"] for r in results]
    assert "Valid" in titles


def test_null_valid_until_always_included():
    add_memory_record("feedback", "Permanent", "permanent content")
    results = search_memory_records("permanent content")
    titles = [r["title"] for r in results]
    assert "Permanent" in titles


def test_expired_memory_still_exists_in_db():
    r = add_memory_record("feedback", "ExpiredRaw", "raw expired", valid_until=_past(1))
    with managed_conn() as conn:
        row = conn.execute("SELECT id FROM memories WHERE id=?", (r["id"],)).fetchone()
    assert row is not None


# ── auto_decay in curator_report ─────────────────────────────────────────────

def _set_last_accessed(memory_id: str, days_ago: int) -> None:
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    with managed_conn() as conn:
        conn.execute(
            "UPDATE memories SET last_accessed_at=?, updated_at=?, effectiveness_score=0.2, importance=0.4, injected_count=1 WHERE id=?",
            (ts, ts, memory_id),
        )


def test_auto_decay_candidates_listed_in_dry_run():
    r = add_memory_record("feedback", "OldMem", "old content", decay_policy="review", confidence=0.7)
    _set_last_accessed(r["id"], 95)
    report = curator_report(dry_run=True)
    candidate_ids = [c["id"] for c in report["auto_decay_candidates"]]
    assert r["id"] in candidate_ids


def test_auto_decay_reduces_confidence_on_apply():
    r = add_memory_record("feedback", "DecayMem", "old content", decay_policy="review", confidence=0.7)
    _set_last_accessed(r["id"], 95)
    curator_report(dry_run=False)
    with managed_conn() as conn:
        row = conn.execute("SELECT confidence FROM memories WHERE id=?", (r["id"],)).fetchone()
    assert abs(row["confidence"] - (0.7 - _DECAY_STEP)) < 0.001


def test_auto_decay_does_not_go_below_min():
    r = add_memory_record("feedback", "NearFloor", "old", decay_policy="review", confidence=_DECAY_MIN_CONFIDENCE + 0.01)
    _set_last_accessed(r["id"], 95)
    curator_report(dry_run=False)
    with managed_conn() as conn:
        row = conn.execute("SELECT confidence FROM memories WHERE id=?", (r["id"],)).fetchone()
    assert row["confidence"] >= _DECAY_MIN_CONFIDENCE


def test_auto_decay_skips_stable_policy():
    r = add_memory_record("feedback", "Stable", "stable content", decay_policy="stable", confidence=0.8)
    _set_last_accessed(r["id"], 95)
    curator_report(dry_run=False)
    with managed_conn() as conn:
        row = conn.execute("SELECT confidence FROM memories WHERE id=?", (r["id"],)).fetchone()
    assert abs(row["confidence"] - 0.8) < 0.001


def test_auto_decay_skips_recently_accessed():
    r = add_memory_record("feedback", "Recent", "recent content", decay_policy="review", confidence=0.8)
    # explicitly set last_accessed_at to today so it is within the decay window
    ts = datetime.now(timezone.utc).isoformat()
    with managed_conn() as conn:
        conn.execute("UPDATE memories SET last_accessed_at=? WHERE id=?", (ts, r["id"]))
    report = curator_report(dry_run=True)
    candidate_ids = [c["id"] for c in report["auto_decay_candidates"]]
    assert r["id"] not in candidate_ids


def test_curator_summary_includes_auto_decay_count():
    r = add_memory_record("feedback", "SumMem", "sum content", decay_policy="review", confidence=0.7)
    _set_last_accessed(r["id"], 95)
    report = curator_report(dry_run=True)
    assert "auto_decay_candidates" in report["summary"]
    assert report["summary"]["auto_decay_candidates"] >= 1
