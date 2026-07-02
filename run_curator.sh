#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$ROOT/.venv/bin/python"
SERVER="$ROOT/memorycore"
OUT_DIR="$ROOT/reports"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
mkdir -p "$OUT_DIR"
# Auto-cleanup: remove reports older than 7 days
find "$OUT_DIR" -name "*.json" -mtime +7 -delete 2>/dev/null || true
TS="$(date -u +%Y%m%dT%H%M%SZ)"
REPORT="$OUT_DIR/curator-$TS.json"
LLM_REPORT="$OUT_DIR/llm-curator-$TS.json"

truthy_flag() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|y|Y|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

append_apply_flag() {
  local var_name="$1"
  local value="${2:-}"
  local -n flags_ref="$3"
  case "$value" in
    1|true|TRUE|yes|YES|y|Y|on|ON)
      flags_ref=(--apply)
      ;;
    ""|0|false|FALSE|no|NO|n|N|off|OFF)
      ;;
    *)
      echo "Refusing ambiguous ${var_name}=${value}; use 1/true/yes to apply." >&2
      exit 2
      ;;
  esac
}

APPLY_FLAG=()
append_apply_flag "LOCAL_MEMORY_CURATOR_APPLY" "${LOCAL_MEMORY_CURATOR_APPLY:-}" APPLY_FLAG

"$PY" "$SERVER" curator --limit "${LOCAL_MEMORY_CURATOR_LIMIT:-500}" \
  --stale-after-days "${LOCAL_MEMORY_STALE_AFTER_DAYS:-60}" \
  --archive-after-days "${LOCAL_MEMORY_ARCHIVE_AFTER_DAYS:-120}" \
  "${APPLY_FLAG[@]}" > "$REPORT"

LLM_ENABLED="${LOCAL_MEMORY_LLM_CURATOR_ENABLED:-1}"
if truthy_flag "$LLM_ENABLED"; then
  # Skip if an LLM curator job is already running (prevents service-restart interruption)
  LLM_RUNNING=$("$PY" -c "
import json, urllib.request
try:
    r = urllib.request.urlopen('http://127.0.0.1:${MCORE_PORT:-8318}/api/curator/llm/latest', timeout=3)
    d = json.loads(r.read())
    s = (d.get('data') or d).get('status', '')
    print('1' if s == 'running' else '0')
except Exception:
    print('0')
" 2>/dev/null || echo "0")
  if [ "$LLM_RUNNING" = "1" ]; then
    echo "[mcore] LLM curator job already running — skipping this round" >&2
  else
    LLM_APPLY_FLAG=()
    append_apply_flag \
      "LOCAL_MEMORY_LLM_CURATOR_APPLY" \
      "${LOCAL_MEMORY_LLM_CURATOR_APPLY:-${LOCAL_MEMORY_CURATOR_APPLY:-}}" \
      LLM_APPLY_FLAG
    "$PY" "$SERVER" llm-curator --limit "${LOCAL_MEMORY_LLM_CURATOR_LIMIT:-200}" \
      --sim-threshold "${LOCAL_MEMORY_LLM_CURATOR_SIM_THRESHOLD:-0.72}" \
      "${LLM_APPLY_FLAG[@]}" > "$LLM_REPORT"
  fi
fi

"$PY" "$SERVER" html "$ROOT/dashboard.html" >/dev/null

python3 - "$REPORT" "${LLM_REPORT:-}" "$LLM_ENABLED" <<'PY'
import json, sys
path = sys.argv[1]
llm_path = sys.argv[2]
llm_enabled = sys.argv[3]
with open(path, 'r', encoding='utf-8') as f:
    data = json.load(f)
summary = data.get('summary', {})
print(f"local-memory curator report: {path}")
print(json.dumps(summary, ensure_ascii=False, indent=2))
if data.get('skill_promotion_candidates'):
    print('\nskill_candidate promotion candidates:')
    for item in data['skill_promotion_candidates'][:10]:
        print(f"- {item.get('id')} | {item.get('title')}")
if data.get('contradiction_candidates'):
    print('\ncontradiction candidates:')
    for item in data['contradiction_candidates'][:10]:
        print(f"- {item.get('title_key')}")
if llm_enabled.lower() in {'1', 'true', 'yes', 'y', 'on'} and llm_path:
    with open(llm_path, 'r', encoding='utf-8') as f:
        llm_data = json.load(f)
    print(f"\nlocal-memory LLM curator report: {llm_path}")
    print(json.dumps(llm_data.get('summary', {}), ensure_ascii=False, indent=2))
    if llm_data.get('errors'):
        print('\nLLM curator warnings/errors:')
        for error in llm_data['errors'][:10]:
            print(f"- {error}")
PY
