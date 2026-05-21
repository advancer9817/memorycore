"""Tests for Phase 10: effectiveness tracking, injection recording, memory_warnings, memory_update."""
import pytest
import local_memory_mcp as lm


# ---------------------------------------------------------------------------
# effectiveness tracking in add_feedback
# ---------------------------------------------------------------------------

def test_feedback_positive_increments_injected_count():
    r = lm.add_memory_record("project_memory", "Eff positive", "content")
    mid = r["id"]
    result = lm.add_feedback(mid, 2.0, source_agent="pytest")
    mem = result["memory"]
    assert mem["injected_count"] == 1
    assert mem["ineffective_count"] == 0
    assert mem["effectiveness_score"] > 0.5  # pulled up from default 0.5


def test_feedback_negative_increments_ineffective_count():
    r = lm.add_memory_record("project_memory", "Eff negative", "content")
    mid = r["id"]
    result = lm.add_feedback(mid, -1.0, source_agent="pytest")
    mem = result["memory"]
    assert mem["injected_count"] == 0
    assert mem["ineffective_count"] == 1
    assert mem["effectiveness_score"] < 0.5  # pulled down from default 0.5


def test_feedback_zero_does_not_change_counts():
    r = lm.add_memory_record("project_memory", "Eff zero", "content")
    mid = r["id"]
    result = lm.add_feedback(mid, 0.0, source_agent="pytest")
    mem = result["memory"]
    assert mem["injected_count"] == 0
    assert mem["ineffective_count"] == 0
    assert mem["effectiveness_score"] == pytest.approx(0.5)


def test_feedback_effectiveness_clamped_to_unit_interval():
    r = lm.add_memory_record("project_memory", "Eff clamp", "content")
    mid = r["id"]
    # Many large positive scores should not push above 1.0
    for _ in range(30):
        lm.add_feedback(mid, 10.0)
    mem = lm.get_record(mid)
    assert mem["effectiveness_score"] <= 1.0
    # Many large negative scores should not push below 0.0
    for _ in range(30):
        lm.add_feedback(mid, -10.0)
    mem = lm.get_record(mid)
    assert mem["effectiveness_score"] >= 0.0


# ---------------------------------------------------------------------------
# injection recording in build_context_pack
# ---------------------------------------------------------------------------

def test_build_context_pack_increments_injected_count():
    r = lm.add_memory_record("user_profile", "Inject track", "some profile content for injection test")
    mid = r["id"]
    before = lm.get_record(mid)
    assert before["injected_count"] == 0
    assert before["last_injected_at"] is None

    lm.build_context_pack("injection test", agent="pytest")

    after = lm.get_record(mid)
    assert after["injected_count"] >= 1
    assert after["last_injected_at"] is not None
    assert after["last_accessed_at"] is not None


# ---------------------------------------------------------------------------
# schema migrations
# ---------------------------------------------------------------------------

