#!/usr/bin/env bash
set -uo pipefail

MCORE_PORT="${MCORE_PORT:-8318}"
MCORE_HOST="${MCORE_HOST:-127.0.0.1}"
MCORE_URL="http://${MCORE_HOST}:${MCORE_PORT}/mcp"
AGENT="${MCORE_AGENT_ID:-claude}"

STDIN_JSON="$(cat)"

PROMPT="$(printf '%s' "$STDIN_JSON" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    data = {}
tool_input = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
extra = data.get("extra") if isinstance(data.get("extra"), dict) else {}
prompt = (
    tool_input.get("prompt")
    or data.get("prompt")
    or data.get("user_prompt")
    or data.get("message")
    or data.get("input")
    or extra.get("user_message")
    or ""
)
print(str(prompt))
' 2>/dev/null || true)"

PROJECT_PATH="$(printf '%s' "$STDIN_JSON" | python3 -c '
import json, os, sys
try:
    data = json.load(sys.stdin)
except Exception:
    data = {}
extra = data.get("extra") if isinstance(data.get("extra"), dict) else {}
value = (
    data.get("project_path")
    or data.get("cwd")
    or data.get("working_directory")
    or data.get("workspace")
    or extra.get("cwd")
    or extra.get("project_path")
    or os.environ.get("PWD", "")
)
print(str(value))
' 2>/dev/null || true)"

HOOK_EVENT="$(printf '%s' "$STDIN_JSON" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    data = {}
print(str(data.get("hook_event_name") or data.get("hookEventName") or ""))
' 2>/dev/null || true)"

touch /tmp/mcore-session-mark 2>/dev/null || true

[ -z "$PROMPT" ] && exit 0

if command -v ss >/dev/null 2>&1; then
  ss -tln 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${MCORE_PORT}$" || exit 0
fi

INIT_PAYLOAD='{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"mcore-context-hook","version":"1.0"}}}'
INIT_RESPONSE="$(curl -sS -i --max-time 1.0 -X POST "$MCORE_URL" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d "$INIT_PAYLOAD" 2>/dev/null || true)"

SESSION_ID="$(printf '%s' "$INIT_RESPONSE" | awk -F': ' 'tolower($1)=="mcp-session-id"{gsub(/\r/,"",$2); print $2; exit}')"
[ -z "$SESSION_ID" ] && exit 0

PAYLOAD="$(python3 -c '
import json
import sys
prompt = sys.argv[1][:500]
agent = sys.argv[2]
payload = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
        "name": "memory_context",
        "arguments": {"task": prompt, "agent": agent, "project_path": sys.argv[3], "token_budget": 2000},
    },
}
print(json.dumps(payload, ensure_ascii=False))
' "$PROMPT" "$AGENT" "$PROJECT_PATH" 2>/dev/null || true)"

[ -z "$PAYLOAD" ] && exit 0

RESPONSE="$(curl -sS --max-time 3.0 -X POST "$MCORE_URL" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: $SESSION_ID" \
  -d "$PAYLOAD" 2>/dev/null || true)"

CACHE_FILE="/tmp/mcore-last-context-${AGENT}.cache"

[ -z "$RESPONSE" ] && {
  # Fallback: use cached context from last successful call
  [ -f "$CACHE_FILE" ] && CONTEXT="$(cat "$CACHE_FILE" 2>/dev/null || true)" || CONTEXT=""
  [ -z "$CONTEXT" ] && exit 0
  # Skip to output with cached context
  python3 -c '
import json, sys
context = sys.argv[1]
event = sys.argv[2]
if event == "pre_llm_call":
    payload = {"context": context}
else:
    hook_event_name = "BeforeAgent" if event == "BeforeAgent" else "UserPromptSubmit"
    payload = {
        "hookSpecificOutput": {
            "hookEventName": hook_event_name,
            "additionalContext": context,
        }
    }
print(json.dumps(payload, ensure_ascii=False))
' "$CONTEXT" "$HOOK_EVENT" 2>/dev/null || true
  exit 0
}

CONTEXT="$(printf '%s' "$RESPONSE" | python3 -c '
import json
import sys

try:
    body = sys.stdin.read()
    raw = body.strip()
    for line in body.splitlines():
        if line.startswith("data:"):
            raw = line[5:].strip()
            break
    resp = json.loads(raw)
    content = resp.get("result", {}).get("content", [])
    text = content[0].get("text", "") if content else ""
    try:
        inner = json.loads(text)
    except Exception:
        inner = {"context": text}
    ctx = inner.get("context") or inner.get("text") or ""
    used_ids = inner.get("used_ids")
    if isinstance(used_ids, list) and not used_ids:
        ctx = ""
    if str(ctx).strip():
        print(str(ctx))
except Exception:
    pass
' 2>/dev/null || true)"

[ -z "$CONTEXT" ] && exit 0

# Cache successful context for fallback on next timeout
printf '%s' "$CONTEXT" > "$CACHE_FILE" 2>/dev/null || true

python3 -c '
import json, sys
context = sys.argv[1]
event = sys.argv[2]
if event == "pre_llm_call":
    payload = {"context": context}
else:
    hook_event_name = "BeforeAgent" if event == "BeforeAgent" else "UserPromptSubmit"
    payload = {
        "hookSpecificOutput": {
            "hookEventName": hook_event_name,
            "additionalContext": context,
        }
    }
print(json.dumps(payload, ensure_ascii=False))
' "$CONTEXT" "$HOOK_EVENT" 2>/dev/null || true

exit 0
