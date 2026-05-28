"""Models, constants, and helpers for local-memory-mcp.

Extracted from the original local_memory_mcp.py monolith into a dedicated
module with no MCP or I/O dependencies so both storage.py and external
modules (extraction.py, dedup.py) can import them without circular issues.
"""
from __future__ import annotations

import json
import math
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

__all__ = [
    "DEFAULT_ROOT",
    "DEFAULT_DB",
    "_INITIALIZED_DB_PATHS",
    "LOCAL_TZ",
    "DEFAULT_CONFIG",
    "MEMORY_TYPES",
    "STATUSES",
    "VALID_RELATION_TYPES",
    "now",
    "local_now",
    "as_json",
    "from_json",
    "config_path",
    "_deep_merge",
    "load_config",
    "validate_config",
    "db_path",
    "normalize_list",
    "row_to_dict",
    "validate_type",
    "validate_status",
    "finite_float",
    "fts_phrase",
    "parse_ts",
    "normalize_title_key",
]

DEFAULT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = Path(
    os.environ.get(
        "LOCAL_MEMORY_DB",
        DEFAULT_ROOT / "memory.sqlite3",
    )
)
_INITIALIZED_DB_PATHS: set[str] = set()
LOCAL_TZ = timezone(timedelta(hours=8), "CST")

DEFAULT_CONFIG: dict[str, Any] = {
    "backend": {"primary": "sqlite", "fallback": "sqlite"},
    "qdrant": {"url": "http://127.0.0.1:6333", "collection": "agent_memory", "timeout": 30},
    "embedding": {
        "provider": "ollama",
        "model": "nomic-embed-text",
        "dim": 768,
        "ollama_url": "http://127.0.0.1:11434",
        "timeout": 30,
    },
    "context_pack": {"default_token_budget": 2000, "include_stale_warnings": True, "max_records_per_group": 6},
    "temporal": {"enabled": False, "contradiction_detection": "heuristic", "auto_supersede_user_corrections": True},
}

MEMORY_TYPES: set[str] = {
    "user_profile",
    "environment_fact",
    "agent_architecture",
    "project_memory",
    "episodic_memory",
    "timeline_event",
    "decision",
    "feedback",
    "skill_candidate",
    "raw_event",
}

STATUSES: set[str] = {"active", "stale", "archived", "contradicted", "candidate"}

VALID_RELATION_TYPES: frozenset[str] = frozenset({
    "related_to",
    "supersedes",
    "contradicts",
    "supports",
    "part_of",
    "blocked_by",
    "causes",
    "failure_pattern",
})


def local_now() -> datetime:
    return datetime.now(LOCAL_TZ)


def now() -> str:
    return local_now().isoformat(timespec="seconds")


def as_json(value: Any) -> str:
    if value is None:
        value = []
    return json.dumps(value, ensure_ascii=False)


def from_json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def config_path() -> Path:
    return Path(
        os.environ.get("LOCAL_MEMORY_CONFIG", str(DEFAULT_ROOT / "config.yaml"))
    ).expanduser()




def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for key, value in base.items():
        if isinstance(value, dict):
            merged[key] = _deep_merge(value, {})
        else:
            merged[key] = value
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config() -> dict[str, Any]:
    path = config_path()
    if not path.exists():
        return _deep_merge(DEFAULT_CONFIG, {})
    parsed = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return _deep_merge(DEFAULT_CONFIG, parsed)


def validate_config(cfg: dict[str, Any]) -> list[str]:
    """Validate config dict. Returns list of warning strings (empty = OK)."""
    warnings: list[str] = []

    def _warn(msg: str) -> None:
        warnings.append(msg)

    def _pos_int(section: str, key: str, val: Any) -> None:
        if not (isinstance(val, int) and val > 0):
            _warn(f"{section}.{key} must be a positive integer (got {val!r})")

    # embedding
    emb = cfg.get("embedding", {})
    if emb.get("provider") not in ("ollama", "hashing"):
        _warn(f"embedding.provider={emb.get('provider')!r} unknown, expected ollama|hashing")
    _pos_int("embedding", "dim", emb.get("dim"))
    _pos_int("embedding", "timeout", emb.get("timeout"))
    ollama_url = emb.get("ollama_url", "")
    if ollama_url and not str(ollama_url).startswith(("http://", "https://")):
        _warn(f"embedding.ollama_url must start with http:// or https:// (got {ollama_url!r})")

    # qdrant
    qs = cfg.get("qdrant", {})
    if not qs.get("url") and not qs.get("path"):
        _warn("qdrant: neither url nor path is configured, vector search will be unavailable")
    if qs.get("url") and not str(qs["url"]).startswith(("http://", "https://")):
        _warn(f"qdrant.url must start with http:// or https:// (got {qs['url']!r})")
    if "timeout" in qs:
        _pos_int("qdrant", "timeout", qs.get("timeout"))

    # context_pack
    cp = cfg.get("context_pack", {})
    _pos_int("context_pack", "default_token_budget", cp.get("default_token_budget"))
    _pos_int("context_pack", "max_records_per_group", cp.get("max_records_per_group"))

    # backend
    be = cfg.get("backend", {})
    if be.get("primary") not in ("sqlite", None, ""):
        _warn(f"backend.primary={be.get('primary')!r} unknown, only sqlite is supported")

    return warnings


def db_path() -> Path:
    path = Path(
        os.environ.get("LOCAL_MEMORY_DB", str(DEFAULT_ROOT / "memory.sqlite3"))
    ).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def normalize_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        v = value.strip()
        if v.startswith("["):
            try:
                parsed = json.loads(v)
                return [str(x).strip() for x in parsed if str(x).strip()]
            except Exception:
                pass
        return [x.strip() for x in v.split(",") if x.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(x).strip() for x in value if str(x).strip()]
    return [str(value).strip()]


def row_to_dict(row: Any) -> dict[str, Any]:
    d = dict(row)
    d["tags"] = from_json(d.pop("tags_json", "[]"), [])
    d["related_ids"] = from_json(d.pop("related_ids_json", "[]"), [])
    d["metadata"] = from_json(d.pop("metadata_json", "{}"), {})
    return d


def validate_type(memory_type: str) -> str:
    if memory_type not in MEMORY_TYPES:
        raise ValueError(f"type must be one of {sorted(MEMORY_TYPES)}")
    return memory_type


def validate_status(status: str) -> str:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {sorted(STATUSES)}")
    return status


def finite_float(
    value: Any, name: str, min_value: float | None = None, max_value: float | None = None
) -> float:
    try:
        x = float(value)
    except Exception as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(x):
        raise ValueError(f"{name} must be finite")
    if min_value is not None and x < min_value:
        raise ValueError(f"{name} must be >= {min_value}")
    if max_value is not None and x > max_value:
        raise ValueError(f"{name} must be <= {max_value}")
    return x


def fts_phrase(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


def parse_ts(value: str | None) -> datetime:
    if not value:
        return datetime.fromtimestamp(0, timezone.utc)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except Exception:
        return datetime.fromtimestamp(0, timezone.utc)


def normalize_title_key(title: str) -> str:
    tokens = re.findall(r"[\w\u4e00-\u9fff]+", (title or "").lower(), flags=re.UNICODE)
    return " ".join(tokens)[:120]
