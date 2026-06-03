import pytest

import memorycore as lm


@pytest.fixture(autouse=True)
def isolated_memory_db(tmp_path, monkeypatch):
    db = tmp_path / "test_memory.sqlite3"
    monkeypatch.setenv("LOCAL_MEMORY_DB", str(db))
    lm._INITIALIZED_DB_PATHS.clear()
    yield db
    lm._INITIALIZED_DB_PATHS.clear()


@pytest.fixture(autouse=True)
def sync_audit(monkeypatch):
    """Make log_audit_event synchronous in tests so audit rows are readable immediately."""
    import threading
    import uuid
    import memorycore.storage.audit as _audit
    import memorycore.storage as _storage

    def _sync_log(event_type, memory_id=None, agent="unknown", detail=None):
        from memorycore.storage.db import managed_conn
        from memorycore.models import as_json, now
        params = (str(uuid.uuid4()), event_type, memory_id, agent, as_json(detail or {}), now())
        try:
            with managed_conn() as conn:
                conn.execute(
                    "INSERT INTO audit_events (id, event_type, memory_id, agent, detail_json, created_at) VALUES (?,?,?,?,?,?)",
                    params,
                )
        except Exception:
            pass
        t = threading.Thread(target=lambda: None)
        t.start()
        return t

    monkeypatch.setattr(_audit, "log_audit_event", _sync_log)
    monkeypatch.setattr(_storage, "log_audit_event", _sync_log)
    import memorycore.storage.crud as _crud
    import memorycore.storage.agents as _agents
    import memorycore.storage.curator as _curator
    import memorycore.storage.transfer as _transfer
    for _mod in (_crud, _agents, _curator, _transfer):
        monkeypatch.setattr(_mod, "log_audit_event", _sync_log)
