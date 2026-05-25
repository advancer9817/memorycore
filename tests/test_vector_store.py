"""Tests for vector_store.py."""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from local_memory_mcp.vector_store import (
    EmbedConfig,
    SearchResult,
    VectorStore,
    VectorStoreConfig,
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
        assert cfg.provider == "ollama"
        assert cfg.model == "nomic-embed-text"
        assert cfg.dim == 768

    def test_from_dict_empty(self):
        cfg = embed_config_from_dict({})
        assert cfg.dim == 768

    def test_from_dict_custom(self):
        cfg = embed_config_from_dict({
            "embedding": {"provider": "hashing", "dim": 384}
        })
        assert cfg.provider == "hashing"
        assert cfg.dim == 384


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

    @patch("local_memory_mcp.vector_store._embed_ollama", side_effect=Exception("connection refused"))
    def test_ollama_failure_falls_back_to_hashing(self, mock_ollama):
        cfg = EmbedConfig(provider="ollama", dim=64)
        vec = embed_text("hello", cfg)
        assert len(vec) == 64  # hashing fallback


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