def test_init_db_migrates_existing_memories_table_without_effectiveness_columns(tmp_path, monkeypatch):
    import sqlite3

    db = tmp_path / "legacy.sqlite3"
    conn = sqlite3.connect(db)
    conn.execute(
        """CREATE TABLE memories (
          id TEXT PRIMARY KEY,
          type TEXT NOT NULL,
          scope TEXT NOT NULL DEFAULT 'global',
          title TEXT NOT NULL,
          content TEXT NOT NULL,
          tags_json TEXT NOT NULL DEFAULT '[]',
          source TEXT NOT NULL DEFAULT 'manual',
          source_agent TEXT NOT NULL DEFAULT 'unknown',
          project_path TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          last_accessed_at TEXT,
          confidence REAL NOT NULL DEFAULT 0.70,
          importance REAL NOT NULL DEFAULT 0.50,
          status TEXT NOT NULL DEFAULT 'active',
          decay_policy TEXT NOT NULL DEFAULT 'review',
          feedback_score REAL NOT NULL DEFAULT 0,
          related_ids_json TEXT NOT NULL DEFAULT '[]',
          metadata_json TEXT NOT NULL DEFAULT '{}'
        )"""
    )
    conn.execute(
        """INSERT INTO memories (
          id,type,scope,title,content,tags_json,source,source_agent,project_path,
          created_at,updated_at,confidence,importance,status,decay_policy,
          related_ids_json,metadata_json
        ) VALUES ('legacy-id','user_profile','global','Legacy','legacy content','[]','manual','pytest','',
                  '2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00',0.7,0.5,'active','review','[]','{}')"""
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("LOCAL_MEMORY_DB", str(db))
    lm._INITIALIZED_DB_PATHS.clear()

    pack = lm.build_context_pack("legacy content", agent="pytest")
    migrated = lm.get_record("legacy-id")

    assert "legacy-id" in pack["used_ids"]
    assert migrated["effectiveness_score"] == pytest.approx(0.5)
    assert migrated["injected_count"] >= 1
    assert migrated["ineffective_count"] == 0
    assert migrated["last_injected_at"] is not None


# ---------------------------------------------------------------------------
# memory_warnings MCP tool
# ---------------------------------------------------------------------------

def test_memory_warnings_returns_empty_for_no_links():
    r = lm.add_memory_record("project_memory", "Warn no links", "content")
    from local_memory_mcp.storage import get_active_warnings
    result = get_active_warnings([r["id"]])
    assert result == []


def test_memory_warnings_detects_contradicts_link():
    a = lm.add_memory_record("project_memory", "Warn A", "content A")
    b = lm.add_memory_record("project_memory", "Warn B", "content B")
    lm.add_link(a["id"], b["id"], relation_type="contradicts", weight=0.8)

    from local_memory_mcp.storage import get_active_warnings
    warnings = get_active_warnings([a["id"], b["id"]])
    assert len(warnings) == 1
    w = warnings[0]
    assert w["relation_type"] == "contradicts"
    assert w["severity"] == "high"  # weight 0.8 >= 0.7
    assert w["source_id"] == a["id"]
    assert w["target_id"] == b["id"]


def test_memory_warnings_detects_supersedes_link():
    old = lm.add_memory_record("project_memory", "Warn old", "old content")
    new = lm.add_memory_record("project_memory", "Warn new", "new content")
    lm.add_link(new["id"], old["id"], relation_type="supersedes", weight=0.5)

    from local_memory_mcp.storage import get_active_warnings
    warnings = get_active_warnings([old["id"], new["id"]])
    assert len(warnings) == 1
    assert warnings[0]["relation_type"] == "supersedes"
    assert warnings[0]["severity"] == "medium"  # weight 0.5 < 0.7


def test_memory_warnings_respects_min_weight():
    a = lm.add_memory_record("project_memory", "Warn low weight A", "content")
    b = lm.add_memory_record("project_memory", "Warn low weight B", "content")
    lm.add_link(a["id"], b["id"], relation_type="contradicts", weight=0.2)

    from local_memory_mcp.storage import get_active_warnings
    # Default min_weight=0.4 should exclude weight=0.2
    warnings = get_active_warnings([a["id"], b["id"]], min_weight=0.4)
    assert warnings == []
    # Lower threshold should include it
    warnings_low = get_active_warnings([a["id"], b["id"]], min_weight=0.1)
    assert len(warnings_low) == 1


# ---------------------------------------------------------------------------
# memory_update MCP tool
# ---------------------------------------------------------------------------

def test_memory_update_content():
    r = lm.add_memory_record("project_memory", "Update content", "original")
    updated = lm.update_memory_content(r["id"], new_content="revised content")
    assert updated["content"] == "revised content"
    assert updated["title"] == "Update content"  # unchanged


def test_memory_update_title():
    r = lm.add_memory_record("project_memory", "Update title old", "content")
    updated = lm.update_memory_content(r["id"], new_title="Update title new")
    assert updated["title"] == "Update title new"


def test_memory_update_importance_and_confidence():
    r = lm.add_memory_record("project_memory", "Update importance", "content")
    updated = lm.update_memory_content(r["id"], new_importance=0.9, new_confidence=0.8)
    assert updated["importance"] == pytest.approx(0.9)
    assert updated["confidence"] == pytest.approx(0.8)


def test_memory_update_status():
    r = lm.add_memory_record("project_memory", "Update status", "content")
    updated = lm.update_memory_content(r["id"], new_status="stale")
    assert updated["status"] == "stale"


def test_memory_update_missing_id_raises():
    with pytest.raises(ValueError, match="Memory not found"):
        lm.update_memory_content("nonexistent-id", new_content="x")


def test_memory_update_no_fields_is_noop():
    r = lm.add_memory_record("project_memory", "Update noop", "original content")
    updated = lm.update_memory_content(r["id"])
    assert updated["content"] == "original content"
    assert updated["title"] == "Update noop"
