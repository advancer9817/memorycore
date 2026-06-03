"""TDD tests for P0-4 — audit_events table and log_audit_event/get_audit_log."""
from __future__ import annotations

import pytest


def _log(*args, **kwargs):
    """log_audit_event and join the write thread before returning."""
    from memorycore.storage import log_audit_event
    log_audit_event(*args, **kwargs).join()


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    """Patch LOCAL_MEMORY_DB and reset the DB-init cache so each test gets a fresh DB."""
    monkeypatch.setenv("LOCAL_MEMORY_DB", str(tmp_path / "audit_test.sqlite3"))
    from memorycore import models
    monkeypatch.setattr(models, "_INITIALIZED_DB_PATHS", set())
    return tmp_path


class TestLogAuditEvent:
    def test_log_creates_row(self, isolated_db):
        from memorycore.storage import get_audit_log
        _log("memory_add", memory_id="abc-123", agent="test-agent", detail={"type": "feedback"})
        rows = get_audit_log()
        assert len(rows) == 1
        assert rows[0]["event_type"] == "memory_add"
        assert rows[0]["memory_id"] == "abc-123"
        assert rows[0]["agent"] == "test-agent"

    def test_log_never_raises_on_bad_db(self, isolated_db, monkeypatch):
        """log_audit_event must be fire-and-forget — never propagate exceptions."""
        from memorycore import storage as _storage
        from memorycore.storage import log_audit_event

        def broken_conn(*a, **kw):
            raise RuntimeError("DB unavailable")

        monkeypatch.setattr(_storage.db, "managed_conn", broken_conn)
        log_audit_event("memory_add", memory_id="x").join()  # must not raise

    def test_detail_json_stored(self, isolated_db):
        import json
        from memorycore.storage import log_audit_event, get_audit_log
        log_audit_event("memory_update", memory_id="m1", detail={"fields": ["content=?"]}).join()
        rows = get_audit_log()
        detail = json.loads(rows[0]["detail_json"])
        assert detail["fields"] == ["content=?"]


class TestGetAuditLog:
    def test_filter_by_memory_id(self, isolated_db):
        from memorycore.storage import get_audit_log
        _log("memory_add", memory_id="A")
        _log("memory_add", memory_id="B")
        rows = get_audit_log(memory_id="A")
        assert len(rows) == 1
        assert rows[0]["memory_id"] == "A"

    def test_filter_by_event_type(self, isolated_db):
        from memorycore.storage import get_audit_log
        _log("memory_add", memory_id="A")
        _log("memory_status_change", memory_id="A")
        rows = get_audit_log(event_type="memory_status_change")
        assert len(rows) == 1
        assert rows[0]["event_type"] == "memory_status_change"

    def test_limit_respected(self, isolated_db):
        from memorycore.storage import get_audit_log
        for i in range(10):
            _log("memory_add", memory_id=f"m{i}")
        rows = get_audit_log(limit=3)
        assert len(rows) == 3

    def test_ordered_newest_first(self, isolated_db):
        from memorycore.storage import get_audit_log
        _log("memory_add", memory_id="first")
        _log("memory_add", memory_id="second")
        rows = get_audit_log()
        assert rows[0]["memory_id"] == "second"


class TestAuditIntegration:
    def test_add_memory_record_creates_audit(self, isolated_db):
        import time
        from memorycore.storage import add_memory_record, get_audit_log
        record = add_memory_record(
            memory_type="feedback",
            title="Test memory",
            content="Some content about testing",
            source_agent="pytest",
        )
        time.sleep(0.1)  # audit write is async
        rows = get_audit_log(memory_id=record["id"])
        assert len(rows) >= 1
        assert rows[0]["event_type"] == "memory_add"
        assert rows[0]["agent"] == "pytest"

    def test_update_status_creates_audit(self, isolated_db):
        import json, time
        from memorycore.storage import add_memory_record, update_status, get_audit_log
        record = add_memory_record(
            memory_type="feedback",
            title="Status test",
            content="Testing status change audit",
        )
        update_status(record["id"], "stale")
        time.sleep(0.1)  # audit write is async
        rows = get_audit_log(memory_id=record["id"], event_type="memory_status_change")
        assert len(rows) == 1
        assert json.loads(rows[0]["detail_json"])["status"] == "stale"
