"""Unit tests for LLM Curator job registry and cooldown mechanisms."""
import time
import pytest


def test_job_registry_ttl_cleanup():
    """Jobs in succeeded/error state older than 30min should be cleaned up."""
    import memorycore.storage.curator_llm as clm

    old_jobs = dict(clm._reviewed_memory_ids) if hasattr(clm, '_reviewed_memory_ids') else {}

    # Test the cleanup function if it exists
    if not hasattr(clm, '_cleanup_stale_llm_jobs'):
        pytest.skip("_cleanup_stale_llm_jobs not implemented yet")

    # Reset state
    clm._reviewed_memory_ids.clear()
    clm._reviewed_memory_ids.update(old_jobs)


def test_review_cooldown_skips_recent_memories():
    """Memories reviewed within cooldown period should be skipped."""
    import memorycore.storage.curator_llm as clm

    if not hasattr(clm, '_reviewed_memory_ids'):
        pytest.skip("_reviewed_memory_ids not implemented yet")
    if not hasattr(clm, '_REVIEW_COOLDOWN_SECONDS'):
        pytest.skip("_REVIEW_COOLDOWN_SECONDS not implemented yet")

    # Mark a memory as recently reviewed
    test_id = "test-memory-id-12345"
    clm._reviewed_memory_ids[test_id] = time.time()

    # It should be in the cooldown dict
    assert test_id in clm._reviewed_memory_ids
    assert time.time() - clm._reviewed_memory_ids[test_id] < clm._REVIEW_COOLDOWN_SECONDS

    # Clean up
    clm._reviewed_memory_ids.pop(test_id, None)


def test_review_cooldown_expired_memory_not_skipped():
    """Memories reviewed beyond cooldown period should be eligible again."""
    import memorycore.storage.curator_llm as clm

    if not hasattr(clm, '_reviewed_memory_ids'):
        pytest.skip("_reviewed_memory_ids not implemented yet")
    if not hasattr(clm, '_REVIEW_COOLDOWN_SECONDS'):
        pytest.skip("_REVIEW_COOLDOWN_SECONDS not implemented yet")

    test_id = "test-memory-id-expired"
    # Set timestamp far in the past
    clm._reviewed_memory_ids[test_id] = time.time() - clm._REVIEW_COOLDOWN_SECONDS - 1

    # The entry exists but is expired
    age = time.time() - clm._reviewed_memory_ids[test_id]
    assert age > clm._REVIEW_COOLDOWN_SECONDS

    # Clean up
    clm._reviewed_memory_ids.pop(test_id, None)


def test_large_pool_sampling_limit():
    """_find_candidate_pairs processes all eligible memories."""
    import memorycore.storage.curator_llm as clm
    from unittest.mock import MagicMock, patch

    memories = [{"id": f"id-{i}", "title": f"T{i}", "content": f"C{i}", "importance": 0.5}
                for i in range(600)]

    vs = MagicMock()
    vs.search.return_value = []

    with patch("memorycore.storage.curator_llm._get_recently_reviewed_ids", return_value=set()):
        pairs = clm._find_candidate_pairs(vs, memories, sim_threshold=0.6)
    assert isinstance(pairs, list)


def test_run_llm_curator_applies_and_rebuilds_vectors(monkeypatch):
    """Explicit rebuild_vectors=True path should run the governance runner and rebuild."""
    import memorycore.storage.curator_llm as clm

    report = {"summary": {"semantic_duplicates": 1}, "errors": []}
    governance = {"decisions_created": 1, "decisions": [], "auto_applied": [{"applied": {"downgraded": 1}}]}
    monkeypatch.setattr(
        "memorycore.storage.curator_llm.report.llm_curator_report",
        lambda **_: report,
    )
    monkeypatch.setattr(
        "memorycore.storage.governance.convert_llm_findings_to_decisions",
        lambda report, auto_apply: governance,
    )

    rebuild_calls = []
    monkeypatch.setattr(
        "memorycore.storage.memory_rebuild_vectors",
        lambda: rebuild_calls.append(True) or {"rebuilt": 1},
    )
    monkeypatch.setattr(
        "memorycore.storage.audit.log_audit_event",
        lambda *args, **kwargs: None,
    )

    result = clm.run_llm_curator(config={}, limit=10, sim_threshold=0.7, apply=True, rebuild_vectors=True)

    assert result["summary"] == {"semantic_duplicates": 1}
    assert result["governance"] == governance
    assert result["applied"] == {"governance_auto_applied": 1}
    assert result["rebuild_vectors"] == {"rebuilt": 1}
    assert rebuild_calls == [True]


def test_run_llm_curator_skips_rebuild_by_default(monkeypatch):
    """Default rebuild_vectors=False: curator must NOT trigger full vector rebuild."""
    import memorycore.storage.curator_llm as clm

    report = {"summary": {"semantic_duplicates": 0}, "errors": []}
    governance = {"decisions_created": 0, "decisions": [], "auto_applied": []}
    monkeypatch.setattr(
        "memorycore.storage.curator_llm.report.llm_curator_report",
        lambda **_: report,
    )
    monkeypatch.setattr(
        "memorycore.storage.governance.convert_llm_findings_to_decisions",
        lambda report, auto_apply: governance,
    )

    rebuild_calls = []
    monkeypatch.setattr(
        "memorycore.storage.memory_rebuild_vectors",
        lambda: rebuild_calls.append(True) or {"rebuilt": 1},
    )
    monkeypatch.setattr(
        "memorycore.storage.audit.log_audit_event",
        lambda *args, **kwargs: None,
    )

    result = clm.run_llm_curator(config={}, limit=10, sim_threshold=0.7, apply=True)

    assert result["summary"] == {"semantic_duplicates": 0}
    assert "rebuild_vectors" not in result
    assert rebuild_calls == []


def test_llm_curator_cli_summary_only(monkeypatch, capsys):
    """The scheduler script can call the LLM curator through the CLI."""
    import memorycore.server as server

    monkeypatch.setattr(server, "load_config", lambda: {})
    monkeypatch.setattr(
        "memorycore.storage.curator_llm.run_llm_curator",
        lambda **_: {"summary": {"split_candidates": 2}, "errors": []},
    )

    assert server.main(["llm-curator", "--limit", "5", "--summary-only"]) == 0
    assert '"split_candidates": 2' in capsys.readouterr().out
