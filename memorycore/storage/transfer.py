"""Export, import, backup, and vector rebuild helpers."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from memorycore.models import DEFAULT_ROOT, load_config, now
from memorycore.storage.audit import log_audit_event
from memorycore.storage.db import connect, db_path, managed_conn

SCHEMA_VERSION = 1

# All tables eligible for full backup export
_TRANSFER_TABLES = [
    "memories",
    "feedback_events",
    "memory_links",
    "agent_messages",
    "agent_presence",
]

# Tables that represent durable, cross-device knowledge (used by --memories-only / sync)
_SYNC_TABLES = [
    "memories",
    "feedback_events",
    "memory_links",
]

_TABLE_PK = {
    "memories": "id",
    "feedback_events": "id",
    "memory_links": "id",
    "agent_messages": "id",
    "agent_presence": "agent_id",
}

_CONFLICT_POLICIES = {"skip", "replace", "newer"}
_SYNC_TIMESTAMP_FIELDS = ("updated_at", "created_at", "accessed_at")


def _table_columns(conn, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def _exported_at_for_tables(data: dict[str, list[dict[str, Any]]], tables: list[str]) -> str:
    latest = ""
    for table in tables:
        for row in data.get(table, []):
            for field in _SYNC_TIMESTAMP_FIELDS:
                value = str(row.get(field) or "").strip()
                if value > latest:
                    latest = value
    return latest or now()


def _table_rows(conn, table: str) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(f"SELECT * FROM {table}").fetchall()]


def memory_export(
    include_audit: bool = False,
    memories_only: bool = False,
) -> dict[str, Any]:
    """Export memory data as a schema-versioned JSON-compatible payload.

    Args:
        include_audit: Also export audit_events (large, device-local).
        memories_only: Only export memories/feedback_events/memory_links —
            the durable cross-device knowledge. Skips agent_messages,
            and presence (device-local runtime state).
    """
    if memories_only:
        tables = list(_SYNC_TABLES)
    else:
        tables = list(_TRANSFER_TABLES)
    if include_audit and not memories_only:
        tables.append("audit_events")
    data: dict[str, list[dict[str, Any]]] = {}
    with managed_conn() as conn:
        version_row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        schema_version = int(version_row[0] or SCHEMA_VERSION)
        for table in tables:
            data[table] = _table_rows(conn, table)
    return {
        "schema_version": schema_version,
        "exported_at": _exported_at_for_tables(data, tables) if memories_only else now(),
        "memories_only": memories_only,
        "tables": tables,
        "counts": {table: len(rows) for table, rows in data.items()},
        "data": data,
    }


def memory_import(
    payload: dict[str, Any],
    dry_run: bool = True,
    conflict_policy: str = "skip",
) -> dict[str, Any]:
    """Import a schema-versioned memory payload with dry-run conflict reporting.

    conflict_policy:
        skip    — keep existing row, ignore incoming (default)
        replace — overwrite existing row with incoming unconditionally
        newer   — keep whichever row has the later updated_at timestamp
                  (best for multi-device sync; falls back to skip on ties)
    """
    schema_version = int(payload.get("schema_version") or 0)
    if schema_version > SCHEMA_VERSION:
        return {"error": "unsupported_schema_version", "schema_version": schema_version, "supported": SCHEMA_VERSION}
    if conflict_policy not in _CONFLICT_POLICIES:
        return {"error": "invalid_conflict_policy", "allowed": sorted(_CONFLICT_POLICIES)}

    data = payload.get("data") or {}
    conflicts: dict[str, list[str]] = {}
    newer_wins: dict[str, int] = {}   # incoming rows that won the newer comparison
    planned: dict[str, int] = {}
    inserted: dict[str, int] = {}

    tables_in_payload = [t for t in _TRANSFER_TABLES if t in data]
    ignored_tables = sorted(t for t in data.keys() if t not in _TRANSFER_TABLES)

    with managed_conn() as conn:
        for table in tables_in_payload:
            rows = list(data.get(table) or [])
            pk = _TABLE_PK[table]
            ids = [str(row[pk]) for row in rows if pk in row]
            existing_map: dict[str, dict[str, Any]] = {}
            if ids:
                placeholders = ",".join("?" for _ in ids)
                columns = _table_columns(conn, table)
                for raw in conn.execute(
                    f"SELECT * FROM {table} WHERE {pk} IN ({placeholders})", ids
                ).fetchall():
                    row_dict = dict(zip(columns, raw))
                    existing_map[str(row_dict[pk])] = row_dict

            conflicts[table] = [item for item in ids if item in existing_map]
            newer_wins[table] = 0
            candidates: list[dict[str, Any]] = []

            for row in rows:
                row_pk = str(row.get(pk, ""))
                if row_pk not in existing_map:
                    candidates.append(row)
                    continue
                if conflict_policy == "skip":
                    pass  # not a candidate
                elif conflict_policy == "replace":
                    candidates.append(row)
                elif conflict_policy == "newer":
                    incoming_ts = str(row.get("updated_at") or row.get("created_at") or "")
                    existing_ts = str(existing_map[row_pk].get("updated_at") or existing_map[row_pk].get("created_at") or "")
                    if incoming_ts > existing_ts:
                        candidates.append(row)
                        newer_wins[table] += 1

            planned[table] = len(candidates)
            inserted[table] = 0
            if dry_run:
                continue

            columns = _table_columns(conn, table)
            for row in candidates:
                filtered = {key: row.get(key) for key in columns if key in row}
                if not filtered:
                    continue
                names = list(filtered.keys())
                placeholders = ",".join("?" for _ in names)
                verb = "INSERT OR REPLACE" if conflict_policy in ("replace", "newer") else "INSERT"
                conn.execute(
                    f"{verb} INTO {table} ({','.join(names)}) VALUES ({placeholders})",
                    [filtered[name] for name in names],
                )
                inserted[table] += 1

    if not dry_run:
        log_audit_event("memory_import", detail={
            "inserted": inserted,
            "conflict_policy": conflict_policy,
            "newer_wins": newer_wins,
            "ignored_tables": ignored_tables,
        })
    return {
        "dry_run": dry_run,
        "applied": not dry_run,
        "conflict_policy": conflict_policy,
        "ignored_tables": ignored_tables,
        "conflicts": conflicts,
        "newer_wins": newer_wins,
        "planned": planned,
        "inserted": inserted,
    }


def memory_backup(path: str | None = None) -> dict[str, Any]:
    stamp = now().replace(":", "").replace("+", "p")
    destination = Path(path) if path else DEFAULT_ROOT / "backups" / f"memory-{stamp}.sqlite3"
    destination = destination.expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    source = connect()
    with sqlite3.connect(destination) as target:
        source.backup(target)
    log_audit_event("memory_backup", detail={"path": str(destination)})
    return {"path": str(destination), "bytes": destination.stat().st_size}


def memory_rebuild_vectors(dry_run: bool = True, limit: int = 5000) -> dict[str, Any]:
    from memorycore.storage.crud import row_to_dict
    from memorycore.vector_store import get_vector_store

    cap = max(1, min(int(limit), 5000))
    with managed_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM memories WHERE status != 'archived' ORDER BY updated_at DESC LIMIT ?",
            (cap,),
        ).fetchall()
    if dry_run:
        return {"dry_run": True, "planned": len(rows), "rebuilt": 0}
    cfg = load_config()
    vs = get_vector_store(cfg)
    rebuilt = 0
    errors = 0
    for row in rows:
        record = row_to_dict(row)
        try:
            text = f"{record.get('title', '')} {record.get('content', '')}".strip()
            metadata = record.get("metadata") or {}
            payload = {
                "type": record.get("type", ""),
                "scope": record.get("scope", ""),
                "status": record.get("status", "active"),
                "source_agent": record.get("source_agent", ""),
                "tags": record.get("tags", []),
                "kind": metadata.get("kind", ""),
                "parent_id": metadata.get("parent_id", ""),
            }
            vs.upsert(record["id"], text, payload)
            rebuilt += 1
        except Exception as exc:
            import logging as _logging
            _logging.getLogger(__name__).warning("rebuild_vectors: failed for %s: %s", record["id"], exc)
            errors += 1
    log_audit_event("memory_vector_rebuild", detail={"rebuilt": rebuilt, "errors": errors})
    return {"dry_run": False, "planned": len(rows), "rebuilt": rebuilt, "errors": errors}


def memory_vector_audit(dry_run: bool = True, limit: int = 100) -> dict[str, Any]:
    """Compare active SQLite memories with Qdrant points and optionally rebuild missing points."""
    cap = max(1, min(int(limit), 1000))
    with managed_conn() as conn:
        sqlite_active = int(conn.execute(
            "SELECT COUNT(*) FROM memories WHERE status = 'active'"
        ).fetchone()[0] or 0)
        rows = [dict(row) for row in conn.execute(
            "SELECT * FROM memories WHERE status = 'active' ORDER BY updated_at DESC LIMIT ?",
            (cap,),
        ).fetchall()]
    ids = [str(row["id"]) for row in rows]

    try:
        from memorycore.vector_store import get_vector_store

        vs = get_vector_store(load_config())
        status = vs.status()
        if not status.get("available"):
            return {
                "dry_run": dry_run,
                "available": False,
                "sqlite_active": sqlite_active,
                "checked": len(ids),
                "missing_vectors": ids,
                "rebuilt": 0,
                "status": status,
            }
        client = getattr(vs, "_client", None)
        if client is None or not hasattr(client, "retrieve"):
            return {
                "dry_run": dry_run,
                "available": True,
                "degraded": True,
                "reason": "qdrant client does not expose retrieve",
                "sqlite_active": sqlite_active,
                "checked": len(ids),
                "missing_vectors": [],
                "rebuilt": 0,
                "status": status,
            }
        retrieved = client.retrieve(
            collection_name=vs.config.collection,
            ids=ids,
            with_payload=True,
            with_vectors=False,
        ) if ids else []
        present_ids = {str(point.id) for point in retrieved}
        missing = [memory_id for memory_id in ids if memory_id not in present_ids]
        rebuilt = 0
        if not dry_run and missing:
            from memorycore.storage.crud import _sync_to_vector

            by_id = {str(row["id"]): row for row in rows}
            for memory_id in missing:
                row = by_id.get(memory_id)
                if row is None:
                    continue
                _sync_to_vector(row)
                rebuilt += 1
            log_audit_event("memory_vector_audit", detail={"checked": len(ids), "missing": len(missing), "rebuilt": rebuilt})
        return {
            "dry_run": dry_run,
            "available": True,
            "sqlite_active": sqlite_active,
            "checked": len(ids),
            "missing_vectors": missing,
            "rebuilt": rebuilt,
            "vector_count": status.get("count", 0),
            "dimension": status.get("dim"),
            "collection": status.get("collection"),
            "status": status,
        }
    except Exception as exc:
        return {
            "dry_run": dry_run,
            "available": False,
            "degraded": True,
            "reason": f"{type(exc).__name__}: {exc}",
            "sqlite_active": sqlite_active,
            "checked": len(ids),
            "missing_vectors": ids,
            "rebuilt": 0,
        }
