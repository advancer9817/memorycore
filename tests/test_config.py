from pathlib import Path

import memorycore as lm


def test_default_config_path_is_project_config():
    assert lm.config_path() == Path(lm.DEFAULT_ROOT) / "config.yaml"


def test_load_config_reads_nested_yaml_scalars(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        """
backend:
  primary: sqlite
  fallback: sqlite
qdrant:
  url: http://127.0.0.1:6333
  collection: agent_memory
embedding:
  provider: ollama
  model: nomic-embed-text
  dim: 768
context_pack:
  include_stale_warnings: true
  max_records_per_group: 6
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("LOCAL_MEMORY_CONFIG", str(cfg_path))

    config = lm.load_config()

    assert config["backend"]["primary"] == "sqlite"
    assert config["embedding"]["dim"] == 768
    assert config["context_pack"]["include_stale_warnings"] is True


def test_load_config_merges_defaults_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_MEMORY_CONFIG", str(tmp_path / "missing.yaml"))

    config = lm.load_config()

    assert config["backend"]["primary"] == "sqlite"
    assert config["backend"]["fallback"] == "sqlite"
    assert config["embedding"]["provider"] == "auto"
    assert config["embedding"]["api_url"] == ""
    assert config["embedding"]["dim"] == 768
    assert config["qdrant"]["url"] == "http://127.0.0.1:6333"
