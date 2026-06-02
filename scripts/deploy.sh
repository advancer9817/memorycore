#!/usr/bin/env bash
# One-command installer for memorycore.
#
# Installs missing host deps, Python deps, writes config, initializes SQLite,
# installs user systemd services for Qdrant + mcore + curator, and verifies health.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/deploy.sh [options]

One-command memorycore deployment.

Options:
  --root PATH              Install/runtime root. Default: current checkout.
  --host HOST              mcore bind host. Default: 127.0.0.1
  --port PORT              mcore HTTP port. Default: 8318
  --db PATH                SQLite DB path. Default: ROOT/memory.sqlite3
  --config PATH            Config path. Default: ROOT/config.yaml
  --force-config           Rewrite config.yaml even if it exists.
  --skip-install           Skip pip install.
  --skip-tests             Skip pytest verification.
  --no-systemd             Do not install user systemd services.
  --no-qdrant              Do not install/start Qdrant service.
  --bootstrap-deps         Install missing host deps where supported (default).
  --no-bootstrap-deps      Disable host dependency bootstrap.
  --with-ollama            Ensure Ollama is installed/running and pull embedding model (default).
  --no-ollama              Do not install/start Ollama; rely on configured fallback embedding.
  --no-pull-images         Do not pre-pull Docker images.
  --no-pull-models         Do not pre-pull Ollama embedding model.
  --assume-yes             Non-interactive package manager installs where supported (default).
  --no-assume-yes          Allow package manager prompts during dependency bootstrap.
  --qdrant-image IMAGE     Qdrant Docker image. Default: qdrant/qdrant
  --qdrant-http-port PORT  Qdrant HTTP port. Default: 6333
  --qdrant-grpc-port PORT  Qdrant gRPC port. Default: 6334
  --qdrant-storage PATH    Qdrant storage dir. Default: ~/.agent-memory/qdrant_storage
  --curator-apply VALUE    Whether curator applies low-risk lifecycle changes. Default: 1
  --curator-limit N        Curator scan limit. Default: 500
  --stale-after-days N     Active stale threshold. Default: 60
  --archive-after-days N   Stale archive threshold. Default: 120
  --python PATH            Python executable for venv creation. Default: python3.11/python3
  --dry-run                Print resolved plan and exit before writes.
  -h, --help               Show this help.

Environment overrides are also supported: LOCAL_MEMORY_ROOT, MCORE_HOST,
MCORE_PORT, LOCAL_MEMORY_DB, LOCAL_MEMORY_CONFIG, QDRANT_URL,
QDRANT_COLLECTION, LOCAL_MEMORY_EMBEDDING_PROVIDER, LOCAL_MEMORY_EMBEDDING_MODEL,
LOCAL_MEMORY_EMBEDDING_FALLBACK_PROVIDER, LOCAL_MEMORY_SENTENCE_TRANSFORMERS_MODEL,
LOCAL_MEMORY_EMBEDDING_DIM, LOCAL_MEMORY_OLLAMA_URL, MCORE_BOOTSTRAP_DEPS,
MCORE_WITH_OLLAMA, MCORE_ASSUME_YES, MCORE_PULL_IMAGES, MCORE_PULL_MODELS.
USAGE
}

