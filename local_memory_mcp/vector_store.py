"""Vector store layer — Qdrant (local file or server URL mode).

Single vector backend for both semantic search and dedup comparison.
No sqlite-vec, no Mem0 Qdrant instance — one store, one source of truth.

Embeddings via Ollama nomic-embed-text (httpx, no ollama SDK), with
sentence-transformers and hashing fallbacks.

Public API
----------
VectorStore.upsert(id, text, payload)
VectorStore.search(text, top_k, filters) -> list[SearchResult]
VectorStore.delete(id)
VectorStore.count() -> int
VectorStore.close()

embed_text(text, config) -> list[float]   (also usable standalone)
"""
from __future__ import annotations

import atexit
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Embedding config
# ---------------------------------------------------------------------------

@dataclass
class EmbedConfig:
    provider: str = "ollama"          # "ollama" | "sentence-transformers" | "hashing"
    model: str = "nomic-embed-text"
    ollama_url: str = "http://127.0.0.1:11434"
    fallback_provider: str = "sentence-transformers"
    sentence_transformers_model: str = "sentence-transformers/all-mpnet-base-v2"
    dim: int = 768
    timeout: int = 30

    def __post_init__(self):
        # Allow override via env
        if os.environ.get("LOCAL_MEMORY_OLLAMA_URL"):
            self.ollama_url = os.environ["LOCAL_MEMORY_OLLAMA_URL"]
        elif os.environ.get("OLLAMA_HOST"):
            host = os.environ["OLLAMA_HOST"]
            if not host.startswith("http"):
                host = f"http://{host}"
            self.ollama_url = host


