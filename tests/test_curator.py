from datetime import datetime, timedelta, timezone

import local_memory_mcp as lm


def set_updated_at(memory_id, value):
    with lm.managed_conn() as conn:
        conn.execute("UPDATE memories SET updated_at=? WHERE id=?", (value, memory_id))


def test_empty_curator_report():
    report = lm.curator_report(dry_run=True)

    assert report["scanned"] == 0
    assert report["summary"]["duplicates"] == 0
    assert report["actions"] == []


def test_curator_detects_duplicate_title_and_low_feedback():
    first = lm.add_memory_record("feedback", "Duplicate Title", "one", memory_id="dup-1")
    lm.add_memory_record("decision", " duplicate   title ", "two", memory_id="dup-2")
    lm.add_feedback(first["id"], -2)

    report = lm.curator_report(dry_run=True)

    assert report["summary"]["duplicates"] == 1
    assert report["summary"]["low_feedback"] == 1
    assert report["low_feedback_candidates"][0]["id"] == "dup-1"


def test_curator_dry_run_does_not_change_status_and_apply_marks_stale():
    record = lm.add_memory_record("feedback", "Low feedback", "Content", memory_id="low")
    lm.add_feedback(record["id"], -2)

    dry_report = lm.curator_report(dry_run=True)
    assert dry_report["summary"]["low_feedback"] == 1
    assert lm.get_record("low")["status"] == "active"

    applied = lm.curator_report(dry_run=False)
    assert applied["actions"] == [{"id": "low", "action": "mark_stale", "title": "Low feedback"}]
    assert lm.get_record("low")["status"] == "stale"


def test_curator_stale_and_archive_candidates():
    old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(timespec="seconds")
    stale_old = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat(timespec="seconds")
    old_record = lm.add_memory_record("feedback", "Old unimportant", "Content", importance=0.1, memory_id="old")
    lm.add_memory_record("feedback", "Already stale", "Content", status="stale", memory_id="stale")
    lm.add_feedback(old_record["id"], -1)
    set_updated_at("old", old)
    set_updated_at("stale", stale_old)

    report = lm.curator_report(dry_run=False, stale_after_days=5, archive_after_days=15)

    actions = {(a["id"], a["action"]) for a in report["actions"]}
    assert actions == {("old", "mark_stale"), ("stale", "archive")}
    assert lm.get_record("old")["status"] == "stale"
    assert lm.get_record("stale")["status"] == "archived"


def test_curator_archives_dead_candidates_and_promotes_important_candidates():
    dead_candidate = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat(timespec="seconds")
    fresh_candidate = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="seconds")
    promoted_candidate = (datetime.now(timezone.utc) - timedelta(hours=49)).isoformat(timespec="seconds")
    lm.add_memory_record(
        "feedback", "Dead candidate", "temporary task state", status="candidate",
        importance=0.4, memory_id="dead-candidate",
    )
    lm.add_memory_record(
        "feedback", "Fresh candidate", "temporary task state", status="candidate",
        importance=0.4, memory_id="fresh-candidate",
    )
    lm.add_memory_record(
        "project_memory", "Important candidate", "needs promotion", status="candidate",
        importance=0.8, memory_id="important-candidate",
    )
    set_updated_at("dead-candidate", dead_candidate)
    set_updated_at("fresh-candidate", fresh_candidate)
    set_updated_at("important-candidate", promoted_candidate)

    report = lm.curator_report(dry_run=False, stale_after_days=60, archive_after_days=120)

    assert {(a["id"], a["action"]) for a in report["actions"]} == {
        ("dead-candidate", "archive"),
        ("important-candidate", "promote"),
    }
    dead_record = lm.get_record("dead-candidate")
    fresh_record = lm.get_record("fresh-candidate")
    important_record = lm.get_record("important-candidate")
    assert dead_record is not None
    assert fresh_record is not None
    assert important_record is not None
    assert dead_record["status"] == "archived"
    assert fresh_record["status"] == "candidate"
    assert important_record["status"] == "active"


def test_consolidate_dry_run_reports_duplicates_and_low_feedback():
    record = lm.add_memory_record("project_memory", "Same", "one", memory_id="same-1")
    lm.add_memory_record("project_memory", "Same", "two", memory_id="same-2")
    lm.add_feedback(record["id"], -1)

    report = lm.consolidate(dry_run=True)

    assert report["dry_run"] is True
    assert report["applied"] is False
    assert len(report["duplicate_title_groups"]) == 1
    assert [r["id"] for r in report["low_feedback_candidates"]] == ["same-1"]


def test_contradiction_candidates_detected_by_title_key():
    """Active + contradicted records sharing a normalized title key are surfaced."""
    lm.add_memory_record("feedback", "Auth Method", "use JWT", status="active", memory_id="c-active")
    lm.add_memory_record("feedback", "Auth Method", "use sessions", status="contradicted", memory_id="c-contradicted")

    report = lm.curator_report(dry_run=True)

    keys = [c["title_key"] for c in report["contradiction_candidates"]]
    assert any("auth" in k or "method" in k for k in keys)
    assert report["summary"]["contradictions"] >= 1


def test_contradiction_candidates_not_listed_when_only_active():
    """Two active records with the same title are duplicates, not contradictions."""
    lm.add_memory_record("feedback", "Same Key", "v1", status="active", memory_id="sa1")
    lm.add_memory_record("feedback", "Same Key", "v2", status="active", memory_id="sa2")

    report = lm.curator_report(dry_run=True)

    assert report["summary"]["contradictions"] == 0
    assert report["summary"]["duplicates"] == 1


def test_contradiction_candidates_not_listed_without_active_counterpart():
    """A lone contradicted record without an active counterpart is not flagged."""
    lm.add_memory_record("feedback", "Orphan Contradiction", "old", status="contradicted", memory_id="oc1")

    report = lm.curator_report(dry_run=True)

    assert report["summary"]["contradictions"] == 0
