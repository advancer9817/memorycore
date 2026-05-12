"""Mem0 SDK integration backend for local-memory-mcp.

Provides LLM-powered memory extraction and semantic search via Mem0,
using Ollama for both LLM and embeddings (fully local, no cloud).

Architecture:
  local-memory-mcp (SQLite + FTS5) = fast structured layer (governance, curator, timeline)
  Mem0 SDK (Qdrant local + Ollama) = smart extraction layer (auto-extract facts from conversations)

Both layers are complementary. Mem0 extracted memories can be promoted into
the structured SQLite layer via memory_add for long-term governance.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Lazy import — mem0 is optional
_mem0_available: bool | None = None
_Memory = None


def _check_mem0() -> bool:
    """Check if mem0ai is importable."""
    global _mem0_available, _Memory
    if _mem0_available is None:
        try:
            from mem0 import Memory
            _Memory = Memory
            _mem0_available = True
        except ImportError:
            _mem0_available = False
    return _mem0_available


@dataclass
class Mem0Config:
    """Configuration for Mem0 backend."""
    enabled: bool = False
    llm_provider: str = "ollama"
    llm_model: str = "qwen2.5:3b"
    llm_api_key: str = ""
    llm_base_url: str = ""
    ollama_url: str = "http://127.0.0.1:12434"
    embedder_model: str = "nomic-embed-text"
    embedder_dim: int = 768
    vector_store_path: str = ""  # defaults to ~/.agent-memory/mem0_qdrant
    collection_name: str = "agent_memory"
    default_user_id: str = "advancer"
    temperature: float = 0.1
    max_tokens: int = 2000
    timeout: int = 60

    def __post_init__(self):
        if not self.vector_store_path:
            self.vector_store_path = str(
                Path.home() / ".agent-memory" / "mem0_qdrant"
            )


def mem0_config_from_dict(cfg: dict[str, Any]) -> Mem0Config:
    """Build Mem0Config from config.yaml 'mem0' section."""
    mem0_section = cfg.get("mem0", {})
    return Mem0Config(
        enabled=mem0_section.get("enabled", False),
        llm_provider=mem0_section.get("llm_provider", "ollama"),
        llm_model=mem0_section.get("llm_model", "qwen2.5:3b"),
        llm_api_key=mem0_section.get("llm_api_key",
                                      os.environ.get("MEM0_LLM_API_KEY", "")),
        llm_base_url=mem0_section.get("llm_base_url",
                                       os.environ.get("MEM0_LLM_BASE_URL", "")),
        ollama_url=mem0_section.get("ollama_url",
                                     os.environ.get("OLLAMA_HOST", "http://127.0.0.1:12434")),
        embedder_model=mem0_section.get("embedder_model", "nomic-embed-text"),
        embedder_dim=mem0_section.get("embedder_dim", 768),
        vector_store_path=mem0_section.get("vector_store_path", ""),
        collection_name=mem0_section.get("collection_name", "agent_memory"),
        default_user_id=mem0_section.get("default_user_id", "advancer"),
        temperature=mem0_section.get("temperature", 0.1),
        max_tokens=mem0_section.get("max_tokens", 2000),
        timeout=mem0_section.get("timeout", 60),
    )


class Mem0Backend:
    """Wrapper around Mem0 SDK for local-memory-mcp integration."""

    def __init__(self, config: Mem0Config):
        self.config = config
        self._memory = None
        self._initialized = False

    def _ensure_init(self) -> bool:
        """Lazy-initialize Mem0 Memory instance."""
        if self._initialized:
            return self._memory is not None
        self._initialized = True

        if not self.config.enabled:
            logger.info("Mem0 backend disabled in config")
            return False

        if not _check_mem0():
            logger.warning("mem0ai not installed; Mem0 backend unavailable")
            return False

        try:
            # Build LLM config based on provider
            llm_config: dict[str, Any] = {
                "model": self.config.llm_model,
                "temperature": self.config.temperature,
                "max_tokens": self.config.max_tokens,
            }
            if self.config.llm_provider == "ollama":
                llm_config["ollama_base_url"] = self.config.ollama_url
            elif self.config.llm_provider == "deepseek":
                if self.config.llm_api_key:
                    llm_config["api_key"] = self.config.llm_api_key
                if self.config.llm_base_url:
                    llm_config["deepseek_base_url"] = self.config.llm_base_url
            else:
                # Generic OpenAI-compatible providers
                if self.config.llm_api_key:
                    llm_config["api_key"] = self.config.llm_api_key
                if self.config.llm_base_url:
                    llm_config["openai_base_url"] = self.config.llm_base_url

            mem0_config = {
                "llm": {
                    "provider": self.config.llm_provider,
                    "config": llm_config,
                },
                "embedder": {
                    "provider": "ollama",
                    "config": {
                        "model": self.config.embedder_model,
                        "ollama_base_url": self.config.ollama_url,
                    }
                },
                "vector_store": {
                    "provider": "qdrant",
                    "config": {
                        "collection_name": self.config.collection_name,
                        "path": self.config.vector_store_path,
                        "embedding_model_dims": self.config.embedder_dim,
                    }
                },
                "version": "v1.1",
            }
            self._memory = _Memory.from_config(config_dict=mem0_config)
            logger.info("Mem0 backend initialized: llm=%s, store=%s",
                       self.config.llm_model, self.config.vector_store_path)
            return True
        except Exception as e:
            logger.error("Failed to initialize Mem0: %s", e)
            self._memory = None
            return False

    @property
    def available(self) -> bool:
        return self._ensure_init()

    def extract_memories(
        self,
        messages: list[dict[str, str]],
        user_id: str | None = None,
        agent_id: str = "hermes",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Extract memories from a conversation using Mem0's LLM pipeline.

        Args:
            messages: List of {"role": "user"|"assistant", "content": "..."}
            user_id: User identifier for scoping
            agent_id: Agent that produced/consumed the conversation
            metadata: Optional metadata to attach

        Returns:
            {"results": [...], "elapsed_s": float, "error": str|None}
        """
        if not self.available:
            return {"results": [], "elapsed_s": 0, "error": "Mem0 backend not available"}

        user_id = user_id or self.config.default_user_id
        t0 = time.time()
        try:
            kwargs: dict[str, Any] = {
                "messages": messages,
                "user_id": user_id,
                "agent_id": agent_id,
            }
            if metadata:
                kwargs["metadata"] = metadata
            result = self._memory.add(**kwargs)
            elapsed = time.time() - t0
            # Normalize result format
            if isinstance(result, dict) and "results" in result:
                memories = result["results"]
            elif isinstance(result, list):
                memories = result
            else:
                memories = [result] if result else []
            return {"results": memories, "elapsed_s": round(elapsed, 2), "error": None}
        except Exception as e:
            elapsed = time.time() - t0
            logger.error("Mem0 extract_memories failed: %s", e)
            return {"results": [], "elapsed_s": round(elapsed, 2), "error": str(e)}

    def search(
        self,
        query: str,
        user_id: str | None = None,
        agent_id: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Semantic search through Mem0's vector store.

        Returns:
            {"results": [{"memory": str, "score": float, "id": str}], "elapsed_s": float}
        """
        if not self.available:
            return {"results": [], "elapsed_s": 0, "error": "Mem0 backend not available"}

        user_id = user_id or self.config.default_user_id
        t0 = time.time()
        try:
            filters: dict[str, Any] = {"user_id": user_id}
            if agent_id:
                filters["agent_id"] = agent_id
            result = self._memory.search(query, filters=filters, limit=limit)
            elapsed = time.time() - t0
            # Normalize
            if isinstance(result, dict) and "results" in result:
                memories = result["results"]
            elif isinstance(result, list):
                memories = result
            else:
                memories = []
            return {"results": memories, "elapsed_s": round(elapsed, 2), "error": None}
        except Exception as e:
            elapsed = time.time() - t0
            logger.error("Mem0 search failed: %s", e)
            return {"results": [], "elapsed_s": round(elapsed, 2), "error": str(e)}

    def get_all(
        self,
        user_id: str | None = None,
        agent_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Get all memories for a user."""
        if not self.available:
            return {"results": [], "error": "Mem0 backend not available"}

        user_id = user_id or self.config.default_user_id
        try:
            filters: dict[str, Any] = {"user_id": user_id}
            if agent_id:
                filters["agent_id"] = agent_id
            result = self._memory.get_all(filters=filters, limit=limit)
            if isinstance(result, dict) and "results" in result:
                return {"results": result["results"], "error": None}
            elif isinstance(result, list):
                return {"results": result, "error": None}
            return {"results": [], "error": None}
        except Exception as e:
            logger.error("Mem0 get_all failed: %s", e)
            return {"results": [], "error": str(e)}

    def status(self) -> dict[str, Any]:
        """Return Mem0 backend status."""
        return {
            "available": self.available,
            "enabled": self.config.enabled,
            "llm_model": self.config.llm_model,
            "embedder_model": self.config.embedder_model,
            "ollama_url": self.config.ollama_url,
            "vector_store_path": self.config.vector_store_path,
            "collection_name": self.config.collection_name,
            "mem0_sdk_installed": _check_mem0(),
        }


# Module-level singleton (initialized lazily by the MCP server)
_backend: Mem0Backend | None = None


def get_mem0_backend(config: dict[str, Any] | None = None) -> Mem0Backend:
    """Get or create the module-level Mem0Backend singleton."""
    global _backend
    if _backend is None:
        if config is None:
            config = {}
        mem0_cfg = mem0_config_from_dict(config)
        _backend = Mem0Backend(mem0_cfg)
    return _backend


def reset_backend():
    """Reset singleton (for testing)."""
    global _backend
    _backend = None
