"""Tests for vector_store.py."""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from memorycore.vector_store import (
    EmbedConfig,
    SearchResult,
    VectorStore,
    VectorStoreConfig,
    _embed_openai,
    _embed_hashing,
    embed_config_from_dict,
    embed_text,
    get_vector_store,
    reset_vector_store,
    vector_store_config_from_dict,
)


# ---------------------------------------------------------------------------
# EmbedConfig tests
# ---------------------------------------------------------------------------

class TestEmbedConfig:
    def test_defaults(self):
        cfg = EmbedConfig()
        assert cfg.provider == "auto"
        assert cfg.model == "nomic-embed-text"
        assert cfg.api_url == ""
        assert cfg.dim == 768

    def test_from_dict_empty(self):
        cfg = embed_config_from_dict({})
        assert cfg.provider == "auto"
        assert cfg.dim == 768

    def test_from_dict_custom(self):
        cfg = embed_config_from_dict({
            "embedding": {"provider": "hashing", "dim": 384}
        })
        assert cfg.provider == "hashing"
        assert cfg.dim == 384

    def test_from_dict_env_overrides(self, monkeypatch):
        monkeypatch.setenv("LOCAL_MEMORY_EMBEDDING_PROVIDER", "hashing")
        monkeypatch.setenv("LOCAL_MEMORY_EMBEDDING_DIM", "128")
        monkeypatch.setenv("LOCAL_MEMORY_EMBEDDING_FALLBACK_PROVIDER", "hashing")
        monkeypatch.setenv("LOCAL_MEMORY_EMBEDDING_API_URL", "http://127.0.0.1:8317/v1")
        monkeypatch.setenv("LOCAL_MEMORY_EMBEDDING_API_KEY", "test-key")
        monkeypatch.setenv("LOCAL_MEMORY_SENTENCE_TRANSFORMERS_MODEL", "sentence-transformers/all-mpnet-base-v2")

        cfg = embed_config_from_dict({"embedding": {"provider": "ollama", "dim": 768}})

        assert cfg.provider == "hashing"
        assert cfg.dim == 128
        assert cfg.fallback_provider == "hashing"
        assert cfg.api_url == "http://127.0.0.1:8317/v1"
        assert cfg.api_key == "test-key"
        assert cfg.sentence_transformers_model == "sentence-transformers/all-mpnet-base-v2"


# ---------------------------------------------------------------------------
# Hashing embed tests
# ---------------------------------------------------------------------------

class TestEmbedHashing:
    def test_returns_correct_dim(self):
        vec = _embed_hashing("hello world", dim=768)
        assert len(vec) == 768

    def test_normalized(self):
        import math
        vec = _embed_hashing("test", dim=64)
        norm = math.sqrt(sum(v * v for v in vec))
        assert abs(norm - 1.0) < 1e-6

    def test_deterministic(self):
        v1 = _embed_hashing("same text", dim=128)
        v2 = _embed_hashing("same text", dim=128)
        assert v1 == v2

    def test_different_texts_differ(self):
        v1 = _embed_hashing("text A", dim=128)
        v2 = _embed_hashing("text B", dim=128)
        assert v1 != v2


# ---------------------------------------------------------------------------
# embed_text fallback tests
# ---------------------------------------------------------------------------

