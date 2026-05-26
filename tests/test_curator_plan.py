from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import local_memory_mcp as lm


def _set_updated_at(memory_id: str, value: str) -> None:
    with lm.managed_conn() as conn:
        conn.execute("UPDATE memories SET updated_at=? WHERE id=?", (value, memory_id))


def test_curator_dry_run_returns_action_plan_with_reasons_and_rollback():
    record = lm.add_memory_record("project_memory", "Noisy", "Low value", memory_id="plan-noisy")
    lm.add_feedback(record["id"], -1)

    report = lm.curator_report(dry_run=True)
    action = report["action_plan"][0]

    assert report["actions"] == []
    assert action["id"] == "plan-noisy"
    assert action["action"] == "mark_stale"
    assert action["reason"] == "low_feedback"
    assert action["rollback"] == {"status": "active"}


def test_curator_allow_actions_filters_apply_plan():
    old = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat(timespec="seconds")
    lm.add_memory_record("project_memory", "Old", "Content", importance=0.1, memory_id="allow-old")
    lm.add_memory_record("project_memory", "Stale", "Content", status="stale", memory_id="allow-stale")
    _set_updated_at("allow-old", old)
    _set_updated_at("allow-stale", old)

    report = lm.curator_report(
        dry_run=False,
        stale_after_days=5,
        archive_after_days=10,
        allow_actions=["archive"],
    )

    assert {action["action"] for action in report["action_plan"]} == {"archive"}
    assert lm.get_record("allow-old")["status"] == "active"
    assert lm.get_record("allow-stale")["status"] == "archived"


def test_curator_deny_actions_filters_apply_plan():
    record = lm.add_memory_record("project_memory", "Deny stale", "Content", memory_id="deny-stale")
    lm.add_feedback(record["id"], -1)

    report = lm.curator_report(dry_run=False, deny_actions=["mark_stale"])

    assert report["action_plan"] == []
    assert report["actions"] == []
    assert lm.get_record("deny-stale")["status"] == "active"


def test_curator_apply_audit_includes_rollback_metadata():
    record = lm.add_memory_record("project_memory", "Audit rollback", "Content", memory_id="audit-rollback")
    lm.add_feedback(record["id"], -1)

    lm.curator_report(dry_run=False)

    events = lm.get_audit_log(event_type="curator_apply", limit=1)
    detail = json.loads(events[0]["detail_json"])
    assert detail["total_actions"] == 1
    assert detail["actions"][0]["rollback"] == {"status": "active"}
