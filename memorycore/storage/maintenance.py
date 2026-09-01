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

# 0 = 不设条数上限（单次删除/归档/合并可一次处理全部候选）。
# 显式传正整数仍可限制；_resolve_maintenance_cap 统一解释。
DEFAULT_MAINTENANCE_LIMIT = 0
MAINTENANCE_LOCK_NAME = "maintenance.lock"
_MAINTENANCE_CAP_CEILING = 1_000_000  # 无上限时的安全天花板（对记忆库≈不限）


def _resolve_maintenance_cap(limit: int) -> int:
    """Positive limit is honored; 0/negative means no cap (safety ceiling only)."""
    value = int(limit)
    return value if value > 0 else _MAINTENANCE_CAP_CEILING


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


def _archive_extension_config() -> dict[str, Any]:
    """Archive-extension rules (stale/superseded → archived) from config.yaml.

    maintenance.archive_extension:
      enabled: bool (default true)
      min_days_untouched: int (default 90) — last_accessed_at/created_at age gate
    """
    from memorycore.models import load_config

    base = (load_config().get("maintenance", {}) or {}).get("archive_extension", {}) or {}
    return {
        "enabled": bool(base.get("enabled", True)),
        # 30d: stale records untouched for a month are safe to archive
        # (reversible); superseded merges get the same grace period for
        # rollback/audit before leaving the "pending cleanup" backlog.
        "min_days_untouched": max(1, int(base.get("min_days_untouched", 30))),
    }


def _archive_extension_candidates(min_days: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Stale/superseded records untouched for `min_days` → archive candidates.

    These are quality-debt statuses the retrieval layer already filters out;
    archiving them (reversible, backup-first) shrinks the 'pending cleanup'
    backlog reported on the dashboard. Returns (candidates, scanned_rows).
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=min_days)).isoformat(timespec="seconds")
    with read_conn() as conn:
        rows = [
            dict(r)
            for r in conn.execute(
                """
                SELECT id, title, status, created_at,
                       COALESCE(NULLIF(last_accessed_at, ''), created_at) AS last_touch
                FROM memories
                WHERE status IN ('stale', 'superseded')
                """
            ).fetchall()
        ]
    candidates: list[dict[str, Any]] = []
    for r in rows:
        if str(r.get("last_touch") or "") >= cutoff:
            continue  # touched recently — keep for now
        candidates.append({
            "id": r["id"],
            "title": r.get("title") or "",
            "reason": f"archive_extension:{r.get('status')}",
        })
    return candidates, len(rows)


def _contradiction_pair_map() -> tuple[set[str], set[str]]:
    """Older/newer id sets from applied contradiction decisions.

    The LLM contradiction detector records newer_id/older_id in finding_json.
    Decision-backed pairs are adjudicated: the loser archives immediately, the
    winner returns to active. Returns (older_ids, newer_ids).
    """
    older_ids: set[str] = set()
    newer_ids: set[str] = set()
    try:
        with read_conn() as conn:
            rows = conn.execute(
                "SELECT finding_json FROM governance_decisions"
                " WHERE decision_type='contradiction' AND review_status='applied'"
            ).fetchall()
        for (finding_json,) in rows:
            try:
                f = json.loads(finding_json or "{}")
            except Exception:
                continue
            nid = f.get("newer_id")
            oid = f.get("older_id")
            if nid:
                newer_ids.add(nid)
            if oid:
                older_ids.add(oid)
    except Exception:
        pass
    return older_ids, newer_ids


