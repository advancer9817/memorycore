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
    first = lm.add_memory_record("project_memory", "Duplicate Title", "one", memory_id="dup-1")
    lm.add_memory_record("decision", " duplicate   title ", "two", memory_id="dup-2")
    lm.add_feedback(first["id"], -1)

    report = lm.curator_report(dry_run=True)

    assert report["summary"]["duplicates"] == 1
    assert report["summary"]["low_feedback"] == 1
    assert report["low_feedback_candidates"][0]["id"] == "dup-1"


def test_curator_dry_run_does_not_change_status_and_apply_marks_stale():
    record = lm.add_memory_record("project_memory", "Low feedback", "Content", memory_id="low")
    lm.add_feedback(record["id"], -1)

    dry_report = lm.curator_report(dry_run=True)
    assert dry_report["summary"]["low_feedback"] == 1
    assert lm.get_record("low")["status"] == "active"

    applied = lm.curator_report(dry_run=False)
    assert applied["actions"] == [{"id": "low", "action": "mark_stale", "title": "Low feedback"}]
    assert lm.get_record("low")["status"] == "stale"


def test_curator_stale_and_archive_candidates():
    old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(timespec="seconds")
    stale_old = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat(timespec="seconds")
    lm.add_memory_record("project_memory", "Old unimportant", "Content", importance=0.1, memory_id="old")
    lm.add_memory_record("project_memory", "Already stale", "Content", status="stale", memory_id="stale")
    set_updated_at("old", old)
    set_updated_at("stale", stale_old)

    report = lm.curator_report(dry_run=False, stale_after_days=5, archive_after_days=15)

    actions = {(a["id"], a["action"]) for a in report["actions"]}
    assert actions == {("old", "mark_stale"), ("stale", "archive")}
    assert lm.get_record("old")["status"] == "stale"
    assert lm.get_record("stale")["status"] == "archived"


def test_consolidate_dry_run_reports_duplicates_and_low_feedback():
    record = lm.add_memory_record("project_memory", "Same", "one", memory_id="same-1")
    lm.add_memory_record("project_memory", "Same", "two", memory_id="same-2")
    lm.add_feedback(record["id"], -1)

    report = lm.consolidate(dry_run=True)

    assert report["dry_run"] is True
    assert report["applied"] is False
    assert len(report["duplicate_title_groups"]) == 1
    assert [r["id"] for r in report["low_feedback_candidates"]] == ["same-1"]
