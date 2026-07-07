#!/usr/bin/env bash
# mcore 从 Google Drive 拉取最新全量备份
# 用途：将 gdriver:mcore-backup/ 同步到本地 .gdrive-backup/，不自动导入
# 触发：post-merge 钩子（后台执行），也可手动调用
set -euo pipefail

MCORE_DIR="${MCORE_DIR:-$HOME/project/memorycore}"
BACKUP_DIR="$MCORE_DIR/.gdrive-backup"
REMOTE="gdriver:mcore-backup"

mkdir -p "$BACKUP_DIR"

echo "[gdrive-restore] Pulling latest backup from $REMOTE ..." >&2
if rclone sync "$REMOTE" "$BACKUP_DIR" --transfers 4 >/dev/null 2>&1; then
    META_FILE="$BACKUP_DIR/backup-meta.json"
    if [[ -f "$META_FILE" ]]; then
        TIMESTAMP="$(python3 -c "import json; print(json.load(open('$META_FILE')).get('timestamp','?'))" 2>/dev/null || echo '?')"
        DEVICE="$(python3 -c "import json; print(json.load(open('$META_FILE')).get('device','?'))" 2>/dev/null || echo '?')"
        echo "[gdrive-restore] Pulled backup from device=$DEVICE timestamp=$TIMESTAMP" >&2
    else
        echo "[gdrive-restore] Backup pulled (no meta file found)." >&2
    fi
    echo "[gdrive-restore] Full backup available at: $BACKUP_DIR/memories-full.json" >&2
    echo "[gdrive-restore] To restore: mcore import $BACKUP_DIR/memories-full.json --full-replace --apply" >&2
else
    echo "[gdrive-restore] WARNING: rclone sync failed. Check gdriver mount status." >&2
fi