def _contradiction_candidates(
    older_ids: set[str], newer_ids: set[str], min_days: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    """Contradicted records → archive/reactivate per user-approved strategy.

    - Decision-backed loser (contradicted & older_id of an applied decision)
      → archive immediately (the newer side already won the pair).
    - Orphan contradicted (no decision references it) → archive once untouched
      for `min_days` (same gate as stale/superseded).
    - Mis-flagged winner (contradicted & newer_id & never an older_id)
      → reactivate to active (new supersedes old).

    Returns (archive_candidates, reactivate_candidates, scanned).
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=min_days)).isoformat(timespec="seconds")
    with read_conn() as conn:
        rows = [
            dict(r)
            for r in conn.execute(
                """
                SELECT id, title, status, created_at,
                       COALESCE(NULLIF(last_accessed_at, ''), created_at) AS last_touch
                FROM memories
                WHERE status='contradicted'
                """
            ).fetchall()
        ]
    archive: list[dict[str, Any]] = []
    reactivate: list[dict[str, Any]] = []
    for r in rows:
        rid = r["id"]
        if rid in older_ids:
            archive.append({
                "id": rid,
                "title": r.get("title") or "",
                "reason": "archive_extension:contradiction_loser",
            })
        elif rid in newer_ids:
            reactivate.append({
                "id": rid,
                "title": r.get("title") or "",
                "reason": "contradiction_winner",
            })
        elif str(r.get("last_touch") or "") < cutoff:
            archive.append({
                "id": rid,
                "title": r.get("title") or "",
                "reason": "archive_extension:contradiction_orphan",
            })
    return archive, reactivate, len(rows)


def plan_data_maintenance(limit: int = DEFAULT_MAINTENANCE_LIMIT) -> dict[str, Any]:
    """Read-only archive plan for the manual maintenance loop (M1).

    Rule curator scan + archive-extension rules (stale/superseded untouched
    for maintenance.archive_extension.min_days_untouched, default 30 days)
    + contradiction adjudication (losers/orphans → archive, winners → active).
    No writes of any kind happen here.
    """
    from memorycore.storage.curator import curator_report

    cap = _resolve_maintenance_cap(limit)
    cfg = _archive_extension_config()
    report = curator_report(dry_run=True, limit=cap)
    planned = [p for p in report.get("action_plan", []) if p.get("action") == "archive"]
    extension, extension_scanned = (
        _archive_extension_candidates(cfg["min_days_untouched"]) if cfg["enabled"] else ([], 0)
    )
    older_ids, newer_ids = (
        _contradiction_pair_map() if cfg["enabled"] else (set(), set())
    )
    contra_archive, contra_reactivate, contra_scanned = (
        _contradiction_candidates(older_ids, newer_ids, cfg["min_days_untouched"]) if cfg["enabled"] else ([], [], 0)
    )
    # 裁决胜方优先级最高：宁可改归档建议为激活，也不能把胜方归档掉。
    winner_ids = {c["id"] for c in contra_reactivate}
    contra_archive_map = {p["id"]: p for p in contra_archive}
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for p in planned + extension + contra_archive:
        if p["id"] in seen or p["id"] in winner_ids:
            continue
        seen.add(p["id"])
        # 同一记录 curator 与扩展规则都命中时，用扩展规则的原因名（更可读）。
        merged.append(contra_archive_map.get(p["id"], p))
    archive_ids = [p["id"] for p in merged]
    reactivate_ids = [c["id"] for c in contra_reactivate if c["id"] not in seen]
    token_source = "archive|" + ("|".join(sorted(archive_ids)) if archive_ids else "__empty__") \
        + "|active|" + ("|".join(sorted(reactivate_ids)) if reactivate_ids else "__empty__")
    plan_token = hashlib.sha256(token_source.encode("utf-8")).hexdigest()[:24]
    groups: dict[str, dict[str, Any]] = {}
    for p in merged + contra_reactivate:
        reason = str(p.get("reason") or "archive")
        group = groups.setdefault(reason, {"reason": reason, "count": 0, "samples": []})
        group["count"] += 1
        if len(group["samples"]) < 5 and p.get("title"):
            group["samples"].append({"id": p["id"], "title": p["title"]})
    return {
        "dry_run": True,
        "generated_at": now(),
        "scanned": report.get("scanned", 0) + extension_scanned + contra_scanned,
        "plan_token": plan_token,
        "archive_count": len(archive_ids),
        "archive_ids": archive_ids,
        "reactivate_count": len(reactivate_ids),
        "reactivate_ids": reactivate_ids,
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
    reactivate_ids = plan.get("reactivate_ids") or []

    with maintenance_lock(nonblocking=True):
        if not archive_ids and not reactivate_ids:
            log_audit_event(
                "maintenance_archive",
                detail={"plan_token": plan_token, "archived": 0, "noop": True},
            )
            summary = {"archive": 0, "already_clean": True}
            return {"status": "succeeded", "archive": 0, "summary": summary, "backup_path": None}

        backup = memory_backup()
        updates = [(memory_id, "archived") for memory_id in archive_ids]
        updates += [(memory_id, "active") for memory_id in reactivate_ids]
        # Single caller-owned transaction: status writes + cascade Qdrant sync.
        with managed_conn() as conn:
            update_status_batch(conn, updates)
        log_audit_event(
            "maintenance_archive",
            detail={
                "plan_token": plan_token,
                "archived": len(archive_ids),
                "reactivated": len(reactivate_ids),
                "backup": backup.get("path"),
                "kinds": [{"reason": g["reason"], "count": g["count"]} for g in plan["groups"]],
            },
        )
    summary = {
        "archive": len(archive_ids),
        "reactivate": len(reactivate_ids),
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
    action: str = "archive",
) -> dict[str, Any]:
    """Boundary for the background thread: run execute and record the job row.

    `action` selects the maintenance kind: archive (M1), merge (M2), clean (M3).
    """
    try:
        if action == "merge":
            result = execute_data_maintenance_merge(plan_token, limit=limit)
        elif action == "clean":
            result = execute_data_maintenance_clean(plan_token, limit=limit)
        else:
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


# --------------------------------------------------------------------------
# D2 / M2 — deterministic title merge
# --------------------------------------------------------------------------
# plan → (plan_token) → execute: backup → supersede losers (winner keeps its
# status; losers become superseded with lineage via supersede_memory_record) →
# audit. Idempotent per plan_token; shares the maintenance flock with the
# timer curator and M1 (archive). Merge never deletes and never promotes to
# active, so it cannot disturb the retrieval baseline.

MERGE_DEFAULT_LIMIT = 0  # 0 = 无上限（合并候选一次处理）


def _merge_winner_key(row: dict[str, Any]) -> tuple[int, str]:
    """Keeper heuristic: last_accessed > importance > confidence > newer."""
    score = 0
    score = (score << 3) | (1 if row.get("last_accessed_at") else 0)
    score = (score << 3) | max(0, min(7, int(round(float(row.get("importance") or 0.0) * 4))))
    score = (score << 3) | max(0, min(7, int(round(float(row.get("confidence") or 0.0) * 4))))
    return (score, str(row.get("created_at") or ""))


def plan_data_maintenance_merge(limit: int = MERGE_DEFAULT_LIMIT) -> dict[str, Any]:
    """Read-only merge plan: duplicate groups by normalize_title_key.

    Each group keeps its best record (winner); losers would be superseded on
    execute — never deleted, never re-activated.
    """
    from memorycore.models import normalize_title_key

    cap = _resolve_maintenance_cap(limit)
    with read_conn() as conn:
        rows = [
            dict(r)
            for r in conn.execute(
                """
                SELECT id, title, content, status, importance, confidence,
                       created_at, last_accessed_at, source_agent
                FROM memories
                WHERE status IN ('active','candidate')
                ORDER BY created_at ASC
                """
            ).fetchall()
        ]
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        key = normalize_title_key(r.get("title") or "")
        if len(key) < 2:
            continue
        groups.setdefault(key, []).append(r)
    merge_groups: list[dict[str, Any]] = []
    for key, items in groups.items():
        if len(items) < 2:
            continue
        winner = max(items, key=_merge_winner_key)
        losers = [it for it in items if it["id"] != winner["id"]]
        merge_groups.append(
            {
                "key": key,
                "winner_id": winner["id"],
                "winner_title": winner.get("title") or "",
                "count": len(items),
                "loser_ids": [it["id"] for it in losers],
                "loser_titles": [it.get("title") or "" for it in losers],
            }
        )
    merge_groups.sort(key=lambda g: (-g["count"], g["key"]))
    merge_groups = merge_groups[:cap]
    all_ids = sorted(
        {i for g in merge_groups for i in g["loser_ids"]} | {g["winner_id"] for g in merge_groups}
    )
    token_source = "merge|" + ("|".join(all_ids) if all_ids else "__empty__")
    plan_token = hashlib.sha256(token_source.encode("utf-8")).hexdigest()[:24]
    loser_count = sum(len(g["loser_ids"]) for g in merge_groups)
    return {
        "dry_run": True,
        "generated_at": now(),
        "scanned": len(rows),
        "plan_token": plan_token,
        "merge_count": len(merge_groups),
        "merge_groups": merge_groups,
        "loser_count": loser_count,
        "summary": {"merge": len(merge_groups), "losers": loser_count, "scanned": len(rows)},
    }


def execute_data_maintenance_merge(plan_token: str, limit: int = MERGE_DEFAULT_LIMIT) -> dict[str, Any]:
    """Execute a previously planned merge (idempotent per plan_token)."""
    from memorycore.storage.crud import supersede_memory_record
    from memorycore.storage.transfer import memory_backup

    existing = get_maintenance_job_by_token(plan_token)
    if existing and existing.get("status") == "succeeded":
        return {
            "job_id": existing["id"],
            "status": "succeeded",
            "replayed": True,
            "summary": existing.get("summary", {}),
            "backup_path": existing.get("backup_path"),
        }

    plan = plan_data_maintenance_merge(limit=limit)
    if plan["plan_token"] != plan_token:
        raise ValueError(
            "plan_token is stale: the merge candidate set changed since the plan was "
            "generated; run plan again and retry"
        )
    groups = plan["merge_groups"]

    with maintenance_lock(nonblocking=True):
        if not groups:
            log_audit_event("maintenance_merge", detail={"plan_token": plan_token, "merged": 0, "noop": True})
            summary = {"merge": 0, "already_clean": True}
            return {"status": "succeeded", "merged": 0, "summary": summary, "backup_path": None}
        backup = memory_backup()
        merged = 0
        processed: list[dict[str, str]] = []
        for g in groups:
            winner_id = g["winner_id"]
            group_ids = [winner_id] + g["loser_ids"]
            # Unify the lineage root BEFORE superseding: supersede_memory_record
            # rebinds the new record's fact_lineage_root to the old record's
            # root on every call, so without pre-unification the second loser
            # would fail the "lineage merge requires human review" guard.
            placeholders = ",".join("?" for _ in group_ids)
            with managed_conn() as conn:
                conn.execute(
                    f"UPDATE memories SET fact_lineage_root=? WHERE id IN ({placeholders})",
                    (winner_id, *group_ids),
                )
            for loser_id in g["loser_ids"]:
                supersede_memory_record(
                    old_id=loser_id,
                    new_id=winner_id,
                    note="maintenance merge: deterministic title normalization",
                    source_agent="maintenance",
                )
                merged += 1
                processed.append({"loser": loser_id, "winner": winner_id})
        log_audit_event(
            "maintenance_merge",
            detail={
                "plan_token": plan_token,
                "merged": merged,
                "groups": len(groups),
                "backup": backup.get("path"),
                "processed": processed[:200],
            },
        )
    summary = {
        "merge": len(groups),
        "losers": merged,
        "backup_path": backup.get("path"),
        "backup_bytes": backup.get("bytes", 0),
    }
    return {"status": "succeeded", "merged": merged, "summary": summary, "backup_path": backup.get("path")}


# --------------------------------------------------------------------------
# D3 / M3 — whitelist clean (hard delete; backup + explicit confirmation)
# --------------------------------------------------------------------------
# plan → (plan_token) → execute: backup (mandatory) → hard-delete each
# candidate (SQLite row + FTS via trigger + Qdrant point + vector_cache
# entries) → audit. Only whitelisted patterns are ever considered:
#   1) candidate records older than a TTL;
#   2) test-agent data (source_agent blacklist, configurable);
#   3) near-empty fragment candidates.
# Protected: records with a positive effectiveness/access and importance ≥ 0.9.

CLEAN_DEFAULT_LIMIT = 0  # 0 = 无上限（删除候选一次处理，备份先行）
CLEAN_DEFAULT_TTL_DAYS = 30
CLEAN_DEFAULT_MIN_CONTENT_CHARS = 5
CLEAN_SOURCE_AGENT_BLACKLIST = (
    "memorycore-smoke-test",
    "smoke-test",
    "integration-test",
    "manual-test",
    "test",
)


def _clean_config() -> dict[str, Any]:
    from memorycore.models import load_config

    base = (load_config().get("maintenance", {}) or {}).get("clean", {}) or {}
    # User prefers aggressive cleanup: archived junk (never accessed, never
    # injected, no feedback, importance < 0.9) is a candidate — NOT just
    # candidate-status records. conservative keeps the original whitelist.
    mode = base.get("mode", "aggressive")
    return {**base, "mode": mode}


def _clean_candidate_rows(
    cutoff: str,
    blacklist: tuple[str, ...],
    min_chars: int,
    mode: str = "aggressive",
) -> list[dict[str, Any]]:
    """Shared read for the clean plan and replay validation.

    conservative: candidate-TTL / test-agent / fragment whitelist only.
    aggressive (default): adds long-unused ARCHIVED junk (never accessed,
    never injected, no feedback) — high-importance and genuinely-used rows
    are still protected in the plan layer.
    """
    placeholders = ", ".join("?" for _ in blacklist)
    with read_conn() as conn:
        rows = [
            dict(r)
            for r in conn.execute(
                f"""
                SELECT id, title, content, status, source_agent, created_at,
                       last_accessed_at, injected_count, feedback_score,
                       effectiveness_score, importance
                FROM memories
                WHERE status='candidate' AND datetime(created_at) < datetime(?)
                """,
                (cutoff,),
            ).fetchall()
        ]
        rows += [
            dict(r)
            for r in conn.execute(
                f"""
                SELECT id, title, content, status, source_agent, created_at,
                       last_accessed_at, injected_count, feedback_score,
                       effectiveness_score, importance
                FROM memories
                WHERE source_agent IN ({placeholders})
                  AND status NOT IN ('active', 'stale', 'contradicted', 'superseded')
                """,
                tuple(blacklist),
            ).fetchall()
        ]
        rows += [
            dict(r)
            for r in conn.execute(
                f"""
                SELECT id, title, content, status, source_agent, created_at,
                       last_accessed_at, injected_count, feedback_score,
                       effectiveness_score, importance
                FROM memories
                WHERE status='candidate'
                  AND (content IS NULL OR LENGTH(trim(content)) < ?)
                """,
                (min_chars,),
            ).fetchall()
        ]
        if mode == "aggressive":
            rows += [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT id, title, content, status, source_agent, created_at,
                           last_accessed_at, injected_count, feedback_score,
                           effectiveness_score, importance
                    FROM memories
                    WHERE status='archived'
                      AND (last_accessed_at IS NULL OR last_accessed_at = '')
                      AND injected_count = 0
                      AND (feedback_score IS NULL OR feedback_score = 0)
                    """
                ).fetchall()
            ]
    return rows