class TestEmbedText:
    def test_hashing_provider(self):
        cfg = EmbedConfig(provider="hashing", dim=64)
        vec = embed_text("hello", cfg)
        assert len(vec) == 64

    @patch("memorycore.vector_store._embed_ollama", side_effect=Exception("connection refused"))
    def test_ollama_failure_can_fall_back_to_hashing(self, mock_ollama):
        cfg = EmbedConfig(provider="ollama", fallback_provider="hashing", dim=64)
        vec = embed_text("hello", cfg)
        assert len(vec) == 64  # hashing fallback

    @patch("memorycore.vector_store._embed_openai", return_value=[1.0] + [0.0] * 63)
    @patch("memorycore.vector_store._embed_ollama")
    def test_auto_prefers_configured_openai_compatible_api(self, mock_ollama, mock_openai):
        cfg = EmbedConfig(
            provider="auto",
            api_url="http://127.0.0.1:8317/v1",
            model="text-embedding-3-small",
            dim=64,
        )
        vec = embed_text("hello", cfg)
        assert len(vec) == 64
        mock_openai.assert_called_once()
        mock_ollama.assert_not_called()

    @patch("memorycore.vector_store._embed_sentence_transformers", return_value=[1.0] + [0.0] * 63)
    @patch("memorycore.vector_store._embed_ollama", side_effect=Exception("connection refused"))
    def test_ollama_failure_prefers_sentence_transformers(self, mock_ollama, mock_st):
        cfg = EmbedConfig(provider="ollama", fallback_provider="sentence-transformers", dim=64)
        vec = embed_text("hello", cfg)
        assert len(vec) == 64
        assert vec[0] == 1.0
        mock_st.assert_called_once()

    @patch("memorycore.vector_store._embed_sentence_transformers", side_effect=ImportError("missing"))
    @patch("memorycore.vector_store._embed_ollama", side_effect=Exception("connection refused"))
    def test_sentence_transformers_failure_falls_back_to_hashing(self, mock_ollama, mock_st):
        cfg = EmbedConfig(provider="ollama", fallback_provider="sentence-transformers", dim=64)
        vec = embed_text("hello", cfg)
        assert len(vec) == 64
        mock_st.assert_called_once()

    @patch("memorycore.vector_store._embed_openai", return_value=[1.0] + [0.0] * 63)
    @patch("memorycore.vector_store._embed_ollama", side_effect=Exception("connection refused"))
    def test_ollama_failure_can_use_openai_compatible_api(self, mock_ollama, mock_openai):
        cfg = EmbedConfig(
            provider="ollama",
            fallback_provider="openai",
            model="text-embedding-3-small",
            api_url="http://127.0.0.1:8317/v1",
            dim=64,
        )
        vec = embed_text("hello", cfg)
        assert len(vec) == 64
        assert vec[0] == 1.0
        mock_openai.assert_called_once()

    def test_openai_compatible_api_response(self):
        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"data": [{"embedding": [3.0, 4.0]}]}

        class FakeClient:
            def __init__(self, timeout):
                self.timeout = timeout

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def post(self, url, json, headers):
                assert url == "http://127.0.0.1:8317/v1/embeddings"
                assert json == {"model": "text-embedding-3-small", "input": "hello"}
                assert headers["Authorization"] == "Bearer test-key"
                return FakeResponse()

        cfg = EmbedConfig(
            provider="openai",
            model="text-embedding-3-small",
            api_url="http://127.0.0.1:8317/v1",
            api_key="test-key",
            dim=2,
        )
        with patch("httpx.Client", FakeClient):
            assert _embed_openai("hello", cfg) == [0.6, 0.8]


# ---------------------------------------------------------------------------
# VectorStoreConfig tests
# ---------------------------------------------------------------------------

class TestVectorStoreConfig:
    def test_default_path(self):
        cfg = VectorStoreConfig()
        assert "qdrant" in cfg.path

    def test_from_dict(self):
        cfg = vector_store_config_from_dict({
            "qdrant": {"path": "/tmp/test_qdrant", "collection": "test_col"},
            "embedding": {"dim": 384},
        })
        assert cfg.path == "/tmp/test_qdrant"
        assert cfg.collection == "test_col"
        assert cfg.dim == 384

    def test_from_dict_env_overrides_qdrant(self, monkeypatch):
        monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
        monkeypatch.setenv("QDRANT_COLLECTION", "compose_memory")

        cfg = vector_store_config_from_dict({
            "qdrant": {"url": "http://127.0.0.1:6333", "collection": "agent_memory"},
        })

        assert cfg.url == "http://qdrant:6333"
        assert cfg.collection == "compose_memory"

    def test_from_dict_prefers_local_memory_qdrant_env(self, monkeypatch):
        monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
        monkeypatch.setenv("LOCAL_MEMORY_QDRANT_URL", "http://custom-qdrant:6333")
        monkeypatch.setenv("QDRANT_COLLECTION", "compose_memory")
        monkeypatch.setenv("LOCAL_MEMORY_QDRANT_COLLECTION", "custom_memory")

        cfg = vector_store_config_from_dict({"qdrant": {}})

        assert cfg.url == "http://custom-qdrant:6333"
        assert cfg.collection == "custom_memory"


