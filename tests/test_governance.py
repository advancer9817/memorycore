import json

from memorycore.storage import (
    add_memory_record,
    apply_governance_decision,
    convert_llm_findings_to_decisions,
    create_governance_decision,
    get_audit_log,
    list_governance_decisions,
    policy_gate,
    reject_governance_decision,
    rollback_governance_decision,
)
from memorycore.storage.db import read_conn


def test_policy_gate_auto_approves_low_risk_high_confidence_memory():
    result = policy_gate(
        "downgrade",
        0.95,
        "low",
        memories=[{"type": "episodic_memory", "importance": 0.2, "feedback_score": 0}],
    )

    assert result["review_status"] == "auto_approved"


def test_policy_gate_protects_precious_memory_from_auto_apply():
    result = policy_gate(
        "archive_duplicate",
        0.99,
        "low",
        memories=[{"type": "user_profile", "importance": 0.2, "feedback_score": 0}],
    )

    assert result["review_status"] == "needs_review"
    assert "precious" in result["policy_reason"]


def test_policy_gate_rejects_delete_and_reviews_merge_actions():
    delete_result = policy_gate(
        "delete",
        0.99,
        "low",
        memories=[{"type": "episodic_memory", "importance": 0.1, "feedback_score": 0}],
    )
    merge_result = policy_gate(
        "archive_and_merge_duplicate",
        0.99,
        "low",
        memories=[{"type": "episodic_memory", "importance": 0.1, "feedback_score": 0}],
    )

    assert delete_result["review_status"] == "rejected"
    assert merge_result["review_status"] == "needs_review"
    assert "merge" in merge_result["policy_reason"]


def test_governance_decision_persists_with_policy_status():
    record = add_memory_record("episodic_memory", "Low value note", "Temporary note", importance=0.2)

    decision = create_governance_decision(
        "importance_reassessment",
        "downgrade",
        [record["id"]],
        0.96,
        "low",
        {"id": record["id"], "action": "downgrade", "new_importance": 0.1},
    )

    assert decision["source_ids"] == [record["id"]]
    assert decision["review_status"] == "auto_approved"
    assert decision["llm_trace"]["rationale"] == ""
    assert decision["before_state"] == []
    assert decision["after_state"] == []
    assert list_governance_decisions(limit=1)[0]["id"] == decision["id"]


def test_convert_llm_finding_to_decision_keeps_precious_memory_in_review_queue():
    record = add_memory_record("project_memory", "Important project fact", "Do not archive casually", importance=0.4)
    report = {
        "importance_reassessments": [{"id": record["id"], "action": "archive", "new_importance": 0.1, "confidence": 0.99}],
    }

    result = convert_llm_findings_to_decisions(report, auto_apply=True)

    decision = result["decisions"][0]
    assert decision["review_status"] == "needs_review"
    assert result["auto_applied"] == []
    with read_conn() as conn:
        status = conn.execute("SELECT status FROM memories WHERE id=?", (record["id"],)).fetchone()["status"]
    assert status == "active"


def test_auto_approved_apply_and_rollback_are_audited():
    record = add_memory_record("episodic_memory", "Drifted score", "Can be downgraded", importance=0.6)
    decision = create_governance_decision(
        "importance_reassessment",
        "downgrade",
        [record["id"]],
        0.95,
        "low",
        {"id": record["id"], "action": "downgrade", "new_importance": 0.2},
    )

    applied = apply_governance_decision(decision["id"], source_agent="pytest")

    assert applied["decision"]["review_status"] == "applied"
    assert applied["decision"]["before_state"]
    assert applied["decision"]["after_state"]
    with read_conn() as conn:
        row = conn.execute("SELECT importance FROM memories WHERE id=?", (record["id"],)).fetchone()
    assert row["importance"] == 0.2

    rollback = rollback_governance_decision(decision["id"], source_agent="pytest")

    assert rollback["decision"]["review_status"] == "rolled_back"
    with read_conn() as conn:
        row = conn.execute("SELECT importance FROM memories WHERE id=?", (record["id"],)).fetchone()
    assert row["importance"] == 0.6
    assert get_audit_log(event_type="governance_decision_apply", limit=1)
    assert get_audit_log(event_type="governance_decision_rollback", limit=1)


def test_llm_finding_persists_trace_fields():
    record = add_memory_record("episodic_memory", "Trace candidate", "Trace content", importance=0.2)
    report = {
        "importance_reassessments": [{
            "id": record["id"],
            "action": "downgrade",
            "new_importance": 0.1,
            "confidence": 0.96,
            "reason": "less useful",
            "llm_prompt": "score this memory",
            "llm_raw": '{"results": []}',
            "llm_thinking": "hidden trace summary",
        }],
    }

    result = convert_llm_findings_to_decisions(report, auto_apply=False)

    trace = result["decisions"][0]["llm_trace"]
    assert trace["prompt"] == "score this memory"
    assert trace["response"] == '{"results": []}'
    assert trace["rationale"] == "less useful"


def test_reject_governance_decision_writes_audit():
    record = add_memory_record("episodic_memory", "Reject candidate", "No change", importance=0.2)
    decision = create_governance_decision(
        "importance_reassessment",
        "downgrade",
        [record["id"]],
        0.95,
        "low",
        {"id": record["id"], "action": "downgrade", "new_importance": 0.1},
    )

    rejected = reject_governance_decision(decision["id"], source_agent="pytest", reason="bad recommendation")

    assert rejected["review_status"] == "rejected"
    rows = get_audit_log(event_type="governance_decision_reject", limit=1)
    detail = json.loads(rows[0]["detail_json"])
    assert detail["decision_id"] == decision["id"]
