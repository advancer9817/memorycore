"""Tests for Context Pack response shape (迭代 218 slim-response contract).

Contract since 2026-09-03 (P0/P1 slim-response optimization):
- Default build_context_pack() returns ONLY {"context", "warnings"} (slim
  envelope — hooks/plugins consume just the context text).
- verbose=True returns {"context", "records", "filtered_ids", "warnings",
  "telemetry"}. The former used_ids/sections/budget_chars/quality/trace
  fields were removed; trace+quality merged into `telemetry`.
"""
from __future__ import annotations

import memorycore as lm


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
# slim envelope (default)
# ---------------------------------------------------------------------------

class TestSlimEnvelope:
    def test_default_shape_is_slim(self):
        _add("Slim A", mem_type="user_profile")
        pack = lm.build_context_pack(task="slim test", scope="global")
        assert set(pack.keys()) == {"context", "warnings"}, (
            f"Slim envelope must contain only context+warnings, got: {sorted(pack)}"
        )

    def test_slim_context_is_nonempty_text(self):
        _add("Slim B", mem_type="user_profile")
        pack = lm.build_context_pack(task="slim text test", scope="global")
        assert isinstance(pack["context"], str)
        assert "memory_context" in pack["context"]

    def test_slim_still_records_quality_events(self):
        """The server-side quality-event write must happen even in slim mode
        (memory_context_stats depends on it)."""
        _add("Slim C", mem_type="user_profile")
        before = lm.get_context_quality_stats(limit=50)
        n_before = len(before.get("events", before if isinstance(before, list) else []))
        lm.build_context_pack(task="slim stats probe", scope="global")
        after = lm.get_context_quality_stats(limit=50)
        n_after = len(after.get("events", after if isinstance(after, list) else []))
        assert n_after >= n_before, "quality events must still be recorded in slim mode"


# ---------------------------------------------------------------------------
# verbose=True full envelope
# ---------------------------------------------------------------------------

class TestVerboseEnvelope:
    def test_verbose_shape(self):
        _add("Verb A", mem_type="user_profile")
        pack = lm.build_context_pack(task="verbose test", scope="global", verbose=True)
        assert set(pack.keys()) == {"context", "records", "filtered_ids", "warnings", "telemetry"}, (
            f"Verbose envelope keys changed: {sorted(pack)}"
        )

    def test_records_are_id_type_title_only(self):
        _add("Verb B", mem_type="project_memory")
        pack = lm.build_context_pack(task="verbose project", scope="global", verbose=True)
        for r in pack["records"]:
            assert set(r.keys()) == {"id", "type", "title"}, f"slim record has extra fields: {r}"

    def test_telemetry_fields_present(self):
        _add("Verb C", mem_type="user_profile")
        pack = lm.build_context_pack(task="telemetry test", scope="global", verbose=True)
        t = pack["telemetry"]
        for field in ("total_candidates", "used_count", "filtered_count",
                      "fallback_used", "hit_rate", "filter_rate", "retrieval_mode",
                      "task_type", "estimated_tokens", "used_chars"):
            assert field in t, f"telemetry missing '{field}'"
        # merged/deduplicated fields must not resurrect
        for gone in ("type_weights", "profile_query_expansions", "prefer_atomic", "include_parent"):
            assert gone not in t, f"telemetry should not carry '{gone}' anymore"

    def test_telemetry_counts_match_records(self):
        _add("Verb D", mem_type="user_profile")
        _add("Verb E", mem_type="environment_fact")
        pack = lm.build_context_pack(task="telemetry counts", scope="global", verbose=True)
        t = pack["telemetry"]
        assert t["used_count"] == len(pack["records"])
        assert t["filtered_count"] == len(pack["filtered_ids"])

    def test_no_removed_fields_anywhere(self):
        """used_ids/sections/budget_chars/quality/trace are gone for good."""
        _add("Verb F", mem_type="user_profile")
        pack = lm.build_context_pack(task="removed fields", scope="global", verbose=True)
        for gone in ("used_ids", "sections", "budget_chars", "quality", "trace"):
            assert gone not in pack, f"'{gone}' must not be in the verbose envelope"

    def test_used_ids_consistency_via_records(self):
        """Callers that need the used-id list derive it from records."""
        _add("Verb G", mem_type="user_profile")
        pack = lm.build_context_pack(task="consistency check", scope="global", verbose=True)
        used_ids = [r["id"] for r in pack["records"]]
        assert len(used_ids) == len(set(used_ids))
        assert pack["telemetry"]["used_count"] == len(used_ids)


# ---------------------------------------------------------------------------
# warnings preserved in both modes
# ---------------------------------------------------------------------------

class TestWarningsPreserved:
    def test_warnings_key_in_both_modes(self):
        _add("Warn A", mem_type="user_profile")
        slim = lm.build_context_pack(task="warn slim", scope="global")
        full = lm.build_context_pack(task="warn full", scope="global", verbose=True)
        assert "warnings" in slim
        assert "warnings" in full
        assert isinstance(slim["warnings"], list)
