from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
from datetime import datetime, timezone

import pytest

from memorycore.storage.maintenance import (
    MaintenanceBusyError,
    archive_statistics,
    create_maintenance_job,
    execute_data_maintenance,
    get_latest_maintenance_job,
    get_maintenance_job,
    maintenance_lock,
    plan_data_maintenance,
    run_data_maintenance_job,
    run_maintenance,
)


NOW = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
OLD = "2026-06-01T00:00:00+00:00"
RECENT = "2026-07-09T00:00:00+00:00"


def _create_database(path):
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE audit_events (
              id TEXT PRIMARY KEY, event_type TEXT, memory_id TEXT, agent TEXT,
              detail_json TEXT, created_at TEXT
            );
            CREATE TABLE governance_decisions (
              id TEXT PRIMARY KEY, review_status TEXT, finding_json TEXT, created_at TEXT
            );
            CREATE TABLE governance_executions (
              id TEXT PRIMARY KEY, status TEXT, started_at TEXT
            );
            CREATE TABLE governance_mutation_log (
              id TEXT PRIMARY KEY, status TEXT, created_at TEXT
            );
            """
        )
        conn.executemany(
            "INSERT INTO audit_events VALUES (?,?,?,?,?,?)",
            [
                ("a-old", "memory_update", None, "test", '{"old":true}', OLD),
                ("a-recent", "memory_update", None, "test", '{"recent":true}', RECENT),
            ],
        )
        conn.executemany(
            "INSERT INTO governance_decisions VALUES (?,?,?,?)",
            [
                ("d-old", "applied", '{"old":true}', OLD),
                ("d-review", "needs_review", '{"keep":true}', OLD),
                ("d-recent", "applied", '{"recent":true}', RECENT),
            ],
        )
        conn.executemany(
            "INSERT INTO governance_executions VALUES (?,?,?)",
            [
                ("e-old", "applied", OLD),
                ("e-running", "running", OLD),
                ("e-recent", "applied", RECENT),
            ],
        )
        conn.executemany(
            "INSERT INTO governance_mutation_log VALUES (?,?,?)",
            [
                ("m-old", "applied", OLD),
                ("m-running", "pending", OLD),
                ("m-recent", "applied", RECENT),
            ],
        )


def test_maintenance_dry_run_has_no_side_effects(tmp_path):
    database = tmp_path / "memory.sqlite3"
    archives = tmp_path / "archives"
    _create_database(database)

    result = run_maintenance(
        retention_days=30,
        database=database,
        archive_dir=archives,
        current_time=NOW,
    )

    assert result["dry_run"] is True
    assert result["planned_rows"] == 4
    assert not archives.exists()
    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM governance_decisions").fetchone()[0] == 3


def test_maintenance_applies_verified_archive_and_preserves_live_rows(tmp_path):
    database = tmp_path / "memory.sqlite3"
    archives = tmp_path / "archives"
    backup = tmp_path / "before.sqlite3"
    _create_database(database)

    result = run_maintenance(
        retention_days=30,
        apply=True,
        vacuum=False,
        database=database,
        archive_dir=archives,
        backup_path=backup,
        current_time=NOW,
    )

    assert result["dry_run"] is False
    assert result["deleted"] == {
        "governance_mutation_log": 1,
        "governance_executions": 1,
        "governance_decisions": 1,
        "audit_events": 1,
    }
    assert result["integrity_check"] == "ok"
    assert backup.exists()
    with sqlite3.connect(backup) as conn:
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 2

    archive = archives / NOW.strftime("%Y%m%dT%H%M%S%fZ")
    manifest = json.loads((archive / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["applied"] is True
    assert manifest["device_local"] is True
    assert manifest["import_supported"] is False
    for table, item in manifest["tables"].items():
        archive_file = archive / item["file"]
        assert hashlib.sha256(archive_file.read_bytes()).hexdigest() == item["sha256"]
        with gzip.open(archive_file, "rt", encoding="utf-8") as handle:
            assert len([json.loads(line) for line in handle]) == item["rows"] == 1

    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT id FROM audit_events").fetchall() == [("a-recent",)]
        assert {row[0] for row in conn.execute("SELECT id FROM governance_decisions")} == {"d-review", "d-recent"}
        assert {row[0] for row in conn.execute("SELECT id FROM governance_executions")} == {"e-running", "e-recent"}
        assert {row[0] for row in conn.execute("SELECT id FROM governance_mutation_log")} == {"m-running", "m-recent"}

    stats = archive_statistics(archives)
    assert stats["total_rows"] == 4
    assert stats["archives"][0]["applied"] is True
    assert stats["compressed_bytes"] > 0


def test_maintenance_rejects_invalid_retention(tmp_path):
    database = tmp_path / "memory.sqlite3"
    _create_database(database)

    try:
        run_maintenance(retention_days=0, database=database)
    except ValueError as exc:
        assert "at least 1" in str(exc)
    else:
        raise AssertionError("expected invalid retention to fail")


def test_maintenance_apply_is_noop_without_candidates(tmp_path):
    database = tmp_path / "memory.sqlite3"
    archives = tmp_path / "archives"
    backup = tmp_path / "before.sqlite3"
    _create_database(database)

    result = run_maintenance(
        retention_days=365,
        apply=True,
        database=database,
        archive_dir=archives,
        backup_path=backup,
        current_time=NOW,
    )

    assert result["noop"] is True
    assert result["integrity_check"] == "ok"
    assert not backup.exists()
    assert not archives.exists()


# ──────────────────────────────────────────────────────────────────────────
# D1 — One-click manual data maintenance: plan (read-only) → execute (archive)
# ──────────────────────────────────────────────────────────────────────────


def _add_stale_episodic(title: str, days_old: int = 60) -> str:
    """Insert a stale episodic memory old enough to hit episodic_archive."""
    import datetime as _dt
    import uuid as _uuid

    from memorycore.models import now as _now
    from memorycore.storage.db import managed_conn as _mc

    memory_id = str(_uuid.uuid4())
    ts = _now()
    old_ts = (_dt.datetime.now().astimezone() - _dt.timedelta(days=days_old)).isoformat(timespec="seconds")
    with _mc() as conn:
        conn.execute(
            "INSERT INTO memories (id, type, scope, title, content, source_agent, created_at, updated_at, "
            "status, confidence, importance, decay_policy, feedback_score, injected_count, last_accessed_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (memory_id, "episodic_memory", "global", title, f"content {title}", "test-agent",
             ts, ts, "stale", 0.7, 0.4, "review", 0.0, 1, None),
        )
        conn.execute("UPDATE memories SET updated_at=? WHERE id=?", (old_ts, memory_id))
    return memory_id


def _status_of(memory_id: str) -> str:
    from memorycore.storage.db import read_conn

    with read_conn() as conn:
        row = conn.execute("SELECT status FROM memories WHERE id=?", (memory_id,)).fetchone()
    return str(row["status"]) if row else "missing"


class TestDataMaintenancePlan:
    def test_plan_is_read_only(self):
        mid = _add_stale_episodic("plan-ro-memory", days_old=60)
        plan = plan_data_maintenance(limit=1000)
        assert mid in plan["archive_ids"]
        assert plan["archive_count"] >= 1
        assert plan["plan_token"]
        assert plan["dry_run"] is True
        assert _status_of(mid) == "stale"  # planning never mutates

    def test_plan_groups_reasons_and_samples(self):
        _add_stale_episodic("plan-sample-a", days_old=60)
        _add_stale_episodic("plan-sample-b", days_old=90)
        plan = plan_data_maintenance(limit=1000)
        assert plan["archive_count"] >= 2
        assert sum(g["count"] for g in plan["groups"]) == plan["archive_count"]


class TestDataMaintenanceExecute:
    def test_execute_archives_and_records_job(self):
        mid = _add_stale_episodic("execute-me", days_old=60)
        plan = plan_data_maintenance(limit=1000)
        token = plan["plan_token"]
        assert mid in plan["archive_ids"]

        job = create_maintenance_job(token)
        result = run_data_maintenance_job(job["job_id"], token, limit=1000)
        assert result["status"] == "succeeded"
        assert result["summary"]["archive"] >= 1
        assert _status_of(mid) == "archived"
        assert result["backup_path"] and "backups" in str(result["backup_path"])

        latest = get_latest_maintenance_job()
        assert latest is not None
        assert latest["status"] == "succeeded"
        fetched = get_maintenance_job(job["job_id"])
        assert fetched is not None and fetched["status"] == "succeeded"

    def test_execute_rejects_stale_token(self):
        mid = _add_stale_episodic("stale-token", days_old=60)
        plan = plan_data_maintenance(limit=1000)
        token = plan["plan_token"]
        from memorycore.storage.db import managed_conn

        with managed_conn() as conn:
            conn.execute("UPDATE memories SET status='archived' WHERE id=?", (mid,))
        with pytest.raises(ValueError, match="stale"):
            execute_data_maintenance(token, limit=1000)

    def test_execute_is_idempotent_via_plan_token(self):
        mid = _add_stale_episodic("idempotent", days_old=60)
        plan = plan_data_maintenance(limit=1000)
        token = plan["plan_token"]

        first = run_data_maintenance_job(create_maintenance_job(token)["job_id"], token, limit=1000)
        assert first["status"] == "succeeded"
        second = run_data_maintenance_job(create_maintenance_job(token)["job_id"], token, limit=1000)
        assert second["status"] == "succeeded"
        assert second["replayed"] is True
        assert _status_of(mid) == "archived"

    def test_lock_mutual_exclusion_with_curator(self):
        _add_stale_episodic("locked", days_old=60)
        plan = plan_data_maintenance(limit=1000)
        with maintenance_lock(nonblocking=True):
            with pytest.raises(MaintenanceBusyError):
                execute_data_maintenance(plan["plan_token"], limit=1000)


class TestDataMaintenanceApi:
    def test_plan_execute_latest_loop(self):
        import time as _time

        from starlette.applications import Starlette
        from starlette.routing import Route
        from starlette.testclient import TestClient

        from memorycore.frontend import configure_frontend, frontend_api

        _add_stale_episodic("api-archive-me", days_old=60)
        configure_frontend(host="127.0.0.1", port=8318, enabled=True)
        app = Starlette(routes=[
            Route("/api/{path:path}", frontend_api, methods=["GET", "POST", "PATCH", "PUT", "DELETE"]),
        ])
        with TestClient(app) as client:
            plan = client.get("/api/v1/maintenance/plan")
            assert plan.status_code == 200
            data = plan.json()
            assert data["plan_token"]
            assert data["archive_count"] >= 1

            job = client.post("/api/v1/maintenance/execute", json={"plan_token": data["plan_token"]})
            assert job.status_code == 200
            job_id = job.json()["job_id"]
            assert job_id

            status = None
            for _ in range(200):
                job_status = client.get(f"/api/v1/maintenance/{job_id}")
                assert job_status.status_code == 200
                status = job_status.json()["status"]
                if status in ("succeeded", "failed"):
                    break
                _time.sleep(0.1)
            assert status == "succeeded"

            latest = client.get("/api/v1/maintenance/latest")
            assert latest.status_code == 200
            assert latest.json()["job_id"] == job_id

            bad = client.post("/api/v1/maintenance/execute", json={})
            assert bad.status_code == 400

            missing = client.get("/api/v1/maintenance/does-not-exist")
            assert missing.status_code == 404
