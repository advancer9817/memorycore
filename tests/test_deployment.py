from pathlib import Path

import local_memory_mcp as lm

ROOT = Path(__file__).resolve().parents[1]


def test_checked_in_config_is_portable():
    text = (ROOT / "config.yaml").read_text(encoding="utf-8")

    assert "/home/advancer" not in text
    assert "e-pengyang" not in text
    assert "C:\\" not in text
    assert "primary: sqlite" in text


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


def test_start_script_installs_full_extras_by_default():
    text = (ROOT / "start.sh").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    deploy = (ROOT / "scripts" / "deploy.sh").read_text(encoding="utf-8")

    assert 'pip install -q -e ".[all]"' in text
    assert 'pip install -q -e ".[extraction]"' not in text
    assert "pip install -e .[all]" in readme
    assert 'pip install -e ".[all]"' in deploy


def test_deploy_bootstraps_runtime_dependencies_by_default():
    deploy = (ROOT / "scripts" / "deploy.sh").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    docs = (ROOT / "docs" / "deployment.md").read_text(encoding="utf-8")

    assert "BOOTSTRAP_DEPS=1" in deploy
    assert "WITH_OLLAMA=1" in deploy
    assert "ASSUME_YES=1" in deploy
    assert "--no-bootstrap-deps" in deploy
    assert "--no-ollama" in deploy
    assert "--no-assume-yes" in deploy
    assert 'have docker || missing+=(docker.io)' in deploy
    assert "curl -fsSL https://ollama.com/install.sh | sh" in deploy
    assert 'docker pull "$QDRANT_IMAGE"' in deploy
    assert "补齐系统依赖" in readme and "默认" in readme
    assert "`--no-ollama`" in docs


def test_start_script_rebuilds_drifted_venv():
    text = (ROOT / "start.sh").read_text(encoding="utf-8")

    assert "venv_needs_rebuild()" in text
    assert 'for script in "$venv/bin/pip" "$venv/bin/pytest"; do' in text
    assert '"/.venv/bin/python"*' in text
    assert "Detected venv path drift" in text
    assert 'rm -rf "$VENV"' in text
    assert 'Rebuilding venv because existing scripts point outside this checkout' in text


def test_docker_compose_enables_qdrant_and_full_extras():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert 'INSTALL_EXTRAS: "all"' in compose
    assert "qdrant:" in compose
    assert "image: qdrant/qdrant:latest" in compose
    assert "qdrant_data:" in compose
    assert "QDRANT_URL: http://qdrant:6333" in compose
    assert "depends_on:" in compose and "- qdrant" in compose

    assert "ARG INSTALL_EXTRAS=all" in dockerfile
    assert 'pip install -e ".[${INSTALL_EXTRAS}]"' in dockerfile
    assert "QDRANT_URL=http://qdrant:6333" in dockerfile
    assert "LOCAL_MEMORY_EMBEDDING_PROVIDER=hashing" in dockerfile


def test_hook_setup_registers_prompt_context_injection():
    setup = (ROOT / "scripts" / "setup-hooks.sh").read_text(encoding="utf-8")
    connect_agents = (ROOT / "scripts" / "connect_agents.py").read_text(encoding="utf-8")
    context_hook = (ROOT / "scripts" / "hooks" / "lmmcp-context.sh").read_text(encoding="utf-8")

    assert 'add_hook(hooks, "UserPromptSubmit", f"LMMCP_AGENT_ID=claude bash {lmmcp_context}", 5)' in setup
    assert 'add_hook(codex_hook_root, "UserPromptSubmit", f"LMMCP_AGENT_ID=codex bash {lmmcp_context}", 5)' in setup
    assert "context_command = f\"LMMCP_AGENT_ID=claude bash {HOOK_LMMCP_CONTEXT}\"" in connect_agents
    assert "context_command = f\"LMMCP_AGENT_ID=codex bash {HOOK_LMMCP_CONTEXT}\"" in connect_agents
    assert '"project_path": sys.argv[3]' in context_hook
    assert 'or extra.get("user_message")' in context_hook
    assert 'if event == "pre_llm_call":' in context_hook
    assert 'payload = {"context": context}' in context_hook
    assert 'hook_event_name = "BeforeAgent" if event == "BeforeAgent" else "UserPromptSubmit"' in context_hook
    assert 'if isinstance(used_ids, list) and not used_ids:' in context_hook


def test_session_start_hook_registers_presence_and_capabilities():
    hook = (ROOT / "scripts" / "hooks" / "session-start.sh").read_text(encoding="utf-8")

    assert "ensure_lmmcp_running 2>/dev/null || true" in hook
    assert "agent_presence_update" in hook
    assert "agent_capability_register" in hook
    assert "Mcp-Session-Id" in hook
    assert "coding,implementation,tests,debugging,repo" in hook
    assert "reasoning,review,documentation,coding" in hook
    assert "curl -sS --max-time" in hook
    assert "|| true" in hook
    assert hook.rstrip().endswith("exit 0")


