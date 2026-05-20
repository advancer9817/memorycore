#!/usr/bin/env bash
# session-start.sh — Hook: ensure lmmcp is running, optionally fetch context.
# Called by Agent hooks at SessionStart / before_session.
# Exits 0 always (non-blocking; failure must not break agent startup).
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lmmcp-daemon.sh" 2>/dev/null || true

LMMCP_PORT="${LMMCP_PORT:-8318}"
LMMCP_HOST="${LMMCP_HOST:-127.0.0.1}"
LMMCP_URL="http://${LMMCP_HOST}:${LMMCP_PORT}/mcp"

ensure_lmmcp_running 2>/dev/null || true

TASK="${CLAUDE_TASK:-${HERMES_TASK:-${OPENCODE_TASK:-general}}}"
AGENT="${LMMCP_AGENT_ID:-unknown}"

curl -sf -X POST "$LMMCP_URL" \
  -H "Content-Type: application/json" \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{\"name\":\"memory_context\",\"arguments\":{\"task\":\"$TASK\",\"agent\":\"$AGENT\",\"token_budget\":1500}}}" \
  > /tmp/lmmcp-context.json 2>/dev/null || true

exit 0
