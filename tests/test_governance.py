import json

from memorycore.storage import (
    add_memory_record,
    apply_governance_decision,
    apply_governance_decisions_batch,
    convert_llm_findings_to_decisions,
    create_governance_decision,
    get_audit_log,
    get_governance_metrics,
    list_governance_decisions,
    policy_gate,
    recalibrate_governance_review_queue,
    reject_governance_decision,
    rollback_governance_decision,
)
from memorycore.storage.db import managed_conn, read_conn


def mark_memories_as_old(*memory_ids: str) -> None:
    with managed_conn() as conn:
        for memory_id in memory_ids:
            conn.execute(
                "UPDATE memories SET created_at='2000-01-01T00:00:00', updated_at='2000-01-01T00:00:00' WHERE id=?",
                (memory_id,),
            )


def test_policy_gate_auto_approves_low_risk_high_confidence_memory():
    result = policy_gate(
        "downgrade",
        0.95,
        "low",
        memories=[{"type": "episodic_memory", "importance": 0.2, "feedback_score": 0}],
    )

    assert result["review_status"] == "auto_approved"


def test_policy_gate_auto_approves_precious_memory_under_relaxed_policy():
    result = policy_gate(
        "archive_duplicate",
        0.99,
        "low",
        memories=[{"type": "user_profile", "importance": 0.2, "feedback_score": 0}],
    )

    assert result["review_status"] == "auto_approved"


def test_policy_gate_auto_approves_low_risk_duplicate_archive_above_calibrated_threshold():
    result = policy_gate(
        "archive_duplicate",
        0.80,
        "low",
        memories=[{"type": "episodic_memory", "importance": 0.2, "feedback_score": 0}],
    )

    assert result["review_status"] == "auto_approved"


def test_policy_gate_auto_approves_positive_feedback_duplicate_archive():
    result = policy_gate(
        "archive_duplicate",
        0.99,
        "low",
        memories=[{"type": "episodic_memory", "importance": 0.2, "feedback_score": 1}],
    )

    assert result["review_status"] == "auto_approved"


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


def test_recalibrate_governance_review_queue_promotes_safe_existing_decisions_without_applying():
    keep = add_memory_record("episodic_memory", "Canonical duplicate", "Keep this duplicate", importance=0.3)
    drop = add_memory_record("episodic_memory", "Duplicate copy", "Drop this duplicate", importance=0.2)
    mark_memories_as_old(keep["id"], drop["id"])
    decision = create_governance_decision(
        "semantic_duplicate",
        "archive_duplicate",
        [keep["id"], drop["id"]],
        0.72,
        "low",
        {"keep_id": keep["id"], "drop_id": drop["id"], "action": "archive_duplicate"},
    )
    with managed_conn() as conn:
        conn.execute(
            "UPDATE governance_decisions SET review_status='needs_review', policy_reason='legacy threshold' WHERE id=?",
            (decision["id"],),
        )
    with read_conn() as conn:
        legacy = conn.execute("SELECT review_status FROM governance_decisions WHERE id=?", (decision["id"],)).fetchone()
    assert legacy["review_status"] == "needs_review"

    dry = recalibrate_governance_review_queue(dry_run=True, source_agent="pytest")
    assert dry["would_reclassify"] >= 1
    assert decision["id"] in dry["decision_ids"]
    with read_conn() as conn:
        before = conn.execute("SELECT review_status FROM governance_decisions WHERE id=?", (decision["id"],)).fetchone()
        drop_status = conn.execute("SELECT status FROM memories WHERE id=?", (drop["id"],)).fetchone()
    assert before["review_status"] == "needs_review"
    assert drop_status["status"] == "active"

    applied = recalibrate_governance_review_queue(dry_run=False, source_agent="pytest")
    assert applied["reclassified"] >= 1
    with read_conn() as conn:
        after = conn.execute("SELECT review_status FROM governance_decisions WHERE id=?", (decision["id"],)).fetchone()
        drop_status = conn.execute("SELECT status FROM memories WHERE id=?", (drop["id"],)).fetchone()
    assert after["review_status"] == "auto_approved"
    assert drop_status["status"] == "active"


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


