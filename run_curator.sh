#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$ROOT/.venv/bin/python"
SERVER="$ROOT/memorycore"
OUT_DIR="$ROOT/reports"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
mkdir -p "$OUT_DIR"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
REPORT="$OUT_DIR/curator-$TS.json"

APPLY_FLAG=()
case "${LOCAL_MEMORY_CURATOR_APPLY:-}" in
  1|true|TRUE|yes|YES|y|Y)
    APPLY_FLAG=(--apply)
    ;;
  ""|0|false|FALSE|no|NO|n|N)
    ;;
  *)
    echo "Refusing ambiguous LOCAL_MEMORY_CURATOR_APPLY=${LOCAL_MEMORY_CURATOR_APPLY}; use 1/true/yes to apply." >&2
    exit 2
    ;;
esac

"$PY" "$SERVER" curator --limit "${LOCAL_MEMORY_CURATOR_LIMIT:-500}" \
  --stale-after-days "${LOCAL_MEMORY_STALE_AFTER_DAYS:-60}" \
  --archive-after-days "${LOCAL_MEMORY_ARCHIVE_AFTER_DAYS:-120}" \
  "${APPLY_FLAG[@]}" > "$REPORT"

"$PY" "$SERVER" html "$ROOT/dashboard.html" >/dev/null

python3 - "$REPORT" <<'PY'
import json, sys
path = sys.argv[1]
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
PY
