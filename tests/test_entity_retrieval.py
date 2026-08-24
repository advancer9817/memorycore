from __future__ import annotations

from unittest.mock import MagicMock, patch

import memorycore as lm
from memorycore.storage.db import managed_conn


def _mock_vector_store():
    store = MagicMock()
    store.upsert.return_value = True
    store.delete.return_value = True
    return store


def test_entity_search_matches_mcore_aliases():
    record = lm.add_memory_record(
        "environment_fact",
        "memorycore service facts",
        "The memorycore source lives in /home/advancer/project/memorycore.",
        memory_id="entity-mcore",
        atomize=False,
    )

    hits = lm.entity_search("memorycore", limit=5)

    assert [hit["memory_id"] for hit in hits] == [record["id"]]
    assert hits[0]["normalized_entity"] == "mcore"
    assert hits[0]["boost"] > 0


def test_context_uses_entity_hits_and_prefers_atomic_child_over_parent(monkeypatch):
    monkeypatch.setattr(
        "memorycore.storage.search._vector_search_ids",
        lambda task, top_k=20, score_threshold=0.35: [],
    )
    content = "\n".join([
        "- memorycore source path is /home/advancer/project/memorycore for code changes.",
        "- memory.sqlite3 is the SQLite DB under /home/advancer/project/memorycore.",
        "- MCP endpoint is http://127.0.0.1:8318/mcp for clients.",
    ])
    with patch("memorycore.storage.crud._get_vector_store", return_value=_mock_vector_store()):
        parent = lm.add_memory_record(
            "project_memory",
            "Parent memorycore memory.sqlite3 summary",
            content,
            memory_id="entity-parent",
            atomize=True,
        )

    with managed_conn() as conn:
        child_ids = [
            row["id"] for row in conn.execute(
                """
                SELECT id FROM memories
                WHERE json_extract(metadata_json, '$.parent_id') = ?
                """,
                (parent["id"],),
            ).fetchall()
        ]

    pack = lm.build_context_pack("memorycore memory.sqlite3", agent="pytest")

    assert pack["trace"]["entity_hits"] >= 1
    assert any(child_id in pack["used_ids"] for child_id in child_ids)
    assert parent["id"] not in pack["used_ids"]
    assert pack["trace"]["prefer_atomic"] is True
    assert pack["trace"]["include_parent"] is False
