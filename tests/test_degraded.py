"""TDD tests for P0-5 — degraded/fallback response contract.

When external dependencies (Qdrant, DeepSeek LLM) are unavailable,
MCP tools must return structured degraded responses instead of raising.
"""
from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field


class TestMemoryIngestDegraded:
    def test_returns_degraded_on_pipeline_error(self, monkeypatch):
        """If dedup.ingest raises (e.g. LLM/Qdrant down), memory_ingest returns degraded dict."""
        fake_dedup = types.ModuleType("memorycore.dedup")

        def broken_ingest(*a, **kw):
            raise ConnectionError("DeepSeek unreachable")

        fake_dedup.ingest = broken_ingest
        monkeypatch.setitem(sys.modules, "memorycore.dedup", fake_dedup)

        import memorycore.server as srv
        result = srv.memory_ingest(messages=[{"role": "user", "content": "hello"}])
        assert result["degraded"] is True
        assert "reason" in result
        assert result["added"] == 0
        assert result["errors"] == 1

    def test_returns_degraded_false_on_success(self, monkeypatch):
        """Successful ingest includes degraded=False for contract consistency."""
        @dataclass
        class FakeResult:
            added: int = 1
            updated: int = 0
            skipped: int = 0
            errors: int = 0
            elapsed_s: float = 0.1
            extraction_elapsed_s: float = 0.05

        fake_dedup = types.ModuleType("memorycore.dedup")
        fake_dedup.ingest = lambda *a, **kw: FakeResult()
        monkeypatch.setitem(sys.modules, "memorycore.dedup", fake_dedup)

        import memorycore.server as srv
        result = srv.memory_ingest(messages=[{"role": "user", "content": "hello"}])
        assert result["degraded"] is False
        assert result["added"] == 1


class TestMemoryVectorSearchDegraded:
    def test_returns_degraded_list_on_qdrant_error(self, monkeypatch):
        """If Qdrant is down, memory_vector_search returns a single-item list with degraded=True."""
        fake_vs_mod = types.ModuleType("memorycore.vector_store")

        class BrokenVS:
            def search(self, *a, **kw):
                raise ConnectionRefusedError("Qdrant not running")

        fake_vs_mod.get_vector_store = lambda cfg: BrokenVS()
        monkeypatch.setitem(sys.modules, "memorycore.vector_store", fake_vs_mod)

        import memorycore.server as srv
        result = srv.memory_vector_search(query="test query")
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["degraded"] is True
        assert "reason" in result[0]

    def test_normal_path_has_no_degraded_field(self, monkeypatch):
        """Normal Qdrant path returns results without a degraded field."""
        @dataclass
        class FakeHit:
            id: str = "abc"
            score: float = 0.9
            text: str = "some text"
            payload: dict = field(default_factory=dict)

        fake_vs_mod = types.ModuleType("memorycore.vector_store")

        class OkVS:
            def search(self, *a, **kw):
                return [FakeHit()]

        fake_vs_mod.get_vector_store = lambda cfg: OkVS()
        monkeypatch.setitem(sys.modules, "memorycore.vector_store", fake_vs_mod)

        import memorycore.server as srv
        result = srv.memory_vector_search(query="test query")
        assert isinstance(result, list)
        assert result[0]["id"] == "abc"
        assert "degraded" not in result[0]


class TestMemoryVectorStatusDegraded:
    def test_returns_degraded_on_connection_error(self, monkeypatch):
        """If Qdrant status() raises, memory_vector_status returns degraded structure."""
        fake_vs_mod = types.ModuleType("memorycore.vector_store")

        class BrokenVS:
            def status(self):
                raise OSError("cannot connect to Qdrant")

        fake_vs_mod.get_vector_store = lambda cfg: BrokenVS()
        monkeypatch.setitem(sys.modules, "memorycore.vector_store", fake_vs_mod)

        import memorycore.server as srv
        result = srv.memory_vector_status()
        assert result["degraded"] is True
        assert result["available"] is False
        assert "reason" in result
