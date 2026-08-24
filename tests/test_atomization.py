from __future__ import annotations

from unittest.mock import MagicMock, patch

import memorycore as lm
from memorycore.storage.db import managed_conn


def _mock_vector_store():
    store = MagicMock()
    store.upsert.return_value = True
    store.delete.return_value = True
    return store


def test_memory_add_atomizes_parent_into_linked_child_facts():
    content = "\n".join([
        "- memorycore source path is /home/advancer/project/memorycore and it is the service root.",
        "- MCP endpoint is http://127.0.0.1:8318/mcp for memorycore clients.",
        "- SQLite DB is /home/advancer/project/memorycore/memory.sqlite3 for durable facts.",
        "- Qdrant endpoint is http://127.0.0.1:6333 and collection is agent_memory.",
    ])

    with patch("memorycore.storage.crud._get_vector_store", return_value=_mock_vector_store()):
        parent = lm.add_memory_record(
            "project_memory",
            "Long memorycore operating facts",
            content,
            memory_id="atom-parent",
            atomize=True,
        )

    parent_after = lm.get_record(parent["id"])
    assert parent_after["metadata"]["kind"] == "parent_memory"
    assert parent_after["metadata"]["child_count"] >= 3

    with managed_conn() as conn:
        children = [dict(row) for row in conn.execute(
            """
            SELECT * FROM memories
            WHERE json_extract(metadata_json, '$.parent_id') = ?
            ORDER BY created_at
            """,
            (parent["id"],),
        ).fetchall()]
        child_ids = [row["id"] for row in children]
        links = [dict(row) for row in conn.execute(
            "SELECT source_id, target_id, relation_type FROM memory_links"
        ).fetchall()]

    assert len(children) >= 3
    for child in children:
        metadata = lm.get_record(child["id"])["metadata"]
        assert metadata["kind"] == "atomic_fact"
        assert metadata["parent_id"] == parent["id"]
        assert metadata["fact_hash"]
        assert metadata["source_span"]["end"] > metadata["source_span"]["start"]
        assert metadata["atomizer_version"] == "mem0-inspired-v1"

    assert not any(lm.get_record(child_id)["metadata"].get("parent_id") in child_ids for child_id in child_ids)
    assert {link["relation_type"] for link in links} >= {"part_of", "supports"}
    assert all(
        any(link["source_id"] == child_id and link["target_id"] == parent["id"] and link["relation_type"] == "part_of" for link in links)
        for child_id in child_ids
    )
    assert all(
        any(link["source_id"] == parent["id"] and link["target_id"] == child_id and link["relation_type"] == "supports" for link in links)
        for child_id in child_ids
    )


def test_atomize_report_is_idempotent():
    content = "\n".join([
        "- memorycore service root is /home/advancer/project/memorycore.",
        "- memorycore MCP endpoint is http://127.0.0.1:8318/mcp.",
        "- memory.sqlite3 is the SQLite database for memorycore.",
    ])
    parent = lm.add_memory_record(
        "project_memory",
        "Idempotent atomization",
        content,
        memory_id="atom-idempotent",
        atomize=False,
    )

    with patch("memorycore.storage.crud._get_vector_store", return_value=_mock_vector_store()):
        first = lm.atomize_report(record_id=parent["id"], dry_run=False, min_chars=1)
        second = lm.atomize_report(record_id=parent["id"], dry_run=False, min_chars=1)

    assert first["created"] >= 2
    assert second["created"] == 0
    assert second["duplicates"] >= first["created"]
