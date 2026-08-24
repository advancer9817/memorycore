"""Safe archival and compaction for device-local audit/governance history."""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import logging
import os
import shutil
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from memorycore.models import DEFAULT_ROOT, as_json, db_path, now
from memorycore.storage.audit import log_audit_event
from memorycore.storage.db import managed_conn, read_conn


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


# ──────────────────────────────────────────────────────────────────────────
# D1 / M1 — Manual data maintenance (archive-only minimal closed loop)
# --------------------------------------------------------------------------
# plan → (plan_token) → execute: backup → archive (single tx) → vector sync
# (cascade via update_status_batch) → audit. Idempotent per plan_token;
# mutually exclusive with the timer curator via a shared flock
# (run_curator.sh acquires the same lockfile).
# ──────────────────────────────────────────────────────────────────────────

DEFAULT_MAINTENANCE_LIMIT = 500
MAINTENANCE_LOCK_NAME = "maintenance.lock"


class MaintenanceBusyError(RuntimeError):
    """Raised when the timer curator or another maintenance job holds the lock."""


def maintenance_lock_path() -> Path:
    return DEFAULT_ROOT / "logs" / MAINTENANCE_LOCK_NAME


@contextmanager
def maintenance_lock(nonblocking: bool = True):
    """Cross-process mutual exclusion shared with run_curator.sh (flock)."""
    import fcntl

    path = maintenance_lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("w")
    try:
        if nonblocking:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise MaintenanceBusyError(
                    "another curator/maintenance job is holding the maintenance lock; "
                    "try again after it finishes"
                ) from None
        else:
            fcntl.flock(handle, fcntl.LOCK_EX)
        yield handle
    finally:
        try:
            fcntl.flock(handle, fcntl.LOCK_UN)
        except Exception:
            pass
        handle.close()


def plan_data_maintenance(limit: int = DEFAULT_MAINTENANCE_LIMIT) -> dict[str, Any]:
    """Read-only archive plan for the manual maintenance loop (M1).

    Reuses the rule curator's scan (curator_report, dry-run) and keeps only
    archive transitions. No writes of any kind happen here.
    """
    from memorycore.storage.curator import curator_report

    cap = max(1, min(int(limit), 5000))
    report = curator_report(dry_run=True, limit=cap)
    planned = [p for p in report.get("action_plan", []) if p.get("action") == "archive"]
    archive_ids = [p["id"] for p in planned]
    token_source = "|".join(sorted(archive_ids)) if archive_ids else "__empty__"
    plan_token = hashlib.sha256(token_source.encode("utf-8")).hexdigest()[:24]
    groups: dict[str, dict[str, Any]] = {}
    for p in planned:
        reason = str(p.get("reason") or "archive")
        group = groups.setdefault(reason, {"reason": reason, "count": 0, "samples": []})
        group["count"] += 1
        if len(group["samples"]) < 5 and p.get("title"):
            group["samples"].append({"id": p["id"], "title": p["title"]})
    return {
        "dry_run": True,
        "generated_at": now(),
        "scanned": report.get("scanned", 0),
        "plan_token": plan_token,
        "archive_count": len(archive_ids),
        "archive_ids": archive_ids,
        "groups": list(groups.values()),
        "summary": report.get("summary", {}),
    }


def _job_row_to_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    d = dict(row)
    d["job_id"] = d.get("id")
    d["summary"] = json.loads(d.pop("summary_json") or "{}")
    d["backup_path"] = d.get("backup_path") or None
    d["error"] = d.get("error") or None
    return d


def create_maintenance_job(plan_token: str, kind: str = "archive") -> dict[str, Any]:
    job_id = str(uuid.uuid4())
    ts = now()
    with managed_conn() as conn:
        conn.execute(
            "INSERT INTO maintenance_jobs (id, plan_token, kind, status, summary_json, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (job_id, plan_token, kind, "running", "{}", ts),
        )
    return {
        "job_id": job_id,
        "plan_token": plan_token,
        "kind": kind,
        "status": "running",
        "created_at": ts,
    }


def update_maintenance_job(
    job_id: str,
    *,
    status: str,
    summary: dict[str, Any] | None = None,
    backup_path: str | None = None,
    error: str | None = None,
) -> None:
    with managed_conn() as conn:
        conn.execute(
            "UPDATE maintenance_jobs SET status=?, summary_json=?, backup_path=?, error=?, finished_at=? "
            "WHERE id=?",
            (status, as_json(summary or {}), backup_path or "", error or "", now(), job_id),
        )


