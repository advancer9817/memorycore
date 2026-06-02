"""Tests for extraction.py — LLM-powered fact extraction."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from memorycore.extraction import (
    ExtractionConfig,
    ExtractedFact,
    _parse_response,
    extract_facts,
    extraction_config_from_dict,
)


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------

class TestExtractionConfig:
    def test_defaults(self):
        cfg = ExtractionConfig(api_key="test-key")
        assert cfg.model == "deepseek-v4-flash"
        assert cfg.base_url == "https://api.deepseek.com/v1"
        assert cfg.temperature == 0.1

    def test_from_dict_empty(self):
        cfg = extraction_config_from_dict({})
        assert cfg.model == "deepseek-v4-flash"

    def test_from_dict_extraction_section(self):
        cfg = extraction_config_from_dict({
            "extraction": {
                "model": "gpt-4o",
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-test",
            }
        })
        assert cfg.model == "gpt-4o"
        assert cfg.api_key == "sk-test"

    def test_from_dict_mem0_fallback(self):
        # mem0 compat section is removed; extraction section is the sole config path
        cfg = extraction_config_from_dict({
            "extraction": {
                "model": "qwen2.5:7b",
                "base_url": "http://localhost:11434",
            }
        })
        assert cfg.model == "qwen2.5:7b"

    def test_from_dict_extraction_overrides_mem0(self):
        cfg = extraction_config_from_dict({
            "mem0": {"llm_model": "old-model"},
            "extraction": {"model": "new-model"},
        })
        assert cfg.model == "new-model"


# ---------------------------------------------------------------------------
# Response parser tests
# ---------------------------------------------------------------------------

class TestParseResponse:
    def test_empty_memory(self):
        assert _parse_response('{"memory": []}') == []

    def test_single_fact(self):
        raw = '{"memory": [{"id": "0", "text": "User uses Neovim"}]}'
        facts = _parse_response(raw)
        assert len(facts) == 1
        assert facts[0].text == "User uses Neovim"
        assert facts[0].raw_id == "0"

    def test_multiple_facts(self):
        raw = json.dumps({"memory": [
            {"id": "0", "text": "User is a developer"},
            {"id": "1", "text": "User prefers Python"},
        ]})
        facts = _parse_response(raw)
        assert len(facts) == 2
        assert facts[1].text == "User prefers Python"

    def test_linked_memory_ids(self):
        raw = json.dumps({"memory": [
            {"id": "0", "text": "User switched to Rust",
             "linked_memory_ids": ["abc-123"]}
        ]})
        facts = _parse_response(raw)
        assert facts[0].linked_memory_ids == ["abc-123"]

    def test_old_facts_format(self):
        raw = json.dumps({"facts": ["User likes coffee", "User works remotely"]})
        facts = _parse_response(raw)
        assert len(facts) == 2
        assert facts[0].text == "User likes coffee"

    def test_string_items_in_memory(self):
        raw = json.dumps({"memory": ["User uses WSL2"]})
        facts = _parse_response(raw)
        assert len(facts) == 1
        assert facts[0].text == "User uses WSL2"

    def test_malformed_json_with_embedded(self):
        raw = 'Here is the result: {"memory": [{"id": "0", "text": "fact"}]} done.'
        facts = _parse_response(raw)
        assert len(facts) == 1

    def test_completely_invalid(self):
        assert _parse_response("not json at all") == []

    def test_skips_empty_text(self):
        raw = json.dumps({"memory": [
            {"id": "0", "text": ""},
            {"id": "1", "text": "Valid fact"},
        ]})
        facts = _parse_response(raw)
        assert len(facts) == 1
        assert facts[0].text == "Valid fact"


# ---------------------------------------------------------------------------
# extract_facts integration (mocked LLM)
# ---------------------------------------------------------------------------

class TestExtractFacts:
    def _make_config(self):
        return ExtractionConfig(api_key="sk-test", model="deepseek-v4-flash")

    def test_no_api_key_returns_empty(self):
        import os
        # Temporarily clear all key env vars so __post_init__ finds nothing
        keys = ("MEM0_LLM_API_KEY", "DEEPSEEK_API_KEY")
        saved = {k: os.environ.pop(k, None) for k in keys}
        try:
            cfg = ExtractionConfig(api_key="")
            facts, elapsed = extract_facts(
                [{"role": "user", "content": "hello"}], config=cfg
            )
            assert facts == []
            assert elapsed == 0.0
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v

    @patch("memorycore.extraction._call_llm")
    def test_basic_extraction(self, mock_call):
        mock_call.return_value = json.dumps({"memory": [
            {"id": "0", "text": "User works on WSL2 Ubuntu"},
            {"id": "1", "text": "User uses Hermes Agent as AI secretary"},
        ]})
        cfg = self._make_config()
        facts, elapsed = extract_facts(
            [
                {"role": "user", "content": "I work on WSL2 Ubuntu with Hermes Agent"},
                {"role": "assistant", "content": "Got it!"},
            ],
            config=cfg,
        )
        assert len(facts) == 2
        assert facts[0].text == "User works on WSL2 Ubuntu"
        assert elapsed >= 0

    @patch("memorycore.extraction._call_llm")
    def test_empty_conversation(self, mock_call):
        mock_call.return_value = '{"memory": []}'
        cfg = self._make_config()
        facts, _ = extract_facts([{"role": "user", "content": "Hi"}], config=cfg)
        assert facts == []

    @patch("memorycore.extraction._call_llm")
    def test_with_existing_memories(self, mock_call):
        mock_call.return_value = json.dumps({"memory": [
            {"id": "0", "text": "User switched from Python to Rust",
             "linked_memory_ids": ["existing-uuid-1"]}
        ]})
        cfg = self._make_config()
        existing = [{"id": "existing-uuid-1", "content": "User uses Python"}]
        facts, _ = extract_facts(
            [{"role": "user", "content": "I now use Rust instead of Python"}],
            existing_memories=existing,
            config=cfg,
        )
        assert len(facts) == 1
        assert facts[0].linked_memory_ids == ["existing-uuid-1"]

    @patch("memorycore.extraction._call_llm", side_effect=Exception("network error"))
    def test_llm_error_returns_empty(self, mock_call):
        cfg = self._make_config()
        facts, elapsed = extract_facts(
            [{"role": "user", "content": "test"}], config=cfg
        )
        assert facts == []
        assert elapsed >= 0

    @patch("memorycore.extraction._call_llm")
    def test_chinese_input(self, mock_call):
        mock_call.return_value = json.dumps({"memory": [
            {"id": "0", "text": "用户使用 Neovim 编写代码，配置了 lazy.nvim 插件管理器"}
        ]})
        cfg = self._make_config()
        facts, _ = extract_facts(
            [{"role": "user", "content": "我用 Neovim 写代码，配了 lazy.nvim"}],
            config=cfg,
        )
        assert len(facts) == 1
        assert "Neovim" in facts[0].text
