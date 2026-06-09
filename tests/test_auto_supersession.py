"""Tests for Phase 3 temporal auto-supersession."""
from __future__ import annotations

import memorycore as lm
from memorycore.models import invalidate_config_cache
from memorycore.storage import add_feedback, add_memory_record, get_record, list_governance_decisions, memory_lineage
from memorycore.storage.governance import rollback_governance_decision
from memorycore.storage.db import managed_conn


def _enable_auto(monkeypatch, tmp_path, auto_threshold: float = 0.94, review_threshold: float = 0.80) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "temporal:\n"
        "  auto_supersede_enabled: true\n"
        f"  auto_supersede_threshold: {auto_threshold}\n"
        f"  review_similarity_threshold: {review_threshold}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LOCAL_MEMORY_CONFIG", str(cfg))
    invalidate_config_cache()


def _disable_auto(monkeypatch, tmp_path, review_threshold: float = 0.80) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "temporal:\n"
        "  auto_supersede_enabled: false\n"
        "  auto_supersede_threshold: 0.94\n"
        f"  review_similarity_threshold: {review_threshold}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LOCAL_MEMORY_CONFIG", str(cfg))
    invalidate_config_cache()


def test_auto_supersession_threshold_hit_marks_old_superseded(monkeypatch, tmp_path):
    _enable_auto(monkeypatch, tmp_path)
    old = add_memory_record("feedback", "Retry limit", "Retry limit is three attempts", importance=0.4)
    new = add_memory_record("feedback", "Retry limit", "Retry limit is three attempts", importance=0.4)

    old_after = get_record(old["id"])
    new_after = get_record(new["id"])
    decisions = list_governance_decisions(limit=5)

    assert old_after["status"] == "superseded"
    assert old_after["superseded_by"] == new["id"]
    assert new_after["status"] == "active"
    assert decisions[0]["decision_type"] == "supersession"
    assert decisions[0]["review_status"] == "applied"
    assert decisions[0]["before_state"]
    assert decisions[0]["after_state"]


def test_auto_supersession_no_hit_creates_no_decision(monkeypatch, tmp_path):
    _enable_auto(monkeypatch, tmp_path)
    add_memory_record("feedback", "Retry limit", "Retry limit is three attempts")
    add_memory_record("feedback", "Dashboard path", "Dashboard lives under the UI directory")

    assert list_governance_decisions(limit=5) == []


def test_precious_memory_skips_auto_and_routes_to_review(monkeypatch, tmp_path):
    _enable_auto(monkeypatch, tmp_path)
    old = add_memory_record("decision", "Model choice", "Use Opus for architectural review", importance=0.4)
    new = add_memory_record("decision", "Model choice", "Use Opus for architectural review", importance=0.4)

    old_after = get_record(old["id"])
    decisions = list_governance_decisions(limit=5)

    assert old_after["status"] == "active"
    assert decisions[0]["decision_type"] == "supersession"
    assert decisions[0]["review_status"] == "needs_review"
    assert "precious" in decisions[0]["policy_reason"]
    assert new["id"] in decisions[0]["source_ids"]


def test_mid_confidence_candidate_creates_review_decision(monkeypatch, tmp_path):
    _enable_auto(monkeypatch, tmp_path, auto_threshold=0.99, review_threshold=0.50)
    old = add_memory_record("feedback", "Retry limit", "Retry limit is three attempts for API calls")
    add_memory_record("feedback", "Retry limit", "Retry limit is four attempts for API calls")

    old_after = get_record(old["id"])
    decisions = list_governance_decisions(review_status="needs_review", limit=5)

    assert old_after["status"] == "active"
    assert decisions
    assert decisions[0]["decision_type"] == "supersession"
    assert decisions[0]["recommended_action"] == "supersede"


def test_qdrant_unavailable_does_not_crash_auto_supersession(monkeypatch, tmp_path):
    _enable_auto(monkeypatch, tmp_path)

    class BrokenVectorStore:
        def upsert(self, *_args, **_kwargs):
            raise RuntimeError("qdrant unavailable")

        def delete(self, *_args, **_kwargs):
            raise RuntimeError("qdrant unavailable")

    import memorycore.storage.crud as crud

    monkeypatch.setattr(crud, "_get_vector_store", lambda _cfg: BrokenVectorStore())
    old = add_memory_record("feedback", "Retry limit", "Retry limit is three attempts", importance=0.4)
    new = add_memory_record("feedback", "Retry limit", "Retry limit is three attempts", importance=0.4)

    assert get_record(old["id"])["status"] == "superseded"
    assert get_record(new["id"])["status"] == "active"


