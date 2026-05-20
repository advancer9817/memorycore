from pathlib import Path

import local_memory_mcp as lm

ROOT = Path(__file__).resolve().parents[1]


def test_checked_in_config_is_portable():
    text = (ROOT / "config.yaml").read_text(encoding="utf-8")

    assert "/home/advancer" not in text
    assert "e-pengyang" not in text
    assert "C:\\" not in text
    assert "primary: sqlite" in text
    assert "memory_ops.sqlite3" in text


def test_init_script_exists_and_documents_safe_behavior():
    script = ROOT / "scripts" / "init_local_memory.sh"
    text = script.read_text(encoding="utf-8")

    assert script.exists()
    assert "set -euo pipefail" in text
    assert "--force-config" in text
    assert "python3.11" in text
    assert "rsync" in text and "tar" in text
    assert "http://127.0.0.1:8318/mcp" in text
    assert "Hermes/Codex/Claude Code/Gemini/OpenCode" in text
    assert "does not" in text.lower() and "automatically" in text.lower()


def test_deployment_doc_mentions_target_machine_verification():
    text = (ROOT / "docs" / "deployment.md").read_text(encoding="utf-8")

    assert "Portable with initialization" in text
    assert "Python 3.11+" in text
    assert "LOCAL_MEMORY_EMBEDDING_PROVIDER=hashing" in text
    assert "Post-deploy verification" in text


def test_gitignore_excludes_local_runtime_state():
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "memory.sqlite3" in text
    assert ".venv/" in text
    assert "backups/" in text
    assert "dashboard.html" in text
    assert "__pycache__/" in text


def test_load_config_returns_dict_without_openmemory(tmp_path, monkeypatch):
    """openmemory backend was removed; config should not contain that key."""
    monkeypatch.setenv("LOCAL_MEMORY_CONFIG", str(tmp_path / "missing.yaml"))

    config = lm.load_config()

    assert "openmemory" not in config
