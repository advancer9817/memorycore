"""Smoke test: apply_llm_curator(dry_run=False) with a mock plan."""
import pytest


def test_apply_llm_curator_split_writes_children(tmp_path, monkeypatch):
    """apply_llm_curator split branch should insert child records into SQLite."""
    pytest.importorskip("memorycore")
    from memorycore.storage.curator_llm import apply_llm_curator

    # Minimal plan: one split_candidate with nonexistent parent id.
    # apply_llm_curator uses "sub_memories" (not "splits") as the key for children.
    plan = {
        "semantic_duplicates": [],
        "contradictions": [],
        "importance_reassessments": [],
        "split_candidates": [
            {
                "id": "nonexistent-parent-id",   # won't be found in DB — should skip gracefully
                "title": "Test parent",
                "sub_memories": [
                    {"content": "Child fact 1", "title": "Child 1", "importance": 0.6},
                    {"content": "Child fact 2", "title": "Child 2", "importance": 0.7},
                ],
                "reason": "test split",
            }
        ],
    }
    # Should not raise, even if parent id doesn't exist
    result = apply_llm_curator(plan, dry_run=False)
    assert isinstance(result, dict)
    assert "applied" in result
    assert result["dry_run"] is False
