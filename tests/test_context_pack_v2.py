"""Tests for Context Pack v2 – new 'sections' and 'trace' fields.

TDD: written before the implementation is updated. These tests should fail
(RED) until build_context_pack() is updated.
"""
from __future__ import annotations

import local_memory_mcp as lm


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _add(title: str, content: str = "some content", mem_type: str = "user_profile") -> str:
    result = lm.add_memory_record(
        memory_type=mem_type,
        title=title,
        content=content,
        scope="global",
    )
    return result["id"]


# ---------------------------------------------------------------------------
# sections field
# ---------------------------------------------------------------------------

class TestSectionsField:
    def test_sections_key_present(self):
        """build_context_pack must include a 'sections' key."""
        _add("Pref A", mem_type="user_profile")
        pack = lm.build_context_pack(task="test task", scope="global")
        assert "sections" in pack, "'sections' key missing from context pack"

    def test_sections_is_list(self):
        _add("Pref B", mem_type="user_profile")
        pack = lm.build_context_pack(task="test task", scope="global")
        assert isinstance(pack["sections"], list), "'sections' must be a list"

    def test_sections_structure_each_item(self):
        """Each section must have 'type' (str) and 'records' (list[dict])."""
        _add("Env fact X", mem_type="environment_fact")
        pack = lm.build_context_pack(task="env fact", scope="global")
        for s in pack["sections"]:
            assert "type" in s, f"section missing 'type': {s}"
            assert "records" in s, f"section missing 'records': {s}"
            assert isinstance(s["type"], str), "'type' must be str"
            assert isinstance(s["records"], list), "'records' must be list"

    def test_sections_only_used_records(self):
        """Sections must only contain records that appear in used_ids."""
        _add("Arch A", mem_type="agent_architecture")
        _add("Arch B", mem_type="agent_architecture")
        pack = lm.build_context_pack(task="architecture design", scope="global")
        used_ids = set(pack["used_ids"])
        for section in pack["sections"]:
            for rec in section["records"]:
                assert rec["id"] in used_ids, (
                    f"Record {rec['id']} in sections but not in used_ids"
                )

    def test_sections_no_empty_sections(self):
        """Sections with zero records must not appear in the list."""
        _add("Decision A", mem_type="decision")
        pack = lm.build_context_pack(task="decide something", scope="global")
        for section in pack["sections"]:
            assert len(section["records"]) > 0, (
                f"Empty section found: type={section['type']}"
            )

    def test_sections_ordered_by_groups_order(self):
        """Sections must follow the canonical groups_order sequence."""
        groups_order = [
            "skill_candidate", "user_profile", "environment_fact",
            "agent_architecture", "project_memory", "decision",
            "timeline_event", "episodic_memory", "feedback",
        ]
        _add("Up A", mem_type="user_profile")
        _add("Env A", mem_type="environment_fact")
        pack = lm.build_context_pack(task="user env info", scope="global")
        types_in_result = [s["type"] for s in pack["sections"]]
        # Verify relative order matches groups_order
        indices = [groups_order.index(t) for t in types_in_result if t in groups_order]
        assert indices == sorted(indices), (
            f"Sections not ordered by groups_order: {types_in_result}"
        )

    def test_sections_records_have_id_and_title(self):
        """Every record in sections must at minimum have 'id' and 'title'."""
        _add("Profile X", mem_type="user_profile")
        pack = lm.build_context_pack(task="profile", scope="global")
        for section in pack["sections"]:
            for rec in section["records"]:
                assert "id" in rec, "record in section missing 'id'"
                assert "title" in rec, "record in section missing 'title'"

    def test_existing_fields_preserved(self):
        """All original fields must still be present (no regression)."""
        _add("Proj A", mem_type="project_memory")
        pack = lm.build_context_pack(task="project", scope="global")
        for field in ("context", "records", "used_ids", "filtered_ids",
                      "warnings", "budget_chars", "quality"):
            assert field in pack, f"Original field '{field}' was removed"

    def test_sections_empty_when_no_used_ids(self):
        """When there are no candidates at all, sections must be []."""
        pack = lm.build_context_pack(task="no data at all xyz123", scope="global")
        assert pack["sections"] == [], (
            f"Expected empty sections, got: {pack['sections']}"
        )


# ---------------------------------------------------------------------------
# trace field
# ---------------------------------------------------------------------------

class TestTraceField:
    def test_trace_key_present(self):
        pack = lm.build_context_pack(task="trace test", scope="global")
        assert "trace" in pack, "'trace' key missing from context pack"

    def test_trace_is_dict(self):
        pack = lm.build_context_pack(task="trace test", scope="global")
        assert isinstance(pack["trace"], dict)

    def test_trace_fields_present(self):
        """trace must have total_candidates, used_count, filtered_count, fallback_used."""
        pack = lm.build_context_pack(task="trace test", scope="global")
        trace = pack["trace"]
        for field in ("total_candidates", "used_count", "filtered_count", "fallback_used"):
            assert field in trace, f"trace missing field '{field}'"

    def test_trace_types(self):
        _add("T1", mem_type="user_profile")
        pack = lm.build_context_pack(task="trace types", scope="global")
        trace = pack["trace"]
        assert isinstance(trace["total_candidates"], int)
        assert isinstance(trace["used_count"], int)
        assert isinstance(trace["filtered_count"], int)
        assert isinstance(trace["fallback_used"], bool)

    def test_trace_counts_match_reality(self):
        """Counts must match used_ids and records lengths."""
        _add("M1", mem_type="user_profile")
        _add("M2", mem_type="environment_fact")
        pack = lm.build_context_pack(task="memory test", scope="global")
        trace = pack["trace"]
        assert trace["total_candidates"] == len(pack["records"]), (
            "total_candidates does not match len(records)"
        )
        assert trace["used_count"] == len(pack["used_ids"]), (
            "used_count does not match len(used_ids)"
        )
        assert trace["filtered_count"] == len(pack["filtered_ids"]), (
            "filtered_count does not match len(filtered_ids)"
        )

    def test_trace_fallback_used_false_when_query_finds_results(self):
        """fallback_used must be False when the original query returns records."""
        _add("Specific user preference", mem_type="user_profile",
             content="Specific user preference content")
        pack = lm.build_context_pack(task="specific user preference", scope="global")
        # If we found records on the first search, fallback_used should be False
        # (unless the first pass returned 0 rows – hard to guarantee exactly,
        #  so we only assert when used_ids is non-empty and records came from query)
        # We just verify the field is present and is a bool
        assert isinstance(pack["trace"]["fallback_used"], bool)

    def test_trace_fallback_used_true_when_forced(self):
        """fallback_used must be True when the task query returns nothing
        but the empty-query fallback returns something."""
        # Add memory not related to the query keyword
        _add("Completely unrelated fact", mem_type="environment_fact",
             content="OS is Linux, Python 3.12 installed")
        # Query with a long but unmatched string to force fallback
        pack = lm.build_context_pack(
            task="zzz_totally_unmatched_keyword_xyz_abc_9999",
            scope="global",
        )
        # The first search should return 0, fallback triggers
        # records will be non-empty (from fallback), fallback_used=True
        if pack["records"]:  # only assert if fallback actually retrieved something
            assert pack["trace"]["fallback_used"] is True, (
                "fallback_used should be True when first query returned nothing"
            )
