"""Concurrent write tests and schema_version migration tests."""
from __future__ import annotations

import threading
from typing import Any

import pytest


def test_concurrent_writes_no_corruption(isolated_memory_db):
    """Multiple threads writing simultaneously must not corrupt the DB."""
    from memorycore.storage import add_memory_record, search_memory_records

    errors: list[Exception] = []
    results: list[dict[str, Any]] = []
    lock = threading.Lock()

    def _write(i: int) -> None:
        try:
            rec = add_memory_record(
                "project_memory",
                f"Concurrent title {i}",
                f"Content for thread {i}",
                source_agent=f"thread-{i}",
            )
            with lock:
                results.append(rec)
        except Exception as exc:
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=_write, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"Concurrent writes raised errors: {errors}"
    assert len(results) == 20
    ids = [r["id"] for r in results]
    assert len(set(ids)) == 20


def test_concurrent_reads_during_writes(isolated_memory_db):
    """Reads should succeed while writes are in progress."""
    from memorycore.storage import add_memory_record, list_recent

    add_memory_record("feedback", "Seed", "seed content")

    read_errors: list[Exception] = []
    write_errors: list[Exception] = []

    def _read():
        for _ in range(10):
            try:
                list_recent(5)
            except Exception as exc:
                read_errors.append(exc)

    def _write(i: int):
        try:
            add_memory_record("feedback", f"Write {i}", f"body {i}")
        except Exception as exc:
            write_errors.append(exc)

    readers = [threading.Thread(target=_read) for _ in range(3)]
    writers = [threading.Thread(target=_write, args=(i,)) for i in range(10)]
    for t in readers + writers:
        t.start()
    for t in readers + writers:
        t.join()

    assert read_errors == [], f"Read errors: {read_errors}"
    assert write_errors == [], f"Write errors: {write_errors}"


def test_schema_version_created_on_init(isolated_memory_db):
    """schema_version table must have exactly one row with version=1 after init."""
    from memorycore.storage.db import managed_conn

    with managed_conn() as conn:
        rows = conn.execute("SELECT version, applied_at FROM schema_version").fetchall()

    assert len(rows) == 1
    assert rows[0]["version"] == 1
    assert rows[0]["applied_at"] is not None


def test_schema_version_idempotent(isolated_memory_db):
    """Calling init_db twice must not create duplicate schema_version rows."""
    from memorycore.storage.db import init_db, managed_conn

    with managed_conn() as conn:
        init_db(conn)

    with managed_conn() as conn:
        count = conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]

    assert count == 1


def test_ensure_column_is_idempotent(isolated_memory_db):
    """_ensure_column must not raise if column already exists."""
    from memorycore.storage.db import _ensure_column, managed_conn

    with managed_conn() as conn:
        _ensure_column(conn, "memories", "injected_count", "INTEGER NOT NULL DEFAULT 0")
        conn.execute("SELECT injected_count FROM memories LIMIT 1")
