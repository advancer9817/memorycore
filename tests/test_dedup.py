"""Tests for dedup.py — deduplication engine."""
from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from local_memory_mcp.dedup import (
    LINK_THRESHOLD,
    SKIP_THRESHOLD,
    UPDATE_THRESHOLD,
    DedupDecision,
    IngestResult,
    decide,
    ingest,
)
from local_memory_mcp.vector_store import SearchResult


# ---------------------------------------------------------------------------
# decide() unit tests — pure logic, no I/O
# ---------------------------------------------------------------------------

class TestDecide:
    def _hit(self, id: str, score: float, text: str = "") -> SearchResult:
        return SearchResult(id=id, score=score, text=text or f"fact {id}")

    def test_no_similar_returns_add(self):
        d = decide("new fact", similar=[])
        assert d.action == "add"
        assert d.fact_text == "new fact"

    def test_high_similarity_returns_skip(self):
        d = decide("same fact", similar=[self._hit("id1", SKIP_THRESHOLD + 0.01)])
        assert d.action == "skip"
        assert d.existing_id == "id1"

    def test_medium_similarity_returns_update(self):
        score = (UPDATE_THRESHOLD + SKIP_THRESHOLD) / 2
        d = decide("updated fact", similar=[self._hit("id1", score)])
        assert d.action == "update"
        assert d.existing_id == "id1"
        assert abs(d.similarity - score) < 0.001

    def test_low_similarity_returns_add(self):
        score = LINK_THRESHOLD + 0.05
        d = decide("new fact", similar=[self._hit("id1", score)])
        assert d.action == "add"
        assert "id1" in d.linked_ids  # related but not duplicate

    def test_below_link_threshold_no_links(self):
        score = LINK_THRESHOLD - 0.1
        d = decide("unrelated fact", similar=[self._hit("id1", score)])
        assert d.action == "add"
        assert d.linked_ids == []

    def test_llm_linked_ids_preserved_on_add(self):
        d = decide("new fact", similar=[], linked_memory_ids=["llm-linked-id"])
        assert d.action == "add"
        assert "llm-linked-id" in d.linked_ids

    def test_llm_linked_ids_preserved_on_update(self):
        score = (UPDATE_THRESHOLD + SKIP_THRESHOLD) / 2
        d = decide("updated", similar=[self._hit("id1", score)],
                   linked_memory_ids=["llm-id"])
        assert d.action == "update"
        assert "llm-id" in d.linked_ids

    def test_skip_ignores_llm_links(self):
        d = decide("dup", similar=[self._hit("id1", SKIP_THRESHOLD + 0.01)],
                   linked_memory_ids=["llm-id"])
        assert d.action == "skip"
        # linked_ids not populated for skip (no write happens)

    def test_multiple_similar_uses_top(self):
        hits = [
            self._hit("id1", 0.95),
            self._hit("id2", 0.80),
        ]
        d = decide("fact", similar=hits)
        assert d.action == "skip"
        assert d.existing_id == "id1"

    def test_add_collects_related_from_search(self):
        hits = [
            self._hit("id1", LINK_THRESHOLD + 0.05),
            self._hit("id2", LINK_THRESHOLD + 0.02),
        ]
        d = decide("new fact", similar=hits)
        assert d.action == "add"
        assert "id1" in d.linked_ids
        assert "id2" in d.linked_ids

    def test_custom_thresholds(self):
        # score=0.75 is between update_threshold=0.7 and skip_threshold=0.9 → update
        d = decide("fact", similar=[self._hit("id1", 0.75)],
                   skip_threshold=0.9, update_threshold=0.7, link_threshold=0.4)
        assert d.action == "update"


# ---------------------------------------------------------------------------
# ingest() integration tests (mocked dependencies)
# ---------------------------------------------------------------------------

