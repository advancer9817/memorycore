#!/usr/bin/env bash
# install_services.sh — 一键安装 MemoryCore 全套 systemd 单元。
#
# 安装内容：
#   mcore.service          — 主服务（MCP + UI 代理）
#   mcore-curator.service  — 定时 curator oneshot
#   mcore-curator.timer    — hourly 触发器
#
# 同时迁移旧单元（lmmcp.service / lmmcp-curator.*），避免冲突。
#
# 用法：
#   bash scripts/install_services.sh
#   bash scripts/install_services.sh --host 0.0.0.0 --port 8318 --ui-port 3001
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"

# ── 参数 ──────────────────────────────────────────────────────────────────────
HOST="${MCORE_HOST:-127.0.0.1}"
PORT="${MCORE_PORT:-8318}"
UI_PORT="${MCORE_UI_PORT:-3001}"
PYTHON_BIN="$ROOT/.venv/bin/python"
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
    -e "s|__UI_PORT__|$UI_PORT|g" \
    -e "s|__CONFIG__|$CONFIG|g" \
    -e "s|__DB__|$DB|g" \
    -e "s|__QDRANT_SERVICE__|$QDRANT_SERVICE|g" \
    "$ROOT/scripts/mcore.service" \
    > "$SYSTEMD_USER_DIR/mcore.service"

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
    "$ROOT/scripts/mcore-curator.service" \
    > "$SYSTEMD_USER_DIR/mcore-curator.service"

  # --- mcore-curator.timer ---
  cp "$ROOT/scripts/mcore-curator.timer" "$SYSTEMD_USER_DIR/mcore-curator.timer"

  # --- 迁移旧单元 ---
  for old in lmmcp.service lmmcp-curator.service lmmcp-curator.timer; do
    if systemctl --user is-enabled "$old" &>/dev/null; then
      _log "Disabling legacy unit: $old"
      systemctl --user disable "$old" 2>/dev/null || true
    fi
    if systemctl --user is-active "$old" &>/dev/null; then
      _log "Stopping legacy unit: $old"
      systemctl --user stop "$old" 2>/dev/null || true
    fi
  done

  systemctl --user daemon-reload
  systemctl --user enable --now mcore.service
  systemctl --user enable --now mcore-curator.timer

  _log "Done. Status:"
  systemctl --user status mcore.service --no-pager | head -8
  echo ""
  systemctl --user list-timers mcore-curator.timer --no-pager
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
  install_cron
fi
