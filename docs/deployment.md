# Deployment and reuse guide

## Reuse verdict

Portable with initialization.

This project supports one-command deployment on Linux/macOS/WSL. The deployment
script is designed to be portable: it derives paths from the chosen install root
and exposes ports, paths, Qdrant image/storage, and verification behavior as
command-line options or environment variables.

## Quick start

From a clone or copied checkout:

```bash
cd /path/to/local-memory-mcp
scripts/deploy.sh
```

The default deployment:

1. Installs missing host packages where supported; use `--no-bootstrap-deps` to disable.
2. Creates `.venv` with Python 3.11+.
3. Installs `requirements.txt`.
4. Writes `config.yaml` if missing.
5. Initializes `memory.sqlite3`.
6. Renders `dashboard.html`.
7. Ensures Ollama is installed/running and pulls the embedding model; use `--no-ollama` to rely on fallback embeddings.
8. Installs user systemd services:
   - `qdrant.service`
   - `lmmcp.service`
   - `lmmcp-curator.timer` / `lmmcp-curator.service`
9. Pulls the Qdrant Docker image unless `--no-pull-images` is used.
10. Starts Qdrant and lmmcp.
11. Runs curator summary and health checks.
12. Runs pytest unless `--skip-tests` is used.

Default unified endpoint layout:

```text
http://127.0.0.1:8318/        frontend control console
http://127.0.0.1:8318/api/*   frontend REST API
http://127.0.0.1:8318/mcp     MCP endpoint
http://127.0.0.1:8318/health  health check
http://127.0.0.1:8318/metrics metrics
```

The default bind host is loopback-only. For remote access, provide a token:

```bash
LOCAL_MEMORY_FRONTEND_TOKEN='change-me' .venv/bin/python -m local_memory_mcp serve --host 0.0.0.0 --port 8318
```

MCP clients should continue using:

```text
http://127.0.0.1:8318/mcp
```

## Common commands

```bash
# Full deployment, preserving existing config.yaml
scripts/deploy.sh

# Regenerate config.yaml for this machine/root
scripts/deploy.sh --force-config

# Install into another root
scripts/deploy.sh --root /opt/local-memory-mcp

# Initialize only; do not install services
scripts/deploy.sh --no-systemd

# Use an externally managed Qdrant
QDRANT_URL=http://127.0.0.1:6333 scripts/deploy.sh --no-qdrant

# Disable host dependency bootstrap or Ollama on constrained machines
scripts/deploy.sh --no-bootstrap-deps
scripts/deploy.sh --no-ollama

# Skip tests on constrained machines
scripts/deploy.sh --skip-tests

# Preview resolved paths and ports without changing anything
scripts/deploy.sh --dry-run
```

Backward-compatible conservative initialization is still available:

```bash
scripts/init_local_memory.sh
```

`init_local_memory.sh` now delegates to `scripts/deploy.sh --no-systemd`.

## Docker Compose

For container-only deployment, `docker-compose.yml` starts both lmmcp and
Qdrant with persistent volumes:

```bash
docker compose up --build
```

The lmmcp image installs `.[all]` by default so Qdrant and extraction
dependencies are present without pulling the large sentence-transformers stack. Compose defaults
`LOCAL_MEMORY_EMBEDDING_PROVIDER=hashing` because the Ollama daemon is usually
outside the container; override the environment if you provide an Ollama
endpoint reachable from the container network.

## Prerequisites

Minimum:

- Linux/macOS/WSL shell with `bash`.
- Python 3.11+ and venv support.
- Network access to PyPI for first dependency install, unless packages are cached.

For the default service deployment:

- User-level systemd session.
- Docker available to the current user.
- Network access to pull `qdrant/qdrant` if the image is not local.

Optional but recommended:

- Ollama with `nomic-embed-text` pulled.
- `sentence-transformers` extra and model cache for local fallback when Ollama is offline.

If Ollama is unavailable, lmmcp tries the configured sentence-transformers
fallback first, then falls back to deterministic hashing embeddings if the local
model or dependency is unavailable. SQLite/FTS/context pack still work. To force
the fully portable fallback explicitly:

```bash
export LOCAL_MEMORY_EMBEDDING_PROVIDER=hashing
export LOCAL_MEMORY_EMBEDDING_DIM=384
```

Install the local sentence-transformers fallback only when you explicitly want
that heavier offline embedding path:

```bash
.venv/bin/python -m pip install -e .[embedding]
# or all optional features including the heavy embedding fallback:
.venv/bin/python -m pip install -e .[full]
```

## Configuration knobs

CLI options have priority over environment defaults.

