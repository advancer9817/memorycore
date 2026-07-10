from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
from datetime import datetime, timezone

from memorycore.storage.maintenance import archive_statistics, run_maintenance


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