def _clean_candidate_items() -> tuple[list[dict[str, Any]], int, int]:
    """Shared uncapped clean-candidate scan.

    Returns (candidates, scanned, protected_count) where candidates is the
    full whitelist-matched, protection-filtered list in scan order. Both the
    capped plan and the paginated UI listing use this scan, so pagination
    offsets stay consistent with the plan's candidate order.
    """
    cfg = _clean_config()
    mode = cfg.get("mode", "aggressive")
    ttl_days = int(cfg.get("candidate_ttl_days", CLEAN_DEFAULT_TTL_DAYS))
    blacklist = tuple(cfg.get("source_agents", CLEAN_SOURCE_AGENT_BLACKLIST))
    min_chars = int(cfg.get("min_content_chars", CLEAN_DEFAULT_MIN_CONTENT_CHARS))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=ttl_days)).isoformat(timespec="seconds")

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    protected: set[str] = set()
    for r in _clean_candidate_rows(cutoff, blacklist, min_chars, mode):
        rid = r["id"]
        if rid in seen:
            continue
        seen.add(rid)
        # Genuinely used — never auto-clean. effectiveness_score defaults to
        # 0.5 so it cannot be trusted as a usage signal; rely on direct marks.
        if (
            r.get("last_accessed_at")
            or int(r.get("injected_count") or 0) > 0
            or (r.get("feedback_score") not in (None, 0, "0"))
        ):
            protected.add(rid)
            continue
        if float(r.get("importance") or 0.0) >= 0.9:
            protected.add(rid)
            continue  # high-importance — never auto-clean
        reasons: list[str] = []
        if r.get("status") == "candidate" and r.get("created_at"):
            created = str(r["created_at"])
            if _iso_compare(created, cutoff) < 0:
                reasons.append("candidate_ttl")
        if r.get("source_agent") in blacklist:
            reasons.append(f"source_agent:{r['source_agent']}")
        if r.get("status") == "candidate" and len((r.get("content") or "").strip()) < min_chars:
            reasons.append("fragment")
        if r.get("status") == "archived" and mode == "aggressive":
            reasons.append("archived_unused")
        if not reasons:
            continue
        candidates.append({
            "id": rid,
            "title": r.get("title") or "",
            "reason": ",".join(reasons),
            "status": r.get("status") or "",
            "created_at": r.get("created_at") or "",
            "source_agent": r.get("source_agent") or "",
        })
    return candidates, len(seen), len(protected)