def test_convert_llm_finding_auto_approves_precious_memory_under_relaxed_policy():
    record = add_memory_record("project_memory", "Important project fact", "Do not archive casually", importance=0.4)
    report = {
        "importance_reassessments": [{"id": record["id"], "action": "archive", "new_importance": 0.1, "confidence": 0.99}],
    }

    result = convert_llm_findings_to_decisions(report, auto_apply=True)

    decision = result["decisions"][0]
    assert decision["review_status"] in ("auto_approved", "applied")
    assert result["auto_applied"] != []


def test_convert_llm_findings_skips_keep_results():
    record = add_memory_record("episodic_memory", "Keep note", "No mutation needed", importance=0.2)
    report = {
        "importance_reassessments": [{"id": record["id"], "action": "keep", "confidence": 0.99}],
    }

    result = convert_llm_findings_to_decisions(report, auto_apply=True)

    assert result["decisions_created"] == 0
    assert result["decisions"] == []
    assert result["auto_applied"] == []
    assert result["skipped_keep"] == 1


def test_actionable_governance_list_excludes_history_and_noop_keep():
    active = add_memory_record("episodic_memory", "Active candidate", "Can be downgraded", importance=0.3)
    keep = add_memory_record("episodic_memory", "Keep candidate", "No mutation needed", importance=0.3)
    applied_record = add_memory_record("episodic_memory", "Applied candidate", "Already handled", importance=0.3)
    active_decision = create_governance_decision(
        "importance_reassessment",
        "downgrade",
        [active["id"]],
        0.75,
        "low",
        {"id": active["id"], "action": "downgrade", "new_importance": 0.2},
    )
    keep_decision = create_governance_decision(
        "importance_reassessment",
        "keep",
        [keep["id"]],
        0.95,
        "medium",
        {"id": keep["id"], "action": "keep"},
    )
    applied_decision = create_governance_decision(
        "importance_reassessment",
        "downgrade",
        [applied_record["id"]],
        0.95,
        "low",
        {"id": applied_record["id"], "action": "downgrade", "new_importance": 0.2},
    )
    apply_governance_decision(applied_decision["id"], source_agent="pytest")

    actionable_ids = {decision["id"] for decision in list_governance_decisions("actionable", limit=10)}

    assert active_decision["id"] in actionable_ids
    assert keep_decision["id"] not in actionable_ids
    assert applied_decision["id"] not in actionable_ids


def test_low_risk_importance_adjustments_auto_approve_at_result_threshold():
    record = add_memory_record("episodic_memory", "Moderate confidence", "Safe adjustment", importance=0.3)

    decision = create_governance_decision(
        "importance_reassessment",
        "promote",
        [record["id"]],
        0.70,
        "low",
        {"id": record["id"], "action": "promote", "new_importance": 0.5},
    )

    assert decision["review_status"] == "auto_approved"


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
        "archive_and_merge_duplicate",
        0.80,
        "high",
        memories=[{"type": "user_profile", "importance": 0.9, "feedback_score": 1.0}],
    )

    assert result["review_status"] == "needs_review"
    assert result["policy_version"]
    assert "merge_requires_review" in result["policy_reasons"]


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


def test_apply_governance_decisions_batch_success():
    record1 = add_memory_record("episodic_memory", "Batch record 1", "Will be downgraded", importance=0.8)
    record2 = add_memory_record("episodic_memory", "Batch record 2", "Will be downgraded", importance=0.7)

    d1 = create_governance_decision(
        "importance_reassessment",
        "downgrade",
        [record1["id"]],
        0.95,
        "low",
        {"id": record1["id"], "action": "downgrade", "new_importance": 0.2},
    )
    d2 = create_governance_decision(
        "importance_reassessment",
        "downgrade",
        [record2["id"]],
        0.95,
        "low",
        {"id": record2["id"], "action": "downgrade", "new_importance": 0.3},
    )

    res = apply_governance_decisions_batch([d1["id"], d2["id"]], source_agent="pytest_batch")

    assert res["applied_count"] == 2
    assert len(res["decisions"]) == 2
    assert res["run_id"]

    # Verify database updates
    with read_conn() as conn:
        mem1 = conn.execute("SELECT importance, status FROM memories WHERE id=?", (record1["id"],)).fetchone()
        mem2 = conn.execute("SELECT importance, status FROM memories WHERE id=?", (record2["id"],)).fetchone()

        dec1 = conn.execute("SELECT review_status, execution_id FROM governance_decisions WHERE id=?", (d1["id"],)).fetchone()
        dec2 = conn.execute("SELECT review_status, execution_id FROM governance_decisions WHERE id=?", (d2["id"],)).fetchone()

    assert mem1["importance"] == 0.2
    assert mem2["importance"] == 0.3
    assert dec1["review_status"] == "applied"
    assert dec2["review_status"] == "applied"
    assert dec1["execution_id"] != dec2["execution_id"]

    # Check audit log
    logs = get_audit_log(event_type="governance_decision_apply", limit=2)
    assert len(logs) >= 2


