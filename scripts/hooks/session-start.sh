#!/usr/bin/env bash
# session-start.sh — Hook: ensure lmmcp is running and mark session start.
# Called by Agent hooks at SessionStart / before_session.
# Exits 0 always; failure must not break agent startup.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lmmcp-daemon.sh" 2>/dev/null || true

LMMCP_PORT="${LMMCP_PORT:-8318}"
LMMCP_HOST="${LMMCP_HOST:-127.0.0.1}"
LMMCP_URL="http://${LMMCP_HOST}:${LMMCP_PORT}/mcp"

ensure_lmmcp_running 2>/dev/null || true

touch /tmp/lmmcp-session-mark 2>/dev/null || true

exit 0
