"""Tests for Mem0 backend integration."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mem0_backend import Mem0Backend, Mem0Config, mem0_config_from_dict, reset_backend


class TestMem0Config:
    def test_default_config(self):
        cfg = Mem0Config()
        assert cfg.enabled is False
        assert cfg.llm_model == "qwen2.5:3b"
        assert cfg.embedder_model == "nomic-embed-text"
        assert cfg.embedder_dim == 768
        assert "mem0_qdrant" in cfg.vector_store_path

    def test_from_dict_empty(self):
        cfg = mem0_config_from_dict({})
        assert cfg.enabled is False
        assert cfg.llm_model == "qwen2.5:3b"

    def test_from_dict_custom(self):
        cfg = mem0_config_from_dict({
            "mem0": {
                "enabled": True,
                "llm_model": "qwen2.5:7b",
                "ollama_url": "http://localhost:11434",
                "default_user_id": "testuser",
            }
        })
        assert cfg.enabled is True
        assert cfg.llm_model == "qwen2.5:7b"
        assert cfg.ollama_url == "http://localhost:11434"
        assert cfg.default_user_id == "testuser"


class TestMem0BackendDisabled:
    def test_disabled_returns_unavailable(self):
        cfg = Mem0Config(enabled=False)
        backend = Mem0Backend(cfg)
        assert backend.available is False

    def test_disabled_extract_returns_error(self):
        cfg = Mem0Config(enabled=False)
        backend = Mem0Backend(cfg)
        result = backend.extract_memories([{"role": "user", "content": "hello"}])
        assert result["error"] == "Mem0 backend not available"
        assert result["results"] == []

    def test_disabled_search_returns_error(self):
        cfg = Mem0Config(enabled=False)
        backend = Mem0Backend(cfg)
        result = backend.search("test query")
        assert result["error"] == "Mem0 backend not available"
        assert result["results"] == []

    def test_disabled_status(self):
        cfg = Mem0Config(enabled=False)
        backend = Mem0Backend(cfg)
        status = backend.status()
        assert status["available"] is False
        assert status["enabled"] is False


class TestMem0BackendMocked:
    """Test with mocked Mem0 Memory class."""

    @patch("mem0_backend._check_mem0", return_value=True)
    @patch("mem0_backend._Memory")
    def test_extract_memories_success(self, mock_memory_cls, mock_check):
        mock_instance = MagicMock()
        mock_instance.add.return_value = {
            "results": [
                {"id": "abc123", "memory": "User prefers Python", "event": "ADD"}
            ]
        }
        mock_memory_cls.from_config.return_value = mock_instance

        cfg = Mem0Config(enabled=True)
        backend = Mem0Backend(cfg)
        # Force re-init
        backend._initialized = False
        backend._memory = None

        # Manually set the memory instance since mock won't go through from_config properly
        backend._initialized = True
        backend._memory = mock_instance

        result = backend.extract_memories(
            [{"role": "user", "content": "I prefer Python"}],
            user_id="testuser",
            agent_id="hermes",
        )
        assert result["error"] is None
        assert len(result["results"]) == 1
        assert result["results"][0]["memory"] == "User prefers Python"
        assert result["elapsed_s"] >= 0

    @patch("mem0_backend._check_mem0", return_value=True)
    def test_search_success(self, mock_check):
        mock_instance = MagicMock()
        mock_instance.search.return_value = {
            "results": [
                {"id": "xyz", "memory": "User uses WSL2", "score": 0.85}
            ]
        }

        cfg = Mem0Config(enabled=True)
        backend = Mem0Backend(cfg)
        backend._initialized = True
        backend._memory = mock_instance

        result = backend.search("work environment", user_id="testuser")
        assert result["error"] is None
        assert len(result["results"]) == 1
        assert result["results"][0]["score"] == 0.85

    @patch("mem0_backend._check_mem0", return_value=True)
    def test_get_all_success(self, mock_check):
        mock_instance = MagicMock()
        mock_instance.get_all.return_value = {
            "results": [
                {"id": "a", "memory": "fact 1"},
                {"id": "b", "memory": "fact 2"},
            ]
        }

        cfg = Mem0Config(enabled=True)
        backend = Mem0Backend(cfg)
        backend._initialized = True
        backend._memory = mock_instance

        result = backend.get_all(user_id="testuser")
        assert result["error"] is None
        assert len(result["results"]) == 2

    @patch("mem0_backend._check_mem0", return_value=False)
    def test_sdk_not_installed(self, mock_check):
        cfg = Mem0Config(enabled=True)
        backend = Mem0Backend(cfg)
        assert backend.available is False
        status = backend.status()
        assert status["mem0_sdk_installed"] is False


class TestMem0ConfigYaml:
    """Test config.yaml mem0 section parsing."""

    def test_config_yaml_has_mem0_section(self):
        config_path = Path(__file__).resolve().parent.parent / "config.yaml"
        if not config_path.exists():
            pytest.skip("config.yaml not found")
        content = config_path.read_text()
        assert "mem0:" in content
        assert "enabled:" in content
        assert "llm_model:" in content
        assert "ollama_url:" in content
