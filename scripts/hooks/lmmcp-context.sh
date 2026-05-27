#!/usr/bin/env bash
set -uo pipefail

LMMCP_PORT="${LMMCP_PORT:-8318}"
LMMCP_HOST="${LMMCP_HOST:-127.0.0.1}"
LMMCP_URL="http://${LMMCP_HOST}:${LMMCP_PORT}/mcp"
AGENT="${LMMCP_AGENT_ID:-claude}"

STDIN_JSON="$(cat)"

PROMPT="$(printf '%s' "$STDIN_JSON" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    data = {}
prompt = (
    data.get("tool_input", {}).get("prompt")
    or data.get("prompt")
    or data.get("message")
    or ""
)
print(str(prompt))
' 2>/dev/null || true)"

touch /tmp/lmmcp-session-mark 2>/dev/null || true

[ -z "$PROMPT" ] && exit 0

if command -v ss >/dev/null 2>&1; then
  ss -tln 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${LMMCP_PORT}$" || exit 0
fi

PAYLOAD="$(python3 -c '
import json, sys
prompt = sys.argv[1][:300]
payload = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
        "name": "memory_context",
        "arguments": {
            "task": prompt,
            "agent": sys.argv[2],
            "token_budget": 1500,
        },
    },
}
print(json.dumps(payload, ensure_ascii=False))
' "$PROMPT" "$AGENT" 2>/dev/null || true)"

[ -z "$PAYLOAD" ] && exit 0

RESPONSE="$(curl -sf --max-time 1.8 -X POST "$LMMCP_URL" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" 2>/dev/null || true)"

[ -z "$RESPONSE" ] && exit 0

CONTEXT="$(printf '%s' "$RESPONSE" | python3 -c '
import json, sys
try:
    resp = json.load(sys.stdin)
    content = resp.get("result", {}).get("content", [])
    text = content[0].get("text", "") if content else ""
    try:
        inner = json.loads(text)
    except Exception:
        inner = {"context": text}
    ctx = inner.get("context") or inner.get("text") or ""
    if str(ctx).strip():
        print(str(ctx))
except Exception:
    pass
' 2>/dev/null || true)"

[ -z "$CONTEXT" ] && exit 0

python3 -c '
import json, sys
print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": sys.argv[1],
    }
}, ensure_ascii=False))
' "$CONTEXT" 2>/dev/null || true

exit 0
