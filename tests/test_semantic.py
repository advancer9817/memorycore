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


def test_semantic_index_and_search_when_available(monkeypatch):
    monkeypatch.setenv("LOCAL_MEMORY_EMBEDDING_PROVIDER", "hashing")
    monkeypatch.setenv("LOCAL_MEMORY_EMBEDDING_DIM", "384")
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


def test_ollama_embedding_provider_returns_768_float32_bytes(monkeypatch):
    if lm.np is None:
        pytest.skip("numpy is not available")

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b'{"embeddings": [[0.5, 0.5, 0.0, 0.0]]}'

    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = request.data.decode("utf-8")
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(lm.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("LOCAL_MEMORY_OLLAMA_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("LOCAL_MEMORY_EMBEDDING_MODEL", "nomic-embed-text")
    monkeypatch.setenv("LOCAL_MEMORY_EMBEDDING_DIM", "4")

    raw = lm.embed_text_ollama("hello memory")

    assert captured["url"] == "http://127.0.0.1:11434/api/embed"
    assert '"model": "nomic-embed-text"' in captured["body"]
    vector = lm.np.frombuffer(raw, dtype=lm.np.float32)
    assert vector.shape == (4,)
    assert math.isclose(float(lm.np.linalg.norm(vector)), 1.0, rel_tol=1e-6)


def test_vector_schema_migrates_from_hashing_384_to_ollama_768(monkeypatch):
    if not lm.semantic_available():
        pytest.skip("sqlite-vec/numpy not available")

    monkeypatch.setenv("LOCAL_MEMORY_EMBEDDING_PROVIDER", "hashing")
    monkeypatch.setenv("LOCAL_MEMORY_EMBEDDING_DIM", "384")
    with lm.managed_conn() as conn:
        original = conn.execute("SELECT sql FROM sqlite_master WHERE name='memory_vec'").fetchone()[0]
        assert "float[384]" in original

    lm._INITIALIZED_DB_PATHS.clear()
    monkeypatch.setenv("LOCAL_MEMORY_EMBEDDING_PROVIDER", "ollama")
    monkeypatch.setenv("LOCAL_MEMORY_EMBEDDING_MODEL", "nomic-embed-text")
    monkeypatch.setenv("LOCAL_MEMORY_EMBEDDING_DIM", "768")
    with lm.managed_conn() as conn:
        migrated = conn.execute("SELECT sql FROM sqlite_master WHERE name='memory_vec'").fetchone()[0]
        indexed = conn.execute("SELECT COUNT(*) FROM memory_embedding_index").fetchone()[0]

    assert "float[768]" in migrated
    assert indexed == 0
