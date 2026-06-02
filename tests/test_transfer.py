from __future__ import annotations

import json
from pathlib import Path

from memorycore.storage import (
    add_memory_record,
    get_audit_log,
    log_audit_event,
    managed_conn,
    memory_backup,
    memory_export,
    memory_import,
)


def test_memory_export_contains_schema_and_core_tables():
    record = add_memory_record("project_memory", "Export me", "Content to export")

    payload = memory_export()

    assert payload["schema_version"] == 1
    assert payload["counts"]["memories"] == 1
    assert payload["data"]["memories"][0]["id"] == record["id"]
    assert "agent_permissions" not in payload["data"]


def test_memory_import_dry_run_reports_conflicts_without_writing():
    record = add_memory_record("project_memory", "Existing", "Existing content")
    payload = memory_export()

    result = memory_import(payload, dry_run=True)

    assert result["dry_run"] is True
    assert result["applied"] is False
    assert result["conflicts"]["memories"] == [record["id"]]
    assert result["planned"]["memories"] == 0


def test_memory_import_applies_missing_rows():
    payload = {
        "schema_version": 1,
        "data": {
            "memories": [
                {
                    "id": "imported-1",
                    "type": "project_memory",
                    "scope": "global",
                    "title": "Imported",
                    "content": "Imported content",
                    "tags_json": "[]",
                    "source": "manual",
                    "source_agent": "importer",
                    "project_path": "",
                    "created_at": "2026-05-26T00:00:00+00:00",
                    "updated_at": "2026-05-26T00:00:00+00:00",
                    "last_accessed_at": None,
                    "confidence": 0.7,
                    "importance": 0.5,
                    "status": "active",
                    "decay_policy": "review",
                    "feedback_score": 0,
                    "related_ids_json": "[]",
                    "metadata_json": "{}",
                    "injected_count": 0,
                    "ineffective_count": 0,
                    "effectiveness_score": 0.5,
                    "last_injected_at": None,
                }
            ]
        },
    }

    result = memory_import(payload, dry_run=False)

    assert result["applied"] is True
    assert result["inserted"]["memories"] == 1
    with managed_conn() as conn:
        row = conn.execute("SELECT title FROM memories WHERE id='imported-1'").fetchone()
    assert row[0] == "Imported"


def test_memory_import_reports_ignored_audit_events():
    log_audit_event("test_audit_export", detail={"x": 1})
    payload = memory_export(include_audit=True)

    assert "audit_events" in payload["data"]
    result = memory_import(payload, dry_run=False, conflict_policy="newer")

    assert result["ignored_tables"] == ["audit_events"]
    audit_rows = get_audit_log(event_type="memory_import", limit=1)
    assert audit_rows
    assert json.loads(audit_rows[0]["detail_json"])["ignored_tables"] == ["audit_events"]


def test_memory_import_rejects_newer_schema():
    result = memory_import({"schema_version": 999, "data": {}}, dry_run=True)

    assert result["error"] == "unsupported_schema_version"


def test_memory_backup_creates_sqlite_copy(tmp_path):
    add_memory_record("project_memory", "Backup", "Backup content")
    out = tmp_path / "backup.sqlite3"

    result = memory_backup(str(out))

    assert result["path"] == str(out)
    assert Path(result["path"]).exists()
    assert result["bytes"] > 0
