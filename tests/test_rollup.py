from datetime import datetime, timedelta, timezone

import memorycore as lm


def _old(memory_id: str, hours: int = 48) -> None:
    ts = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
    with lm.managed_conn() as conn:
        conn.execute("UPDATE memories SET created_at=?, updated_at=? WHERE id=?", (ts, ts, memory_id))


def _proposal(rows):
    return [
        {
            "type": "project_memory",
            "title": "Rollup summary",
            "content": "User wants episodic memories periodically condensed into durable memories.",
            "importance": 0.82,
            "confidence": 0.77,
            "tags": ["memory"],
            "source_ids": [row["id"] for row in rows],
        }
    ]


def test_rollup_does_not_trigger_below_threshold():
    lm.add_memory_record(
        "episodic_memory",
        "One event",
        "temporary event",
        source="extraction",
        source_agent="agent-a",
        status="candidate",
        memory_id="e1",
    )

    report = lm.rollup_report(dry_run=True, min_count=3, _summarize_fn=_proposal)

    assert report["triggered"] is False
    assert report["summary"]["proposed"] == 0
    assert lm.get_record("e1")["status"] == "candidate"


def test_rollup_dry_run_proposes_durable_records_without_writing():
    for idx in range(3):
        lm.add_memory_record(
            "episodic_memory",
            f"Event {idx}",
            f"memory fragment {idx}",
            source="extraction",
            source_agent="agent-a",
            status="candidate",
            memory_id=f"dry-{idx}",
        )

    report = lm.rollup_report(dry_run=True, min_count=3, _summarize_fn=_proposal)

    assert report["triggered"] is True
    assert report["trigger_reason"] == "count"
    assert report["summary"]["proposed"] == 1
    assert report["created_records"] == []
    assert all(lm.get_record(f"dry-{idx}")["status"] == "candidate" for idx in range(3))


def test_rollup_apply_creates_durable_record_and_archives_sources():
    for idx in range(3):
        lm.add_memory_record(
            "episodic_memory",
            f"Apply event {idx}",
            f"memory fragment {idx}",
            source="extraction",
            source_agent="agent-a",
            status="candidate",
            memory_id=f"apply-{idx}",
        )

    report = lm.rollup_report(dry_run=False, min_count=3, _summarize_fn=_proposal)

    assert report["summary"]["created"] == 1
    assert report["summary"]["archived_sources"] == 3
    created = report["created_records"][0]
    assert created["type"] == "project_memory"
    assert created["source"] == "rollup"
    assert created["status"] == "active"
    assert set(created["related_ids"]) == {"apply-0", "apply-1", "apply-2"}
    assert all(lm.get_record(f"apply-{idx}")["status"] == "archived" for idx in range(3))


def test_rollup_age_trigger_for_small_old_batch():
    for idx in range(2):
        lm.add_memory_record(
            "episodic_memory",
            f"Old event {idx}",
            f"old memory fragment {idx}",
            source="extraction",
            source_agent="agent-a",
            status="candidate",
            memory_id=f"old-{idx}",
        )
        _old(f"old-{idx}", hours=30)

    report = lm.rollup_report(
        dry_run=True,
        min_count=30,
        min_age_count=2,
        max_age_hours=24,
        _summarize_fn=_proposal,
    )

    assert report["triggered"] is True
    assert report["trigger_reason"] == "age"
    assert report["summary"]["proposed"] == 1
