"""Tests for Graph / Warning enhancements.

New relation types: blocked_by, causes, failure_pattern (total 8).
New warning triggers: causes and failure_pattern (severity="medium").

TDD: these tests should fail (RED) before models.py / storage.py are updated.
"""
from __future__ import annotations

import memorycore as lm
from memorycore.models import VALID_RELATION_TYPES


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _add(title: str, content: str = "content", mem_type: str = "episodic_memory") -> str:
    result = lm.add_memory_record(
        memory_type=mem_type,
        title=title,
        content=content,
        scope="global",
    )
    return result["id"]


def _link(src: str, tgt: str, relation: str, weight: float = 0.9) -> dict:
    return lm.memory_link_add(
        source_id=src,
        target_id=tgt,
        relation_type=relation,
        weight=weight,
    )


# ---------------------------------------------------------------------------
# VALID_RELATION_TYPES – 8 types
# ---------------------------------------------------------------------------

class TestValidRelationTypes:
    def test_total_count_is_eight(self):
        assert len(VALID_RELATION_TYPES) == 8, (
            f"Expected 8 relation types, got {len(VALID_RELATION_TYPES)}: "
            f"{sorted(VALID_RELATION_TYPES)}"
        )

    def test_original_five_present(self):
        for rt in ("related_to", "supersedes", "contradicts", "supports", "part_of"):
            assert rt in VALID_RELATION_TYPES, f"Original type '{rt}' missing"

    def test_blocked_by_present(self):
        assert "blocked_by" in VALID_RELATION_TYPES

    def test_causes_present(self):
        assert "causes" in VALID_RELATION_TYPES

    def test_failure_pattern_present(self):
        assert "failure_pattern" in VALID_RELATION_TYPES


# ---------------------------------------------------------------------------
# memory_link_add accepts new types
# ---------------------------------------------------------------------------

class TestLinkAddNewTypes:
    def test_blocked_by_link_created(self):
        a = _add("Task A")
        b = _add("Task B")
        result = _link(a, b, "blocked_by")
        assert "error" not in result, f"blocked_by link failed: {result}"
        assert result.get("relation_type") == "blocked_by"

    def test_causes_link_created(self):
        a = _add("Event X")
        b = _add("Event Y")
        result = _link(a, b, "causes")
        assert "error" not in result, f"causes link failed: {result}"
        assert result.get("relation_type") == "causes"

    def test_failure_pattern_link_created(self):
        a = _add("Bug Z")
        b = _add("Symptom W")
        result = _link(a, b, "failure_pattern")
        assert "error" not in result, f"failure_pattern link failed: {result}"
        assert result.get("relation_type") == "failure_pattern"

    def test_invalid_type_still_rejected(self):
        a = _add("Node A")
        b = _add("Node B")
        result = _link(a, b, "unknown_type_xyz")
        assert "error" in result, "Expected error for invalid relation type"


# ---------------------------------------------------------------------------
# get_active_warnings includes causes and failure_pattern
# ---------------------------------------------------------------------------

class TestWarningsForNewTypes:
    def test_causes_triggers_warning(self):
        a = _add("Root cause")
        b = _add("Effect")
        _link(a, b, "causes", weight=0.9)
        warnings = lm.get_active_warnings(memory_ids=[a, b])
        relation_types_in_warnings = {w["relation_type"] for w in warnings}
        assert "causes" in relation_types_in_warnings, (
            f"Expected 'causes' in warnings, got: {relation_types_in_warnings}"
        )

    def test_failure_pattern_triggers_warning(self):
        a = _add("Failure source")
        b = _add("Failure target")
        _link(a, b, "failure_pattern", weight=0.9)
        warnings = lm.get_active_warnings(memory_ids=[a, b])
        relation_types_in_warnings = {w["relation_type"] for w in warnings}
        assert "failure_pattern" in relation_types_in_warnings, (
            f"Expected 'failure_pattern' in warnings, got: {relation_types_in_warnings}"
        )

    def test_causes_warning_severity_is_medium(self):
        a = _add("Cause node")
        b = _add("Effect node")
        _link(a, b, "causes", weight=0.5)
        warnings = lm.get_active_warnings(memory_ids=[a, b])
        causes_warnings = [w for w in warnings if w["relation_type"] == "causes"]
        assert causes_warnings, "No causes warning found"
        for w in causes_warnings:
            assert w["severity"] == "medium", (
                f"causes warning severity should be 'medium', got: {w['severity']}"
            )

    def test_failure_pattern_warning_severity_is_medium(self):
        a = _add("FP source")
        b = _add("FP target")
        _link(a, b, "failure_pattern", weight=0.5)
        warnings = lm.get_active_warnings(memory_ids=[a, b])
        fp_warnings = [w for w in warnings if w["relation_type"] == "failure_pattern"]
        assert fp_warnings, "No failure_pattern warning found"
        for w in fp_warnings:
            assert w["severity"] == "medium", (
                f"failure_pattern warning severity should be 'medium', got: {w['severity']}"
            )

    def test_existing_contradicts_still_triggers_warning(self):
        a = _add("Claim P")
        b = _add("Counter claim")
        _link(a, b, "contradicts", weight=0.8)
        warnings = lm.get_active_warnings(memory_ids=[a, b])
        relation_types = {w["relation_type"] for w in warnings}
        assert "contradicts" in relation_types, "contradicts should still trigger warnings"

    def test_existing_supersedes_still_triggers_warning(self):
        a = _add("New fact")
        b = _add("Old fact")
        _link(a, b, "supersedes", weight=0.8)
        warnings = lm.get_active_warnings(memory_ids=[a, b])
        relation_types = {w["relation_type"] for w in warnings}
        assert "supersedes" in relation_types, "supersedes should still trigger warnings"

    def test_related_to_does_not_trigger_warning(self):
        """related_to, supports, part_of, blocked_by should NOT trigger warnings."""
        a = _add("Node 1")
        b = _add("Node 2")
        _link(a, b, "related_to", weight=0.9)
        warnings = lm.get_active_warnings(memory_ids=[a, b])
        relation_types = {w["relation_type"] for w in warnings}
        assert "related_to" not in relation_types

    def test_blocked_by_does_not_trigger_warning(self):
        """blocked_by is structural and should NOT trigger a warning."""
        a = _add("Blocked task")
        b = _add("Blocker")
        _link(a, b, "blocked_by", weight=0.9)
        warnings = lm.get_active_warnings(memory_ids=[a, b])
        relation_types = {w["relation_type"] for w in warnings}
        assert "blocked_by" not in relation_types, (
            "blocked_by should not trigger warnings"
        )

    def test_warning_respects_min_weight(self):
        """causes with weight below min_weight threshold should not surface."""
        a = _add("Low weight cause")
        b = _add("Effect ignored")
        _link(a, b, "causes", weight=0.1)
        warnings = lm.get_active_warnings(memory_ids=[a, b], min_weight=0.4)
        causes_warnings = [w for w in warnings if w["relation_type"] == "causes"]
        assert causes_warnings == [], (
            "causes with weight < min_weight should be filtered out"
        )