def plan_data_maintenance_clean(limit: int = CLEAN_DEFAULT_LIMIT) -> dict[str, Any]:
    """Read-only hard-delete plan (whitelist only; protected records skipped)."""
    cap = _resolve_maintenance_cap(limit)
    candidates, scanned, protected_count = _clean_candidate_items()
    candidates = candidates[:cap]
    token_source = "clean|" + ("|".join(sorted(c["id"] for c in candidates)) if candidates else "__empty__")
    plan_token = hashlib.sha256(token_source.encode("utf-8")).hexdigest()[:24]
    groups: dict[str, dict[str, Any]] = {}
    for c in candidates:
        reason = c["reason"].split(",")[0]
        group = groups.setdefault(reason, {"reason": reason, "count": 0, "samples": []})
        group["count"] += 1
        if len(group["samples"]) < 5:
            group["samples"].append({"id": c["id"], "title": c["title"]})
    return {
        "dry_run": True,
        "generated_at": now(),
        "scanned": scanned,
        "plan_token": plan_token,
        "clean_count": len(candidates),
        "clean_ids": [c["id"] for c in candidates],
        "protected_count": protected_count,
        "groups": list(groups.values()),
        "summary": {"clean": len(candidates), "scanned": scanned, "protected": protected_count},
    }


