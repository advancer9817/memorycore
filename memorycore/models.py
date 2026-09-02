"""Models, constants, and helpers for memorycore.

Extracted from the original memorycore.py monolith into a dedicated
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
    "output_language": "auto",  # "zh" | "en" | "auto"
    "backend": {"primary": "sqlite", "fallback": "sqlite"},
    "qdrant": {"url": "http://127.0.0.1:6333", "collection": "agent_memory", "timeout": 30},
    "embedding": {
        "provider": "auto",
        "model": "nomic-embed-text",
        "fallback_provider": "hashing",
        "api_url": "",
        "api_key": "",
        "sentence_transformers_model": "sentence-transformers/all-mpnet-base-v2",
        "dim": 768,
        "ollama_url": "http://127.0.0.1:11434",
        "timeout": 30,
    },
    "context_pack": {
        "default_token_budget": 2000,
        "include_stale_warnings": True,
        "max_records_per_group": 6,
        "recency_weight": 0.05,
        "cluster_similarity_threshold": 0.85,
        "cluster_enabled": True,
        "profile_boost_weight": 0.15,
        "profile_conflict_penalty": 0.6,
        "profile_query_expand_enabled": True,
        "profile_query_expand_min_overlap": 1,
        "profile_query_expand_max_terms": 3,
        "profile_conflict_filter_enabled": True,
    },
    "temporal": {
        "enabled": True,
        "contradiction_detection": "heuristic",
        "auto_supersede_user_corrections": True,
        "auto_supersede_enabled": True,
        "auto_supersede_threshold": 0.88,
        "review_similarity_threshold": 0.72,
        "recency_half_life_days": 90,
        "llm_temporal_prompts": True,
        "dedup_temporal_guard": True,
        "governance_age_risk_days": 7,
    },
    "subject_context": {
        "enabled": False,  # opt-in: populate projects whitelist, then enable
        "default_scope": "global",
        "auto_discover": False,  # ~/project/* git repos as subject projects
        "projects": [],
    },
    "rule_curator": {
        "decay_step": 0.05,
        "decay_interval_days": 30,
        "decay_min_confidence": 0.15,
        "candidate_ttl_episodic_days": 7,
        "candidate_ttl_precious_days": 30,
        "candidate_ttl_default_days": 7,
        "stale_days_episodic": 14,
        "archive_days_episodic": 30,
        "stale_days_default": 365,
        "archive_days_default": 730,
        "contradicted_archive_days": 90,
        "never_accessed_candidate_days": 14,
        "promote_importance_threshold": 0.75,
        "promote_injected_threshold": 3,
        "precious_types": ["user_profile", "environment_fact", "decision", "project_memory", "skill_candidate"],
        "stale_importance_threshold": 0.45,
        "stale_feedback_threshold": -0.5,
        "precious_stale_feedback": -2.0,
        "precious_stale_importance": 0.3,
        "revival_window_days": 7,
        "revival_effectiveness_min": 0.5,
        "revival_feedback_min": 0.0,
        "skill_promote_importance": 0.65,
        "skill_promote_feedback_min": 0.0,
    },
    "llm_curator": {
        "sim_threshold": 0.50,
        "batch_size": 10,
        "importance_limit": 1000,
        "split_content_threshold": 400,
        "review_cooldown_seconds": 1800,
        "reviewed_ids_max_age_seconds": 86400,
        "temperature": 0.6,
        "content_max_chars": 2000,
        "prompt_style": "aggressive",
        "keep_threshold": 0.02,
        "preset": "aggressive",
        "max_dedup_pairs": 200,
        "max_contradiction_pairs": 200,
        "max_split_candidates": 100,
        "max_link_pairs": 100,
    },
    "governance": {
        "review_confidence_threshold": 0.55,
        "high_importance_threshold": 0.85,
        "auto_approve_confidence": 0.90,
        "auto_approve_low_risk_confidence": 0.70,
        "precious_types": ["user_profile", "decision", "project_memory"],
        "manual_only_actions": ["split"],
        "merge_actions": ["archive_and_merge_duplicate"],
    },
    "extraction_strategy": {
        "min_importance": 0.3,
        "default_confidence": 0.65,
        "default_importance": 0.5,
        "chinese_detection_ratio": 0.15,
        "skip_threshold": 0.92,
        "update_threshold": 0.78,
        "link_threshold": 0.55,
        "context_sample_length": 200,
        "context_memory_limit": 10,
        "dedup_search_limit": 5,
        "max_related_ids": 10,
        "default_memory_type": "episodic_memory",
        "default_status": "candidate",
        "default_decay_policy": "review",
        "title_max_length": 80,
        "default_scope": "global",
    },
    "user_profile": {
        "enabled": False,
        "extract_limit": 200,
        "max_snapshot_chars": 800,
        "min_confidence": 0.6,
        "schema": [],
    },
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

STATUSES: set[str] = {"active", "stale", "archived", "contradicted", "candidate", "superseded"}

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


_config_cache: dict[str, Any] = {}


def invalidate_config_cache() -> None:
    _config_cache.clear()


def load_config() -> dict[str, Any]:
    path = config_path()
    try:
        mtime = path.stat().st_mtime if path.exists() else 0.0
    except OSError:
        mtime = 0.0
    key = str(path)
    cached = _config_cache.get(key)
    if cached is not None and cached["mtime"] == mtime:
        return cached["cfg"]
    if not path.exists():
        cfg = _deep_merge(DEFAULT_CONFIG, {})
    else:
        parsed = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        cfg = _deep_merge(DEFAULT_CONFIG, parsed)
    _config_cache[key] = {"mtime": mtime, "cfg": cfg}
    return cfg


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
    valid_embedding_providers = ("auto", "ollama", "openai", "api", "sentence-transformers", "hashing")
    if emb.get("provider") not in valid_embedding_providers:
        _warn(f"embedding.provider={emb.get('provider')!r} unknown, expected auto|ollama|openai|api|sentence-transformers|hashing")
    fallback_provider = emb.get("fallback_provider", "hashing")
    if fallback_provider not in ("openai", "api", "sentence-transformers", "hashing"):
        _warn(f"embedding.fallback_provider={fallback_provider!r} unknown, expected openai|api|sentence-transformers|hashing")
    _pos_int("embedding", "dim", emb.get("dim"))
    _pos_int("embedding", "timeout", emb.get("timeout"))
    ollama_url = emb.get("ollama_url", "")
    if ollama_url and not str(ollama_url).startswith(("http://", "https://")):
        _warn(f"embedding.ollama_url must start with http:// or https:// (got {ollama_url!r})")
    api_url = emb.get("api_url", "")
    if api_url and not str(api_url).startswith(("http://", "https://")):
        _warn(f"embedding.api_url must start with http:// or https:// (got {api_url!r})")

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

    # rule_curator
    rc = cfg.get("rule_curator", {})
    _day_keys = (
        "decay_interval_days", "candidate_ttl_episodic_days", "candidate_ttl_precious_days",
        "candidate_ttl_default_days", "stale_days_episodic", "archive_days_episodic",
        "stale_days_default", "archive_days_default", "contradicted_archive_days",
        "never_accessed_candidate_days", "revival_window_days",
    )
    for key in _day_keys:
        if key in rc:
            _pos_int("rule_curator", key, rc[key])
    if "promote_injected_threshold" in rc:
        _pos_int("rule_curator", "promote_injected_threshold", rc["promote_injected_threshold"])
    for key in ("decay_step", "decay_min_confidence", "promote_importance_threshold",
                "stale_importance_threshold", "precious_stale_importance",
                "revival_effectiveness_min", "skill_promote_importance"):
        if key in rc:
            val = rc[key]
            if not (isinstance(val, (int, float)) and 0 <= val <= 1):
                _warn(f"rule_curator.{key} must be a 0-1 float (got {val!r})")
    for key in ("stale_feedback_threshold", "precious_stale_feedback",
                "revival_feedback_min", "skill_promote_feedback_min"):
        if key in rc:
            val = rc[key]
            if not isinstance(val, (int, float)):
                _warn(f"rule_curator.{key} must be a number (got {val!r})")
    pt = rc.get("precious_types")
    if pt is not None:
        if not isinstance(pt, list):
            _warn("rule_curator.precious_types must be a list")
        else:
            for t in pt:
                if t not in MEMORY_TYPES:
                    _warn(f"rule_curator.precious_types: unknown type {t!r}")

    # llm_curator
    lc = cfg.get("llm_curator", {})
    if "sim_threshold" in lc:
        val = lc["sim_threshold"]
        if not (isinstance(val, (int, float)) and 0 <= val <= 1):
            _warn(f"llm_curator.sim_threshold must be a 0-1 float (got {val!r})")
    for key in ("batch_size", "importance_limit", "split_content_threshold",
                "review_cooldown_seconds", "reviewed_ids_max_age_seconds"):
        if key in lc:
            _pos_int("llm_curator", key, lc[key])

    # governance
    gc = cfg.get("governance", {})
    for key in ("review_confidence_threshold", "high_importance_threshold",
                "auto_approve_confidence", "auto_approve_low_risk_confidence"):
        if key in gc:
            val = gc[key]
            if not (isinstance(val, (int, float)) and 0 <= val <= 1):
                _warn(f"governance.{key} must be a 0-1 float (got {val!r})")
    review_ct = gc.get("review_confidence_threshold", 0.55)
    auto_ct = gc.get("auto_approve_confidence", 0.90)
    if isinstance(review_ct, (int, float)) and isinstance(auto_ct, (int, float)) and review_ct >= auto_ct:
        _warn("governance: review_confidence_threshold should be less than auto_approve_confidence")
    gpt = gc.get("precious_types")
    if gpt is not None:
        if not isinstance(gpt, list):
            _warn("governance.precious_types must be a list")
        else:
            for t in gpt:
                if t not in MEMORY_TYPES:
                    _warn(f"governance.precious_types: unknown type {t!r}")

    # extraction_strategy
    es = cfg.get("extraction_strategy", {})
    for key in ("min_importance", "default_confidence", "default_importance"):
        if key in es:
            val = es[key]
            if not (isinstance(val, (int, float)) and 0 <= val <= 1):
                _warn(f"extraction_strategy.{key} must be a 0-1 float (got {val!r})")
    if "chinese_detection_ratio" in es:
        val = es["chinese_detection_ratio"]
        if not (isinstance(val, (int, float)) and 0.05 <= val <= 0.50):
            _warn(f"extraction_strategy.chinese_detection_ratio must be 0.05-0.50 (got {val!r})")
    for key in ("skip_threshold", "update_threshold", "link_threshold"):
        if key in es:
            val = es[key]
            if not (isinstance(val, (int, float)) and 0 < val < 1):
                _warn(f"extraction_strategy.{key} must be a 0-1 float (got {val!r})")
    skip_t = es.get("skip_threshold", 0.92)
    update_t = es.get("update_threshold", 0.78)
    link_t = es.get("link_threshold", 0.55)
    if (isinstance(skip_t, (int, float)) and isinstance(update_t, (int, float))
            and isinstance(link_t, (int, float)) and not (skip_t > update_t > link_t)):
        _warn("extraction_strategy: skip_threshold must be > update_threshold > link_threshold")
    for key in ("context_sample_length", "context_memory_limit", "dedup_search_limit",
                "max_related_ids", "title_max_length"):
        if key in es:
            _pos_int("extraction_strategy", key, es[key])
    if "default_memory_type" in es and es["default_memory_type"] not in MEMORY_TYPES:
        _warn(f"extraction_strategy.default_memory_type={es['default_memory_type']!r} unknown")
    if "default_status" in es and es["default_status"] not in {"candidate", "active"}:
        _warn(f"extraction_strategy.default_status must be 'candidate' or 'active' (got {es['default_status']!r})")
    if "default_decay_policy" in es and es["default_decay_policy"] not in {"review", "standard", "slow", "never"}:
        _warn(f"extraction_strategy.default_decay_policy={es['default_decay_policy']!r} unknown")
    if "default_scope" in es and es["default_scope"] not in {"global", "session", "agent"}:
        _warn(f"extraction_strategy.default_scope={es['default_scope']!r} unknown")

    # user_profile
    up = cfg.get("user_profile", {})
    if not isinstance(up.get("enabled", False), bool):
        _warn(f"user_profile.enabled must be a bool (got {up.get('enabled')!r})")
    for key in ("extract_limit", "max_snapshot_chars"):
        if key in up:
            _pos_int("user_profile", key, up[key])
    min_conf = up.get("min_confidence", 0.6)
    if not (isinstance(min_conf, (int, float)) and 0 <= min_conf <= 1):
        _warn(f"user_profile.min_confidence must be a 0-1 float (got {min_conf!r})")
    schema = up.get("schema")
    if schema is not None:
        if not isinstance(schema, list):
            _warn("user_profile.schema must be a list")
        else:
            seen_names: set[str] = set()
            for entry in schema:
                if not isinstance(entry, dict) or not str(entry.get("name", "")).strip():
                    _warn(f"user_profile.schema entries must be dicts with a non-empty 'name' (got {entry!r})")
                    continue
                name = str(entry["name"]).strip()
                if name in seen_names:
                    _warn(f"user_profile.schema: duplicate attribute name {name!r} (阿里云建议属性名语义唯一)")
                seen_names.add(name)

    # subject_context
    sc = cfg.get("subject_context", {})
    if not isinstance(sc.get("enabled", False), bool):
        _warn(f"subject_context.enabled must be a bool (got {sc.get('enabled')!r})")
    projects = sc.get("projects", [])
    if not isinstance(projects, list):
        _warn("subject_context.projects must be a list")
    else:
        seen_names: set[str] = set()
        for entry in projects:
            if not isinstance(entry, dict) or not str(entry.get("name", "")).strip():
                _warn(f"subject_context.projects entries must be dicts with a non-empty 'name' (got {entry!r})")
                continue
            name = str(entry["name"]).strip()
            if name in seen_names:
                _warn(f"subject_context.projects: duplicate project name {name!r}")
            seen_names.add(name)
            paths = entry.get("paths", [])
            if paths and not isinstance(paths, list):
                _warn(f"subject_context.projects[{name}].paths must be a list")

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
