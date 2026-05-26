"""Export, import, backup, and vector rebuild helpers."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from local_memory_mcp.models import DEFAULT_ROOT, now
from local_memory_mcp.storage.audit import log_audit_event
from local_memory_mcp.storage.db import connect, db_path, managed_conn

SCHEMA_VERSION = 1
_TRANSFER_TABLES = [
    "memories",
    "feedback_events",
    "memory_links",
    "agent_messages",
    "agent_presence",
    "agent_permissions",
]
_TABLE_PK = {
    "memories": "id",
    "feedback_events": "id",
    "memory_links": "id",
    "agent_messages": "id",
    "agent_presence": "agent_id",
    "agent_permissions": "agent_id",
}


def _table_columns(conn, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def _table_rows(conn, table: str) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(f"SELECT * FROM {table}").fetchall()]


def memory_export(include_audit: bool = False) -> dict[str, Any]:
    tables = list(_TRANSFER_TABLES)
    if include_audit:
        tables.append("audit_events")
    data: dict[str, list[dict[str, Any]]] = {}
    with managed_conn() as conn:
        version_row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        schema_version = int(version_row[0] or SCHEMA_VERSION)
        for table in tables:
            data[table] = _table_rows(conn, table)
    return {
        "schema_version": schema_version,
        "exported_at": now(),
        "tables": tables,
        "counts": {table: len(rows) for table, rows in data.items()},
        "data": data,
    }


def memory_import(
    payload: dict[str, Any],
    dry_run: bool = True,
    conflict_policy: str = "skip",
) -> dict[str, Any]:
    schema_version = int(payload.get("schema_version") or 0)
    if schema_version > SCHEMA_VERSION:
        return {"error": "unsupported_schema_version", "schema_version": schema_version, "supported": SCHEMA_VERSION}
    if conflict_policy not in {"skip", "replace"}:
        return {"error": "invalid_conflict_policy", "allowed": ["skip", "replace"]}

    data = payload.get("data") or {}
    conflicts: dict[str, list[str]] = {}
    planned: dict[str, int] = {}
    inserted: dict[str, int] = {}

    with managed_conn() as conn:
        for table in _TRANSFER_TABLES:
            rows = list(data.get(table) or [])
            pk = _TABLE_PK[table]
            ids = [str(row[pk]) for row in rows if pk in row]
            existing: set[str] = set()
            if ids:
                placeholders = ",".join("?" for _ in ids)
                existing = {str(row[0]) for row in conn.execute(
                    f"SELECT {pk} FROM {table} WHERE {pk} IN ({placeholders})",
                    ids,
                ).fetchall()}
            conflicts[table] = [item for item in ids if item in existing]
            candidates = [row for row in rows if conflict_policy == "replace" or str(row.get(pk)) not in existing]
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
                verb = "INSERT OR REPLACE" if conflict_policy == "replace" else "INSERT"
                conn.execute(
                    f"{verb} INTO {table} ({','.join(names)}) VALUES ({placeholders})",
                    [filtered[name] for name in names],
                )
                inserted[table] += 1

    if not dry_run:
        log_audit_event("memory_import", detail={"inserted": inserted, "conflict_policy": conflict_policy})
    return {
        "dry_run": dry_run,
        "applied": not dry_run,
        "conflict_policy": conflict_policy,
        "conflicts": conflicts,
        "planned": planned,
        "inserted": inserted,
    }


def memory_backup(path: str | None = None) -> dict[str, Any]:
    destination = Path(path) if path else DEFAULT_ROOT / "backups" / f"memory-{now().replace(':', '').replace('+', 'Z')}.sqlite3"
    destination = destination.expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    source = connect()
    with sqlite3.connect(destination) as target:
        source.backup(target)
    log_audit_event("memory_backup", detail={"path": str(destination)})
    return {"path": str(destination), "bytes": destination.stat().st_size}


def memory_rebuild_vectors(dry_run: bool = True, limit: int = 5000) -> dict[str, Any]:
    from local_memory_mcp.storage.crud import _sync_to_vector

    cap = max(1, min(int(limit), 5000))
    with managed_conn() as conn:
        rows = [dict(row) for row in conn.execute(
            "SELECT * FROM memories WHERE status != 'archived' ORDER BY updated_at DESC LIMIT ?",
            (cap,),
        ).fetchall()]
    if dry_run:
        return {"dry_run": True, "planned": len(rows), "rebuilt": 0}
    rebuilt = 0
    for row in rows:
        _sync_to_vector(row)
        rebuilt += 1
    log_audit_event("memory_vector_rebuild", detail={"rebuilt": rebuilt})
    return {"dry_run": False, "planned": len(rows), "rebuilt": rebuilt}
