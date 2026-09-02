#!/usr/bin/env python3
"""Backfill subject anchors (project_path / scope / project:* tag) for existing memories.

One-off tool for the subject-context iteration. Dry-run by default; ``--apply``
writes changes. High-confidence signals only; weak signals are flagged for
manual review instead of being written automatically.

High-confidence (≥2 signals, or explicit mcore/memorycore mention):
    project_path=<canonical path>, scope=project, tag project:mcore, metadata.subject

Signals: mcore, memorycore, qdrant, 8318, 18318, nomic-embed-text,
memory.sqlite3, memory_entities, entity_search, context_pack, curator_llm,
/storage/, /api/v1/

Usage:
    .venv/bin/python scripts/backfill_subject.py            # dry-run plan
    .venv/bin/python scripts/backfill_subject.py --apply    # execute (backs up DB first)
    .venv/bin/python scripts/backfill_subject.py --limit 500 --apply
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PROJECT_NAME = "mcore"
PROJECT_TAG = f"project:{PROJECT_NAME}"
PROJECT_SCOPE = "project"

STRONG_SIGNALS = [
    "mcore", "memorycore", "memory-core",
    "qdrant", "nomic-embed-text", "memory.sqlite3",
    "memory_entities", "entity_search", "context_pack",
    "curator_llm", "storage/maintenance", "storage/curator",
    ":8318", "/api/v1/", "mcore-ui", "8318/api",
]
SIGNAL_BASE_WEIGHT = {"mcore": 2, "memorycore": 2, "memory-core": 2}  # explicit mention = confident alone

EXCLUDED_STATUSES = {"archived", "superseded"}


def _signals(text: str) -> list[str]:
    low = text.lower()
    return [s for s in STRONG_SIGNALS if s in low]


def _score(signals: list[str]) -> int:
    explicit = [s for s in signals if s in SIGNAL_BASE_WEIGHT]
    if explicit:
        return 2
    return min(len(signals), 2)


def plan(conn: sqlite3.Connection, limit: int) -> dict:
    rows = conn.execute(
        """
        SELECT id, title, content, tags_json, scope, project_path
        FROM memories
        WHERE status NOT IN ('archived', 'superseded')
          AND (project_path IS NULL OR project_path = '')
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.row_factory = sqlite3.Row

    high, weak, already = [], [], []
    for row in rows:
        text = f"{row['title'] or ''}\n{row['content'] or ''}"
        signals = _signals(text)
        if not signals:
            continue
        if _score(signals) >= 2:
            high.append({"id": row["id"], "signals": signals})
        else:
            weak.append({"id": row["id"], "signals": signals})
    return {
        "scanned": len(rows),
        "high_confidence": high,
        "weak_review": weak,
        "protected": already,
    }


def project_root() -> str:
    return str(Path(__file__).resolve().parent.parent)


def apply(conn: sqlite3.Connection, plan_result: dict, dry_run: bool = True) -> dict:
    root = project_root()
    applied, review_flagged = 0, 0
    now_iso = datetime.now().astimezone().isoformat(timespec="seconds")
    for item in plan_result["high_confidence"]:
        if dry_run:
            applied += 1
            continue
        row = conn.execute(
            "SELECT tags_json, metadata_json FROM memories WHERE id = ?", (item["id"],)
        ).fetchone()
        tags = json.loads(row["tags_json"] or "[]")
        meta = json.loads(row["metadata_json"] or "{}") if row["metadata_json"] else {}
        changed = False
        if PROJECT_TAG not in tags:
            tags.append(PROJECT_TAG)
            changed = True
        if meta.get("subject") != PROJECT_NAME:
            meta["subject"] = PROJECT_NAME
            meta["subject_backfilled_at"] = now_iso
            changed = True
        if changed:
            conn.execute(
                "UPDATE memories SET project_path=?, scope=?, tags_json=?, metadata_json=? WHERE id=?",
                (root, PROJECT_SCOPE, json.dumps(tags, ensure_ascii=False),
                 json.dumps(meta, ensure_ascii=False), item["id"]),
            )
            applied += 1
    for item in plan_result["weak_review"]:
        if dry_run:
            review_flagged += 1
            continue
        row = conn.execute(
            "SELECT metadata_json FROM memories WHERE id = ?", (item["id"],)
        ).fetchone()
        meta = json.loads(row["metadata_json"] or "{}") if row["metadata_json"] else {}
        if not meta.get("subject_needs_review"):
            meta["subject_needs_review"] = True
            meta["subject_signals"] = item["signals"]
            conn.execute(
                "UPDATE memories SET metadata_json=? WHERE id=?",
                (json.dumps(meta, ensure_ascii=False), item["id"]),
            )
            review_flagged += 1
    return {"applied": applied, "review_flagged": review_flagged}


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill subject anchors for existing memories (dry-run by default)")
    parser.add_argument("--apply", action="store_true", help="Write changes (creates a backup first)")
    parser.add_argument("--limit", type=int, default=100000, help="Max records to scan")
    parser.add_argument("--json", action="store_true", help="Output plan as JSON")
    args = parser.parse_args()

    from memorycore.models import db_path

    db = Path(db_path())
    if not db.exists():
        print(f"DB not found: {db}")
        return 1

    conn = sqlite3.connect(f"file:{db}?mode=rw", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        plan_result = plan(conn, args.limit)
        if args.json:
            print(json.dumps(plan_result, ensure_ascii=False, indent=2))
            return 0
        print(f"扫描（status 未归档且 project_path 为空）: {plan_result['scanned']} 条")
        print(f"  高置信（将写入 project:{PROJECT_NAME} + path + scope）: {len(plan_result['high_confidence'])}")
        print(f"  弱信号（仅标记 needs_review，不自动写入）: {len(plan_result['weak_review'])}")
        if not args.apply:
            print("\n[DRY-RUN] 未写入任何数据。确认后加 --apply 执行。")
            return 0

        backup = db.with_name(f"memory-backup-before-subject-{time.strftime('%Y%m%d-%H%M%S')}.sqlite3")
        shutil.copy2(db, backup)
        print(f"\n备份: {backup}")
        result = apply(conn, plan_result, dry_run=False)
        conn.commit()
        print(f"写入: project 标注 {result['applied']} 条 | needs_review 标记 {result['review_flagged']} 条")
        print("\n后续步骤：")
        print(f"  1. 重建实体索引/向量: .venv/bin/python -c \"import ...\" 或在 UI/CLI 触发 memory_rebuild_vectors")
        print(f"  2. 抽检: entity_search('{PROJECT_NAME}') 应命中本次标注记录")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