| Option / env | Default | Purpose |
|---|---|---|
| `--root` / `LOCAL_MEMORY_ROOT` | current checkout | Install/runtime root |
| `--host` / `LMMCP_HOST` | `127.0.0.1` | lmmcp bind host |
| `--port` / `LMMCP_PORT` | `8318` | lmmcp HTTP port |
| `--db` / `LOCAL_MEMORY_DB` | `$ROOT/memory.sqlite3` | SQLite DB path |
| `--config` / `LOCAL_MEMORY_CONFIG` | `$ROOT/config.yaml` | Config file path |
| `--bootstrap-deps` / `--no-bootstrap-deps` / `LMMCP_BOOTSTRAP_DEPS=0/1` | on | Install missing host packages with apt/dnf/yum/brew when possible |
| `--with-ollama` / `--no-ollama` / `LMMCP_WITH_OLLAMA=0/1` | on | Ensure Ollama is present/reachable and pull the embedding model |
| `--no-pull-images` / `LMMCP_PULL_IMAGES=0` | pull enabled | Skip Docker image pre-pull |
| `--no-pull-models` / `LMMCP_PULL_MODELS=0` | pull enabled | Skip Ollama model pull |
| `--assume-yes` / `--no-assume-yes` / `LMMCP_ASSUME_YES=0/1` | on | Pass non-interactive yes flags to supported package managers |
| `--qdrant-image` / `QDRANT_IMAGE` | `qdrant/qdrant` | Docker image |
| `--qdrant-http-port` / `QDRANT_HTTP_PORT` | `6333` | Qdrant HTTP host port |
| `--qdrant-grpc-port` / `QDRANT_GRPC_PORT` | `6334` | Qdrant gRPC host port |
| `--qdrant-storage` / `QDRANT_STORAGE` | `~/.agent-memory/qdrant_storage` | Persistent Qdrant storage |
| `QDRANT_URL` | `http://127.0.0.1:$QDRANT_HTTP_PORT` | Qdrant URL written to config |
| `QDRANT_COLLECTION` | `agent_memory` | Qdrant collection |
| `LOCAL_MEMORY_EMBEDDING_PROVIDER` | `ollama` | Embedding provider |
| `LOCAL_MEMORY_EMBEDDING_MODEL` | `nomic-embed-text` | Embedding model |
| `LOCAL_MEMORY_EMBEDDING_FALLBACK_PROVIDER` | `sentence-transformers` | Embedding fallback after Ollama failure |
| `LOCAL_MEMORY_SENTENCE_TRANSFORMERS_MODEL` | `sentence-transformers/all-mpnet-base-v2` | sentence-transformers fallback model |
| `LOCAL_MEMORY_EMBEDDING_DIM` | `768` | Embedding dimension |
| `LOCAL_MEMORY_OLLAMA_URL` | `http://127.0.0.1:11434` | Ollama URL |
| `--curator-apply` / `LOCAL_MEMORY_CURATOR_APPLY` | `1` | Apply low-risk stale/archive transitions |

## Installed systemd units

`deploy.sh` writes user units to `~/.config/systemd/user/`.

- `qdrant.service`: runs Docker `qdrant/qdrant` with persistent storage.
- `lmmcp.service`: starts the HTTP MCP server and has `Wants/After=qdrant.service`.
- `lmmcp-curator.timer`: runs hourly.
- `lmmcp-curator.service`: runs `run_curator.sh` from the deployed root with
  `LOCAL_MEMORY_CURATOR_APPLY=1` by default.

Useful commands:

```bash
systemctl --user status qdrant.service lmmcp.service lmmcp-curator.timer
journalctl --user -u lmmcp.service -f
tail -80 /path/to/local-memory-mcp/logs/curator.log
```

## MCP client configuration

All clients should point to the same HTTP endpoint:

```text
http://127.0.0.1:8318/mcp
```

Hermes:

```yaml
mcp_servers:
  local_memory:
    enabled: true
    type: http
    url: http://127.0.0.1:8318/mcp
```

Codex `~/.codex/config.toml`:

```toml
[mcp_servers.local_memory]
type = "http"
url = "http://127.0.0.1:8318/mcp"
```

Claude Code user config:

```json
"mcpServers": {
  "local_memory": {
    "type": "http",
    "url": "http://127.0.0.1:8318/mcp"
  }
}
```

## Post-deploy verification

```bash
curl -fsS http://127.0.0.1:6333/collections
systemctl --user is-active qdrant.service lmmcp.service lmmcp-curator.timer
PY=/path/to/local-memory-mcp/.venv/bin/python
$PY -m pytest tests -q
```

You can also call the MCP tool `memory_vector_status`; expected result after
Qdrant starts is `available: true`.

## Deployment risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Python < 3.11 | dependency install fails | Install Python 3.11+ before running deploy; on apt systems `--bootstrap-deps` also installs venv support |
| Docker unavailable | Qdrant service cannot be installed | Default deploy tries to install Docker where supported; otherwise install Docker manually, or run with `--no-qdrant` and provide `QDRANT_URL` |
| Docker image missing/offline | Qdrant startup fails | Default deploy pre-pulls `qdrant/qdrant`; pre-seed the image for offline installs or use `--no-pull-images` only when already cached |
| User systemd unavailable | services cannot be installed | Run with `--no-systemd`, or install as a platform-specific service manually |
| Port conflict | Qdrant/lmmcp health checks fail | Override `--port`, `--qdrant-http-port`, or `--qdrant-grpc-port` |
| Copying live SQLite files | database locks or stale data | Use the generated DB or export/import intentionally; do not overwrite a live DB |
| Ollama unavailable | embedding quality degrades | Default deploy tries to install/start Ollama and pull the model; use `--no-ollama` only when relying on fallback embeddings intentionally |
