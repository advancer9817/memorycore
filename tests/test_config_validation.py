"""Tests for config schema validation."""
import pytest
from local_memory_mcp.models import validate_config, DEFAULT_CONFIG, load_config


def test_default_config_is_valid():
    """DEFAULT_CONFIG must pass validation with no warnings."""
    warnings = validate_config(DEFAULT_CONFIG)
    assert warnings == [], f"Unexpected warnings: {warnings}"


def test_invalid_embedding_provider():
    cfg = {"embedding": {"provider": "mem0", "dim": 768, "timeout": 30}}
    warns = validate_config(cfg)
    assert any("provider" in w for w in warns)


def test_invalid_dim():
    cfg = {"embedding": {"provider": "ollama", "dim": -1, "timeout": 30}}
    warns = validate_config(cfg)
    assert any("dim" in w for w in warns)


def test_invalid_ollama_url():
    cfg = {"embedding": {"provider": "ollama", "dim": 768, "timeout": 30,
                          "ollama_url": "localhost:11434"}}
    warns = validate_config(cfg)
    assert any("ollama_url" in w for w in warns)


def test_valid_ollama_url():
    cfg = {"embedding": {"provider": "ollama", "dim": 768, "timeout": 30,
                          "ollama_url": "http://127.0.0.1:11434"}}
    warns = validate_config(cfg)
    assert not any("ollama_url" in w for w in warns)


def test_qdrant_no_url_no_path():
    cfg = {"qdrant": {"url": "", "path": ""}}
    warns = validate_config(cfg)
    assert any("qdrant" in w and "url" in w and "path" in w for w in warns)


def test_qdrant_bad_url_scheme():
    cfg = {"qdrant": {"url": "grpc://localhost:6333"}}
    warns = validate_config(cfg)
    assert any("qdrant.url" in w for w in warns)


def test_qdrant_good_url():
    cfg = {"qdrant": {"url": "http://127.0.0.1:6333"}}
    warns = validate_config(cfg)
    assert not any("qdrant.url" in w for w in warns)


def test_context_pack_bad_budget():
    cfg = {"context_pack": {"default_token_budget": 0, "max_records_per_group": 6}}
    warns = validate_config(cfg)
    assert any("default_token_budget" in w for w in warns)


def test_backend_unknown_primary():
    cfg = {"backend": {"primary": "postgres"}}
    warns = validate_config(cfg)
    assert any("backend.primary" in w for w in warns)


def test_backend_sqlite_ok():
    cfg = {"backend": {"primary": "sqlite"}}
    warns = validate_config(cfg)
    assert not any("backend" in w for w in warns)


def test_empty_config_produces_some_warnings():
    """Completely empty config should produce at least embedding warnings."""
    warns = validate_config({})
    # dim=None → must warn
    assert len(warns) > 0


def test_load_config_result_passes_validation():
    """load_config() from disk should produce no warnings (config.yaml is valid)."""
    cfg = load_config()
    warns = validate_config(cfg)
    # config.yaml 的 mem0.enabled=true 等过时字段不影响校验（只校验已知 section）
    assert warns == [], f"load_config() produced validation warnings: {warns}"
