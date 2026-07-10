"""Safe archival and compaction for device-local audit/governance history."""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from memorycore.models import DEFAULT_ROOT, db_path


@dataclass(frozen=True)
class ArchiveSpec:
    table: str
    time_column: str
    terminal_column: str | None = None
    terminal_values: tuple[str, ...] = ()

    def where(self) -> str:
        clause = f"datetime({self.time_column}) < datetime(?)"
        if self.terminal_column:
            values = ",".join("?" for _ in self.terminal_values)
            clause += f" AND {self.terminal_column} IN ({values})"
        return clause

    def params(self, cutoff: str) -> tuple[str, ...]:
        return (cutoff, *self.terminal_values)


ARCHIVE_SPECS = (
    ArchiveSpec("audit_events", "created_at"),
    ArchiveSpec("governance_decisions", "created_at", "review_status", ("applied", "rejected", "rolled_back")),
    ArchiveSpec("governance_executions", "started_at", "status", ("applied", "completed", "failed", "error", "rolled_back")),
    ArchiveSpec("governance_mutation_log", "created_at", "status", ("applied", "completed", "failed", "error", "rolled_back")),
)

DELETE_ORDER = (
    "governance_mutation_log",
    "governance_executions",
    "governance_decisions",
    "audit_events",
)


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=60000")
    return conn


