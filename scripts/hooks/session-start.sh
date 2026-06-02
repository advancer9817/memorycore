#!/usr/bin/env bash
# session-start.sh — Hook: ensure mcore is running and register the agent.
# Called by Agent hooks at SessionStart / before_session.
# Exits 0 always; failure must not break agent startup.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../mcore-daemon.sh" 2>/dev/null || true

MCORE_PORT="${MCORE_PORT:-8318}"
MCORE_HOST="${MCORE_HOST:-127.0.0.1}"
MCORE_URL="http://${MCORE_HOST}:${MCORE_PORT}/mcp"
AGENT="${MCORE_AGENT_ID:-agent}"
NAMESPACE="${MCORE_AGENT_NAMESPACE:-default}"
INIT_TIMEOUT="${MCORE_SESSION_START_INIT_TIMEOUT:-1.5}"
CALL_TIMEOUT="${MCORE_SESSION_START_CALL_TIMEOUT:-1.5}"

ensure_mcore_running 2>/dev/null || true

touch /tmp/mcore-session-mark 2>/dev/null || true

command -v curl >/dev/null 2>&1 || exit 0
command -v python3 >/dev/null 2>&1 || exit 0

case "${AGENT,,}" in
  codex)
    DEFAULT_CAPABILITIES="coding,implementation,tests,debugging,repo"
    ;;
  claude)
    DEFAULT_CAPABILITIES="reasoning,review,documentation,coding"
    ;;
  hermes)
    DEFAULT_CAPABILITIES="planning,orchestration,handoff,memory"
    ;;
  opencode)
    DEFAULT_CAPABILITIES="coding,implementation,tests"
    ;;
  *)
    DEFAULT_CAPABILITIES="memory,collaboration"
    ;;
esac
CAPABILITIES="${MCORE_AGENT_CAPABILITIES:-$DEFAULT_CAPABILITIES}"

INIT_PAYLOAD='{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"mcore-session-start-hook","version":"1.0"}}}'
INIT_RESPONSE="$(curl -sS -i --max-time "$INIT_TIMEOUT" -X POST "$MCORE_URL" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d "$INIT_PAYLOAD" 2>/dev/null || true)"

SESSION_ID="$(printf '%s' "$INIT_RESPONSE" | awk -F': ' 'tolower($1)=="mcp-session-id"{gsub(/\r/,"",$2); print $2; exit}')"
[ -z "$SESSION_ID" ] && exit 0

METADATA_JSON="$(python3 - "$AGENT" "$NAMESPACE" <<'PY' 2>/dev/null || true
import json
import os
import socket
import sys

agent, namespace = sys.argv[1], sys.argv[2]
metadata = {
    "agent": agent,
    "namespace": namespace,
    "hook": "session-start",
    "cwd": os.environ.get("PWD", ""),
    "host": socket.gethostname(),
}
print(json.dumps(metadata, ensure_ascii=False))
PY
)"
[ -z "$METADATA_JSON" ] && exit 0

tool_payload() {
  python3 - "$1" "$2" "$3" <<'PY' 2>/dev/null || true
import json
import sys

request_id = int(sys.argv[1])
tool_name = sys.argv[2]
arguments = json.loads(sys.argv[3])
print(json.dumps({
    "jsonrpc": "2.0",
    "id": request_id,
    "method": "tools/call",
    "params": {"name": tool_name, "arguments": arguments},
}, ensure_ascii=False))
PY
}

call_tool() {
  local request_id="$1"
  local tool_name="$2"
  local arguments="$3"
  local payload
  payload="$(tool_payload "$request_id" "$tool_name" "$arguments")"
  [ -z "$payload" ] && return 0
  curl -sS --max-time "$CALL_TIMEOUT" -X POST "$MCORE_URL" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -H "Mcp-Session-Id: $SESSION_ID" \
    -d "$payload" >/dev/null 2>&1 || true
}

PRESENCE_ARGS="$(python3 - "$AGENT" "$METADATA_JSON" <<'PY' 2>/dev/null || true
import json
import sys

print(json.dumps({
    "agent_id": sys.argv[1],
    "status": "online",
    "metadata": json.loads(sys.argv[2]),
}, ensure_ascii=False))
PY
)"

CAPABILITY_ARGS="$(python3 - "$AGENT" "$NAMESPACE" "$CAPABILITIES" "$METADATA_JSON" <<'PY' 2>/dev/null || true
import json
import sys

caps = [item.strip() for item in sys.argv[3].split(",") if item.strip()]
metadata = json.loads(sys.argv[4])
metadata["capability_source"] = "session-start"
print(json.dumps({
    "agent_id": sys.argv[1],
    "namespace": sys.argv[2] or "default",
    "capabilities": caps,
    "metadata": metadata,
}, ensure_ascii=False))
PY
)"

[ -n "$PRESENCE_ARGS" ] && call_tool 1 agent_presence_update "$PRESENCE_ARGS"
[ -n "$CAPABILITY_ARGS" ] && call_tool 2 agent_capability_register "$CAPABILITY_ARGS"

exit 0
