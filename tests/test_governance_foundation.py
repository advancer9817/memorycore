import pytest

from memorycore.storage import add_memory_record, apply_governance_decision, create_governance_decision
from memorycore.storage.db import init_db, managed_conn, read_conn
from memorycore.storage.mutation_executor import create_execution, query_ledger
from memorycore.storage.mutations import MutationContext, MutationRequest, evaluate_mutation_policy, validate_execution_transition


def test_governance_ledger_schema_exists_and_is_idempotent():
    with managed_conn() as conn:
        init_db(conn)
        tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        indexes = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()}

    assert {"governance_runs", "governance_executions", "governance_mutation_log"} <= tables
    assert "idx_governance_runs_source_status" in indexes
    assert "idx_governance_executions_status" in indexes
    assert "idx_governance_mutation_log_entity" in indexes


def test_mutation_request_validation_rejects_invalid_inputs():
    with pytest.raises(ValueError, match="unsupported mutation action"):
        MutationRequest("bad", "memory", "id").validate()
    with pytest.raises(ValueError, match="actor is required"):
        evaluate_mutation_policy(
            MutationRequest("memory_status_update", "memory", "id", {"status": "archived"}, risk_level="low"),
            MutationContext(actor="", origin="governance"),
        )
    with pytest.raises(ValueError, match="unsupported mutation origin"):
        evaluate_mutation_policy(
            MutationRequest("memory_status_update", "memory", "id", {"status": "archived"}, risk_level="low"),
            MutationContext(actor="pytest", origin="unknown"),
        )
    with pytest.raises(ValueError, match="confidence"):
        MutationRequest("memory_status_update", "memory", "id", {"status": "archived"}, confidence=2.0).validate()
    with pytest.raises(ValueError, match="cannot require rollback"):
        MutationRequest("maintenance_cleanup", "maintenance", rollback_required=True).validate()


def test_mutation_policy_covers_allowed_queued_and_rejected_outcomes():
    context = MutationContext(actor="pytest", origin="governance")
    allowed = evaluate_mutation_policy(
        MutationRequest("memory_importance_update", "memory", "id", {"importance": 0.2}, risk_level="low", confidence=0.95),
        context,
    )
    queued = evaluate_mutation_policy(
        MutationRequest("memory_status_update", "memory", "id", {"status": "contradicted"}, risk_level="medium", confidence=0.60),
        context,
    )
    rejected = evaluate_mutation_policy(
        MutationRequest("memory_importance_update", "memory", "id", {"importance": 0.2}, risk_level="low", confidence=0.1),
        context,
    )

    assert allowed["policy_decision"] == "allowed"
    assert queued["policy_decision"] == "queued"
    assert rejected["policy_decision"] == "rejected"


def test_execution_state_machine_and_duplicate_applying_guard():
    validate_execution_transition("planned", "policy_evaluated")
    with pytest.raises(ValueError, match="invalid governance execution transition"):
        validate_execution_transition("planned", "applied")

    context = MutationContext(actor="pytest", origin="governance", decision_id="")
    with managed_conn() as conn:
        first = create_execution(context, "low", {"ok": True}, conn, execution_id="exec-1", idempotency_key="key-1")
        conn.execute("UPDATE governance_executions SET status='applying' WHERE id=?", (first,))
        with pytest.raises(ValueError, match="duplicate concurrent applying"):
            create_execution(context, "low", {"ok": True}, conn, execution_id="exec-2", idempotency_key="key-2")


def test_blocked_execution_does_not_mark_decision_applied():
    """A mutation with confidence below reject threshold should not mark the decision applied."""
    record = add_memory_record("episodic_memory", "Queued target", "Needs review", importance=0.3)
    decision = create_governance_decision(
        "importance_reassessment",
        "downgrade",
        [record["id"]],
        0.40,
        "medium",
        {"id": record["id"], "action": "downgrade", "new_importance": 0.1},
    )
    with managed_conn() as conn:
        conn.execute(
            "UPDATE governance_decisions SET review_status='auto_approved' WHERE id=?",
            (decision["id"],),
        )

    result = apply_governance_decision(decision["id"], source_agent="pytest")

    assert result["execution"]["status"] in ("queued", "rejected")
    assert result["decision"].get("applied_at") is None


def test_governance_apply_writes_execution_and_mutation_log():
    record = add_memory_record("episodic_memory", "Ledger target", "Can be downgraded", importance=0.6)
    decision = create_governance_decision(
        "importance_reassessment",
        "downgrade",
        [record["id"]],
        0.95,
        "low",
        {"id": record["id"], "action": "downgrade", "new_importance": 0.2},
    )

    # Decision is auto-applied on creation; verify via DB
    assert decision["review_status"] == "applied"
    execution_id = decision.get("execution_id", "")
    assert execution_id

    ledger = query_ledger(correlation_id=execution_id)
    assert ledger
    assert ledger[0]["mutation_type"] == "memory_importance_update"
    assert ledger[0]["before_json"]
    assert ledger[0]["after_json"]
    assert ledger[0]["inverse_json"]
    with read_conn() as conn:
        execution = conn.execute("SELECT * FROM governance_executions WHERE id=?", (execution_id,)).fetchone()
    assert execution["status"] == "applied"
