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

if [ "$MCORE_HOST" = "127.0.0.1" ] || [ "$MCORE_HOST" = "localhost" ]; then
  ensure_mcore_running 2>/dev/null || true
fi

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
INIT_RESPONSE="$(curl -sS -i --noproxy "*" --max-time "$INIT_TIMEOUT" -X POST "$MCORE_URL" \
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
  curl -sS --noproxy "*" --max-time "$CALL_TIMEOUT" -X POST "$MCORE_URL" \
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

python3 - <<'PY' 2>/dev/null || true
import json
from pathlib import Path
from datetime import datetime

report_file = Path.home() / ".agent-memory" / "last_ingest.json"
if not report_file.exists():
    exit(0)

try:
    data = json.loads(report_file.read_text(encoding="utf-8"))
    if data.get("read", False):
        exit(0)

    ts_str = data.get("timestamp", "")
    if ts_str:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
        if (now - dt).total_seconds() > 86400:
            exit(0)

    data["read"] = True
    report_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    added = data.get("added", 0)
    updated = data.get("updated", 0)
    skipped = data.get("skipped", 0)
    errors = data.get("errors", 0)
    titles = data.get("added_titles", []) or data.get("updated_titles", [])
    title_summary = ("（" + "、".join(titles[:2]) + ("等" if len(titles) > 2 else "") + "）") if titles else ""

    if errors > 0 or data.get("degraded", False):
        err_msg = data.get("error", "外部抽取端点响应异常")
        print(f"\033[33m⚠️ [mcore] 上次会话提炼未完成: {err_msg}，对话记录已暂存待重试\033[0m")
    elif added > 0 or updated > 0:
        action_desc = f"沉淀 {added} 条新事实" if added else ""
        if updated:
            action_desc += f"{'，' if action_desc else ''}更新/废弃 {updated} 条旧规则"
        skip_desc = f"，跳过 {skipped} 条重复" if skipped else ""
        print(f"\033[32m💡 [mcore] 上次会话提炼完成: {action_desc}{title_summary}{skip_desc}。\033[0m")
    else:
        print("\033[36m💤 [mcore] 上次会话已归档: 未发现新增长期规则，保持知识库干净。\033[0m")
except Exception:
    pass
PY

python3 - <<'PY' 2>/dev/null || true
import json
from pathlib import Path
from datetime import datetime

digest_file = Path.home() / ".agent-memory" / "last_curator_digest.json"
if not digest_file.exists():
    exit(0)

try:
    data = json.loads(digest_file.read_text(encoding="utf-8"))
    if data.get("read", False) or not data.get("changed", False):
        exit(0)

    ts_str = data.get("timestamp", "")
    if ts_str:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
        if (now - dt).total_seconds() > 86400:
            exit(0)

    data["read"] = True
    digest_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    active_cnt = data.get("active_count", 0)
    details = []
    if data.get("expired_reviews", 0) > 0:
        details.append(f"过期审核 {data['expired_reviews']} 条")
    if data.get("audit_cleaned", 0) > 0:
        details.append(f"清理审计 {data['audit_cleaned']} 条")
    if data.get("quality_cleaned", 0) > 0:
        details.append(f"质检日志 {data['quality_cleaned']} 条")
    if data.get("vector_purged", 0) > 0:
        details.append(f"清除孤儿向量 {data['vector_purged']} 个")
    if data.get("vector_backfilled", 0) > 0:
        details.append(f"补齐向量 {data['vector_backfilled']} 个")

    detail_str = ("，" + "、".join(details)) if details else ""
    print(f"\033[36m🧹 [mcore 晨报] 夜间治理完成: 活跃库容 {active_cnt} 条{detail_str}，系统自检健康。\033[0m")
except Exception:
    pass
PY

exit 0
