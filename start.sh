#!/usr/bin/env bash
# start.sh — 一键启动 local-memory-mcp（含记忆导入）
#
# 适用场景：新设备 clone 仓库后第一次启动，或日常启动。
# 执行步骤：
#   1. 创建/复用 Python venv
#   2. 安装/更新依赖
#   3. 初始化 SQLite DB（幂等）
#   4. 导入 memory-sync/memories.json（冲突策略 newer，有则导入无则跳过）
#   4.5 配置 Agent hooks / 软注入规则（幂等）
#   5. 启动 HTTP MCP 服务
#
# 用法：
#   bash start.sh                   # 前台运行
#   bash start.sh --daemon          # 后台运行（PID 写入 /tmp/lmmcp.pid）
#   bash start.sh --no-import       # 跳过记忆导入
#   bash start.sh --host 0.0.0.0 --port 8318
#   LMMCP_AUTO_SYNC=0 bash start.sh # 同上效果（兼容 lmmcp 脚本变量）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── 参数 ──────────────────────────────────────────────────────────────────────
HOST="${LMMCP_HOST:-127.0.0.1}"
PORT="${LMMCP_PORT:-8318}"
DAEMON=0
SKIP_IMPORT=0
PYTHON_BIN="${LMMCP_PYTHON:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)        HOST="$2";    shift 2 ;;
    --port)        PORT="$2";    shift 2 ;;
    --daemon)      DAEMON=1;     shift ;;
    --no-import)   SKIP_IMPORT=1; shift ;;
    --python)      PYTHON_BIN="$2"; shift 2 ;;
    -h|--help)
      grep '^#' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

LOG="$SCRIPT_DIR/lmmcp.log"
SYNC_FILE="$SCRIPT_DIR/memory-sync/memories.json"
PID_FILE="${LMMCP_PID_FILE:-/tmp/lmmcp.pid}"

_log()  { echo "[start.sh] $*"; }
_warn() { echo "[start.sh] WARNING: $*" >&2; }

# ── 1. Python venv ─────────────────────────────────────────────────────────────
if [[ -z "$PYTHON_BIN" ]]; then
  for candidate in python3.11 python3.12 python3.13 python3; do
    if command -v "$candidate" &>/dev/null; then
      PYTHON_BIN="$(command -v "$candidate")"
      break
    fi
  done
fi
[[ -n "$PYTHON_BIN" ]] || { echo "[start.sh] ERROR: Python 3.11+ not found" >&2; exit 1; }

VENV="$SCRIPT_DIR/.venv"
if [[ ! -x "$VENV/bin/python" ]]; then
  _log "Creating venv with $PYTHON_BIN ..."
  "$PYTHON_BIN" -m venv "$VENV"
fi
PY="$VENV/bin/python"

# ── 2. 依赖 ───────────────────────────────────────────────────────────────────
_log "Installing/updating dependencies ..."
"$PY" -m pip install -q -e ".[extraction]"

# ── 3. 初始化 DB（幂等）──────────────────────────────────────────────────────
_log "Initializing database ..."
"$PY" -m local_memory_mcp init

# ── 4. 导入记忆 ───────────────────────────────────────────────────────────────
if [[ "$SKIP_IMPORT" -eq 0 ]]; then
  if [[ -f "$SYNC_FILE" ]]; then
    _log "Importing memories from $SYNC_FILE (conflict_policy=newer) ..."
    "$PY" -m local_memory_mcp import "$SYNC_FILE" --conflict-policy newer --apply
  else
    _log "No sync file found at $SYNC_FILE — skipping import (first run on this device?)"
    _log "To sync from another device: git pull && bash start.sh"
  fi
else
  _log "--no-import: skipping memory import"
fi

# ── 4.5 配置 Agent Hooks / 软注入规则（幂等）────────────────────────────────
_log "Configuring agent hooks and memory rules ..."
bash "$SCRIPT_DIR/scripts/setup-hooks.sh" || _warn "Hook setup failed (non-fatal)"

# ── 5. 启动服务 ───────────────────────────────────────────────────────────────
_log "Starting MCP service on http://$HOST:$PORT ..."
_log "  MCP endpoint : http://$HOST:$PORT/mcp"
_log "  Dashboard    : http://$HOST:$PORT/"
_log "  Health       : http://$HOST:$PORT/health"

if [[ "$DAEMON" -eq 1 ]]; then
  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    _warn "Already running (pid $(cat "$PID_FILE")). Use 'scripts/lmmcp stop' first."
    exit 1
  fi
  nohup "$PY" -m local_memory_mcp serve --host "$HOST" --port "$PORT" >> "$LOG" 2>&1 &
  echo $! > "$PID_FILE"
  sleep 1
  if kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    _log "Started in background (pid $(cat "$PID_FILE")). Log: $LOG"
    _log "Stop with: scripts/lmmcp stop"
  else
    echo "[start.sh] ERROR: service failed to start — check $LOG" >&2
    exit 1
  fi
else
  exec "$PY" -m local_memory_mcp serve --host "$HOST" --port "$PORT"
fi
