#!/usr/bin/env bash
# Install mcore-curator systemd user timer (or cron fallback).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"

# --- systemd path ---
install_systemd() {
    mkdir -p "$SYSTEMD_USER_DIR"
    cp "$ROOT/scripts/mcore-curator.service" "$SYSTEMD_USER_DIR/mcore-curator.service"
    cp "$ROOT/scripts/mcore-curator.timer"   "$SYSTEMD_USER_DIR/mcore-curator.timer"

    # Patch WorkingDirectory and ExecStart with actual HOME path
    sed -i "s|%h|$HOME|g" "$SYSTEMD_USER_DIR/mcore-curator.service"

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