def embed_config_from_dict(cfg: dict[str, Any]) -> EmbedConfig:
    emb = cfg.get("embedding", {})
    dim = os.environ.get("LOCAL_MEMORY_EMBEDDING_DIM", emb.get("dim", 768))
    timeout = os.environ.get("LOCAL_MEMORY_OLLAMA_TIMEOUT", emb.get("timeout", 30))
    return EmbedConfig(
        provider=os.environ.get("LOCAL_MEMORY_EMBEDDING_PROVIDER", emb.get("provider", "ollama")),
        model=os.environ.get("LOCAL_MEMORY_EMBEDDING_MODEL", emb.get("model", "nomic-embed-text")),
        ollama_url=os.environ.get(
            "LOCAL_MEMORY_OLLAMA_URL",
            emb.get("ollama_url", os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")),
        ),
        fallback_provider=os.environ.get(
            "LOCAL_MEMORY_EMBEDDING_FALLBACK_PROVIDER",
            emb.get("fallback_provider", "sentence-transformers"),
        ),
        sentence_transformers_model=os.environ.get(
            "LOCAL_MEMORY_SENTENCE_TRANSFORMERS_MODEL",
            emb.get("sentence_transformers_model", "sentence-transformers/all-mpnet-base-v2"),
        ),
        dim=int(dim),
        timeout=int(timeout),
    )


# ---------------------------------------------------------------------------
# Embedding functions
# ---------------------------------------------------------------------------

def embed_text(text: str, config: EmbedConfig | None = None) -> list[float]:
    """Return a float vector for text.

    Default chain:
    Ollama -> sentence-transformers -> deterministic hashing.
    """
    if config is None:
        config = EmbedConfig()
    provider = _normalize_provider(config.provider)
    if provider == "hashing":
        return _embed_hashing(text, config.dim)
    if provider == "sentence-transformers":
        try:
            return _embed_sentence_transformers(text, config)
        except Exception as exc:
            logger.warning("embed_text: sentence-transformers failed (%s), using hashing fallback", exc)
            return _embed_hashing(text, config.dim)
    if provider != "ollama":
        logger.warning("embed_text: unknown provider %r, using hashing fallback", config.provider)
        return _embed_hashing(text, config.dim)
    try:
        return _embed_ollama(text, config)
    except Exception as exc:
        logger.warning("embed_text: Ollama failed (%s), using %s fallback", exc, config.fallback_provider)
        return _embed_fallback(text, config)


def _normalize_provider(provider: str) -> str:
    value = str(provider or "").strip().lower().replace("_", "-")
    if value in {"sentence-transformer", "sentence-transformers", "st"}:
        return "sentence-transformers"
    return value


def _embed_fallback(text: str, config: EmbedConfig) -> list[float]:
    fallback = _normalize_provider(config.fallback_provider)
    if fallback == "sentence-transformers":
        try:
            return _embed_sentence_transformers(text, config)
        except Exception as exc:
            logger.warning("embed_text: sentence-transformers fallback failed (%s), using hashing fallback", exc)
    return _embed_hashing(text, config.dim)


def _embed_ollama(text: str, config: EmbedConfig) -> list[float]:
    """Call Ollama /api/embed endpoint."""
    try:
        import httpx
        url = config.ollama_url.rstrip("/") + "/api/embed"
        with httpx.Client(timeout=config.timeout) as client:
            resp = client.post(url, json={"model": config.model, "input": text})
            resp.raise_for_status()
            data = resp.json()
    except ImportError:
        import urllib.request
        url = config.ollama_url.rstrip("/") + "/api/embed"
        payload = json.dumps({"model": config.model, "input": text}).encode()
        req = urllib.request.Request(url, data=payload,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=config.timeout) as r:
            data = json.loads(r.read())

    # Ollama returns {"embeddings": [[...]]} or {"embedding": [...]}
    if "embeddings" in data:
        vec = data["embeddings"][0]
    else:
        vec = data["embedding"]
    return _fit_dim([float(x) for x in vec], config.dim)


_ST_MODELS: dict[str, Any] = {}


def _embed_sentence_transformers(text: str, config: EmbedConfig) -> list[float]:
    """Embed text with sentence-transformers when the optional dependency exists."""
    from sentence_transformers import SentenceTransformer

    model_name = config.sentence_transformers_model
    model = _ST_MODELS.get(model_name)
    if model is None:
        model = SentenceTransformer(model_name)
        _ST_MODELS[model_name] = model
    vector = model.encode(text, normalize_embeddings=True)
    if hasattr(vector, "tolist"):
        vector = vector.tolist()
    return _fit_dim([float(x) for x in vector], config.dim)


def _fit_dim(vec: list[float], dim: int) -> list[float]:
    """Coerce embedding length to the configured Qdrant collection dimension."""
    if len(vec) > dim:
        vec = vec[:dim]
    elif len(vec) < dim:
        vec = vec + [0.0] * (dim - len(vec))
    norm = sum(v * v for v in vec) ** 0.5 or 1.0
    return [v / norm for v in vec]


def _embed_hashing(text: str, dim: int = 768) -> list[float]:
    """Deterministic pseudo-embedding via hashing (no external deps)."""
    import hashlib
    import math
    h = hashlib.sha256(text.encode()).digest()
    vals: list[float] = []
    for i in range(dim):
        byte = h[i % 32]
        angle = (byte / 255.0) * 2 * math.pi + i
        vals.append(math.sin(angle))
    norm = math.sqrt(sum(v * v for v in vals)) or 1.0
    return [v / norm for v in vals]


# ---------------------------------------------------------------------------
# Qdrant vector store
# ---------------------------------------------------------------------------

@dataclass
class VectorStoreConfig:
    path: str = ""                    # local file path; "" → ~/.agent-memory/qdrant
    url: str = ""                     # server URL; e.g. "http://127.0.0.1:6333"
    collection: str = "agent_memory"
    dim: int = 768
    embed: EmbedConfig = field(default_factory=EmbedConfig)

    def __post_init__(self):
        if not self.path:
            self.path = str(Path.home() / ".agent-memory" / "qdrant")


def vector_store_config_from_dict(cfg: dict[str, Any]) -> VectorStoreConfig:
    qs = cfg.get("qdrant", {})
    embed_cfg = embed_config_from_dict(cfg)
    env_url = _env_first("LOCAL_MEMORY_QDRANT_URL", "QDRANT_URL")
    env_path = _env_first("LOCAL_MEMORY_QDRANT_PATH", "QDRANT_PATH")
    env_collection = _env_first("LOCAL_MEMORY_QDRANT_COLLECTION", "QDRANT_COLLECTION")
    return VectorStoreConfig(
        path=env_path if env_path is not None else qs.get("path", ""),
        url=env_url if env_url is not None else qs.get("url", ""),
        collection=env_collection if env_collection is not None else qs.get("collection", "agent_memory"),
        dim=embed_cfg.dim,
        embed=embed_cfg,
    )


def _env_first(*names: str) -> str | None:
    for name in names:
        if name in os.environ:
            return os.environ[name]
    return None


@dataclass
class SearchResult:
    id: str
    score: float
    payload: dict[str, Any] = field(default_factory=dict)
    text: str = ""


class VectorStore:
    """Thin wrapper around qdrant-client (local file or server URL mode)."""

    def __init__(self, config: VectorStoreConfig | None = None):
        self.config = config or VectorStoreConfig()
        self._client = None
        self._initialized = False
        atexit.register(self.close)

    # ------------------------------------------------------------------
    # Lazy init
    # ------------------------------------------------------------------

    def _ensure_init(self) -> bool:
        if self._initialized:
            return self._client is not None
        self._initialized = True
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Distance, VectorParams

            # Prefer server URL mode; fall back to local file mode
            if self.config.url:
                self._client = QdrantClient(url=self.config.url, timeout=30)
                logger.info("vector_store: connected to Qdrant server at %s", self.config.url)
            else:
                Path(self.config.path).mkdir(parents=True, exist_ok=True)
                self._client = QdrantClient(path=self.config.path)
                logger.info("vector_store: using local file mode at %s", self.config.path)

            # Create collection if it doesn't exist
            existing = [c.name for c in self._client.get_collections().collections]
            if self.config.collection not in existing:
                self._client.create_collection(
                    collection_name=self.config.collection,
                    vectors_config=VectorParams(
                        size=self.config.dim,
                        distance=Distance.COSINE,
                    ),
                )
                logger.info("vector_store: created collection '%s' dim=%d",
                            self.config.collection, self.config.dim)
            else:
                logger.info("vector_store: opened collection '%s'",
                            self.config.collection)
            return True
        except Exception as exc:
            logger.error("vector_store: init failed: %s", exc)
            self._client = None
            return False

    @property
    def available(self) -> bool:
        return self._ensure_init()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def upsert(
        self,
        id: str,
        text: str,
        payload: dict[str, Any] | None = None,
    ) -> bool:
        """Insert or update a vector by UUID string id."""
        if not self.available:
            return False
        try:
            from qdrant_client.models import PointStruct
            vec = embed_text(text, self.config.embed)
            p = dict(payload or {})
            p["text"] = text
            # Qdrant needs integer or UUID point ids; use UUID string directly
            self._client.upsert(
                collection_name=self.config.collection,
                points=[PointStruct(id=id, vector=vec, payload=p)],
            )
            return True
        except Exception as exc:
            logger.error("vector_store: upsert failed for id=%s: %s", id, exc)
            return False

    def search(
        self,
        text: str,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
        score_threshold: float = 0.0,
    ) -> list[SearchResult]:
        """Semantic search.  filters: {"status": "active", "user_id": "..."} etc."""
        if not self.available:
            return []
        try:
            from qdrant_client.models import Filter, FieldCondition, MatchValue

            vec = embed_text(text, self.config.embed)

            qdrant_filter = None
            if filters:
                conditions = [
                    FieldCondition(key=k, match=MatchValue(value=v))
                    for k, v in filters.items()
                ]
                qdrant_filter = Filter(must=conditions)

            # qdrant-client >= 1.7 uses query_points; older uses search
            if hasattr(self._client, "query_points"):
                from qdrant_client.models import QueryRequest
                result = self._client.query_points(
                    collection_name=self.config.collection,
                    query=vec,
                    limit=top_k,
                    query_filter=qdrant_filter,
                    score_threshold=score_threshold if score_threshold > 0 else None,
                    with_payload=True,
                )
                hits = result.points
            else:
                hits = self._client.search(
                    collection_name=self.config.collection,
                    query_vector=vec,
                    limit=top_k,
                    query_filter=qdrant_filter,
                    score_threshold=score_threshold if score_threshold > 0 else None,
                    with_payload=True,
                )

            return [
                SearchResult(
                    id=str(h.id),
                    score=float(h.score),
                    payload=dict(h.payload or {}),
                    text=str((h.payload or {}).get("text", "")),
                )
                for h in hits
            ]
        except Exception as exc:
            logger.error("vector_store: search failed: %s", exc)
            return []

    def delete(self, id: str) -> bool:
        """Delete a point by UUID string id."""
        if not self.available:
            return False
        try:
            from qdrant_client.models import PointIdsList
            self._client.delete(
                collection_name=self.config.collection,
                points_selector=PointIdsList(points=[id]),
            )
            return True
        except Exception as exc:
            logger.error("vector_store: delete failed for id=%s: %s", id, exc)
            return False

    def count(self) -> int:
        """Return number of vectors in the collection."""
        if not self.available:
            return 0
        try:
            result = self._client.count(collection_name=self.config.collection)
            return result.count
        except Exception as exc:
            logger.error("vector_store: count failed: %s", exc)
            return 0

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

    def status(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "path": self.config.path,
            "url": self.config.url,
            "collection": self.config.collection,
            "dim": self.config.dim,
            "embed_provider": self.config.embed.provider,
            "embed_model": self.config.embed.model,
            "embed_fallback_provider": self.config.embed.fallback_provider,
            "sentence_transformers_model": self.config.embed.sentence_transformers_model,
            "ollama_url": self.config.embed.ollama_url,
            "count": self.count(),
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_store: VectorStore | None = None


def get_vector_store(config: dict[str, Any] | None = None) -> VectorStore:
    global _store
    if _store is None:
        vs_cfg = vector_store_config_from_dict(config or {})
        _store = VectorStore(vs_cfg)
    return _store


def reset_vector_store() -> None:
    global _store
    if _store is not None:
        _store.close()
    _store = None
