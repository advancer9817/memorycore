# Deployment and reuse guide

This project is reusable on another project computer, but not as a raw folder copy only. A target machine needs a compatible Python runtime, project-local dependencies, an initialized SQLite database, and MCP client entries that point at the target machine's paths.

## Reuse verdict

Portable with initialization.

The code now avoids hardcoding the original Windows/WSL username in the default `config.yaml`. Runtime paths should be derived from the chosen install root and target user.

## Target machine prerequisites

- Linux/macOS/WSL shell with `bash`.
- Python 3.11+.
- `python3.11-venv` or equivalent venv support.
- Network access to PyPI for first install, unless packages are pre-cached.
- Optional but recommended: Ollama with `nomic-embed-text` pulled.

If Ollama is unavailable, use the hashing fallback until local embeddings are installed:

```bash
export LOCAL_MEMORY_EMBEDDING_PROVIDER=hashing
export LOCAL_MEMORY_EMBEDDING_DIM=384
```

## One-command initialization

From a clone or copied checkout:

```bash
cd /path/to/local-memory-mcp
scripts/init_local_memory.sh
```

Default runtime root:

```bash
the current local-memory-mcp checkout
```

Custom root:

```bash
scripts/init_local_memory.sh --root /opt/local-memory-mcp
```

Regenerate config for the current target user/root:

```bash
scripts/init_local_memory.sh --force-config
```

Skip dependency installation when a venv is already prepared:

```bash
scripts/init_local_memory.sh --skip-install
```

## What the script does

1. Creates the runtime root.
2. Copies project files when the source checkout differs from the runtime root.
3. Creates `.venv` with Python 3.11+.
4. Installs `requirements.txt`.
5. Writes `config.yaml` if missing or `--force-config` is passed.
6. Initializes `memory.sqlite3`.
7. Renders `dashboard.html`.
8. Prints MCP command snippets.

The script does not edit Hermes/Codex/Claude Code config files automatically. This is intentional to avoid overwriting target-machine agent settings.

## MCP command

All clients should point to the target root and venv:

```bash
/path/to/local-memory-mcp/.venv/bin/python -m local_memory_mcp serve --port 8318
```

Hermes as a client:

```bash
hermes mcp add local_memory --url "http://127.0.0.1:8318/mcp"
hermes mcp test local_memory
```

For Codex, Claude Code, Gemini, and OpenCode, configure the same HTTP endpoint:
`http://127.0.0.1:8318/mcp`.

## Configuration knobs

- `LOCAL_MEMORY_ROOT`: default install/runtime root used by the init script.
- `LOCAL_MEMORY_CONFIG`: override config file path.
- `LOCAL_MEMORY_DB`: override SQLite database path.
- `LOCAL_MEMORY_USER_ID`: target OpenMemory user id written by the init script.
- `OPENMEMORY_URL`: OpenMemory endpoint written by the init script.
- `QDRANT_URL`: Qdrant endpoint written by the init script.
- `QDRANT_COLLECTION`: Qdrant collection name written by the init script.
- `LOCAL_MEMORY_EMBEDDING_PROVIDER`: `ollama` or `hashing`.
- `LOCAL_MEMORY_EMBEDDING_MODEL`: e.g. `nomic-embed-text`.
- `LOCAL_MEMORY_EMBEDDING_DIM`: `768` for nomic-embed-text, `384` for hashing fallback.
- `LOCAL_MEMORY_OLLAMA_URL`: Ollama endpoint.

## Deployment risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Python < 3.11 | `numpy==2.4.4` install fails | Install Python 3.11+ before running init script |
| Ollama missing | semantic-index fails for provider `ollama` | Install Ollama + pull `nomic-embed-text`, or use hashing fallback |
| Paths copied from another user | MCP clients point to nonexistent files | Run `scripts/init_local_memory.sh --force-config` on the target computer and update MCP command paths |
| OpenMemory/Qdrant down | future adapter backends unavailable | Keep `backend.primary=sqlite` until services are installed and backend abstraction is complete |
| Copying live SQLite files | database locks or stale data | Export/import intentionally; do not blindly overwrite a live `memory.sqlite3` |

## Post-deploy verification

```bash
MEM_ROOT="${LOCAL_MEMORY_ROOT:-/path/to/local-memory-mcp}"
PY="$MEM_ROOT/.venv/bin/python"

"$PY" -m local_memory_mcp init
"$PY" -m local_memory_mcp semantic-status
"$PY" -m local_memory_mcp curator --summary-only
"$PY" -m pytest -q
```

Expected minimum result:

- DB path prints successfully.
- pytest passes.
- `semantic-status` reports either Ollama availability or a clear fallback/error.
- MCP client can start the stdio server.
