import math

import pytest

import local_memory_mcp as lm


def test_semantic_status_reports_counts():
    lm.add_memory_record("project_memory", "Semantic status", "Content")

    status = lm.semantic_status()

    assert status["total_records"] == 1
    assert status["indexed_records"] >= 0
    assert "available" in status


def test_hashing_embedding_dimension_determinism_and_normalization():
    if lm.np is None:
        pytest.skip("numpy is not available")

    first = lm.embed_text_hashing("alpha beta alpha")
    second = lm.embed_text_hashing("alpha beta alpha")
    other = lm.embed_text_hashing("different text")

    assert first == second
    assert first != other
    assert len(first) == lm.SEMANTIC_DIM * 4

    vector = lm.np.frombuffer(first, dtype=lm.np.float32)
    assert math.isclose(float(lm.np.linalg.norm(vector)), 1.0, rel_tol=1e-6)


def test_semantic_index_and_search_when_available():
    lm.add_memory_record("project_memory", "Vector Search", "alpha vector memory", memory_id="semantic-1")

    if not lm.semantic_available():
        assert lm.semantic_index()["available"] is False
        assert lm.semantic_search("alpha") == []
        return

    indexed = lm.semantic_index(force=True)
    assert indexed["available"] is True
    assert indexed["indexed"] == 1

    results = lm.semantic_search("alpha vector", limit=5)
    assert results
    assert results[0]["id"] == "semantic-1"
    assert isinstance(results[0]["semantic_distance"], float)
