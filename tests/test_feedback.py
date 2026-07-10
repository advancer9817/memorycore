import json

import pytest

import memorycore as lm


def set_created_at(memory_id, value):
    with lm.managed_conn() as conn:
        conn.execute("UPDATE memories SET created_at=? WHERE id=?", (value, memory_id))


def test_feedback_scores_are_averaged():
    record = lm.add_memory_record("project_memory", "Feedback target", "Content", memory_id="mem-feedback")

    first = lm.add_feedback(record["id"], 4, note="helpful", source_agent="pytest")
    assert first["memory"]["feedback_score"] == 4

    second = lm.add_feedback(record["id"], -2)
    assert second["memory"]["feedback_score"] == 1


def test_feedback_rejects_invalid_score_and_missing_memory():
    record = lm.add_memory_record("project_memory", "Feedback target", "Content")

    with pytest.raises(ValueError, match="score must be <="):
        lm.add_feedback(record["id"], 11)

    with pytest.raises(ValueError, match="memory not found"):
        lm.add_feedback("missing", 1)


def test_seed_feedback_does_not_increment_injected_count():
    record = lm.add_memory_record("project_memory", "Seed feedback", "Content")

    result = lm.add_feedback(
        record["id"],
        0.4,
        note="auto:seed",
        source_agent="system",
        count_as_injection=False,
    )

    assert result["memory"]["injected_count"] == 0
    assert result["memory"]["feedback_score"] == 0.4
    audits = lm.get_audit_log(memory_id=record["id"], event_type="memory_feedback")
    detail = json.loads(audits[0]["detail_json"])
    assert detail["note"] == "auto:seed"
    assert detail["count_as_injection"] is False


def test_update_status_validates_and_returns_record():
    record = lm.add_memory_record("project_memory", "Status target", "Content")

    updated = lm.update_status(record["id"], "stale")
    assert updated["status"] == "stale"

    with pytest.raises(ValueError, match="status must be one of"):
        lm.update_status(record["id"], "bad")

    with pytest.raises(ValueError, match="memory not found"):
        lm.update_status("missing", "active")


def test_timeline_returns_chronological_decision_timeline_feedback_records():
    lm.add_memory_record("timeline_event", "First event", "alpha", memory_id="first")
    lm.add_memory_record("project_memory", "Ignored", "alpha", memory_id="ignored")
    lm.add_memory_record("decision", "Second decision", "alpha", memory_id="second")
    lm.add_memory_record("feedback", "Third feedback", "alpha", memory_id="third")
    set_created_at("first", "2024-01-01T00:00:00+00:00")
    set_created_at("second", "2024-01-02T00:00:00+00:00")
    set_created_at("third", "2024-01-03T00:00:00+00:00")

    rows = lm.timeline("alpha")

    assert [r["id"] for r in rows] == ["first", "second", "third"]
