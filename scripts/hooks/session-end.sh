#!/usr/bin/env bash
# session-end.sh — Hook: mark the agent idle when a session ends (Stop / SessionEnd).
# Mirrors session-start.sh's MCP plumbing but only flips presence to idle;
# the backend TTL (24h → idle, 7d → offline) handles the rest.
# Failure must never block agent shutdown.
set -uo pipefail

MCORE_URL="${MCORE_URL:-http://${MCORE_HOST:-127.0.0.1}:${MCORE_PORT:-8318}/mcp}"
AGENT="${MCORE_AGENT_ID:-agent}"
INIT_TIMEOUT="${MCORE_SESSION_END_INIT_TIMEOUT:-2}"
CALL_TIMEOUT="${MCORE_SESSION_END_CALL_TIMEOUT:-2}"

command -v curl >/dev/null 2>&1 || exit 0
command -v python3 >/dev/null 2>&1 || exit 0

# ── 1. initialize to obtain a fresh MCP session id ────────────────────────
INIT_PAYLOAD='{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"mcore-session-end-hook","version":"1.0"}}}'
INIT_RESPONSE="$(curl -sS -i --noproxy "*" --max-time "$INIT_TIMEOUT" -X POST "$MCORE_URL" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d "$INIT_PAYLOAD" 2>/dev/null || true)"

SESSION_ID="$(printf '%s' "$INIT_RESPONSE" | awk -F': ' 'tolower($1)=="mcp-session-id"{gsub(/\r/,"",$2); print $2; exit}')"
[ -z "$SESSION_ID" ] && exit 0

# ── 2. presence idle ──────────────────────────────────────────────────────
PRESENCE_ARGS="$(python3 - "$AGENT" <<'PY' 2>/dev/null || true
import json
import sys

print(json.dumps({
    "agent_id": sys.argv[1],
    "status": "idle",
    "metadata": {"hook": "session-end"},
}, ensure_ascii=False))
PY
)"
[ -z "$PRESENCE_ARGS" ] && exit 0

PAYLOAD="$(python3 - 1 agent_presence_update "$PRESENCE_ARGS" <<'PY' 2>/dev/null || true
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
)"
[ -z "$PAYLOAD" ] && exit 0

curl -sS --noproxy "*" --max-time "$CALL_TIMEOUT" -X POST "$MCORE_URL" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: $SESSION_ID" \
  -d "$PAYLOAD" >/dev/null 2>&1 || true

exit 0