def test_hook_setup_registers_session_start_presence_hook():
    setup = (ROOT / "scripts" / "setup-hooks.sh").read_text(encoding="utf-8")
    connect_agents = (ROOT / "scripts" / "connect_agents.py").read_text(encoding="utf-8")

    assert 'add_hook(hooks, "SessionStart", f"LMMCP_AGENT_ID=claude bash {lmmcp_session_start}", 5)' in setup
    assert 'add_hook(codex_hook_root, "SessionStart", f"LMMCP_AGENT_ID=codex bash {lmmcp_session_start}", 5)' in setup
    assert "start_command = f\"LMMCP_AGENT_ID=claude bash {HOOK_SESSION_START}\"" in connect_agents
    assert "start_command = f\"LMMCP_AGENT_ID=codex bash {HOOK_SESSION_START}\"" in connect_agents
    assert "hooks[\"session_start\"] = f\"LMMCP_AGENT_ID=opencode bash {HOOK_SESSION_START}\"" in connect_agents


def test_gemini_hooks_register_context_and_session_end_ingest():
    setup = (ROOT / "scripts" / "setup-hooks.sh").read_text(encoding="utf-8")
    connect_agents = (ROOT / "scripts" / "connect_agents.py").read_text(encoding="utf-8")
    ingest_hook = (ROOT / "scripts" / "hooks" / "lmmcp-ingest.py").read_text(encoding="utf-8")

    assert 'GEMINI_SETTINGS="${GEMINI_SETTINGS:-$HOME/.gemini/settings.json}"' in setup
    assert 'gemini_servers["local_memory"] = {"httpUrl": endpoint, "timeout": 60000}' in setup
    assert 'add_hook(gemini_hooks, "BeforeAgent", f"LMMCP_AGENT_ID=gemini bash {lmmcp_context}", 5000)' in setup
    assert 'add_hook(gemini_hooks, "SessionEnd", f"python3 {lmmcp_ingest} --agent gemini --background", 30000)' in setup

    assert "def register_hooks_gemini" in connect_agents
    assert '"BeforeAgent", CODEX_LMMCP_CONTEXT_FRAGMENTS' in connect_agents
    assert 'context_command = f"LMMCP_AGENT_ID=gemini bash {HOOK_LMMCP_CONTEXT}"' in connect_agents
    assert 'end_command = f"python3 {HOOK_LMMCP_INGEST} --agent gemini --background"' in connect_agents
    assert 'register_hooks_gemini(detected["gemini"], backup_dir, dry_run)' in connect_agents

    assert "def _payload_transcript_path" in ingest_hook
    assert "transcript_path" in ingest_hook
    assert "def _find_gemini_transcript" in ingest_hook


def test_opencode_session_end_uses_background_ingest():
    connect_agents = (ROOT / "scripts" / "connect_agents.py").read_text(encoding="utf-8")
    ingest_hook = (ROOT / "scripts" / "hooks" / "lmmcp-ingest.py").read_text(encoding="utf-8")

    assert 'end_command = f"python3 {HOOK_LMMCP_INGEST} --agent opencode --background"' in connect_agents
    assert "def _extract_opencode_from_db" in ingest_hook
    assert "OPENCODE_DB" in ingest_hook
    assert "GEMINI_SESSION_FILE" in ingest_hook


def test_hermes_hooks_register_pre_llm_context_injection():
    setup = (ROOT / "scripts" / "setup-hooks.sh").read_text(encoding="utf-8")
    connect_agents = (ROOT / "scripts" / "connect_agents.py").read_text(encoding="utf-8")

    assert 'HERMES_CONTEXT_DEST="$HERMES_HOOK_DIR/lmmcp-context.sh"' in setup
    assert 'cp "$HERMES_CONTEXT_SRC" "$HERMES_CONTEXT_DEST"' in setup
    assert 'context_command = f"LMMCP_AGENT_ID=hermes bash {hermes_context_dest}"' in setup
    assert 'hooks_cfg["pre_llm_call"] = [{"command": context_command, "timeout": 5}]' in setup
    assert '"event": "pre_llm_call"' in setup
    assert '--agent hermes --background' in setup

    assert "hermes_context_hook = hermes_hook_dir / \"lmmcp-context.sh\"" in connect_agents
    assert 'context_command = f"LMMCP_AGENT_ID=hermes bash {hermes_context_hook}"' in connect_agents
    assert '"pre_llm_call",' in connect_agents
    assert '"on_session_end", ingest_command' in connect_agents
    assert '--agent hermes --background' in connect_agents


def test_opencode_plugin_registers_pre_llm_context_injection():
    connect_agents = (ROOT / "scripts" / "connect_agents.py").read_text(encoding="utf-8")
    plugin = (ROOT / "scripts" / "hooks" / "opencode-lmmcp-plugin.js").read_text(encoding="utf-8")

    assert 'HOOK_OPENCODE_PLUGIN = str(HOOKS_DIR / "opencode-lmmcp-plugin.js")' in connect_agents
    assert 'plugin_entry = [HOOK_OPENCODE_PLUGIN, {"agent": "opencode", "url": endpoint}]' in connect_agents
    assert 'register_hooks_opencode(detected["opencode"], endpoint, backup_dir, dry_run)' in connect_agents
    assert '"experimental.chat.system.transform"' in plugin
    assert 'name: "memory_context"' in plugin
    assert "client.session.messages" in plugin
    assert "Array.isArray(inner.used_ids) && inner.used_ids.length === 0" in plugin
    assert "output.system.push" in plugin


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
