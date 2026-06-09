#!/usr/bin/env bash
# install_services.sh — 一键安装 MemoryCore 全套 systemd 单元。
#
# 安装内容：
#   mcore.service          — MCP 后端服务
#   mcore-ui.service       — Next.js Web UI
#   mcore-curator.service  — 定时 curator oneshot
#   mcore-curator.timer    — hourly 触发器
#   ~/.local/bin/mcore     — 快捷管理命令
#
# 用法：
#   bash scripts/install_services.sh
#   bash scripts/install_services.sh --host 0.0.0.0 --port 8318 --ui-port 18318
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"

# ── 参数 ──────────────────────────────────────────────────────────────────────
HOST="${MCORE_HOST:-127.0.0.1}"
PORT="${MCORE_PORT:-8318}"
UI_PORT="${MCORE_UI_PORT:-18318}"
PYTHON_BIN="$ROOT/.venv/bin/python"
NODE_BIN="$(command -v node 2>/dev/null || true)"
CONFIG="$ROOT/config.yaml"
DB="$ROOT/memory.sqlite3"
ENV_FILE="$ROOT/.env"
QDRANT_SERVICE="qdrant.service"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)     HOST="$2";     shift 2 ;;
    --port)     PORT="$2";     shift 2 ;;
    --ui-port)  UI_PORT="$2";  shift 2 ;;
    --python)   PYTHON_BIN="$2"; shift 2 ;;
    --node)     NODE_BIN="$2"; shift 2 ;;
    -h|--help)
      grep '^#' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

_log() { echo "[install_services] $*"; }

# ── systemd install ───────────────────────────────────────────────────────────
install_systemd() {
  mkdir -p "$SYSTEMD_USER_DIR" "$ROOT/logs"

  # --- mcore.service ---
  sed \
    -e "s|__ROOT__|$ROOT|g" \
    -e "s|__PYTHON__|$PYTHON_BIN|g" \
    -e "s|__MCORE_HOST__|$HOST|g" \
    -e "s|__MCORE_PORT__|$PORT|g" \
    -e "s|__CONFIG__|$CONFIG|g" \
    -e "s|__DB__|$DB|g" \
    -e "s|__QDRANT_SERVICE__|$QDRANT_SERVICE|g" \
    "$ROOT/scripts/mcore.service" \
    > "$SYSTEMD_USER_DIR/mcore.service"

  # --- mcore-ui.service ---
  if [[ -z "$NODE_BIN" ]]; then
    _log "WARNING: node not found — skipping mcore-ui.service install"
  elif [[ ! -f "$ROOT/ui/node_modules/next/dist/bin/next" ]]; then
    _log "WARNING: Next.js binary missing ($ROOT/ui/node_modules/next/dist/bin/next) — skipping mcore-ui.service install"
    _log "  Run: cd $ROOT/ui && pnpm install"
  else
    sed \
      -e "s|__ROOT__|$ROOT|g" \
      -e "s|__NODE__|$NODE_BIN|g" \
      -e "s|__MCORE_HOST__|$HOST|g" \
      -e "s|__UI_PORT__|$UI_PORT|g" \
      "$ROOT/scripts/mcore-ui.service" \
      > "$SYSTEMD_USER_DIR/mcore-ui.service"
    systemctl --user enable --now mcore-ui.service
    _log "mcore-ui.service installed (http://$HOST:$UI_PORT)"
  fi

  # --- mcore-curator.service ---
  sed \
    -e "s|__ROOT__|$ROOT|g" \
    -e "s|__MCORE_SERVICE__|mcore.service|g" \
    -e "s|__ENV_FILE__|$ENV_FILE|g" \
    -e "s|__CONFIG__|$CONFIG|g" \
    -e "s|__DB__|$DB|g" \
    -e "s|__CURATOR_APPLY__|1|g" \
    -e "s|__CURATOR_LIMIT__|500|g" \
    -e "s|__STALE_AFTER_DAYS__|60|g" \
    -e "s|__ARCHIVE_AFTER_DAYS__|120|g" \
    -e "s|__LLM_CURATOR_ENABLED__|1|g" \
    -e "s|__LLM_CURATOR_APPLY__|1|g" \
    -e "s|__LLM_CURATOR_LIMIT__|200|g" \
    -e "s|__LLM_CURATOR_SIM_THRESHOLD__|0.72|g" \
    "$ROOT/scripts/mcore-curator.service" \
    > "$SYSTEMD_USER_DIR/mcore-curator.service"

  # --- mcore-curator.timer ---
  cp "$ROOT/scripts/mcore-curator.timer" "$SYSTEMD_USER_DIR/mcore-curator.timer"

  # --- mcore CLI ---
  install_mcore_cmd

  systemctl --user daemon-reload
  systemctl --user enable --now mcore.service
  systemctl --user enable --now mcore-curator.timer

  _log "Done. Status:"
  systemctl --user status mcore.service --no-pager | head -8
  echo ""
  systemctl --user list-timers mcore-curator.timer --no-pager
}

# ── mcore CLI install ─────────────────────────────────────────────────────────
install_mcore_cmd() {
  local bin_dir="$HOME/.local/bin"
  local target="$bin_dir/mcore"
  local tmp
  mkdir -p "$bin_dir"
  tmp="$(mktemp "${TMPDIR:-/tmp}/mcore.XXXXXX")"
  sed \
    -e "s|__ROOT__|$ROOT|g" \
    -e "s|__PYTHON__|$PYTHON_BIN|g" \
    "$ROOT/scripts/mcore" \
    > "$tmp"
  chmod +x "$tmp"
  mv -f "$tmp" "$target"
  _log "mcore command installed at $target"
  if [[ ":$PATH:" != *":$bin_dir:"* ]]; then
    _log "  NOTE: $bin_dir is not in PATH. Add it to your shell profile."
  fi
}

# ── cron fallback ─────────────────────────────────────────────────────────────
install_cron() {
  mkdir -p "$ROOT/logs"
  CRON_LINE="17 * * * * $ROOT/run_curator.sh >> $ROOT/logs/curator.log 2>&1"
  ( crontab -l 2>/dev/null | grep -v "run_curator.sh"; echo "$CRON_LINE" ) | crontab -
  _log "cron job installed: $CRON_LINE"
  _log "Note: mcore.service requires systemd. Start manually: bash start.sh --daemon"
}

# ── main ──────────────────────────────────────────────────────────────────────
if systemctl --user status >/dev/null 2>&1; then
  _log "systemd user session detected — installing full unit suite."
  install_systemd
else
  _log "systemd user session not available — falling back to cron."
  install_mcore_cmd
  install_cron
fi
