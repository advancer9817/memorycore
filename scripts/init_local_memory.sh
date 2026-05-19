#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/init_local_memory.sh [--root PATH] [--force-config] [--skip-install]

Initialize local-memory-mcp on a new project computer.

Options:
  --root PATH       Install/runtime root. Default: $LOCAL_MEMORY_ROOT or
                    $HOME/.agent-memory/local-memory-mcp
  --force-config   Rewrite config.yaml even if it already exists.
  --skip-install   Do not run pip install; useful when dependencies are already installed.
  -h, --help       Show this help.

The script is intentionally conservative: it creates the venv, initializes the
SQLite DB, renders dashboard.html, and prints MCP config snippets. It does not
edit Hermes/Codex/Claude configs automatically.
USAGE
}

ROOT="${LOCAL_MEMORY_ROOT:-$HOME/.agent-memory/local-memory-mcp}"
FORCE_CONFIG=0
SKIP_INSTALL=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --root)
      ROOT="${2:?--root requires a path}"
      shift 2
      ;;
    --force-config)
      FORCE_CONFIG=1
      shift
      ;;
    --skip-install)
      SKIP_INSTALL=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
mkdir -p "$ROOT"
ROOT="$(cd "$ROOT" && pwd -P)"

if [ "$SOURCE_DIR" != "$ROOT" ]; then
  echo "[copy] Syncing project files to $ROOT"
  if command -v rsync >/dev/null 2>&1; then
    rsync -a \
      --exclude '.git/' \
      --exclude '.venv/' \
      --exclude '__pycache__/' \
      --exclude 'tests/__pycache__/' \
      --exclude 'memory.sqlite3*' \
      --exclude 'memory_ops.sqlite3*' \
      "$SOURCE_DIR/" "$ROOT/"
  else
    (cd "$SOURCE_DIR" && tar \
      --exclude='.git' \
      --exclude='.venv' \
      --exclude='__pycache__' \
      --exclude='tests/__pycache__' \
      --exclude='memory.sqlite3*' \
      --exclude='memory_ops.sqlite3*' \
      -cf - .) | (cd "$ROOT" && tar -xf -)
  fi
fi

cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-}"
if [ -z "$PYTHON_BIN" ]; then
  if command -v python3.11 >/dev/null 2>&1; then
    PYTHON_BIN=python3.11
  else
    PYTHON_BIN=python3
  fi
fi

"$PYTHON_BIN" - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit("Python 3.11+ is required because requirements.txt pins modern packages")
PY

if [ ! -d .venv ]; then
  echo "[venv] Creating .venv with $PYTHON_BIN"
  "$PYTHON_BIN" -m venv .venv
fi

PY="$ROOT/.venv/bin/python"
if [ "$SKIP_INSTALL" -eq 0 ]; then
  echo "[deps] Installing requirements"
  "$PY" -m pip install -U pip
  "$PY" -m pip install -r requirements.txt
fi

USER_ID="${LOCAL_MEMORY_USER_ID:-$(id -un 2>/dev/null || whoami 2>/dev/null || echo local-user)}"
CONFIG_PATH="$ROOT/config.yaml"
if [ ! -f "$CONFIG_PATH" ] || [ "$FORCE_CONFIG" -eq 1 ]; then
  echo "[config] Writing $CONFIG_PATH"
  cat > "$CONFIG_PATH" <<YAML
backend:
  primary: sqlite
  fallback: sqlite

openmemory:
  url: ${OPENMEMORY_URL:-http://127.0.0.1:8765}
  user_id: ${USER_ID}
  timeout: 30

qdrant:
  url: ${QDRANT_URL:-http://127.0.0.1:6333}
  collection: ${QDRANT_COLLECTION:-agent_memory}
  timeout: 30

embedding:
  provider: ${LOCAL_MEMORY_EMBEDDING_PROVIDER:-ollama}
  model: ${LOCAL_MEMORY_EMBEDDING_MODEL:-nomic-embed-text}
  dim: ${LOCAL_MEMORY_EMBEDDING_DIM:-768}
  ollama_url: ${LOCAL_MEMORY_OLLAMA_URL:-http://127.0.0.1:11434}
  timeout: ${LOCAL_MEMORY_OLLAMA_TIMEOUT:-30}

context_pack:
  default_token_budget: 2000
  include_stale_warnings: true
  max_records_per_group: 6

temporal:
  enabled: false
  contradiction_detection: heuristic
  auto_supersede_user_corrections: true

ops_db:
  path: $ROOT/memory_ops.sqlite3
YAML
else
  echo "[config] Keeping existing $CONFIG_PATH"
fi

echo "[init] Initializing SQLite DB"
LOCAL_MEMORY_CONFIG="$CONFIG_PATH" LOCAL_MEMORY_DB="${LOCAL_MEMORY_DB:-$ROOT/memory.sqlite3}" "$PY" local_memory_mcp.py init

echo "[html] Rendering dashboard.html"
LOCAL_MEMORY_CONFIG="$CONFIG_PATH" LOCAL_MEMORY_DB="${LOCAL_MEMORY_DB:-$ROOT/memory.sqlite3}" "$PY" local_memory_mcp.py html "$ROOT/dashboard.html"

echo "[status] Semantic status"
LOCAL_MEMORY_CONFIG="$CONFIG_PATH" LOCAL_MEMORY_DB="${LOCAL_MEMORY_DB:-$ROOT/memory.sqlite3}" "$PY" local_memory_mcp.py semantic-status || true

cat <<EOF

[done] local-memory-mcp initialized at:
  $ROOT

Use this server command in MCP clients:
  $ROOT/.venv/bin/python $ROOT/local_memory_mcp.py serve

Hermes example:
  hermes mcp add local_memory --command "$ROOT/.venv/bin/python $ROOT/local_memory_mcp.py serve"

Codex/Claude Code should use the same stdio command. If Ollama is not installed
on the target computer, either install/pull nomic-embed-text or set:
  LOCAL_MEMORY_EMBEDDING_PROVIDER=hashing
  LOCAL_MEMORY_EMBEDDING_DIM=384
EOF
