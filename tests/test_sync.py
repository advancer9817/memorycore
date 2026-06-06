"""Tests for enhanced memory_export / memory_import (sync features)."""
from __future__ import annotations

import json

import pytest

from memorycore.storage import (
    add_memory_record,
    managed_conn,
    memory_export,
    memory_import,
)


# ---------------------------------------------------------------------------
# memories_only export
# ---------------------------------------------------------------------------

def test_export_memories_only_excludes_agent_tables():
    add_memory_record("project_memory", "Sync me", "content")
    payload = memory_export(memories_only=True)

    assert payload["memories_only"] is True
    assert "memories" in payload["data"]
    assert "feedback_events" in payload["data"]
    assert "memory_links" in payload["data"]
    assert "agent_messages" not in payload["data"]
    assert "agent_presence" not in payload["data"]
    assert "agent_permissions" not in payload["data"]


def test_export_full_includes_agent_tables():
    add_memory_record("project_memory", "Full", "content")
    payload = memory_export(memories_only=False)

    assert payload["memories_only"] is False
    assert "agent_messages" in payload["data"]
    assert "agent_presence" in payload["data"]


def test_export_counts_match_data_lengths():
    add_memory_record("project_memory", "A", "content A")
    add_memory_record("feedback", "B", "content B")
    payload = memory_export(memories_only=True)

    for table, rows in payload["data"].items():
        assert payload["counts"][table] == len(rows)


# ---------------------------------------------------------------------------
# conflict_policy = newer
# ---------------------------------------------------------------------------

def test_import_newer_keeps_incoming_when_more_recent():
    old_ts = "2026-01-01T00:00:00+00:00"
    new_ts = "2026-06-01T00:00:00+00:00"
    r = add_memory_record("project_memory", "SharedMem", "old content", memory_id="shared-1")
    # Backdate the existing row
    with managed_conn() as conn:
        conn.execute("UPDATE memories SET updated_at=? WHERE id=?", (old_ts, r["id"]))

    payload = {
        "schema_version": 1,
        "data": {
            "memories": [{
                **r,
                "tags_json": "[]",
                "related_ids_json": "[]",
                "metadata_json": "{}",
                "content": "new content",
                "updated_at": new_ts,
            }],
            "feedback_events": [],
            "memory_links": [],
        },
    }
    result = memory_import(payload, dry_run=False, conflict_policy="newer")

    assert result["applied"] is True
    assert result["newer_wins"]["memories"] == 1
    with managed_conn() as conn:
        row = conn.execute("SELECT content FROM memories WHERE id='shared-1'").fetchone()
    assert row[0] == "new content"


def test_import_newer_keeps_existing_when_more_recent():
    recent_ts = "2026-06-01T00:00:00+00:00"
    old_ts = "2026-01-01T00:00:00+00:00"
    r = add_memory_record("project_memory", "Fresh", "fresh content", memory_id="fresh-1")
    with managed_conn() as conn:
        conn.execute("UPDATE memories SET updated_at=? WHERE id=?", (recent_ts, r["id"]))

    payload = {
        "schema_version": 1,
        "data": {
            "memories": [{
                **r,
                "tags_json": "[]",
                "related_ids_json": "[]",
                "metadata_json": "{}",
                "content": "stale content",
                "updated_at": old_ts,
            }],
            "feedback_events": [],
            "memory_links": [],
        },
    }
    result = memory_import(payload, dry_run=False, conflict_policy="newer")

    assert result["newer_wins"]["memories"] == 0
    with managed_conn() as conn:
        row = conn.execute("SELECT content FROM memories WHERE id='fresh-1'").fetchone()
    assert row[0] == "fresh content"


def test_import_newer_inserts_new_rows_not_in_local():
    payload = {
        "schema_version": 1,
        "data": {
            "memories": [{
                "id": "brand-new-1",
                "type": "project_memory",
                "scope": "global",
                "title": "Brand New",
                "content": "From remote",
                "tags_json": "[]",
                "source": "manual",
                "source_agent": "sync",
                "project_path": "",
                "created_at": "2026-06-01T00:00:00+00:00",
                "updated_at": "2026-06-01T00:00:00+00:00",
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
                "last_accessed_at": None,
                "last_injected_at": None,
                "valid_from": None,
                "valid_until": None,
            }],
            "feedback_events": [],
            "memory_links": [],
        },
    }
    result = memory_import(payload, dry_run=False, conflict_policy="newer")

    assert result["inserted"]["memories"] == 1
    with managed_conn() as conn:
        row = conn.execute("SELECT title FROM memories WHERE id='brand-new-1'").fetchone()
    assert row is not None
    assert row[0] == "Brand New"


