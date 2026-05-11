import pytest

import local_memory_mcp as lm


def test_add_get_list_normalizes_fields():
    record = lm.add_memory_record(
        "project_memory",
        "  Core Title  ",
        "  Useful content  ",
        tags="alpha, beta",
        related_ids='["one", "two"]',
        metadata={"k": "v"},
        confidence="0.8",
        importance="0.9",
        memory_id="mem-core",
    )

    assert record["id"] == "mem-core"
    assert record["title"] == "Core Title"
    assert record["content"] == "Useful content"
    assert record["tags"] == ["alpha", "beta"]
    assert record["related_ids"] == ["one", "two"]
    assert record["metadata"] == {"k": "v"}
    assert record["scope"] == "global"

    assert lm.get_record("mem-core")["id"] == "mem-core"
    assert [r["id"] for r in lm.list_recent(5)] == ["mem-core"]


def test_normalize_list_accepts_common_shapes():
    assert lm.normalize_list(None) == []
    assert lm.normalize_list("") == []
    assert lm.normalize_list("a, b,,c") == ["a", "b", "c"]
    assert lm.normalize_list('["a", " b "]') == ["a", "b"]
    assert lm.normalize_list(("x", 2)) == ["x", "2"]


def test_validates_type_status_and_numeric_ranges():
    with pytest.raises(ValueError, match="type must be one of"):
        lm.add_memory_record("bad_type", "Title", "Content")

    with pytest.raises(ValueError, match="status must be one of"):
        lm.add_memory_record("project_memory", "Title", "Content", status="bad")

    with pytest.raises(ValueError, match="title and content are required"):
        lm.add_memory_record("project_memory", "", "Content")

    with pytest.raises(ValueError, match="confidence must be <="):
        lm.add_memory_record("project_memory", "Title", "Content", confidence=2)