# ---------------------------------------------------------------------------
# Graph API integration tests
# ---------------------------------------------------------------------------

def _make_graph_client():
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient
    from memorycore.frontend import configure_frontend, frontend_api

    configure_frontend(host="127.0.0.1", port=8318, auth_token="", enabled=True)
    app = Starlette(routes=[
        Route("/api/{path:path}", frontend_api, methods=["GET", "POST", "PATCH", "PUT", "DELETE"]),
    ])
    return TestClient(app)


class TestGraphAPI:
    def test_graph_api_returns_nodes(self):
        """GET /api/graph should return nodes for existing memories."""
        lm.add_memory_record("feedback", "Graph test memory", "Testing graph endpoint content")

        with _make_graph_client() as client:
            graph_resp = client.get("/api/graph")

        assert graph_resp.status_code == 200
        data = graph_resp.json()
        payload = data.get("data", data)
        assert "nodes" in payload
        assert len(payload["nodes"]) >= 1

    def test_graph_api_nodes_have_importance(self):
        """Each node in /api/graph must have an importance field."""
        lm.add_memory_record("feedback", "Importance test", "Testing importance field in graph")

        with _make_graph_client() as client:
            graph_resp = client.get("/api/graph")

        data = graph_resp.json()
        payload = data.get("data", data)
        nodes = payload.get("nodes", [])
        assert len(nodes) > 0
        for node in nodes:
            assert "importance" in node, f"Node {node.get('id')} missing importance field"

    def test_graph_api_edges_present(self):
        """GET /api/graph should return an edges list."""
        with _make_graph_client() as client:
            graph_resp = client.get("/api/graph")

        data = graph_resp.json()
        payload = data.get("data", data)
        assert "edges" in payload
        assert isinstance(payload["edges"], list)

    def test_graph_api_status_all_includes_archived_part_of_edges(self):
        """status=all should keep links whose endpoints are not both active."""
        parent_id = _add("Archived graph parent")
        child_id = _add("Archived graph child")
        lm.update_status(parent_id, "archived")
        _link(child_id, parent_id, "part_of")

        with _make_graph_client() as client:
            default_resp = client.get("/api/graph")
            all_resp = client.get("/api/graph?status=all")
            limited_all_resp = client.get("/api/graph?status=all&limit=1")

        default_payload = default_resp.json().get("data", default_resp.json())
        all_payload = all_resp.json().get("data", all_resp.json())
        limited_all_payload = limited_all_resp.json().get("data", limited_all_resp.json())

        default_edges = [
            edge for edge in default_payload["edges"]
            if edge["source"] == child_id and edge["target"] == parent_id
        ]
        all_edges = [
            edge for edge in all_payload["edges"]
            if edge["source"] == child_id and edge["target"] == parent_id
        ]
        limited_edges = [
            edge for edge in limited_all_payload["edges"]
            if edge["source"] == child_id and edge["target"] == parent_id
        ]

        assert default_edges == []
        assert limited_edges == []
        assert all_edges == [{
            "source": child_id,
            "target": parent_id,
            "relation_type": "part_of",
            "weight": 0.9,
        }]