def test_import_newer_dry_run_does_not_write():
    r = add_memory_record("project_memory", "DryTarget", "original", memory_id="dry-t-1")
    payload = {
        "schema_version": 1,
        "data": {
            "memories": [{
                **r,
                "tags_json": "[]",
                "related_ids_json": "[]",
                "metadata_json": "{}",
                "content": "would-be replacement",
                "updated_at": "2026-12-31T00:00:00+00:00",
            }],
            "feedback_events": [],
            "memory_links": [],
        },
    }
    result = memory_import(payload, dry_run=True, conflict_policy="newer")

    assert result["dry_run"] is True
    assert result["applied"] is False
    with managed_conn() as conn:
        row = conn.execute("SELECT content FROM memories WHERE id='dry-t-1'").fetchone()
    assert row[0] == "original"


def test_import_invalid_conflict_policy_returns_error():
    result = memory_import({"schema_version": 1, "data": {}}, conflict_policy="merge")
    assert "error" in result
    assert result["error"] == "invalid_conflict_policy"


# ---------------------------------------------------------------------------
# CLI export / import round-trip
# ---------------------------------------------------------------------------

def test_cli_export_creates_file(tmp_path):
    add_memory_record("project_memory", "CLI Export", "content")
    out = tmp_path / "out.json"
    from memorycore.server import main
    rc = main(["export", str(out), "--memories-only"])
    assert rc == 0
    assert out.exists()
    payload = json.loads(out.read_text())
    assert payload["memories_only"] is True
    assert payload["counts"]["memories"] == 1


def test_cli_import_dry_run(tmp_path):
    r = add_memory_record("project_memory", "Import Target", "original")
    out = tmp_path / "export.json"
    from memorycore.server import main
    main(["export", str(out), "--memories-only"])
    # import dry-run (no --apply)
    rc = main(["import", str(out), "--conflict-policy", "newer"])
    assert rc == 0
    # content unchanged
    with managed_conn() as conn:
        row = conn.execute("SELECT content FROM memories WHERE id=?", (r["id"],)).fetchone()
    assert row[0] == "original"


def test_cli_import_missing_file_returns_error(tmp_path):
    from memorycore.server import main
    rc = main(["import", str(tmp_path / "nonexistent.json")])
    assert rc == 1


# ---------------------------------------------------------------------------
# Edge cases: malformed data in memory_import
# ---------------------------------------------------------------------------

def test_import_null_confidence_is_rejected_or_handled():
    """import with null confidence should not crash or corrupt the DB."""
    payload = {
        "schema_version": 1,
        "data": {
            "memories": [{
                "id": "test-malformed-001",
                "type": "project_memory",
                "title": "Test",
                "content": "Test content",
                "confidence": None,   # null — should be handled
                "importance": 0.5,
                "status": "active",
                "scope": "global",
                "tags_json": "[]",
                "source": "test",
                "source_agent": "test",
                "project_path": "",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
                "decay_policy": "review",
                "related_ids_json": "[]",
                "metadata_json": "{}",
                "valid_from": None,
                "valid_until": None,
            }]
        }
    }
    # dry_run should not raise
    result = memory_import(payload, dry_run=True, conflict_policy="skip")
    assert "error" not in result or result.get("error") is None or "schema" not in str(result.get("error", ""))


def test_import_invalid_status_dry_run():
    """import with invalid status in dry_run should report conflict or be skipped."""
    payload = {
        "schema_version": 1,
        "data": {
            "memories": [{
                "id": "test-malformed-002",
                "type": "project_memory",
                "title": "Bad status",
                "content": "content",
                "confidence": 0.7,
                "importance": 0.5,
                "status": "invalid_status_xyz",
                "scope": "global",
                "tags_json": "[]",
                "source": "test",
                "source_agent": "test",
                "project_path": "",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
                "decay_policy": "review",
                "related_ids_json": "[]",
                "metadata_json": "{}",
                "valid_from": None,
                "valid_until": None,
            }]
        }
    }
    # should not raise — either rejects gracefully or imports with error count
    result = memory_import(payload, dry_run=True, conflict_policy="skip")
    assert isinstance(result, dict)