def list_data_maintenance_clean_candidates(offset: int = 0, limit: int = 100) -> dict[str, Any]:
    """Paginated read-only clean-candidate listing for the UI preview dialog.

    Uses the same candidate scan as the plan (consistent ordering/offset);
    page size is capped at 500 rows per request.
    """
    candidates, scanned, protected_count = _clean_candidate_items()
    total = len(candidates)
    page_size = max(1, min(int(limit), 500))
    start = max(0, int(offset))
    items = candidates[start:start + page_size]
    return {
        "dry_run": True,
        "generated_at": now(),
        "action": "clean",
        "total": total,
        "offset": start,
        "limit": len(items),
        "scanned": scanned,
        "protected_count": protected_count,
        "items": items,
    }


def _iso_compare(a: str, b: str) -> int:
    """Compare two local/UTC ISO timestamps lexicographically after a light
    normalization of the offset suffix; returns -1/0/1."""
    def _norm(value: str) -> str:
        return value.replace("Z", "+00:00").replace(" ", "T")
    return (_norm(a) > _norm(b)) - (_norm(a) < _norm(b))


def execute_data_maintenance_clean(
    plan_token: str,
    limit: int = CLEAN_DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Execute a previously planned hard delete (idempotent per plan_token).

    Mandatory full backup first; then per-record: Qdrant point delete →
    vector_cache sweep → SQLite row delete (FTS follows via trigger).
    """
    import hashlib as _hashlib

    from memorycore.models import load_config
    from memorycore.storage.transfer import memory_backup
    from memorycore.vector_store import get_vector_store

    existing = get_maintenance_job_by_token(plan_token)
    if existing and existing.get("status") == "succeeded":
        return {
            "job_id": existing["id"],
            "status": "succeeded",
            "replayed": True,
            "summary": existing.get("summary", {}),
            "backup_path": existing.get("backup_path"),
        }

    plan = plan_data_maintenance_clean(limit=limit)
    if plan["plan_token"] != plan_token:
        raise ValueError(
            "plan_token is stale: the clean candidate set changed since the plan was "
            "generated; run plan again and retry"
        )
    clean_ids = plan["clean_ids"]

    with maintenance_lock(nonblocking=True):
        if not clean_ids:
            log_audit_event("maintenance_clean", detail={"plan_token": plan_token, "deleted": 0, "noop": True})
            summary = {"clean": 0, "already_clean": True}
            return {"status": "succeeded", "deleted": 0, "summary": summary, "backup_path": None}
        backup = memory_backup()
        vs = get_vector_store(load_config())
        deleted: list[str] = []
        fragments: list[str] = []
        with managed_conn() as conn:
            for cid in clean_ids:
                row = conn.execute(
                    "SELECT title, content FROM memories WHERE id=?", (cid,)
                ).fetchone()
                if row is None:
                    fragments.append(cid)
                    continue
                # vector_cache sweep for the exact text hashes (same algorithm
                # as vector_store._embed_text_hash) — non-fatal.
                text_sources = [str(row["title"] or ""), str(row["content"] or "")]
                for text in text_sources:
                    if text:
                        text_hash = _hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
                        try:
                            conn.execute("DELETE FROM vector_cache WHERE text_hash=?", (text_hash,))
                        except Exception:
                            pass
                deleted.append(cid)
            if deleted:
                placeholders = ",".join("?" for _ in deleted)
                conn.execute(
                    f"DELETE FROM memories WHERE id IN ({placeholders})",
                    tuple(deleted),
                )
        # Qdrant points after the SQLite commit (best-effort; a missing point
        # is harmless — the DB row is already gone/archived).
        try:
            for cid in deleted:
                vs.delete(cid)
        except Exception as exc:
            logger = logging.getLogger(__name__)
            logger.warning("maintenance_clean: qdrant sync failed for some ids: %s", exc)
        log_audit_event(
            "maintenance_clean",
            detail={
                "plan_token": plan_token,
                "deleted": len(deleted),
                "already_missing": len(fragments),
                "backup": backup.get("path"),
                "ids": deleted,
            },
        )
    summary = {
        "clean": len(deleted),
        "backup_path": backup.get("path"),
        "backup_bytes": backup.get("bytes", 0),
    }
    return {"status": "succeeded", "deleted": len(deleted), "summary": summary, "backup_path": backup.get("path")}
