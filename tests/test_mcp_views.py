"""Tests for MCP Dedicated Presentation Layer (Agent DTO / View Adapter).

Verifies that MCP tools strictly return lightweight, isolated Agent views
without leaking internal SQLite schema columns, tracking metrics, or governance metadata.
"""
from __future__ import annotations

from typing import Any
import pytest

from memorycore.mcp_views import (
    to_mcp_add_result,
    to_mcp_entity_hit,
    to_mcp_feedback_result,
    to_mcp_memories,
    to_mcp_memory,
    to_mcp_update_result,
    to_mcp_vector_hit,
)
import memorycore.server as srv


def _mock_full_row() -> dict[str, Any]:
    return {
        "id": "test-id-12345",
        "type": "project_memory",
        "scope": "project",
        "title": "测试记忆标题",
        "content": "测试记忆的详细事实正文内容",
        "source": "manual",
        "source_agent": "hermes",
        "project_path": "/home/advancer/project/memorycore",
        "created_at": "2026-09-01T10:00:00+08:00",
        "updated_at": "2026-09-04T12:00:00+08:00",
        "last_accessed_at": "2026-09-04T12:00:00+08:00",
        "confidence": 0.95,
        "importance": 0.85,
        "status": "active",
        "decay_policy": "review",
        "feedback_score": 0.5,
        "injected_count": 42,
        "ineffective_count": 1,
        "effectiveness_score": 0.98,
        "last_injected_at": "2026-09-04T12:00:00+08:00",
        "valid_from": None,
        "valid_until": None,
        "superseded_by": None,
        "fact_lineage_root": None,
        "tags": ["project:mcore", "mcp"],
        "related_ids": [],
        "metadata": {"fact_hash": "abcd1234ef", "parent_id": "root-001"},
    }


def test_to_mcp_memory_filters_all_internal_fields():
    raw = _mock_full_row()
    view = to_mcp_memory(raw)
    assert view is not None

    expected_keys = {"id", "title", "content", "type", "tags", "updated_at", "project_path"}
    assert set(view.keys()) == expected_keys
    assert view["id"] == "test-id-12345"
    assert view["title"] == "测试记忆标题"
    assert view["content"] == "测试记忆的详细事实正文内容"
    assert view["type"] == "project_memory"
    assert view["tags"] == ["project:mcore", "mcp"]
    assert view["updated_at"] == "2026-09-04"
    assert view["project_path"] == "/home/advancer/project/memorycore"

    # Strictly verify internal leakages are removed
    forbidden_keys = {
        "importance", "confidence", "feedback_score", "effectiveness_score",
        "injected_count", "ineffective_count", "last_accessed_at", "last_injected_at",
        "status", "decay_policy", "source", "source_agent", "metadata",
        "valid_from", "valid_until", "superseded_by", "fact_lineage_root", "related_ids",
        "created_at",
    }
    for k in forbidden_keys:
        assert k not in view, f"Internal field '{k}' must NOT leak to MCP view!"


def test_to_mcp_memory_without_project_path():
    raw = _mock_full_row()
    raw["project_path"] = ""
    view = to_mcp_memory(raw)
    assert view is not None
    assert "project_path" not in view
    assert set(view.keys()) == {"id", "title", "content", "type", "tags", "updated_at"}


def test_to_mcp_vector_hit_flattens_and_deduplicates():
    class MockHit:
        id = "vec-1"
        score = 0.89234
        text = "Vector matching text"
        payload = {
            "type": "decision",
            "tags": ["arch"],
            "project_path": "/path/to/repo",
            "text": "Vector matching text",  # duplicate in payload
            "kind": "atomic_fact",
            "parent_id": "p-1",
        }

    hit = MockHit()
    view = to_mcp_vector_hit(hit)

    assert view == {
        "id": "vec-1",
        "score": 0.8923,
        "text": "Vector matching text",
        "type": "decision",
        "tags": ["arch"],
        "project_path": "/path/to/repo",
    }
    assert "payload" not in view


def test_to_mcp_entity_hit_cleans_nested_memory():
    raw_hit = {
        "memory_id": "ent-mem-1",
        "entity": "MemoryCore",
        "normalized_entity": "memorycore",
        "entity_type": "project",
        "weight": 1.0,
        "boost": 0.25,
        "memory": _mock_full_row(),
        "matched_query_entities": ["mcore"],
    }
    view = to_mcp_entity_hit(raw_hit)
    assert view is not None
    assert view["memory_id"] == "ent-mem-1"
    assert view["boost"] == 0.25
    assert set(view["memory"].keys()) == {"id", "title", "content", "type", "tags", "updated_at", "project_path"}
    assert "importance" not in view["memory"]


def test_to_mcp_action_receipts():
    raw = _mock_full_row()

    add_res = to_mcp_add_result(raw)
    assert add_res == {
        "id": "test-id-12345",
        "status": "active",
        "title": "测试记忆标题",
        "type": "project_memory",
        "source_agent": "hermes",
        "project_path": "/home/advancer/project/memorycore",
    }

    update_res = to_mcp_update_result(raw)
    assert update_res == {
        "id": "test-id-12345",
        "updated": True,
        "title": "测试记忆标题",
        "type": "project_memory",
    }

    feedback_res = to_mcp_feedback_result({"feedback_id": "fb-001", "memory": raw}, "test-id-12345", 0.75)
    assert feedback_res == {
        "id": "test-id-12345",
        "feedback_id": "fb-001",
        "recorded": True,
        "score": 0.75,
    }
    assert "memory" not in feedback_res


def test_server_mcp_tools_return_slim_views(isolated_memory_db):
    """End-to-end test against server.py MCP tools."""
    # 1. memory_add
    add_out = srv.memory_add(
        type="project_memory",
        title="Server test memory",
        content="Testing MCP slim view returns",
        tags=["test"],
    )
    assert "id" in add_out
    assert add_out["title"] == "Server test memory"
    assert "importance" not in add_out
    assert "created_at" not in add_out

    mem_id = add_out["id"]

    # 2. memory_get
    get_out = srv.memory_get(mem_id)
    assert get_out is not None
    assert get_out["id"] == mem_id
    assert get_out["title"] == "Server test memory"
    assert "importance" not in get_out
    assert "status" not in get_out

    # 3. memory_search
    search_out = srv.memory_search(query="Server test memory")
    assert isinstance(search_out, list)
    assert len(search_out) >= 1
    hit = [r for r in search_out if r["id"] == mem_id][0]
    assert set(hit.keys()) == {"id", "title", "content", "type", "tags", "updated_at"}

    # 4. memory_feedback
    fb_out = srv.memory_feedback(mem_id, score=0.8, note="good")
    assert fb_out["id"] == mem_id
    assert fb_out["recorded"] is True
    assert fb_out["score"] == 0.8
    assert "memory" not in fb_out

    # 5. memory_update
    up_out = srv.memory_update(mem_id, title="Server test memory updated")
    assert up_out["id"] == mem_id
    assert up_out["updated"] is True
    assert up_out["title"] == "Server test memory updated"
    assert "importance" not in up_out
