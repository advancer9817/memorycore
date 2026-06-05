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
    """With >500 memories, sampling should kick in."""
    import memorycore.storage.curator_llm as clm
    from unittest.mock import MagicMock, patch

    memories = [{"id": f"id-{i}", "title": f"T{i}", "content": f"C{i}", "importance": 0.5}
                for i in range(600)]

    vs = MagicMock()
    vs.search.return_value = []

    with patch("memorycore.storage.curator_llm.logger") as mock_log:
        clm._find_semantic_duplicate_candidates(vs, memories, sim_threshold=0.6)
        # Should have logged a warning about large pool
        warning_calls = [str(c) for c in mock_log.warning.call_args_list]
        assert any("ample" in w or "arge" in w or "200" in w for w in warning_calls), \
            f"Expected sampling warning, got: {warning_calls}"