def test_lineage_continuity_and_rollback_vector_sync(monkeypatch, tmp_path):
    _enable_auto(monkeypatch, tmp_path)
    calls: list[tuple[str, str]] = []

    class FakeVectorStore:
        def upsert(self, memory_id, *_args, **_kwargs):
            calls.append(("upsert", memory_id))

        def delete(self, memory_id):
            calls.append(("delete", memory_id))

    import memorycore.storage.crud as crud

    monkeypatch.setattr(crud, "_get_vector_store", lambda _cfg: FakeVectorStore())
    old = add_memory_record("feedback", "Retry limit", "Retry limit is three attempts", importance=0.4)
    new = add_memory_record("feedback", "Retry limit", "Retry limit is three attempts", importance=0.4)

    lineage = memory_lineage(new["id"])
    assert lineage["root_id"] == old["id"]
    assert any(link["source_id"] == new["id"] and link["target_id"] == old["id"] for link in lineage["links"])
    assert ("delete", old["id"]) in calls
    assert ("upsert", new["id"]) in calls

    decision = list_governance_decisions(limit=1)[0]
    rollback_governance_decision(decision["id"], source_agent="pytest")

    assert get_record(old["id"])["status"] == "active"
    assert ("upsert", old["id"]) in calls


def test_positive_feedback_skips_auto_and_routes_to_review(monkeypatch, tmp_path):
    _enable_auto(monkeypatch, tmp_path)
    old = add_memory_record("feedback", "Retry limit", "Retry limit is three attempts", importance=0.4)
    add_feedback(old["id"], 1.0, source_agent="pytest")
    add_memory_record("feedback", "Retry limit", "Retry limit is three attempts", importance=0.4)

    assert get_record(old["id"])["status"] == "active"
    assert list_governance_decisions(limit=1)[0]["review_status"] == "needs_review"


def test_auto_disabled_routes_candidate_to_review(monkeypatch, tmp_path):
    _disable_auto(monkeypatch, tmp_path)
    old = add_memory_record("feedback", "Retry limit", "Retry limit is three attempts", importance=0.4)
    add_memory_record("feedback", "Retry limit", "Retry limit is three attempts", importance=0.4)

    assert get_record(old["id"])["status"] == "active"
    assert list_governance_decisions(limit=1)[0]["review_status"] == "needs_review"


def test_rollback_removes_supersedes_link_from_memory_links(monkeypatch, tmp_path):
    """Rollback must clean up the supersedes link created during apply, not just restore memory fields."""
    _enable_auto(monkeypatch, tmp_path)
    old = add_memory_record("feedback", "Retry limit", "Retry limit is three attempts", importance=0.4)
    new = add_memory_record("feedback", "Retry limit", "Retry limit is three attempts", importance=0.4)

    # Supersedes link exists after auto-apply
    lineage_before_rollback = memory_lineage(new["id"])
    assert any(
        link["source_id"] == new["id"] and link["target_id"] == old["id"]
        for link in lineage_before_rollback["links"]
    ), "supersedes link should exist after auto-apply"

    decision = list_governance_decisions(limit=1)[0]
    rollback_governance_decision(decision["id"], source_agent="pytest")

    # Memory fields restored
    assert get_record(old["id"])["status"] == "active"
    assert get_record(old["id"])["superseded_by"] is None

    # Supersedes link must be gone
    with managed_conn() as conn:
        link_count = conn.execute(
            "SELECT COUNT(*) FROM memory_links WHERE source_id=? AND target_id=? AND relation_type='supersedes'",
            (new["id"], old["id"]),
        ).fetchone()[0]
    assert link_count == 0, "supersedes link must be removed after rollback"

    # Lineage should no longer show the supersedes link
    lineage_after_rollback = memory_lineage(old["id"])
    assert not any(
        link["source_id"] == new["id"] and link["target_id"] == old["id"]
        for link in lineage_after_rollback["links"]
    ), "lineage must not contain rolled-back supersedes link"
    _enable_auto(monkeypatch, tmp_path)
    old = add_memory_record("feedback", "Retry limit", "Retry limit is three attempts", scope="global", project_path="/a")
    add_memory_record("feedback", "Retry limit", "Retry limit is three attempts", scope="global", project_path="/b")

    with managed_conn() as conn:
        count = conn.execute("SELECT COUNT(*) FROM governance_decisions").fetchone()[0]
    assert get_record(old["id"])["status"] == "active"
    assert count == 0