def test_apply_governance_decisions_batch_skips_policy_blocked_decisions():
    allowed_record = add_memory_record("episodic_memory", "Batch allowed", "Allowed downgrade", importance=0.8)
    blocked_record = add_memory_record("episodic_memory", "Batch blocked", "Blocked archive", importance=0.7)

    allowed = create_governance_decision(
        "importance_reassessment",
        "downgrade",
        [allowed_record["id"]],
        0.95,
        "low",
        {"id": allowed_record["id"], "action": "downgrade", "new_importance": 0.2},
    )
    blocked = create_governance_decision(
        "importance_reassessment",
        "downgrade",
        [blocked_record["id"]],
        0.30,
        "low",
        {"id": blocked_record["id"], "action": "downgrade", "new_importance": 0.1},
    )
    with managed_conn() as conn:
        conn.execute(
            "UPDATE governance_decisions SET review_status='auto_approved', policy_reason='legacy auto approval' WHERE id=?",
            (blocked["id"],),
        )

    assert allowed["review_status"] == "auto_approved"

    res = apply_governance_decisions_batch([allowed["id"], blocked["id"]], source_agent="pytest_batch")

    assert res["applied_count"] == 1
    assert [d["id"] for d in res["decisions"]] == [allowed["id"]]
    assert res["skipped_count"] == 1
    assert res["skipped"][0]["id"] == blocked["id"]
    assert "confidence_below_reject_threshold" in res["skipped"][0]["reason"]

    with read_conn() as conn:
        allowed_memory = conn.execute("SELECT importance FROM memories WHERE id=?", (allowed_record["id"],)).fetchone()
        blocked_memory = conn.execute("SELECT status FROM memories WHERE id=?", (blocked_record["id"],)).fetchone()
        allowed_decision = conn.execute("SELECT review_status FROM governance_decisions WHERE id=?", (allowed["id"],)).fetchone()
        blocked_decision = conn.execute("SELECT review_status FROM governance_decisions WHERE id=?", (blocked["id"],)).fetchone()

    assert allowed_memory["importance"] == 0.2
    assert blocked_memory["status"] == "active"
    assert allowed_decision["review_status"] == "applied"
    assert blocked_decision["review_status"] == "auto_approved"


def test_apply_governance_decisions_batch_rollback():
    record1 = add_memory_record("episodic_memory", "Rollback record 1", "Will not be downgraded", importance=0.8)
    record2 = add_memory_record("episodic_memory", "Rollback record 2", "Will not be downgraded", importance=0.7)

    d1 = create_governance_decision(
        "importance_reassessment",
        "downgrade",
        [record1["id"]],
        0.95,
        "low",
        {"id": record1["id"], "action": "downgrade", "new_importance": 0.2},
    )
    d2 = create_governance_decision(
        "importance_reassessment",
        "downgrade",
        [record2["id"]],
        0.95,
        "low",
        {"id": record2["id"], "action": "downgrade", "new_importance": 0.3},
    )

    # Reject the second decision so that it is in an invalid status for batch application
    reject_governance_decision(d2["id"], source_agent="pytest")

    try:
        apply_governance_decisions_batch([d1["id"], d2["id"]], source_agent="pytest_batch")
        assert False, "Should have failed due to rejected status on second decision"
    except ValueError as e:
        assert "cannot be applied from status" in str(e)

    # Verify that first decision was NOT applied (atomicity check)
    with read_conn() as conn:
        mem1 = conn.execute("SELECT importance FROM memories WHERE id=?", (record1["id"],)).fetchone()
        dec1 = conn.execute("SELECT review_status FROM governance_decisions WHERE id=?", (d1["id"],)).fetchone()

    assert mem1["importance"] == 0.8
    assert dec1["review_status"] == "auto_approved"
