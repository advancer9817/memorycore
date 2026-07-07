#!/usr/bin/env bash
# mcore 全量备份到 Google Drive
# 用途：导出 mcore --full 数据并通过 rclone 同步到 gdriver:mcore-backup/
# 可直接调用，也可被 git 钩子调用
set -euo pipefail

MCORE_DIR="${MCORE_DIR:-$HOME/project/memorycore}"
PYTHON="${MCORE_PYTHON:-$MCORE_DIR/.venv/bin/python}"
BACKUP_DIR="$MCORE_DIR/.gdrive-backup"
REMOTE="gdriver:mcore-backup"
DEVICE="$(hostname -s 2>/dev/null || echo unknown)"
TIMESTAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

mkdir -p "$BACKUP_DIR"

# 1. 导出全量数据（memories + governance + entities + audit + curator state）
EXPORT_FILE="$BACKUP_DIR/memories-full.json"
echo "[gdrive-backup] Exporting full mcore data..." >&2
if ! "$PYTHON" -m memorycore export "$EXPORT_FILE" --full >/dev/null 2>&1; then
    echo "[gdrive-backup] WARNING: mcore export failed, skipping backup." >&2
    exit 0
fi

# 2. 写入元数据文件
cat > "$BACKUP_DIR/backup-meta.json" << METAEOF
{
  "device": "$DEVICE",
  "timestamp": "$TIMESTAMP",
  "source": "$MCORE_DIR"
}
METAEOF

# 3. 同步到 Google Drive（非阻塞，后台执行）
echo "[gdrive-backup] Syncing to $REMOTE ..." >&2
if rclone sync "$BACKUP_DIR" "$REMOTE" --transfers 4 >/dev/null 2>&1; then
    echo "[gdrive-backup] Backup synced to Google Drive ($TIMESTAMP)." >&2
else
    echo "[gdrive-backup] WARNING: rclone sync failed. Local backup at $BACKUP_DIR" >&2
fi
