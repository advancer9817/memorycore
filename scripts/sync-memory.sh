#!/usr/bin/env bash
# sync-memory.sh — 多设备记忆同步脚本
#
# 用法:
#   scripts/sync-memory.sh push          # 导出 → git commit → git push
#   scripts/sync-memory.sh pull          # git pull → import (--conflict-policy newer)
#   scripts/sync-memory.sh sync          # push 后再 pull (完整双向同步)
#   scripts/sync-memory.sh status        # 查看待同步状态
#
# 环境变量:
#   LMMCP_DIR         本项目根目录 (默认 $HOME/project/local-memory-mcp)
#   LMMCP_PYTHON      Python 解释器 (默认 $LMMCP_DIR/.venv/bin/python)
#   LOCAL_MEMORY_DB   SQLite 数据库路径 (默认由 lmmcp 自动确定)
#   SYNC_FILE         导出文件名 (默认 memory-sync/memories.json)
#   SYNC_REMOTE       git remote (默认 origin)
#   SYNC_BRANCH       git branch (默认当前分支)
#   SYNC_DEVICE       设备标识，写入 commit message (默认 hostname)
#
# 同步策略:
#   - 导出时只导出 memories/feedback_events/memory_links (--memories-only)
#   - 导入时使用 --conflict-policy newer：两端同一条记忆取 updated_at 更新的
#   - agent_messages / presence / permissions 不参与同步（设备私有运行时状态）
#   - context_quality_events / audit_events 不参与同步（设备私有日志）

set -euo pipefail

LMMCP_DIR="${LMMCP_DIR:-$HOME/project/local-memory-mcp}"
LMMCP_PYTHON="${LMMCP_PYTHON:-$LMMCP_DIR/.venv/bin/python}"
SYNC_FILE="${SYNC_FILE:-memory-sync/memories.json}"
SYNC_REMOTE="${SYNC_REMOTE:-origin}"
SYNC_BRANCH="${SYNC_BRANCH:-$(git -C "$LMMCP_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)}"
SYNC_DEVICE="${SYNC_DEVICE:-$(hostname -s 2>/dev/null || echo unknown)}"

PY="$LMMCP_PYTHON"
CMD="$1"
SYNC_PATH="$LMMCP_DIR/$SYNC_FILE"

_log() { echo "[sync-memory] $*" >&2; }
_die() { echo "[sync-memory] ERROR: $*" >&2; exit 1; }

_check_env() {
    [[ -x "$PY" ]] || _die "Python not found at $PY. Set LMMCP_PYTHON or run: cd $LMMCP_DIR && python3.11 -m venv .venv && .venv/bin/pip install -e ."
    [[ -d "$LMMCP_DIR/.git" ]] || _die "$LMMCP_DIR is not a git repository"
}

_do_push() {
    _log "Exporting memories (--memories-only) ..."
    mkdir -p "$(dirname "$SYNC_PATH")"
    "$PY" -m memorycore export "$SYNC_PATH" --memories-only 2>&1

    cd "$LMMCP_DIR"
    if git diff --quiet "$SYNC_FILE" 2>/dev/null && git ls-files --error-unmatch "$SYNC_FILE" &>/dev/null; then
        _log "No changes in $SYNC_FILE, skipping commit."
        return 0
    fi

    git add "$SYNC_FILE"
    TIMESTAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    COUNT="$(python3 -c "import json,sys; d=json.load(open('$SYNC_FILE')); print(d['counts'].get('memories',0))" 2>/dev/null || echo '?')"
    git commit -m "chore(memory-sync): $SYNC_DEVICE @ $TIMESTAMP — ${COUNT} memories"
    _log "Pushing to $SYNC_REMOTE/$SYNC_BRANCH ..."
    git push "$SYNC_REMOTE" "$SYNC_BRANCH"
    _log "Push complete."
}

_do_pull() {
    cd "$LMMCP_DIR"
    _log "Pulling from $SYNC_REMOTE/$SYNC_BRANCH ..."
    git pull "$SYNC_REMOTE" "$SYNC_BRANCH" --ff-only || {
        _log "WARNING: fast-forward failed. Run 'git pull --rebase' manually if needed."
        return 1
    }

    if [[ ! -f "$SYNC_PATH" ]]; then
        _log "No sync file found at $SYNC_PATH, nothing to import."
        return 0
    fi

    _log "Dry-run import (conflict_policy=newer) ..."
    "$PY" -m memorycore import "$SYNC_PATH" --conflict-policy newer 2>&1

    echo ""
    read -r -p "[sync-memory] Apply import? (y/N) " answer
    if [[ "${answer,,}" == "y" ]]; then
        "$PY" -m memorycore import "$SYNC_PATH" --conflict-policy newer --apply 2>&1
        _log "Import applied."
    else
        _log "Import skipped (dry-run only)."
    fi
}

_do_status() {
    cd "$LMMCP_DIR"
    _log "Git status for sync file:"
    git status "$SYNC_FILE" 2>/dev/null || true
    _log "Remote ahead/behind:"
    git fetch "$SYNC_REMOTE" "$SYNC_BRANCH" --quiet 2>/dev/null || true
    git rev-list --left-right --count "HEAD...$SYNC_REMOTE/$SYNC_BRANCH" 2>/dev/null || true
    _log "Local memory stats:"
    "$PY" -c "
import json, sys
sys.path.insert(0, '$LMMCP_DIR')
from memorycore.storage.crud import get_memory_stats
s = get_memory_stats()
print(f'  total={s[\"total\"]}  by_status={s[\"by_status\"]}')
" 2>/dev/null || true
}

_check_env

case "$CMD" in
    push)   _do_push ;;
    pull)   _do_pull ;;
    sync)   _do_push && _do_pull ;;
    status) _do_status ;;
    *)
        echo "Usage: $0 push|pull|sync|status"
        echo ""
        echo "  push   Export memories and push to git remote"
        echo "  pull   Pull from git remote and import memories"
        echo "  sync   push then pull (full bidirectional sync)"
        echo "  status Show sync status and local memory stats"
        exit 1
        ;;
esac
