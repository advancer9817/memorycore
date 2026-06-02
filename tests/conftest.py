import pytest

import memorycore as lm


@pytest.fixture(autouse=True)
def isolated_memory_db(tmp_path, monkeypatch):
    db = tmp_path / "test_memory.sqlite3"
    monkeypatch.setenv("LOCAL_MEMORY_DB", str(db))
    lm._INITIALIZED_DB_PATHS.clear()
    yield db
    lm._INITIALIZED_DB_PATHS.clear()
