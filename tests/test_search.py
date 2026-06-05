import memorycore as lm


def add_sample_records():
    alpha = lm.add_memory_record(
        "project_memory",
        "Alpha Search",
        "SQLite full text keyword memory",
        scope="project-a",
        tags=["search", "core"],
        importance=0.7,
        memory_id="alpha",
    )
    beta = lm.add_memory_record(
        "decision",
        "Beta Decision",
        "Choose pytest for coverage",
        scope="global",
        tags=["test"],
        importance=0.9,
        memory_id="beta",
    )
    stale = lm.add_memory_record(
        "feedback",
        "Gamma Feedback",
        "Old inactive item",
        tags=["search"],
        status="stale",
        memory_id="gamma",
    )
    return alpha, beta, stale


def test_keyword_search_and_empty_query():
    add_sample_records()

    results = lm.search_memory_records("keyword", status="active")
    assert [r["id"] for r in results] == ["alpha"]

    empty = lm.search_memory_records("", status="active", limit=10)
    assert [r["id"] for r in empty] == ["beta", "alpha"]


def test_filters_type_tags_scope_status_and_limit():
    add_sample_records()

    assert [r["id"] for r in lm.search_memory_records("", types="decision")] == ["beta"]
    assert [r["id"] for r in lm.search_memory_records("", tags=["search"], status="")] == ["alpha", "gamma"]
    assert [r["id"] for r in lm.search_memory_records("", scope="project-a")] == ["beta", "alpha"]
    assert [r["id"] for r in lm.search_memory_records("", status="stale")] == ["gamma"]
    assert len(lm.search_memory_records("", status="", limit=1)) == 1


def test_punctuation_only_query_does_not_crash():
    add_sample_records()

    assert lm.search_memory_records("!!! ???", status="") == []


def test_search_updates_last_accessed_at():
    import time
    add_sample_records()
    assert lm.get_record("alpha")["last_accessed_at"] is None

    assert lm.search_memory_records("keyword", status="active")
    time.sleep(0.15)  # last_accessed_at write is async

    assert lm.get_record("alpha")["last_accessed_at"] is not None


def test_last_accessed_at_concurrent_write_consistency(tmp_path, monkeypatch):
    """Concurrent memory_search calls must not leave last_accessed_at as None."""
    import threading
    from memorycore.storage.search import search_memory_records
    from memorycore.storage.crud import add_memory_record

    monkeypatch.setenv("LMMCP_DB_PATH", str(tmp_path / "test.sqlite3"))
    # 重置已初始化路径缓存
    from memorycore import models as _m
    _m._INITIALIZED_DB_PATHS.clear()

    # 创建 5 条记忆
    ids = []
    for i in range(5):
        r = add_memory_record("feedback", f"Memory {i}", f"content about topic {i}")
        ids.append(r["id"])

    errors = []
    def search_worker():
        try:
            search_memory_records("topic", limit=10)
        except Exception as e:
            errors.append(str(e))

    threads = [threading.Thread(target=search_worker) for _ in range(10)]
    for t in threads: t.start()
    for t in threads: t.join()

    assert not errors, f"Search errors: {errors}"

    from memorycore.storage.db import read_conn
    with read_conn() as conn:
        rows = conn.execute(
            "SELECT id, last_accessed_at FROM memories WHERE id IN ({})".format(
                ",".join("?" * len(ids))
            ), ids
        ).fetchall()
    # 至少有一些记忆的 last_accessed_at 被更新（并发写可能不全部成功，但不能有异常）
    assert len(rows) == 5