def _existing_tables(conn: sqlite3.Connection) -> set[str]:
    return {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _estimate_row_bytes(conn: sqlite3.Connection, spec: ArchiveSpec, cutoff: str) -> tuple[int, int]:
    columns = [str(row[1]) for row in conn.execute(f"PRAGMA table_info({spec.table})")]
    size_expr = "+".join(f"IFNULL(LENGTH(quote({column})),0)" for column in columns) or "0"
    row = conn.execute(
        f"SELECT COUNT(*), IFNULL(SUM({size_expr}),0) FROM {spec.table} WHERE {spec.where()}",
        spec.params(cutoff),
    ).fetchone()
    return int(row[0]), int(row[1])


def plan_archive(conn: sqlite3.Connection, cutoff: str) -> dict[str, dict[str, int]]:
    existing = _existing_tables(conn)
    return {
        spec.table: {"rows": rows, "estimated_bytes": estimated_bytes}
        for spec in ARCHIVE_SPECS
        if spec.table in existing
        for rows, estimated_bytes in [_estimate_row_bytes(conn, spec, cutoff)]
    }


def _backup_database(conn: sqlite3.Connection, destination: Path) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(destination) as target:
        conn.backup(target)
    with sqlite3.connect(destination) as check:
        integrity = str(check.execute("PRAGMA quick_check").fetchone()[0])
    if integrity != "ok":
        destination.unlink(missing_ok=True)
        raise RuntimeError(f"backup quick_check failed: {integrity}")
    return {"path": str(destination), "bytes": destination.stat().st_size, "quick_check": integrity}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_table_archive(
    conn: sqlite3.Connection,
    spec: ArchiveSpec,
    cutoff: str,
    destination: Path,
) -> dict[str, Any]:
    rows = conn.execute(
        f"SELECT * FROM {spec.table} WHERE {spec.where()} ORDER BY {spec.time_column}, id",
        spec.params(cutoff),
    )
    count = 0
    uncompressed_bytes = 0
    with destination.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as compressed:
            with io.TextIOWrapper(compressed, encoding="utf-8") as text:
                for row in rows:
                    line = json.dumps(dict(row), ensure_ascii=False, separators=(",", ":")) + "\n"
                    text.write(line)
                    count += 1
                    uncompressed_bytes += len(line.encode("utf-8"))
    return {
        "rows": count,
        "file": destination.name,
        "compressed_bytes": destination.stat().st_size,
        "uncompressed_bytes": uncompressed_bytes,
        "sha256": _sha256(destination),
    }


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def archive_statistics(archive_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(archive_dir) if archive_dir else DEFAULT_ROOT / "backups" / "maintenance-archives"
    manifests = []
    total_rows = 0
    total_bytes = 0
    if root.exists():
        for path in sorted(root.glob("*/manifest.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            rows = sum(int(item.get("rows", 0)) for item in data.get("tables", {}).values())
            size = sum(int(item.get("compressed_bytes", 0)) for item in data.get("tables", {}).values())
            manifests.append({
                "archive": str(path.parent),
                "created_at": data.get("created_at"),
                "cutoff": data.get("cutoff"),
                "applied": bool(data.get("applied")),
                "rows": rows,
                "compressed_bytes": size,
            })
            total_rows += rows
            total_bytes += size
    return {"archive_dir": str(root), "archives": manifests, "total_rows": total_rows, "compressed_bytes": total_bytes}


def run_maintenance(
    *,
    retention_days: int = 30,
    apply: bool = False,
    vacuum: bool = True,
    database: str | Path | None = None,
    archive_dir: str | Path | None = None,
    backup_path: str | Path | None = None,
    current_time: datetime | None = None,
) -> dict[str, Any]:
    if retention_days < 1:
        raise ValueError("retention_days must be at least 1")
    database_path = Path(database) if database else db_path()
    archive_root = Path(archive_dir) if archive_dir else DEFAULT_ROOT / "backups" / "maintenance-archives"
    now_utc = (current_time or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = (now_utc - timedelta(days=retention_days)).isoformat()
    stamp = now_utc.strftime("%Y%m%dT%H%M%S%fZ")
    before_bytes = database_path.stat().st_size

    with _connect(database_path) as conn:
        plan = plan_archive(conn, cutoff)
        result: dict[str, Any] = {
            "dry_run": not apply,
            "retention_days": retention_days,
            "cutoff": cutoff,
            "database": str(database_path),
            "database_bytes_before": before_bytes,
            "tables": plan,
            "planned_rows": sum(item["rows"] for item in plan.values()),
            "estimated_bytes": sum(item["estimated_bytes"] for item in plan.values()),
        }
        if not apply:
            return result
        if result["planned_rows"] == 0:
            result.update({
                "noop": True,
                "deleted": {},
                "vacuumed": False,
                "integrity_check": str(conn.execute("PRAGMA quick_check").fetchone()[0]),
                "database_bytes_after": before_bytes,
            })
            return result

        backup = Path(backup_path) if backup_path else DEFAULT_ROOT / "backups" / f"pre-maintenance-{stamp}.sqlite3"
        result["backup"] = _backup_database(conn, backup)

        temporary_dir = archive_root / f".{stamp}.tmp"
        final_dir = archive_root / stamp
        temporary_dir.mkdir(parents=True, exist_ok=False)
        manifest: dict[str, Any] = {
            "format_version": 1,
            "created_at": now_utc.isoformat(),
            "cutoff": cutoff,
            "retention_days": retention_days,
            "database": str(database_path),
            "device_local": True,
            "import_supported": False,
            "applied": False,
            "tables": {},
        }
        try:
            specs = {spec.table: spec for spec in ARCHIVE_SPECS}
            for table, item in plan.items():
                if item["rows"]:
                    manifest["tables"][table] = _write_table_archive(
                        conn, specs[table], cutoff, temporary_dir / f"{table}.jsonl.gz"
                    )
            _write_manifest(temporary_dir / "manifest.json", manifest)
            archive_root.mkdir(parents=True, exist_ok=True)
            os.replace(temporary_dir, final_dir)
        except Exception:
            shutil.rmtree(temporary_dir, ignore_errors=True)
            raise

        deleted: dict[str, int] = {}
        specs = {spec.table: spec for spec in ARCHIVE_SPECS}
        try:
            conn.execute("BEGIN IMMEDIATE")
            for table in DELETE_ORDER:
                if table not in plan:
                    continue
                spec = specs[table]
                count = int(conn.execute(
                    f"DELETE FROM {table} WHERE {spec.where()}", spec.params(cutoff)
                ).rowcount)
                expected = int(plan[table]["rows"])
                if count != expected:
                    raise RuntimeError(f"{table}: archived {expected} rows but delete matched {count}")
                deleted[table] = count
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        if vacuum:
            conn.execute("VACUUM")
        integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity != "ok":
            raise RuntimeError(f"database integrity_check failed: {integrity}")

        result.update({
            "archive": str(final_dir),
            "deleted": deleted,
            "vacuumed": vacuum,
            "integrity_check": integrity,
            "database_bytes_after": database_path.stat().st_size,
        })
        manifest.update({
            "applied": True,
            "deleted": deleted,
            "vacuumed": vacuum,
            "integrity_check": integrity,
            "database_bytes_before": before_bytes,
            "database_bytes_after": result["database_bytes_after"],
        })
        _write_manifest(final_dir / "manifest.json", manifest)
        return result
