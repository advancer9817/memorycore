#!/usr/bin/env bash
# mcore-daemon.sh — Idempotent mcore HTTP server lifecycle manager.
# Usage:
#   bash mcore-daemon.sh start    # ensure server is running
#   bash mcore-daemon.sh status   # check if server is healthy
#   bash mcore-daemon.sh stop     # stop the server
#   source mcore-daemon.sh && ensure_mcore_running   # used by hooks
set -euo pipefail

MCORE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MCORE_PORT="${MCORE_PORT:-8318}"
MCORE_HOST="${MCORE_HOST:-127.0.0.1}"
MCORE_PID_FILE="${MCORE_PID_FILE:-/tmp/mcore.pid}"
MCORE_LOG_FILE="${MCORE_LOG_FILE:-/tmp/mcore.log}"
MCORE_HEALTH_URL="http://${MCORE_HOST}:${MCORE_PORT}/mcp"

is_port_listening() {
  if command -v ss >/dev/null 2>&1; then
    ss -tln 2>/dev/null | awk '{print $4}' | grep -E "[:.]${MCORE_PORT}$" >/dev/null 2>&1
  elif command -v netstat >/dev/null 2>&1; then
    netstat -tln 2>/dev/null | awk '{print $4}' | grep -E "[:.]${MCORE_PORT}$" >/dev/null 2>&1
  else
    bash -c "exec 3<>/dev/tcp/${MCORE_HOST}/${MCORE_PORT}" 2>/dev/null && exec 3>&- 3<&-
  fi
}

is_pid_alive() {
  local pid="${1:-}"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

ensure_mcore_running() {
  if is_port_listening; then
    return 0
  fi
  if [ -f "$MCORE_PID_FILE" ]; then
    local old_pid
    old_pid="$(cat "$MCORE_PID_FILE" 2>/dev/null || echo '')"
    if is_pid_alive "$old_pid"; then
      sleep 1
      is_port_listening && return 0
    fi
    rm -f "$MCORE_PID_FILE"
  fi
  if [ ! -x "$MCORE_ROOT/.venv/bin/python" ]; then
    echo "[mcore-daemon] error: venv not found at $MCORE_ROOT/.venv" >&2
    return 1
  fi
  cd "$MCORE_ROOT"
  nohup "$MCORE_ROOT/.venv/bin/python" -m memorycore serve --host "$MCORE_HOST" --port "$MCORE_PORT" \
    >>"$MCORE_LOG_FILE" 2>&1 &
  local new_pid=$!
  echo "$new_pid" > "$MCORE_PID_FILE"
  local i=0
  while [ $i -lt 30 ]; do
    if is_port_listening; then
      return 0
    fi
    if ! is_pid_alive "$new_pid"; then
      echo "[mcore-daemon] error: server process exited; see $MCORE_LOG_FILE" >&2
      rm -f "$MCORE_PID_FILE"
      return 1
    fi
    sleep 0.2
    i=$((i + 1))
  done
  echo "[mcore-daemon] warning: server started but port not yet ready after 6s" >&2
  return 1
}

cmd_start() { ensure_mcore_running && echo "mcore running on ${MCORE_HOST}:${MCORE_PORT}"; }

cmd_status() {
  if is_port_listening; then
    echo "mcore: listening on ${MCORE_HOST}:${MCORE_PORT}"
    [ -f "$MCORE_PID_FILE" ] && echo "pid: $(cat "$MCORE_PID_FILE")"
    return 0
  fi
  echo "mcore: not running"
  return 1
}

cmd_stop() {
  if [ -f "$MCORE_PID_FILE" ]; then
    local pid
    pid="$(cat "$MCORE_PID_FILE" 2>/dev/null || echo '')"
    if is_pid_alive "$pid"; then
      kill "$pid" 2>/dev/null || true
      sleep 0.5
      is_pid_alive "$pid" && kill -9 "$pid" 2>/dev/null || true
    fi
    rm -f "$MCORE_PID_FILE"
  fi
  echo "mcore: stopped"
}

if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  case "${1:-start}" in
    start) cmd_start ;;
    status) cmd_status ;;
    stop) cmd_stop ;;
    restart) cmd_stop; cmd_start ;;
    *) echo "usage: $0 {start|status|stop|restart}" >&2; exit 2 ;;
  esac
fi
