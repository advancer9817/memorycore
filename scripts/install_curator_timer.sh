#!/usr/bin/env bash
# Install mcore-curator systemd user timer (or cron fallback).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
CONFIG="${LOCAL_MEMORY_CONFIG:-$ROOT/config.yaml}"
DB="${LOCAL_MEMORY_DB:-$ROOT/memory.sqlite3}"
ENV_FILE="$ROOT/.env"

# --- systemd path ---
install_systemd() {
    mkdir -p "$SYSTEMD_USER_DIR"
    sed \
      -e "s|__ROOT__|$ROOT|g" \
      -e "s|__MCORE_SERVICE__|mcore.service|g" \
      -e "s|__ENV_FILE__|$ENV_FILE|g" \
      -e "s|__CONFIG__|$CONFIG|g" \
      -e "s|__DB__|$DB|g" \
      -e "s|__CURATOR_APPLY__|${LOCAL_MEMORY_CURATOR_APPLY:-1}|g" \
      -e "s|__CURATOR_LIMIT__|${LOCAL_MEMORY_CURATOR_LIMIT:-500}|g" \
      -e "s|__STALE_AFTER_DAYS__|${LOCAL_MEMORY_STALE_AFTER_DAYS:-60}|g" \
      -e "s|__ARCHIVE_AFTER_DAYS__|${LOCAL_MEMORY_ARCHIVE_AFTER_DAYS:-120}|g" \
      -e "s|__LLM_CURATOR_ENABLED__|${LOCAL_MEMORY_LLM_CURATOR_ENABLED:-1}|g" \
      -e "s|__LLM_CURATOR_APPLY__|${LOCAL_MEMORY_LLM_CURATOR_APPLY:-${LOCAL_MEMORY_CURATOR_APPLY:-1}}|g" \
      -e "s|__LLM_CURATOR_LIMIT__|${LOCAL_MEMORY_LLM_CURATOR_LIMIT:-200}|g" \
      -e "s|__LLM_CURATOR_SIM_THRESHOLD__|${LOCAL_MEMORY_LLM_CURATOR_SIM_THRESHOLD:-0.72}|g" \
      "$ROOT/scripts/mcore-curator.service" \
      > "$SYSTEMD_USER_DIR/mcore-curator.service"
    cp "$ROOT/scripts/mcore-curator.timer" "$SYSTEMD_USER_DIR/mcore-curator.timer"

    systemctl --user daemon-reload
    systemctl --user enable --now mcore-curator.timer
    echo "systemd timer installed."
    systemctl --user list-timers mcore-curator.timer --no-pager
}

# --- cron fallback ---
install_cron() {
    CRON_LINE="17 * * * * $ROOT/run_curator.sh >> $ROOT/logs/curator.log 2>&1"
    # Remove old entry if present, then append
    ( crontab -l 2>/dev/null | grep -v "run_curator.sh" ; echo "$CRON_LINE" ) | crontab -
    echo "cron job installed: $CRON_LINE"
}

mkdir -p "$ROOT/logs"

if systemctl --user status >/dev/null 2>&1; then
    echo "systemd user session detected — installing timer."
    install_systemd
else
    echo "systemd user session not available — falling back to cron."
    install_cron
fi
