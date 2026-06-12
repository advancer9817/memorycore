from memorycore.storage.governance import filter_applied_or_rejected_findings, create_governance_decision
from memorycore.storage.db import managed_conn

def test_filter_applied_or_rejected_findings():
    finding1 = {"action": "mark_contradicted", "older_id": "1", "newer_id": "2", "reason": "contradiction 1"}
    finding2 = {"action": "archive_duplicate", "drop_id": "3", "keep_id": "4", "reason": "duplicate 1"}
    finding3 = {"action": "archive_and_merge_duplicate", "drop_id": "5", "keep_id": "6", "reason": "duplicate 2"}

    report = {
        "contradictions": [finding1],
        "semantic_duplicates": [finding2, finding3],
        "summary": {
            "contradictions": 1,
            "semantic_duplicates": 2
        }
    }

    filtered1 = filter_applied_or_rejected_findings(report)
    assert len(filtered1["contradictions"]) == 1
    assert len(filtered1["semantic_duplicates"]) == 2
    assert filtered1["summary"]["semantic_duplicates"] == 2

    # Create decisions for finding2 and finding3
    decision2 = create_governance_decision(
        decision_type="semantic_duplicate",
        recommended_action="archive_duplicate",
        source_ids=["3", "4"],
        llm_confidence=0.9,
        risk_level="low",
        finding=finding2
    )
    decision3 = create_governance_decision(
        decision_type="semantic_duplicate",
        recommended_action="archive_and_merge_duplicate",
        source_ids=["5", "6"],
        llm_confidence=0.8,
        risk_level="high",
        finding=finding3
    )

    # Simulate rejecting decision2 and applying decision3
    with managed_conn() as conn:
        conn.execute("UPDATE governance_decisions SET review_status='rejected' WHERE id=?", (decision2["id"],))
        conn.execute("UPDATE governance_decisions SET review_status='applied' WHERE id=?", (decision3["id"],))

    filtered2 = filter_applied_or_rejected_findings(report)
    assert len(filtered2["contradictions"]) == 1
    assert len(filtered2["semantic_duplicates"]) == 0
    assert filtered2["summary"]["semantic_duplicates"] == 0
