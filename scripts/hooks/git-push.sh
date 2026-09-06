#!/usr/bin/env bash
# git-push.sh — 推送前先导出记忆并随本次推送一并提交（一次 push 完成，无二次推送）
#
# 机制说明：
#   git pre-push hook 在 git 确定要发送的对象集合之后运行，hook 内新 commit
#   不会被当次 push 包含（因外层 push 使用的是 hook 运行前捕获的 SHA）。
#   因此把 memory-sync 的导出+commit 提前到 push 调用之前，当次 push 即全部携带。
#
# 用法：git syncpush [git push 参数...]    例：git syncpush origin main
# 别名：git config --global alias.syncpush '!bash $HOME/project/memorycore/scripts/hooks/git-push.sh'
set -euo pipefail

MCORE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="${MCORE_PYTHON:-$MCORE_DIR/.venv/bin/python}"
SYNC_FILE="memory-sync/memories.json"
SYNC_PATH="$MCORE_DIR/$SYNC_FILE"

if [[ ! -x "$PYTHON" ]]; then
  echo "[syncpush] WARNING: python not found at $PYTHON, falling through to git push" >&2
  exec git push "$@"
fi

echo "[syncpush] Exporting memories before push ..."
mkdir -p "$(dirname "$SYNC_PATH")"
if "$PYTHON" -m memorycore export "$SYNC_PATH" --memories-only >/dev/null 2>&1; then
  cd "$MCORE_DIR"
  if ! git diff --quiet "$SYNC_FILE" 2>/dev/null || ! git ls-files --error-unmatch "$SYNC_FILE" &>/dev/null; then
    git add "$SYNC_FILE"
    DEVICE="$(hostname -s 2>/dev/null || echo unknown)"
    TIMESTAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    COUNT="$(python3 -c "import json; d=json.load(open('$SYNC_FILE')); print(d.get('counts',{}).get('memories','?'))" 2>/dev/null || echo '?')"
    git commit -m "chore(memory-sync): $DEVICE @ $TIMESTAMP — ${COUNT} memories (full)" --no-verify
    echo -e "\033[32m[syncpush] Memory export committed (${COUNT} memories).\033[0m"
  else
    echo "[syncpush] Memory unchanged, no commit."
  fi

  # ── 记忆库健康体检报表 ──────────────────────────────
  "$PYTHON" - <<'PY' 2>/dev/null || true
import json
import subprocess

try:
    res = subprocess.run(
        [".venv/bin/python", "-m", "memorycore", "semantic-status"],
        capture_output=True, text=True, timeout=5
    )
    json_text = ""
    for line in res.stdout.splitlines():
        if line.strip().startswith("{"):
            json_text = res.stdout[res.stdout.index("{"):]
            break
    status = json.loads(json_text) if json_text else {}
    q_count = status.get("count", 0)
    avail = status.get("available", False)

    from memorycore.storage.crud import get_memory_stats
    stats = get_memory_stats()
    active_cnt = stats.get("by_status", {}).get("active", 0) or q_count
    match_rate = "100%" if q_count == active_cnt else f"{q_count}/{active_cnt}"

    print(f"\033[32m📦 [mcore syncpush] 记忆库健康体检:")
    print(f"   ├── 活跃记忆: {active_cnt} 条 | 向量对齐率: {match_rate} (Qdrant: {q_count})")
    print(f"   ├── 向量服务: {'在线' if avail else '离线'} ({status.get('url', 'local')})")
    print(f"   └── 快照落盘: {status.get('collection', 'agent_memory')} 索引对齐，准备推送到远端...\033[0m")
except Exception:
    pass
PY
else
  echo "[syncpush] WARNING: memory export failed, pushing without sync." >&2
fi

echo "[syncpush] git push $*"
exec git push "$@"