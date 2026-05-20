#!/usr/bin/env bash
# lmmcp-daemon.sh — Idempotent lmmcp HTTP server lifecycle manager.
# Usage:
#   bash lmmcp-daemon.sh start    # ensure server is running
#   bash lmmcp-daemon.sh status   # check if server is healthy
#   bash lmmcp-daemon.sh stop     # stop the server
#   source lmmcp-daemon.sh && ensure_lmmcp_running   # used by hooks
set -euo pipefail

LMMCP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LMMCP_PORT="${LMMCP_PORT:-8318}"
LMMCP_HOST="${LMMCP_HOST:-127.0.0.1}"
LMMCP_PID_FILE="${LMMCP_PID_FILE:-/tmp/lmmcp.pid}"
LMMCP_LOG_FILE="${LMMCP_LOG_FILE:-/tmp/lmmcp.log}"
LMMCP_HEALTH_URL="http://${LMMCP_HOST}:${LMMCP_PORT}/mcp"

is_port_listening() {
  if command -v ss >/dev/null 2>&1; then
    ss -tln 2>/dev/null | awk '{print $4}' | grep -E "[:.]${LMMCP_PORT}$" >/dev/null 2>&1
  elif command -v netstat >/dev/null 2>&1; then
    netstat -tln 2>/dev/null | awk '{print $4}' | grep -E "[:.]${LMMCP_PORT}$" >/dev/null 2>&1
  else
    bash -c "exec 3<>/dev/tcp/${LMMCP_HOST}/${LMMCP_PORT}" 2>/dev/null && exec 3>&- 3<&-
  fi
}

is_pid_alive() {
  local pid="${1:-}"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

ensure_lmmcp_running() {
  if is_port_listening; then
    return 0
  fi
  if [ -f "$LMMCP_PID_FILE" ]; then
    local old_pid
    old_pid="$(cat "$LMMCP_PID_FILE" 2>/dev/null || echo '')"
    if is_pid_alive "$old_pid"; then
      sleep 1
      is_port_listening && return 0
    fi
    rm -f "$LMMCP_PID_FILE"
  fi
  if [ ! -x "$LMMCP_ROOT/.venv/bin/python" ]; then
    echo "[lmmcp-daemon] error: venv not found at $LMMCP_ROOT/.venv" >&2
    return 1
  fi
  cd "$LMMCP_ROOT"
  nohup "$LMMCP_ROOT/.venv/bin/python" -m local_memory_mcp serve --host "$LMMCP_HOST" --port "$LMMCP_PORT" \
    >>"$LMMCP_LOG_FILE" 2>&1 &
  local new_pid=$!
  echo "$new_pid" > "$LMMCP_PID_FILE"
  local i=0
  while [ $i -lt 30 ]; do
    if is_port_listening; then
      return 0
    fi
    if ! is_pid_alive "$new_pid"; then
      echo "[lmmcp-daemon] error: server process exited; see $LMMCP_LOG_FILE" >&2
      rm -f "$LMMCP_PID_FILE"
      return 1
    fi
    sleep 0.2
    i=$((i + 1))
  done
  echo "[lmmcp-daemon] warning: server started but port not yet ready after 6s" >&2
  return 1
}

cmd_start() { ensure_lmmcp_running && echo "lmmcp running on ${LMMCP_HOST}:${LMMCP_PORT}"; }

cmd_status() {
  if is_port_listening; then
    echo "lmmcp: listening on ${LMMCP_HOST}:${LMMCP_PORT}"
    [ -f "$LMMCP_PID_FILE" ] && echo "pid: $(cat "$LMMCP_PID_FILE")"
    return 0
  fi
  echo "lmmcp: not running"
  return 1
}

cmd_stop() {
  if [ -f "$LMMCP_PID_FILE" ]; then
    local pid
    pid="$(cat "$LMMCP_PID_FILE" 2>/dev/null || echo '')"
    if is_pid_alive "$pid"; then
      kill "$pid" 2>/dev/null || true
      sleep 0.5
      is_pid_alive "$pid" && kill -9 "$pid" 2>/dev/null || true
    fi
    rm -f "$LMMCP_PID_FILE"
  fi
  echo "lmmcp: stopped"
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