def get_maintenance_job(job_id: str) -> dict[str, Any] | None:
    with read_conn() as conn:
        row = conn.execute(
            "SELECT * FROM maintenance_jobs WHERE id=? ORDER BY created_at DESC LIMIT 1",
            (job_id,),
        ).fetchone()
    return _job_row_to_dict(row)


def get_maintenance_job_by_token(plan_token: str) -> dict[str, Any] | None:
    with read_conn() as conn:
        row = conn.execute(
            "SELECT * FROM maintenance_jobs WHERE plan_token=? "
            "ORDER BY CASE status WHEN 'succeeded' THEN 0 WHEN 'failed' THEN 1 ELSE 2 END, "
            "created_at DESC LIMIT 1",
            (plan_token,),
        ).fetchone()
    return _job_row_to_dict(row)


def get_latest_maintenance_job() -> dict[str, Any] | None:
    with read_conn() as conn:
        row = conn.execute(
            "SELECT * FROM maintenance_jobs ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    return _job_row_to_dict(row)


def execute_data_maintenance(
    plan_token: str,
    limit: int = DEFAULT_MAINTENANCE_LIMIT,
) -> dict[str, Any]:
    """Execute a previously planned archive (idempotent per plan_token)."""
    from memorycore.storage.crud import update_status_batch
    from memorycore.storage.transfer import memory_backup

    # Idempotent replay: a job for this exact plan token already succeeded.
    existing = get_maintenance_job_by_token(plan_token)
    if existing and existing.get("status") == "succeeded":
        return {
            "job_id": existing["id"],
            "status": "succeeded",
            "replayed": True,
            "summary": existing.get("summary", {}),
            "backup_path": existing.get("backup_path"),
        }

    plan = plan_data_maintenance(limit=limit)
    if plan["plan_token"] != plan_token:
        raise ValueError(
            "plan_token is stale: the archive candidate set changed since the plan was "
            "generated (e.g. a curator run mutated statuses); run plan again and retry"
        )
    archive_ids = plan["archive_ids"]

    with maintenance_lock(nonblocking=True):
        if not archive_ids:
            log_audit_event(
                "maintenance_archive",
                detail={"plan_token": plan_token, "archived": 0, "noop": True},
            )
            summary = {"archive": 0, "already_clean": True}
            return {"status": "succeeded", "archive": 0, "summary": summary, "backup_path": None}

        backup = memory_backup()
        updates = [(memory_id, "archived") for memory_id in archive_ids]
        # Single caller-owned transaction: status writes + cascade Qdrant sync.
        with managed_conn() as conn:
            update_status_batch(conn, updates)
        log_audit_event(
            "maintenance_archive",
            detail={
                "plan_token": plan_token,
                "archived": len(updates),
                "backup": backup.get("path"),
                "kinds": [{"reason": g["reason"], "count": g["count"]} for g in plan["groups"]],
            },
        )
    summary = {
        "archive": len(updates),
        "backup_path": backup.get("path"),
        "backup_bytes": backup.get("bytes", 0),
        "groups": [{"reason": g["reason"], "count": g["count"]} for g in plan["groups"]],
    }
    return {
        "status": "succeeded",
        "archive": len(updates),
        "summary": summary,
        "backup_path": backup.get("path"),
    }


def run_data_maintenance_job(
    job_id: str,
    plan_token: str,
    limit: int = DEFAULT_MAINTENANCE_LIMIT,
) -> dict[str, Any]:
    """Boundary for the background thread: run execute and record the job row."""
    try:
        result = execute_data_maintenance(plan_token, limit=limit)
        summary = result.get("summary", {})
        backup_path = result.get("backup_path")
        update_maintenance_job(job_id, status="succeeded", summary=summary, backup_path=backup_path)
        return {
            "job_id": job_id,
            "plan_token": plan_token,
            "status": "succeeded",
            "finished_at": now(),
            "summary": summary,
            "backup_path": backup_path,
            "replayed": bool(result.get("replayed")),
        }
    except MaintenanceBusyError as exc:
        message = str(exc)
        update_maintenance_job(job_id, status="failed", error=message)
        return {"job_id": job_id, "plan_token": plan_token, "status": "failed", "error": message}
    except Exception as exc:
        logger = logging.getLogger(__name__)
        logger.exception("maintenance job %s failed", job_id)
        message = f"{type(exc).__name__}: {exc}"
        update_maintenance_job(job_id, status="failed", error=message)
        return {"job_id": job_id, "plan_token": plan_token, "status": "failed", "error": message}
