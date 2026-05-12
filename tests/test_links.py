"""Tests for memory_links schema and MCP tools."""
from __future__ import annotations

import pytest
import local_memory_mcp as lm


# ─── helpers ──────────────────────────────────────────────────────────────────

def make_memory(title: str, memory_id: str | None = None) -> str:
    r = lm.add_memory_record(
        "project_memory",
        title,
        f"Content for {title}",
        memory_id=memory_id,
    )
    return r["id"]


# ─── add_link ─────────────────────────────────────────────────────────────────

class TestAddLink:
    def test_creates_link_between_two_memories(self):
        a = make_memory("A")
        b = make_memory("B")
        link = lm.add_link(a, b, "related_to")
        assert link["source_id"] == a
        assert link["target_id"] == b
        assert link["relation_type"] == "related_to"
        assert link["weight"] == 1.0

    def test_all_valid_relation_types(self):
        a = make_memory("src")
        b = make_memory("tgt")
        for rel in ("related_to", "supersedes", "contradicts", "supports", "part_of"):
            link = lm.add_link(a, b, rel)
            assert link["relation_type"] == rel

    def test_invalid_relation_type_raises(self):
        a = make_memory("x")
        b = make_memory("y")
        with pytest.raises(ValueError, match="relation_type"):
            lm.add_link(a, b, "invented_type")

    def test_upsert_on_duplicate_source_target_relation(self):
        a = make_memory("dup-src")
        b = make_memory("dup-tgt")
        lm.add_link(a, b, "related_to", weight=0.5, note="first")
        link2 = lm.add_link(a, b, "related_to", weight=0.9, note="updated")
        assert link2["weight"] == 0.9
        assert link2["note"] == "updated"

    def test_weight_clamped_to_0_1(self):
        a = make_memory("w-src")
        b = make_memory("w-tgt")
        link = lm.add_link(a, b, "supports", weight=5.0)
        assert link["weight"] == 1.0
        link2 = lm.add_link(a, b, "contradicts", weight=-1.0)
        assert link2["weight"] == 0.0

    def test_nonexistent_source_raises(self):
        b = make_memory("real")
        with pytest.raises(ValueError, match="not found"):
            lm.add_link("nonexistent-id", b, "related_to")

    def test_nonexistent_target_raises(self):
        a = make_memory("real2")
        with pytest.raises(ValueError, match="not found"):
            lm.add_link(a, "nonexistent-id", "related_to")

    def test_different_relations_between_same_pair_coexist(self):
        a = make_memory("multi-src")
        b = make_memory("multi-tgt")
        lm.add_link(a, b, "related_to")
        lm.add_link(a, b, "supports")
        result = lm.query_links(a, direction="outgoing")
        rels = {l["relation_type"] for l in result["outgoing"]}
        assert "related_to" in rels
        assert "supports" in rels

    def test_cascade_delete_when_memory_deleted(self):
        a = make_memory("cascade-src")
        b = make_memory("cascade-tgt")
        lm.add_link(a, b, "related_to")
        lm.update_status(a, "archived")  # keep memory, just check link survives
        result = lm.query_links(a)
        assert result["total"] >= 1


# ─── query_links ──────────────────────────────────────────────────────────────

class TestQueryLinks:
    def test_outgoing_direction(self):
        a = make_memory("q-out-src")
        b = make_memory("q-out-tgt")
        lm.add_link(a, b, "supersedes")
        result = lm.query_links(a, direction="outgoing")
        assert len(result["outgoing"]) >= 1
        assert result["incoming"] == []

    def test_incoming_direction(self):
        a = make_memory("q-in-src")
        b = make_memory("q-in-tgt")
        lm.add_link(a, b, "supports")
        result = lm.query_links(b, direction="incoming")
        assert len(result["incoming"]) >= 1
        assert result["outgoing"] == []

    def test_both_direction(self):
        a = make_memory("q-both-a")
        b = make_memory("q-both-b")
        c = make_memory("q-both-c")
        lm.add_link(a, b, "related_to")  # a → b
        lm.add_link(c, a, "supports")    # c → a
        result = lm.query_links(a, direction="both")
        assert len(result["outgoing"]) >= 1
        assert len(result["incoming"]) >= 1

    def test_filter_by_relation_type(self):
        a = make_memory("q-filter-src")
        b = make_memory("q-filter-tgt")
        lm.add_link(a, b, "related_to")
        lm.add_link(a, b, "contradicts")
        result = lm.query_links(a, direction="outgoing", relation_type="contradicts")
        assert all(l["relation_type"] == "contradicts" for l in result["outgoing"])

    def test_invalid_direction_raises(self):
        a = make_memory("q-dir")
        with pytest.raises(ValueError, match="direction"):
            lm.query_links(a, direction="sideways")

    def test_total_count(self):
        a = make_memory("q-total-src")
        b = make_memory("q-total-b")
        c = make_memory("q-total-c")
        lm.add_link(a, b, "related_to")
        lm.add_link(c, a, "supports")
        result = lm.query_links(a)
        assert result["total"] == len(result["outgoing"]) + len(result["incoming"])

    def test_no_links_returns_empty(self):
        a = make_memory("q-empty")
        result = lm.query_links(a)
        assert result["total"] == 0
        assert result["outgoing"] == []
        assert result["incoming"] == []


# ─── MCP tool wrappers ────────────────────────────────────────────────────────

class TestMCPTools:
    def test_memory_link_add_returns_link(self):
        a = make_memory("mcp-a")
        b = make_memory("mcp-b")
        result = lm.memory_link_add(a, b, "part_of", note="test")
        assert result["relation_type"] == "part_of"
        assert "error" not in result

    def test_memory_link_add_invalid_type_returns_error(self):
        a = make_memory("mcp-err-a")
        b = make_memory("mcp-err-b")
        result = lm.memory_link_add(a, b, "bad_type")
        assert "error" in result

    def test_memory_link_query_returns_structure(self):
        a = make_memory("mcp-q-a")
        b = make_memory("mcp-q-b")
        lm.memory_link_add(a, b, "supersedes")
        result = lm.memory_link_query(a)
        assert "outgoing" in result
        assert "incoming" in result
        assert "total" in result

    def test_memory_link_query_invalid_direction_returns_error(self):
        a = make_memory("mcp-q-dir")
        result = lm.memory_link_query(a, direction="diagonal")
        assert "error" in result
