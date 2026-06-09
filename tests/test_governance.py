import json

from memorycore.storage import (
    add_memory_record,
    apply_governance_decision,
    convert_llm_findings_to_decisions,
    create_governance_decision,
    get_audit_log,
    get_governance_metrics,
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
    assert decision["candidate_hash"]
    assert decision["policy_reasons"] == []
    assert decision["policy_version"]
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


def test_policy_gate_returns_structured_reasons_and_version():
    result = policy_gate(
        "archive_duplicate",
        0.80,
        "high",
        memories=[{"type": "user_profile", "importance": 0.9, "feedback_score": 1.0}],
    )

    assert result["review_status"] == "needs_review"
    assert result["policy_version"]
    assert "precious_memory_type" in result["policy_reasons"]
    assert "high_importance_memory" in result["policy_reasons"]
    assert "high_risk_action" in result["policy_reasons"]


def test_create_governance_decision_dedupes_open_candidate_hash():
    record = add_memory_record("episodic_memory", "Dedupe candidate", "Same recommendation", importance=0.2)
    finding = {"id": record["id"], "action": "downgrade", "new_importance": 0.1}

    before_count = len(list_governance_decisions(limit=500))
    first = create_governance_decision(
        "importance_reassessment",
        "downgrade",
        [record["id"]],
        0.95,
        "low",
        finding,
    )
    second = create_governance_decision(
        "importance_reassessment",
        "downgrade",
        [record["id"]],
        0.95,
        "low",
        dict(finding),
    )
    after_count = len(list_governance_decisions(limit=500))

    # Second call returns same decision — no new row created
    assert second["id"] == first["id"]
    assert first["candidate_hash"]
    assert after_count == before_count + 1


def test_policy_gate_rejects_llm_sql_injection_in_action():
    sql_actions = [
        "UPDATE memories SET status='archived' WHERE 1=1",
        "SELECT * FROM memories",
        "DELETE FROM memories WHERE id='x'",
        "DROP TABLE memories",
    ]
    for sql_action in sql_actions:
        result = policy_gate(sql_action, 0.99, "low")
        assert result["review_status"] == "rejected", f"Expected rejected for: {sql_action!r}"
        assert "llm_instruction_injection_in_action" in result["policy_reasons"]


def test_create_governance_decision_with_sql_action_is_rejected_by_policy():
    record = add_memory_record("episodic_memory", "SQL injection target", "Victim content", importance=0.2)

    decision = create_governance_decision(
        "importance_reassessment",
        "UPDATE memories SET status='archived' WHERE 1=1",
        [record["id"]],
        0.99,
        "low",
        {"id": record["id"]},
    )

    assert decision["review_status"] == "rejected"
    assert "llm_instruction_injection_in_action" in decision["policy_reasons"]
    # Memory must not have been mutated
    with read_conn() as conn:
        row = conn.execute("SELECT status FROM memories WHERE id=?", (record["id"],)).fetchone()
    assert row["status"] == "active"


def test_apply_records_execution_metadata_and_rollback_is_idempotent():
    record = add_memory_record("episodic_memory", "Execution metadata", "Can be downgraded", importance=0.6)
    decision = create_governance_decision(
        "importance_reassessment",
        "downgrade",
        [record["id"]],
        0.95,
        "low",
        {"id": record["id"], "action": "downgrade", "new_importance": 0.2},
    )

    applied = apply_governance_decision(decision["id"], source_agent="pytest")
    rolled_back = rollback_governance_decision(decision["id"], source_agent="pytest")
    rolled_back_again = rollback_governance_decision(decision["id"], source_agent="pytest")

    assert applied["decision"]["execution_id"]
    assert applied["decision"]["applied_by"] == "pytest"
    assert applied["decision"]["approval_kind"] == "auto"
    assert rolled_back["decision"]["rolled_back_by"] == "pytest"
    assert rolled_back_again["already_rolled_back"] is True
    assert rolled_back_again["decision"]["review_status"] == "rolled_back"


def test_get_governance_metrics_structure_and_rates():
    record = add_memory_record("episodic_memory", "Metrics target", "Can be downgraded", importance=0.6)
    decision = create_governance_decision(
        "importance_reassessment",
        "downgrade",
        [record["id"]],
        0.95,
        "low",
        {"id": record["id"], "action": "downgrade", "new_importance": 0.2},
    )
    apply_governance_decision(decision["id"], source_agent="pytest")
    rollback_governance_decision(decision["id"], source_agent="pytest")

    metrics = get_governance_metrics()

    assert "applied_count" in metrics
    assert "rolled_back_count" in metrics
    assert "needs_review_count" in metrics
    assert "rejected_count" in metrics
    assert "rollback_rate" in metrics
    assert "revival_rate" in metrics
    assert "review_queue_age_hours" in metrics
    assert "rejection_rate_by_type" in metrics
    assert "auto_supersede_enabled" in metrics
    assert "degraded_warning" in metrics
    assert "policy_version" in metrics
    assert isinstance(metrics["rollback_rate"], float)
    assert isinstance(metrics["revival_rate"], float)
    assert isinstance(metrics["rejection_rate_by_type"], dict)
    assert metrics["rolled_back_count"] >= 1
    assert metrics["rollback_rate"] > 0.0


def test_split_action_routes_to_needs_review_via_policy_gate():
    result = policy_gate(
        "split",
        0.95,
        "high",
        memories=[{"type": "episodic_memory", "importance": 0.3, "feedback_score": 0}],
    )
    assert result["review_status"] == "needs_review"
    assert "split_requires_manual_action" in result["policy_reasons"]


def test_split_apply_creates_children_and_archives_parent():
    import pytest
    record = add_memory_record("episodic_memory", "Split target", "Fact one. Fact two.", importance=0.4)
    decision = create_governance_decision(
        "split_candidate",
        "split",
        [record["id"]],
        0.90,
        "high",
        {
            "id": record["id"],
            "action": "split",
            "sub_memories": [
                {"title": "Fact one", "content": "Fact one.", "importance": 0.4},
                {"title": "Fact two", "content": "Fact two.", "importance": 0.4},
            ],
        },
    )
    assert decision["review_status"] == "needs_review"

    result = apply_governance_decision(decision["id"], source_agent="pytest")

    assert result["decision"]["review_status"] == "applied"
    payload = result.get("applied", {})
    assert payload.get("children_created") == 2
    assert len(payload.get("child_ids", [])) == 2

    from memorycore.storage import get_record
    parent = get_record(record["id"])
    assert parent["status"] == "archived"

    from memorycore.storage.db import read_conn as _rc
    with _rc() as conn:
        links = conn.execute(
            "SELECT relation_type FROM memory_links WHERE source_id=? OR target_id=?",
            (record["id"], record["id"]),
        ).fetchall()
    relation_types = {r["relation_type"] for r in links}
    assert "part_of" in relation_types
    assert "supports" in relation_types