class TestIngest:
    def _make_mock_vs(self, search_results=None):
        vs = MagicMock()
        vs.available = True
        vs.search.return_value = search_results or []
        vs.upsert.return_value = True
        return vs

    def _make_mock_ext(self, facts):
        """Return a mock extraction config and patch extract_facts."""
        from local_memory_mcp.extraction import ExtractionConfig, ExtractedFact
        cfg = ExtractionConfig(api_key="sk-test")
        return cfg, facts

    def test_empty_extraction_returns_zero(self):
        from local_memory_mcp.extraction import ExtractionConfig
        vs = self._make_mock_vs()
        add_fn = MagicMock()
        upd_fn = MagicMock()

        with __import__("unittest.mock", fromlist=["patch"]).patch(
            "local_memory_mcp.dedup.extract_facts", return_value=([], 0.1)
        ):
            result = ingest(
                [{"role": "user", "content": "hi"}],
                _extraction_config=ExtractionConfig(api_key="sk-test"),
                _vector_store=vs,
                _add_memory_fn=add_fn,
                _update_memory_fn=upd_fn,
            )

        assert result.added == 0
        assert result.updated == 0
        assert result.skipped == 0
        add_fn.assert_not_called()

    def test_new_fact_calls_add(self):
        from local_memory_mcp.extraction import ExtractionConfig, ExtractedFact
        from unittest.mock import patch

        vs = self._make_mock_vs(search_results=[])
        add_fn = MagicMock()
        upd_fn = MagicMock()
        facts = [ExtractedFact(text="User uses Neovim")]

        with patch("local_memory_mcp.dedup.extract_facts", return_value=(facts, 0.5)):
            result = ingest(
                [{"role": "user", "content": "I use Neovim"}],
                _extraction_config=ExtractionConfig(api_key="sk-test"),
                _vector_store=vs,
                _add_memory_fn=add_fn,
                _update_memory_fn=upd_fn,
            )

        assert result.added == 1
        assert result.skipped == 0
        add_fn.assert_called_once()
        call_kwargs = add_fn.call_args
        assert call_kwargs.kwargs["status"] == "candidate"
        assert "extracted" in call_kwargs.kwargs["tags"]

    def test_duplicate_fact_skipped(self):
        from local_memory_mcp.extraction import ExtractionConfig, ExtractedFact
        from unittest.mock import patch

        similar = [SearchResult(id="existing-id", score=0.97, text="User uses Neovim")]
        vs = self._make_mock_vs(search_results=similar)
        add_fn = MagicMock()
        upd_fn = MagicMock()
        facts = [ExtractedFact(text="User uses Neovim editor")]

        with patch("local_memory_mcp.dedup.extract_facts", return_value=(facts, 0.5)):
            result = ingest(
                [{"role": "user", "content": "I use Neovim"}],
                _extraction_config=ExtractionConfig(api_key="sk-test"),
                _vector_store=vs,
                _add_memory_fn=add_fn,
                _update_memory_fn=upd_fn,
            )

        assert result.skipped == 1
        assert result.added == 0
        add_fn.assert_not_called()

    def test_update_fact_adds_candidate_with_supersedes(self):
        from local_memory_mcp.extraction import ExtractionConfig, ExtractedFact
        from unittest.mock import patch

        score = (UPDATE_THRESHOLD + SKIP_THRESHOLD) / 2
        similar = [SearchResult(id="old-id", score=score, text="User uses Python")]
        vs = self._make_mock_vs(search_results=similar)
        add_fn = MagicMock()
        upd_fn = MagicMock()
        facts = [ExtractedFact(text="User switched from Python to Rust")]

        with patch("local_memory_mcp.dedup.extract_facts", return_value=(facts, 0.5)):
            result = ingest(
                [{"role": "user", "content": "I now use Rust"}],
                _extraction_config=ExtractionConfig(api_key="sk-test"),
                _vector_store=vs,
                _add_memory_fn=add_fn,
                _update_memory_fn=upd_fn,
            )

        assert result.updated == 1
        add_fn.assert_called_once()
        kwargs = add_fn.call_args.kwargs
        assert "supersedes:old-id" in kwargs["tags"]
        assert "old-id" in kwargs["related_ids"]

    def test_multiple_facts_mixed(self):
        from local_memory_mcp.extraction import ExtractionConfig, ExtractedFact
        from unittest.mock import patch

        score_dup = SKIP_THRESHOLD + 0.01
        score_new = LINK_THRESHOLD - 0.1

        def mock_search(text, **kwargs):
            if "Neovim" in text:
                return [SearchResult(id="x", score=score_dup, text="User uses Neovim")]
            return []

        vs = self._make_mock_vs()
        vs.search.side_effect = mock_search
        add_fn = MagicMock()
        upd_fn = MagicMock()
        facts = [
            ExtractedFact(text="User uses Neovim"),   # dup → skip
            ExtractedFact(text="User likes Rust"),     # new → add
        ]

        with patch("local_memory_mcp.dedup.extract_facts", return_value=(facts, 0.5)):
            result = ingest(
                [{"role": "user", "content": "..."}],
                _extraction_config=ExtractionConfig(api_key="sk-test"),
                _vector_store=vs,
                _add_memory_fn=add_fn,
                _update_memory_fn=upd_fn,
            )

        assert result.skipped == 1
        assert result.added == 1
        assert add_fn.call_count == 1

    def test_vector_store_unavailable_still_adds(self):
        from local_memory_mcp.extraction import ExtractionConfig, ExtractedFact
        from unittest.mock import patch

        vs = MagicMock()
        vs.available = False
        vs.search.return_value = []
        add_fn = MagicMock()
        upd_fn = MagicMock()
        facts = [ExtractedFact(text="User uses WSL2")]

        with patch("local_memory_mcp.dedup.extract_facts", return_value=(facts, 0.5)):
            result = ingest(
                [{"role": "user", "content": "I use WSL2"}],
                _extraction_config=ExtractionConfig(api_key="sk-test"),
                _vector_store=vs,
                _add_memory_fn=add_fn,
                _update_memory_fn=upd_fn,
            )

        assert result.added == 1
        add_fn.assert_called_once()

    def test_result_has_elapsed_time(self):
        from local_memory_mcp.extraction import ExtractionConfig
        from unittest.mock import patch

        vs = self._make_mock_vs()
        add_fn = MagicMock()
        upd_fn = MagicMock()

        with patch("local_memory_mcp.dedup.extract_facts", return_value=([], 0.1)):
            result = ingest(
                [{"role": "user", "content": "hi"}],
                _extraction_config=ExtractionConfig(api_key="sk-test"),
                _vector_store=vs,
                _add_memory_fn=add_fn,
                _update_memory_fn=upd_fn,
            )

        assert result.elapsed_s >= 0
        assert result.extraction_elapsed_s == 0.1
