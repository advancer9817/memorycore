import pytest

import memorycore as lm


@pytest.fixture(autouse=True)
def isolated_memory_db(tmp_path, monkeypatch):
    db = tmp_path / "test_memory.sqlite3"
    monkeypatch.setenv("LOCAL_MEMORY_DB", str(db))
    lm._INITIALIZED_DB_PATHS.clear()

    # Invalidate stats cache
    import memorycore.storage.crud as crud
    crud._stats_cache.clear()
    crud._stats_cache_ts = 0.0

    # Run _write_queue synchronously in tests
    import memorycore.storage.search as search
    def mock_put_nowait(item):
        search._flush_write_batch([item])
    monkeypatch.setattr(search._write_queue, "put_nowait", mock_put_nowait)

    # Run _record_context_quality_event synchronously in tests
    def mock_record_context_quality_event(task, task_type, agent, project_path, scope, quality, type_weights):
        if quality.get("used_count", 0) == 0:
            return
        from memorycore.storage.db import managed_conn
        from memorycore.models import as_json, now
        import uuid
        params = (
            str(uuid.uuid4()), task, task_type, agent, project_path or "", scope or "global",
            quality["total_candidates"], quality["used_count"], quality["filtered_count"],
            quality["hit_rate"], quality["filter_rate"], quality["ineffective_rate"],
            as_json(type_weights), now(),
        )
        try:
            with managed_conn() as conn:
                conn.execute(
                    """
                    INSERT INTO context_quality_events (
                      id, task, task_type, agent, project_path, scope, total_candidates,
                      used_count, filtered_count, hit_rate, filter_rate, ineffective_rate,
                      type_weights_json, created_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    params,
                )
        except Exception:
            pass
    monkeypatch.setattr(search, "_record_context_quality_event", mock_record_context_quality_event)

    # Run _sync_to_vector synchronously in tests
    def mock_sync_to_vector(record):
        if crud._get_vector_store is None:
            return
        try:
            vs = crud._get_vector_store(crud.load_config())
            status = record.get("status", "active")
            if status != "active":
                vs.delete(record["id"])
                return
            text = f"{record.get('title', '')} {record.get('content', '')}".strip()
            metadata = record.get("metadata") or {}
            payload = {
                "type": record.get("type", ""),
                "scope": record.get("scope", ""),
                "status": status,
                "source_agent": record.get("source_agent", ""),
                "tags": record.get("tags", []),
                "kind": metadata.get("kind", ""),
                "parent_id": metadata.get("parent_id", ""),
            }
            vs.upsert(record["id"], text, payload)
        except Exception as exc:
            crud.logger.warning("_sync_to_vector: failed for id=%s: %s", record.get("id"), exc)
    monkeypatch.setattr(crud, "_sync_to_vector", mock_sync_to_vector)

    yield db
    lm._INITIALIZED_DB_PATHS.clear()
    crud._stats_cache.clear()
    crud._stats_cache_ts = 0.0


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