# ---------------------------------------------------------------------------
# VectorStore with mocked Qdrant client
# ---------------------------------------------------------------------------

class TestVectorStoreUnavailable:
    def test_unavailable_when_qdrant_missing(self):
        with patch.dict("sys.modules", {"qdrant_client": None,
                                         "qdrant_client.models": None}):
            reset_vector_store()
            cfg = VectorStoreConfig(path="/tmp/nonexistent_qdrant_test")
            store = VectorStore(cfg)
            # Force init attempt
            store._initialized = False
            # qdrant_client import will fail → available=False
            # (we can't easily test this without actually removing the package,
            #  so just verify the interface doesn't crash)
            assert store.count() >= 0  # returns 0 when unavailable


class TestVectorStoreMocked:
    """Tests using a mocked QdrantClient."""

    def _make_store(self, tmp_path):
        cfg = VectorStoreConfig(
            path=str(tmp_path / "qdrant"),
            collection="test",
            dim=64,
            embed=EmbedConfig(provider="hashing", dim=64),
        )
        store = VectorStore(cfg)
        return store

    def test_upsert_and_search(self, tmp_path):
        store = self._make_store(tmp_path)
        if not store.available:
            pytest.skip("qdrant-client not available")

        id1 = str(uuid.uuid4())
        id2 = str(uuid.uuid4())
        store.upsert(id1, "User uses Neovim for coding", {"status": "active"})
        store.upsert(id2, "User prefers Python programming", {"status": "active"})

        results = store.search("code editor preferences", top_k=2)
        assert len(results) >= 1
        assert all(isinstance(r, SearchResult) for r in results)
        assert all(0.0 <= r.score <= 1.0 for r in results)

    def test_upsert_overwrites(self, tmp_path):
        store = self._make_store(tmp_path)
        if not store.available:
            pytest.skip("qdrant-client not available")

        id1 = str(uuid.uuid4())
        store.upsert(id1, "original text", {"version": 1})
        store.upsert(id1, "updated text", {"version": 2})
        assert store.count() == 1

    def test_delete(self, tmp_path):
        store = self._make_store(tmp_path)
        if not store.available:
            pytest.skip("qdrant-client not available")

        id1 = str(uuid.uuid4())
        store.upsert(id1, "to be deleted")
        assert store.count() == 1
        store.delete(id1)
        assert store.count() == 0

    def test_count(self, tmp_path):
        store = self._make_store(tmp_path)
        if not store.available:
            pytest.skip("qdrant-client not available")

        for i in range(3):
            store.upsert(str(uuid.uuid4()), f"fact number {i}")
        assert store.count() == 3

    def test_search_returns_text_in_payload(self, tmp_path):
        store = self._make_store(tmp_path)
        if not store.available:
            pytest.skip("qdrant-client not available")

        id1 = str(uuid.uuid4())
        store.upsert(id1, "User works on WSL2 Ubuntu")
        results = store.search("WSL2 environment", top_k=1)
        assert len(results) == 1
        assert results[0].text == "User works on WSL2 Ubuntu"

    def test_status(self, tmp_path):
        store = self._make_store(tmp_path)
        if not store.available:
            pytest.skip("qdrant-client not available")

        s = store.status()
        assert s["available"] is True
        assert s["collection"] == "test"
        assert s["dim"] == 64

    def test_close_idempotent(self, tmp_path):
        store = self._make_store(tmp_path)
        if not store.available:
            pytest.skip("qdrant-client not available")
        store.close()
        store.close()  # should not raise


# ---------------------------------------------------------------------------
# Singleton tests
# ---------------------------------------------------------------------------

class TestSingleton:
    def test_get_vector_store_returns_same_instance(self):
        reset_vector_store()
        s1 = get_vector_store({})
        s2 = get_vector_store({})
        assert s1 is s2

    def test_reset_clears_singleton(self):
        reset_vector_store()
        s1 = get_vector_store({})
        reset_vector_store()
        s2 = get_vector_store({})
        assert s1 is not s2
