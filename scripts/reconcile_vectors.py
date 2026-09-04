#!/usr/bin/env python3
"""Qdrant Vector Store Reconciliation & Orphan Purge Tool.

Audits and synchronizes the Qdrant vector store against the primary SQLite database:
1. Scans all points in Qdrant `agent_memory` collection.
2. Identifies orphan points (ID not in SQLite or SQLite status != active/candidate).
3. Purges orphan points in batches using PointIdsList.
4. Optionally scans SQLite for active memories missing from Qdrant and enqueues/upserts them.
5. Emits audit events and outputs reconciliation metrics.
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

# Ensure project root in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from memorycore.models import db_path, load_config, now
from memorycore.vector_store import get_vector_store

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("reconcile_vectors")


def reconcile_vectors(
    *,
    dry_run: bool = True,
    batch_size: int = 500,
    sync_missing: bool = True,
) -> dict[str, Any]:
    start_time = time.time()
    db_file = db_path()
    logger.info("Opening SQLite DB at: %s", db_file)

    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Query all valid retention statuses in SQLite
    cur.execute("SELECT id, status, title FROM memories")
    all_sqlite_rows = cur.fetchall()
    sqlite_status_map = {r["id"]: r["status"] for r in all_sqlite_rows}
    valid_sqlite_ids = {
        r["id"] for r in all_sqlite_rows if r["status"] in ("active", "candidate")
    }

    logger.info(
        "SQLite state: %d total rows (%d valid retain: active/candidate)",
        len(all_sqlite_rows),
        len(valid_sqlite_ids),
    )

    vs = get_vector_store()
    vs._ensure_init()
    if not vs.available:
        logger.error("Qdrant server unavailable at %s", vs.config.url)
        return {"error": "qdrant_unavailable"}

    client = vs._client
    collection = vs.config.collection
    total_qdrant_points = client.count(collection_name=collection).count
    logger.info("Qdrant collection '%s' points count: %d", collection, total_qdrant_points)

    # 1. Scroll through all points in Qdrant and find orphans
    orphan_ids: list[str] = []
    orphan_reasons: dict[str, int] = {
        "not_in_sqlite": 0,
        "sqlite_archived": 0,
        "sqlite_other_status": 0,
    }
    qdrant_matched_valid_ids: set[str] = set()

    offset = None
    scrolled = 0
    while True:
        points, offset = client.scroll(
            collection_name=collection,
            limit=1000,
            offset=offset,
            with_payload=False,
            with_vectors=False,
        )
        if not points:
            break
        scrolled += len(points)
        for p in points:
            pid = str(p.id)
            if pid not in sqlite_status_map:
                orphan_ids.append(pid)
                orphan_reasons["not_in_sqlite"] += 1
            elif sqlite_status_map[pid] not in ("active", "candidate"):
                orphan_ids.append(pid)
                if sqlite_status_map[pid] == "archived":
                    orphan_reasons["sqlite_archived"] += 1
                else:
                    orphan_reasons["sqlite_other_status"] += 1
            else:
                qdrant_matched_valid_ids.add(pid)

        if offset is None:
            break

    logger.info(
        "Audit finished: %d points scanned. Found %d orphans (%s)",
        scrolled,
        len(orphan_ids),
        orphan_reasons,
    )

    # Check for active SQLite memories missing from Qdrant
    missing_active_ids = list(valid_sqlite_ids - qdrant_matched_valid_ids)
    logger.info("SQLite valid records missing from Qdrant: %d", len(missing_active_ids))

    deleted_count = 0
    if not dry_run and orphan_ids:
        logger.info("Purging %d orphans from Qdrant in batches of %d...", len(orphan_ids), batch_size)
        from qdrant_client.models import PointIdsList

        for i in range(0, len(orphan_ids), batch_size):
            chunk = orphan_ids[i : i + batch_size]
            client.delete(
                collection_name=collection,
                points_selector=PointIdsList(points=chunk),
            )
            deleted_count += len(chunk)
            if deleted_count % 2000 == 0 or deleted_count == len(orphan_ids):
                logger.info("Purged %d / %d orphans...", deleted_count, len(orphan_ids))

        # Log audit event
        try:
            from memorycore.storage.audit import log_audit_event

            log_audit_event(
                "vector_orphan_purge",
                agent="system",
                detail={
                    "purged_count": deleted_count,
                    "reasons": orphan_reasons,
                },
            )
        except Exception as exc:
            logger.warning("Audit logging failed (non-fatal): %s", exc)

    # Optionally resync missing active memories
    resynced_count = 0
    if not dry_run and sync_missing and missing_active_ids:
        logger.info("Backfilling %d active memories into Qdrant...", len(missing_active_ids))
        from memorycore.storage.crud import row_to_dict
        from memorycore.vector_store import embed_text_batch_cached

        cur.execute(
            f"SELECT * FROM memories WHERE id IN ({','.join('?' for _ in missing_active_ids)})",
            missing_active_ids,
        )
        missing_rows = [row_to_dict(r) for r in cur.fetchall()]
        texts = [f"{r.get('title', '')} {r.get('content', '')}".strip() for r in missing_rows]
        vectors = embed_text_batch_cached(texts, vs.config.embed)

        from qdrant_client.models import PointStruct

        points_to_upsert: list[PointStruct] = []
        for r, vec in zip(missing_rows, vectors):
            metadata = r.get("metadata") or {}
            payload = {
                "type": r.get("type", ""),
                "scope": r.get("scope", ""),
                "status": r.get("status", "active"),
                "source_agent": r.get("source_agent", ""),
                "tags": r.get("tags", []),
                "kind": metadata.get("kind", ""),
                "parent_id": metadata.get("parent_id", ""),
            }
            points_to_upsert.append(PointStruct(id=r["id"], vector=vec, payload=payload))

        for i in range(0, len(points_to_upsert), batch_size):
            chunk = points_to_upsert[i : i + batch_size]
            client.upsert(collection_name=collection, points=chunk)
            resynced_count += len(chunk)
        logger.info("Successfully backfilled %d missing memories into Qdrant.", resynced_count)

    elapsed = round(time.time() - start_time, 2)
    final_count = client.count(collection_name=collection).count
    summary = {
        "dry_run": dry_run,
        "scanned_points": scrolled,
        "orphans_found": len(orphan_ids),
        "orphan_reasons": orphan_reasons,
        "orphans_purged": deleted_count,
        "missing_active_in_qdrant": len(missing_active_ids),
        "missing_resynced": resynced_count,
        "initial_qdrant_points": total_qdrant_points,
        "final_qdrant_points": final_count,
        "elapsed_seconds": elapsed,
    }
    return summary


def main():
    parser = argparse.ArgumentParser(description="Qdrant Vector Store Reconciliation & Purge Tool")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually execute orphan purge and sync (default is dry-run only)",
    )
    parser.add_argument(
        "--no-sync-missing",
        action="store_true",
        help="Skip backfilling missing active memories into Qdrant",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Batch size for delete and upsert operations",
    )
    args = parser.parse_args()

    res = reconcile_vectors(
        dry_run=not args.apply,
        batch_size=args.batch_size,
        sync_missing=not args.no_sync_missing,
    )
    import json
    print("\n=== 对账结果报告 ===")
    print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
