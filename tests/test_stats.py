"""Tests for memory_stats / get_memory_stats."""
import pytest
from local_memory_mcp.storage import add_memory_record, add_feedback, add_link, get_memory_stats


@pytest.fixture(autouse=True)
def _db(isolated_memory_db):
    pass


def test_stats_empty_db():
    s = get_memory_stats()
    assert s["total"] == 0
    assert s["by_type"] == {}
    assert s["by_status"] == {}
    assert s["by_agent"] == {}
    assert s["avg_confidence"] == 0.0
    assert s["avg_importance"] == 0.0
    assert s["avg_feedback_score"] == 0.0
    assert s["never_accessed_count"] == 0
    assert s["link_count"] == 0


def test_stats_counts_by_type_and_status():
    add_memory_record("user_profile", "User A", "content a", source_agent="hermes")
    add_memory_record("user_profile", "User B", "content b", source_agent="hermes")
    add_memory_record("project_memory", "Proj X", "content x", source_agent="codex")
    s = get_memory_stats()
    assert s["total"] == 3
    assert s["by_type"]["user_profile"] == 2
    assert s["by_type"]["project_memory"] == 1
    assert s["by_status"]["active"] == 3
    assert s["by_agent"]["hermes"] == 2
    assert s["by_agent"]["codex"] == 1


def test_stats_avg_scores():
    add_memory_record("feedback", "F1", "c1", confidence=0.8, importance=0.6)
    add_memory_record("feedback", "F2", "c2", confidence=0.4, importance=0.2)
    s = get_memory_stats()
    assert abs(s["avg_confidence"] - 0.6) < 0.01
    assert abs(s["avg_importance"] - 0.4) < 0.01


def test_stats_never_accessed_count():
    r = add_memory_record("user_profile", "Unread", "content")
    s = get_memory_stats()
    assert s["never_accessed_count"] == 1


def test_stats_link_count():
    r1 = add_memory_record("user_profile", "A", "ca")
    r2 = add_memory_record("user_profile", "B", "cb")
    add_link(r1["id"], r2["id"], "related_to")
    s = get_memory_stats()
    assert s["link_count"] == 1


def test_stats_feedback_score_avg():
    r = add_memory_record("feedback", "FB", "content")
    add_feedback(r["id"], 1.0)
    add_feedback(r["id"], -0.5)
    s = get_memory_stats()
    assert abs(s["avg_feedback_score"] - 0.25) < 0.01