msg() { printf '\n[%s] %s\n' "$1" "$2"; }
warn() { printf '[warn] %s\n' "$*" >&2; }
die() { printf '[error] %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }
as_bool() {
  case "${1:-0}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}
sudo_cmd() {
  if [ "${EUID:-$(id -u)}" -eq 0 ]; then
    "$@"
  elif have sudo; then
    sudo "$@"
  else
    die "Need root privileges for: $*. Install sudo or rerun as root."
  fi
}
install_packages() {
  [ "$#" -gt 0 ] || return 0
  if have apt-get; then
    local apt_flags=()
    [ "$ASSUME_YES" -eq 1 ] && apt_flags=(-y)
    sudo_cmd apt-get update
    sudo_cmd apt-get install "${apt_flags[@]}" "$@"
  elif have dnf; then
    local dnf_flags=()
    [ "$ASSUME_YES" -eq 1 ] && dnf_flags=(-y)
    sudo_cmd dnf install "${dnf_flags[@]}" "$@"
  elif have yum; then
    local yum_flags=()
    [ "$ASSUME_YES" -eq 1 ] && yum_flags=(-y)
    sudo_cmd yum install "${yum_flags[@]}" "$@"
  elif have brew; then
    brew install "$@"
  else
    die "No supported package manager found for dependency bootstrap. Install manually: $*"
  fi
}
ensure_host_deps() {
  local missing=() py_pkg=""
  have curl || missing+=(curl)
  have rsync || missing+=(rsync)
  have tar || missing+=(tar)
  have ss || missing+=(iproute2)
  if ! have python3.11 && ! have python3; then
    missing+=(python3)
  fi
  if have apt-get; then
    if have python3.11; then py_pkg=python3.11-venv; else py_pkg=python3-venv; fi
    dpkg -s "$py_pkg" >/dev/null 2>&1 || missing+=("$py_pkg")
  fi
  if [ "$INSTALL_SYSTEMD" -eq 1 ]; then
    have systemctl || missing+=(systemd)
    if [ "$INSTALL_QDRANT" -eq 1 ]; then
      have docker || missing+=(docker.io)
    fi
  fi
  if [ "${#missing[@]}" -gt 0 ]; then
    msg deps "Installing missing host packages: ${missing[*]}"
    install_packages "${missing[@]}"
  else
    msg deps "Host package prerequisites already present"
  fi
}
ensure_docker_ready() {
  have docker || die "docker not found; rerun with --bootstrap-deps, install Docker, or rerun with --no-qdrant"
  if ! docker info >/dev/null 2>&1; then
    if have systemctl; then
      warn "Docker daemon is not reachable; trying to start docker.service"
      if [ "${EUID:-$(id -u)}" -eq 0 ]; then systemctl start docker || true;
      elif have sudo; then sudo systemctl start docker || true;
      fi
    fi
  fi
  docker info >/dev/null 2>&1 || die "Docker daemon is not reachable. Start Docker Desktop/service or rerun with --no-qdrant."
}
ensure_ollama_ready() {
  if ! have ollama; then
    if [ "$BOOTSTRAP_DEPS" -eq 1 ]; then
      msg deps "Installing Ollama"
      curl -fsSL https://ollama.com/install.sh | sh
    else
      die "ollama not found; rerun with --bootstrap-deps --with-ollama, install Ollama, or set LOCAL_MEMORY_EMBEDDING_PROVIDER=api or hashing"
    fi
  fi
  if ! curl -fsS "${LOCAL_MEMORY_OLLAMA_URL:-http://127.0.0.1:11434}/api/tags" >/dev/null 2>&1; then
    warn "Ollama service is not reachable; trying to start it"
    if have systemctl; then
      systemctl --user start ollama >/dev/null 2>&1 || {
        if [ "${EUID:-$(id -u)}" -eq 0 ]; then systemctl start ollama || true;
        elif have sudo; then sudo systemctl start ollama || true;
        fi
      }
    fi
    if ! curl -fsS "${LOCAL_MEMORY_OLLAMA_URL:-http://127.0.0.1:11434}/api/tags" >/dev/null 2>&1; then
      nohup ollama serve >/tmp/mcore-ollama.log 2>&1 &
      sleep 2
    fi
  fi
  curl -fsS "${LOCAL_MEMORY_OLLAMA_URL:-http://127.0.0.1:11434}/api/tags" >/dev/null 2>&1 || die "Ollama is installed but not reachable at ${LOCAL_MEMORY_OLLAMA_URL:-http://127.0.0.1:11434}"
  if [ "$PULL_MODELS" -eq 1 ]; then
    msg deps "Ensuring Ollama model ${LOCAL_MEMORY_EMBEDDING_MODEL:-nomic-embed-text}"
    ollama pull "${LOCAL_MEMORY_EMBEDDING_MODEL:-nomic-embed-text}"
  fi
}
abs_path() {
  local p="$1"
  if [[ "$p" = /* ]]; then printf '%s\n' "$p"; else printf '%s/%s\n' "$PWD" "$p"; fi
}
replace_token() {
  local file="$1" token="$2" value="$3"
  "$PY" - "$file" "$token" "$value" <<'PY'
import pathlib, sys
path, token, value = sys.argv[1:4]
p = pathlib.Path(path)
p.write_text(p.read_text().replace(token, value), encoding='utf-8')
PY
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ROOT="${LOCAL_MEMORY_ROOT:-$SOURCE_DIR}"
HOST="${MCORE_HOST:-127.0.0.1}"
PORT="${MCORE_PORT:-8318}"
DB="${LOCAL_MEMORY_DB:-}"
CONFIG="${LOCAL_MEMORY_CONFIG:-}"
FORCE_CONFIG=0
SKIP_INSTALL=0
SKIP_TESTS=0
INSTALL_SYSTEMD=1
INSTALL_QDRANT=1
QDRANT_IMAGE="${QDRANT_IMAGE:-qdrant/qdrant}"
QDRANT_HTTP_PORT="${QDRANT_HTTP_PORT:-6333}"
QDRANT_GRPC_PORT="${QDRANT_GRPC_PORT:-6334}"
QDRANT_STORAGE="${QDRANT_STORAGE:-$HOME/.agent-memory/qdrant_storage}"
CURATOR_APPLY="${LOCAL_MEMORY_CURATOR_APPLY:-1}"
CURATOR_LIMIT="${LOCAL_MEMORY_CURATOR_LIMIT:-500}"
STALE_AFTER_DAYS="${LOCAL_MEMORY_STALE_AFTER_DAYS:-60}"
ARCHIVE_AFTER_DAYS="${LOCAL_MEMORY_ARCHIVE_AFTER_DAYS:-120}"
PYTHON_BIN="${PYTHON_BIN:-}"
BOOTSTRAP_DEPS=1
WITH_OLLAMA=1
PULL_IMAGES=1
PULL_MODELS=1
ASSUME_YES=1
if [ -n "${MCORE_BOOTSTRAP_DEPS:-}" ]; then
  if as_bool "$MCORE_BOOTSTRAP_DEPS"; then BOOTSTRAP_DEPS=1; else BOOTSTRAP_DEPS=0; fi
fi
if [ -n "${MCORE_WITH_OLLAMA:-}" ]; then
  if as_bool "$MCORE_WITH_OLLAMA"; then WITH_OLLAMA=1; else WITH_OLLAMA=0; fi
fi
if [ -n "${MCORE_ASSUME_YES:-}" ]; then
  if as_bool "$MCORE_ASSUME_YES"; then ASSUME_YES=1; else ASSUME_YES=0; fi
fi
if ! as_bool "${MCORE_PULL_IMAGES:-1}"; then PULL_IMAGES=0; fi
if ! as_bool "${MCORE_PULL_MODELS:-1}"; then PULL_MODELS=0; fi
DRY_RUN=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --root) ROOT="${2:?--root requires a path}"; shift 2 ;;
    --host) HOST="${2:?--host requires a value}"; shift 2 ;;
    --port) PORT="${2:?--port requires a value}"; shift 2 ;;
    --db) DB="${2:?--db requires a path}"; shift 2 ;;
    --config) CONFIG="${2:?--config requires a path}"; shift 2 ;;
    --force-config) FORCE_CONFIG=1; shift ;;
    --skip-install) SKIP_INSTALL=1; shift ;;
    --skip-tests) SKIP_TESTS=1; shift ;;
    --no-systemd) INSTALL_SYSTEMD=0; shift ;;
    --no-qdrant) INSTALL_QDRANT=0; shift ;;
    --bootstrap-deps) BOOTSTRAP_DEPS=1; shift ;;
    --no-bootstrap-deps) BOOTSTRAP_DEPS=0; shift ;;
    --with-ollama) WITH_OLLAMA=1; shift ;;
    --no-ollama) WITH_OLLAMA=0; shift ;;
    --no-pull-images) PULL_IMAGES=0; shift ;;
    --no-pull-models) PULL_MODELS=0; shift ;;
    --assume-yes) ASSUME_YES=1; shift ;;
    --no-assume-yes) ASSUME_YES=0; shift ;;
    --qdrant-image) QDRANT_IMAGE="${2:?--qdrant-image requires a value}"; shift 2 ;;
    --qdrant-http-port) QDRANT_HTTP_PORT="${2:?--qdrant-http-port requires a value}"; shift 2 ;;
    --qdrant-grpc-port) QDRANT_GRPC_PORT="${2:?--qdrant-grpc-port requires a value}"; shift 2 ;;
    --qdrant-storage) QDRANT_STORAGE="${2:?--qdrant-storage requires a path}"; shift 2 ;;
    --curator-apply) CURATOR_APPLY="${2:?--curator-apply requires a value}"; shift 2 ;;
    --curator-limit) CURATOR_LIMIT="${2:?--curator-limit requires a value}"; shift 2 ;;
    --stale-after-days) STALE_AFTER_DAYS="${2:?--stale-after-days requires a value}"; shift 2 ;;
    --archive-after-days) ARCHIVE_AFTER_DAYS="${2:?--archive-after-days requires a value}"; shift 2 ;;
    --python) PYTHON_BIN="${2:?--python requires a path}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
done

mkdir -p "$ROOT"
ROOT="$(cd "$ROOT" && pwd -P)"
if [ -z "$DB" ]; then DB="$ROOT/memory.sqlite3"; fi
if [ -z "$CONFIG" ]; then CONFIG="$ROOT/config.yaml"; fi
DB="$(abs_path "$DB")"
CONFIG="$(abs_path "$CONFIG")"
QDRANT_STORAGE="$(abs_path "$QDRANT_STORAGE")"
QDRANT_URL="${QDRANT_URL:-http://127.0.0.1:$QDRANT_HTTP_PORT}"
QDRANT_COLLECTION="${QDRANT_COLLECTION:-agent_memory}"

cat <<PLAN
[plan]
  source:          $SOURCE_DIR
  root:            $ROOT
  python:          ${PYTHON_BIN:-auto}
  host/port:       $HOST:$PORT
  db:              $DB
  config:          $CONFIG
  systemd:         $INSTALL_SYSTEMD
  qdrant:          $INSTALL_QDRANT ($QDRANT_URL, image=$QDRANT_IMAGE, storage=$QDRANT_STORAGE)
  bootstrap deps:  $BOOTSTRAP_DEPS (assume_yes=$ASSUME_YES)
  pull images:     $PULL_IMAGES
  ollama:          $WITH_OLLAMA (model=${LOCAL_MEMORY_EMBEDDING_MODEL:-nomic-embed-text}, pull_models=$PULL_MODELS)
  curator apply:   $CURATOR_APPLY
PLAN
[ "$DRY_RUN" -eq 1 ] && exit 0

if [ "$BOOTSTRAP_DEPS" -eq 1 ]; then
  ensure_host_deps
fi

if [ "$SOURCE_DIR" != "$ROOT" ]; then
  msg copy "Syncing project files to $ROOT"
  if have rsync; then
    rsync -a --exclude '.git/' --exclude '.venv/' --exclude '__pycache__/' \
      --exclude 'memory.sqlite3*' --exclude 'memory_ops.sqlite3*' \
      "$SOURCE_DIR/" "$ROOT/"
  else
    (cd "$SOURCE_DIR" && tar --exclude='.git' --exclude='.venv' --exclude='__pycache__' \
      --exclude='memory.sqlite3*' --exclude='memory_ops.sqlite3*' -cf - .) | (cd "$ROOT" && tar -xf -)
  fi
fi

cd "$ROOT"

if [ -z "$PYTHON_BIN" ]; then
  if have python3.11; then PYTHON_BIN=python3.11; else PYTHON_BIN=python3; fi
fi
"$PYTHON_BIN" - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit('Python 3.11+ is required')
PY

if [ ! -d .venv ]; then
  msg venv "Creating .venv with $PYTHON_BIN"
  "$PYTHON_BIN" -m venv .venv
fi
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || die "venv python not executable: $PY"

if [ "$SKIP_INSTALL" -eq 0 ]; then
  msg deps "Installing requirements"
  "$PY" -m pip install -U pip
  "$PY" -m pip install -r requirements.txt
  "$PY" -m pip install -e ".[all]"
fi

if [ "$WITH_OLLAMA" -eq 1 ]; then
  ensure_ollama_ready
elif [[ "${LOCAL_MEMORY_EMBEDDING_PROVIDER:-auto}" =~ ^(auto|ollama)$ ]] && ! curl -fsS "${LOCAL_MEMORY_OLLAMA_URL:-http://127.0.0.1:11434}/api/tags" >/dev/null 2>&1; then
  warn "Ollama is not reachable; vector embedding will use fallback providers. Remove --no-ollama or set MCORE_WITH_OLLAMA=1 to install/start/pull the model."
fi

if [ ! -f "$CONFIG" ] || [ "$FORCE_CONFIG" -eq 1 ]; then
  msg config "Writing $CONFIG"
  cat > "$CONFIG" <<YAML
backend:
  primary: sqlite
  fallback: sqlite

qdrant:
  url: $QDRANT_URL
  collection: $QDRANT_COLLECTION
  timeout: 30

embedding:
  provider: ${LOCAL_MEMORY_EMBEDDING_PROVIDER:-auto}
  model: ${LOCAL_MEMORY_EMBEDDING_MODEL:-nomic-embed-text}
  fallback_provider: ${LOCAL_MEMORY_EMBEDDING_FALLBACK_PROVIDER:-hashing}
  sentence_transformers_model: ${LOCAL_MEMORY_SENTENCE_TRANSFORMERS_MODEL:-sentence-transformers/all-mpnet-base-v2}
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
  msg config "Keeping existing $CONFIG"
fi

mkdir -p "$ROOT/logs" "$(dirname "$DB")"
msg init "Initializing SQLite and dashboard"
LOCAL_MEMORY_CONFIG="$CONFIG" LOCAL_MEMORY_DB="$DB" PYTHONPATH="$ROOT" "$PY" -m memorycore init >/dev/null
LOCAL_MEMORY_CONFIG="$CONFIG" LOCAL_MEMORY_DB="$DB" PYTHONPATH="$ROOT" "$PY" -m memorycore html "$ROOT/dashboard.html" >/dev/null

if [ "$INSTALL_SYSTEMD" -eq 1 ]; then
  have systemctl || die "systemctl not found; rerun with --no-systemd"
  systemctl --user status >/dev/null 2>&1 || die "systemd user session unavailable; rerun with --no-systemd"
  SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
  mkdir -p "$SYSTEMD_USER_DIR" "$QDRANT_STORAGE"

  QDRANT_SERVICE="qdrant.service"
  if [ "$INSTALL_QDRANT" -eq 1 ]; then
    ensure_docker_ready
    if [ "$PULL_IMAGES" -eq 1 ]; then
      msg deps "Ensuring Docker image $QDRANT_IMAGE"
      docker pull "$QDRANT_IMAGE"
    fi
    msg systemd "Installing $QDRANT_SERVICE"
    cp "$ROOT/scripts/qdrant.service" "$SYSTEMD_USER_DIR/$QDRANT_SERVICE"
    replace_token "$SYSTEMD_USER_DIR/$QDRANT_SERVICE" __QDRANT_HTTP_PORT__ "$QDRANT_HTTP_PORT"
    replace_token "$SYSTEMD_USER_DIR/$QDRANT_SERVICE" __QDRANT_GRPC_PORT__ "$QDRANT_GRPC_PORT"
    replace_token "$SYSTEMD_USER_DIR/$QDRANT_SERVICE" __QDRANT_STORAGE__ "$QDRANT_STORAGE"
    replace_token "$SYSTEMD_USER_DIR/$QDRANT_SERVICE" __QDRANT_IMAGE__ "$QDRANT_IMAGE"
  else
    QDRANT_SERVICE=""
  fi

  msg systemd "Installing mcore.service and mcore-curator.timer"
  cp "$ROOT/scripts/mcore.service" "$SYSTEMD_USER_DIR/mcore.service"
  replace_token "$SYSTEMD_USER_DIR/mcore.service" __ROOT__ "$ROOT"
  replace_token "$SYSTEMD_USER_DIR/mcore.service" __PYTHON__ "$PY"
  replace_token "$SYSTEMD_USER_DIR/mcore.service" __MCORE_HOST__ "$HOST"
  replace_token "$SYSTEMD_USER_DIR/mcore.service" __MCORE_PORT__ "$PORT"
  replace_token "$SYSTEMD_USER_DIR/mcore.service" __CONFIG__ "$CONFIG"
  replace_token "$SYSTEMD_USER_DIR/mcore.service" __DB__ "$DB"
  replace_token "$SYSTEMD_USER_DIR/mcore.service" __QDRANT_SERVICE__ "${QDRANT_SERVICE:-network-online.target}"

  cp "$ROOT/scripts/mcore-curator.service" "$SYSTEMD_USER_DIR/mcore-curator.service"
  cp "$ROOT/scripts/mcore-curator.timer" "$SYSTEMD_USER_DIR/mcore-curator.timer"
  replace_token "$SYSTEMD_USER_DIR/mcore-curator.service" __ROOT__ "$ROOT"
  replace_token "$SYSTEMD_USER_DIR/mcore-curator.service" __ENV_FILE__ "$ROOT/.env"
  replace_token "$SYSTEMD_USER_DIR/mcore-curator.service" __CONFIG__ "$CONFIG"
  replace_token "$SYSTEMD_USER_DIR/mcore-curator.service" __DB__ "$DB"
  replace_token "$SYSTEMD_USER_DIR/mcore-curator.service" __CURATOR_APPLY__ "$CURATOR_APPLY"
  replace_token "$SYSTEMD_USER_DIR/mcore-curator.service" __CURATOR_LIMIT__ "$CURATOR_LIMIT"
  replace_token "$SYSTEMD_USER_DIR/mcore-curator.service" __STALE_AFTER_DAYS__ "$STALE_AFTER_DAYS"
  replace_token "$SYSTEMD_USER_DIR/mcore-curator.service" __ARCHIVE_AFTER_DAYS__ "$ARCHIVE_AFTER_DAYS"
  replace_token "$SYSTEMD_USER_DIR/mcore-curator.service" __MCORE_SERVICE__ "mcore.service"

  systemctl --user daemon-reload
  if [ "$INSTALL_QDRANT" -eq 1 ]; then systemctl --user enable --now "$QDRANT_SERVICE"; fi
  systemctl --user enable --now mcore.service mcore-curator.timer
  systemctl --user restart mcore.service
fi

msg verify "Health checks"
if [ "$INSTALL_SYSTEMD" -eq 1 ]; then
  if [ "$INSTALL_QDRANT" -eq 1 ]; then
    for i in $(seq 1 45); do curl -fsS "$QDRANT_URL/collections" >/dev/null 2>&1 && break; sleep 1; [ "$i" -eq 45 ] && die "Qdrant did not become healthy at $QDRANT_URL"; done
  fi
  for i in $(seq 1 30); do ss -ltn 2>/dev/null | grep -q ":$PORT " && break; sleep 1; [ "$i" -eq 30 ] && die "mcore port $PORT did not open"; done
fi
LOCAL_MEMORY_CONFIG="$CONFIG" LOCAL_MEMORY_DB="$DB" PYTHONPATH="$ROOT" "$PY" - <<'PY'
from memorycore.vector_store import get_vector_store
from memorycore.models import load_config
print(get_vector_store(load_config()).status())
PY
LOCAL_MEMORY_CONFIG="$CONFIG" LOCAL_MEMORY_DB="$DB" PYTHONPATH="$ROOT" "$PY" -m memorycore curator --summary-only >/dev/null

if [ "$SKIP_TESTS" -eq 0 ]; then
  msg tests "Running pytest"
  LOCAL_MEMORY_CONFIG="$CONFIG" LOCAL_MEMORY_DB="$DB" PYTHONPATH="$ROOT" "$PY" -m pytest tests -q --tb=short
fi

cat <<EOF

[done] memorycore deployed
  root:      $ROOT
  endpoint:  http://$HOST:$PORT/mcp
  db:        $DB
  config:    $CONFIG
  qdrant:    $QDRANT_URL

Useful commands:
  systemctl --user status qdrant.service mcore.service mcore-curator.timer
  journalctl --user -u mcore.service -f
  tail -80 $ROOT/logs/curator.log
EOF
