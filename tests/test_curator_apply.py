"""Smoke test: apply_llm_curator(dry_run=False) with a mock plan."""
import json

import pytest


def test_apply_llm_curator_split_writes_children(tmp_path, monkeypatch):
    """apply_llm_curator split branch should insert child records into SQLite."""
    pytest.importorskip("memorycore")
    from memorycore.storage.curator_llm import apply_llm_curator
    from memorycore import add_memory_record

    parent = add_memory_record(
        "project_memory",
        "Split parent",
        "Parent fact A. Parent fact B. Parent fact C.",
        memory_id="split-parent",
    )

    plan = {
        "semantic_duplicates": [],
        "contradictions": [],
        "importance_reassessments": [],
        "split_candidates": [
            {
                "id": parent["id"],
                "title": "Split parent",
                "sub_memories": [
                    {"content": "Child fact 1", "title": "Child 1", "importance": 0.6},
                    {"content": "Child fact 2", "title": "Child 2", "importance": 0.7},
                ],
                "reason": "test split",
            }
        ],
    }

    result = apply_llm_curator(plan, dry_run=False)
    assert isinstance(result, dict)
    assert result["dry_run"] is False
    assert result["applied"]["split_children_created"] == 2
    assert result["applied"]["split_children_skipped"] == 0

    duplicate_result = apply_llm_curator(plan, dry_run=False)
    assert duplicate_result["applied"]["split_children_created"] == 0
    assert duplicate_result["applied"]["split_children_skipped"] == 2

    from memorycore.storage.db import read_conn

    with read_conn() as conn:
        rows = conn.execute(
            "SELECT id, metadata_json FROM memories WHERE json_extract(metadata_json, '$.parent_id') = ?",
            (parent["id"],),
        ).fetchall()
        link_rows = conn.execute(
            "SELECT source_id, target_id, relation_type FROM memory_links WHERE source_id = ? OR target_id = ?",
            (parent["id"], parent["id"]),
        ).fetchall()
    hashes = []
    child_ids = []
    for row in rows:
        metadata = json.loads(row["metadata_json"])
        hashes.append(metadata["fact_hash"])
        child_ids.append(row["id"])
    assert len(hashes) == len(set(hashes)) == 2
    assert {(row["source_id"], row["target_id"], row["relation_type"]) for row in link_rows} == {
        (child_id, parent["id"], "part_of") for child_id in child_ids
    } | {
        (parent["id"], child_id, "supports") for child_id in child_ids
    }


def test_apply_llm_curator_logs_duplicate_merge_audit(tmp_path, monkeypatch):
    """Duplicate archive with merge info should persist merge audit details."""
    pytest.importorskip("memorycore")
    from memorycore.storage.curator_llm import apply_llm_curator
    from memorycore import add_memory_record
    from memorycore.storage.db import read_conn

    keep = add_memory_record("project_memory", "Keep", "Primary fact", memory_id="keep-dup")
    drop = add_memory_record("project_memory", "Drop", "Duplicate fact with extra detail", memory_id="drop-dup")

    result = apply_llm_curator({
        "semantic_duplicates": [{
            "action": "archive_and_merge_duplicate",
            "keep_id": keep["id"],
            "drop_id": drop["id"],
            "keep_title": keep["title"],
            "drop_title": drop["title"],
            "merge_info": "extra detail",
            "reason": "same fact",
        }],
        "contradictions": [],
        "importance_reassessments": [],
        "split_candidates": [],
    }, dry_run=False)

    assert result["applied"]["archived"] == 1
    assert result["applied"]["duplicate_merge_audits"] == 1
    with read_conn() as conn:
        memory_row = conn.execute("SELECT status FROM memories WHERE id=?", (drop["id"],)).fetchone()
        audit_row = conn.execute(
            "SELECT detail_json FROM audit_events WHERE event_type='llm_curator_apply' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    assert memory_row["status"] == "archived"
    detail = json.loads(audit_row["detail_json"])
    assert detail["duplicate_merge_audits"] == [{
        "keep_id": keep["id"],
        "drop_id": drop["id"],
        "keep_title": keep["title"],
        "drop_title": drop["title"],
        "merge_info": "extra detail",
        "reason": "same fact",
    }]


def test_apply_llm_curator_archives_duplicate_atomic_facts(tmp_path, monkeypatch):
    """Duplicate atomic facts with the same parent_id and fact_hash are safely archived."""
    pytest.importorskip("memorycore")
    from memorycore.storage.curator_llm import apply_llm_curator
    from memorycore import add_memory_record
    from memorycore.storage.db import read_conn

    parent = add_memory_record("project_memory", "Parent", "Parent content", memory_id="atomic-parent")
    metadata = {"kind": "atomic_fact", "parent_id": parent["id"], "fact_hash": "same-hash"}
    first = add_memory_record("project_memory", "Fact 1", "Duplicate fact", memory_id="fact-1", metadata=metadata)
    second = add_memory_record("project_memory", "Fact 2", "Duplicate fact", memory_id="fact-2", metadata=metadata)

    result = apply_llm_curator({
        "semantic_duplicates": [],
        "contradictions": [],
        "importance_reassessments": [],
        "split_candidates": [],
    }, dry_run=False)

    assert result["applied"]["duplicate_atomic_facts_archived"] == 1
    with read_conn() as conn:
        rows = conn.execute(
            "SELECT id, status FROM memories WHERE id IN (?, ?) ORDER BY id",
            (first["id"], second["id"]),
        ).fetchall()
        audit_row = conn.execute(
            "SELECT detail_json FROM audit_events WHERE event_type='llm_curator_apply' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    assert {row["id"]: row["status"] for row in rows} == {
        first["id"]: "active",
        second["id"]: "archived",
    }
    detail = json.loads(audit_row["detail_json"])
    assert detail["duplicate_atomic_fact_audits"] == [{
        "parent_id": parent["id"],
        "fact_hash": "same-hash",
        "keep_id": first["id"],
        "archived_ids": [second["id"]],
        "reason": "duplicate atomic facts with same parent_id and fact_hash",
    }]
