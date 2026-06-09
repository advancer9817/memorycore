"""Tests for Temporal Memory Layer: valid_from/valid_until + auto_decay."""
from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone

import memorycore as lm
from memorycore.storage import add_memory_record, build_context_pack, memory_lineage, search_memory_records, supersede_memory_record
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


# ── superseded / lineage ─────────────────────────────────────────────────────


def test_superseded_status_is_valid_and_excluded_from_default_search():
    r = add_memory_record("feedback", "OldFact", "old superseded content", status="superseded")
    assert r["status"] == "superseded"
    results = search_memory_records("old superseded content")
    assert r["id"] not in [item["id"] for item in results]


def test_context_pack_recency_soft_boost_prefers_newer_equally_relevant_memory():
    old = add_memory_record("feedback", "SharedRecency", "shared recency ranking marker")
    new = add_memory_record("feedback", "SharedRecency", "shared recency ranking marker")
    with managed_conn() as conn:
        conn.execute(
            "UPDATE memories SET updated_at=?, importance=0.5, effectiveness_score=0.5, feedback_score=0 WHERE id=?",
            (_past(400), old["id"]),
        )
        conn.execute(
            "UPDATE memories SET updated_at=?, importance=0.5, effectiveness_score=0.5, feedback_score=0 WHERE id=?",
            (_future(0), new["id"]),
        )

    pack = build_context_pack("shared recency ranking marker", token_budget=1000)
    ordered_ids = pack["used_ids"]
    assert ordered_ids.index(new["id"]) < ordered_ids.index(old["id"])


def test_supersede_memory_record_marks_old_and_links_lineage():
    old = add_memory_record("feedback", "Fact", "old fact content")
    new = add_memory_record("feedback", "Fact", "new fact content")

    result = supersede_memory_record(old["id"], new["id"], source_agent="pytest", note="newer correction")

    assert result["old"]["status"] == "superseded"
    assert result["old"]["superseded_by"] == new["id"]
    assert result["old"]["fact_lineage_root"] == old["id"]
    assert result["new"]["fact_lineage_root"] == old["id"]

    lineage = memory_lineage(new["id"])
    lineage_ids = {record["id"] for record in lineage["records"]}
    assert {old["id"], new["id"]}.issubset(lineage_ids)
    assert any(link["source_id"] == new["id"] and link["target_id"] == old["id"] for link in lineage["links"])

    with managed_conn() as conn:
        audit = conn.execute(
            "SELECT detail_json FROM audit_events WHERE event_type='memory_supersede' AND memory_id=?",
            (old["id"],),
        ).fetchone()
    assert audit is not None


# ── auto_decay in curator_report ─────────────────────────────────────────────

def _set_last_accessed(memory_id: str, days_ago: int) -> None:
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    with managed_conn() as conn:
        conn.execute(
            "UPDATE memories SET last_accessed_at=?, updated_at=?, effectiveness_score=0.2, importance=0.4, injected_count=1 WHERE id=?",
            (ts, ts, memory_id),
        )


def test_curator_reports_supersession_candidates_for_newer_same_fact():
    old = add_memory_record("feedback", "Same Fact", "old same fact content", importance=0.4)
    new = add_memory_record("feedback", "Same Fact", "new same fact content", importance=0.4)
    with managed_conn() as conn:
        conn.execute("UPDATE memories SET updated_at=? WHERE id=?", (_past(10), old["id"]))
        conn.execute("UPDATE memories SET updated_at=? WHERE id=?", (_future(0), new["id"]))

    report = curator_report(dry_run=True)
    candidates = report["supersession_candidates"]
    assert any(candidate["old_id"] == old["id"] and candidate["new_id"] == new["id"] for candidate in candidates)
    assert report["summary"]["supersession_candidates"] >= 1


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
