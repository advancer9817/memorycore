#!/usr/bin/env bash
# session-end.sh — Hook: extract facts from the latest transcript into lmmcp.
# Called by Agent hooks at SessionEnd / after_session.
# Runs async (backgrounded curl) so it never blocks agent exit.
set -uo pipefail

LMMCP_PORT="${LMMCP_PORT:-8318}"
LMMCP_HOST="${LMMCP_HOST:-127.0.0.1}"
LMMCP_URL="http://${LMMCP_HOST}:${LMMCP_PORT}/mcp"
AGENT="${LMMCP_AGENT_ID:-unknown}"

if ! ss -tln 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${LMMCP_PORT}$"; then
  exit 0
fi

find_transcript() {
  local f=""
  if [ -n "${CLAUDE_SESSION_FILE:-}" ] && [ -f "$CLAUDE_SESSION_FILE" ]; then
    echo "$CLAUDE_SESSION_FILE"; return
  fi
  f=$(find ~/.claude/projects -name "*.jsonl" -newer /tmp/lmmcp-session-mark 2>/dev/null | head -1)
  [ -n "$f" ] && echo "$f" && return
  f=$(ls -t ~/.claude/projects/*/*.jsonl 2>/dev/null | head -1)
  [ -n "$f" ] && echo "$f"
}

TRANSCRIPT="$(find_transcript)"
[ -z "$TRANSCRIPT" ] && exit 0
[ ! -f "$TRANSCRIPT" ] && exit 0

MESSAGES=$(tail -300 "$TRANSCRIPT" | python3 -c "
import sys, json
msgs = []
for line in sys.stdin:
    line = line.strip()
    if not line: continue
    try:
        obj = json.loads(line)
        msg = obj.get('message', obj)
        role = msg.get('role', '')
        content = msg.get('content', '')
        if isinstance(content, list):
            content = ' '.join(
                b.get('text', '') for b in content
                if isinstance(b, dict) and b.get('type') == 'text'
            )
        if role in ('user', 'assistant') and content:
            msgs.append({'role': role, 'content': content[:800]})
    except Exception:
        pass
print(json.dumps(msgs[-40:]))
" 2>/dev/null)

[ -z "$MESSAGES" ] || [ "$MESSAGES" = "[]" ] && exit 0

curl -sf -X POST "$LMMCP_URL" \
  -H "Content-Type: application/json" \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{\"name\":\"memory_ingest\",\"arguments\":{\"messages\":$MESSAGES,\"agent_id\":\"$AGENT\"}}}" \
  > /dev/null 2>&1 &

exit 0
