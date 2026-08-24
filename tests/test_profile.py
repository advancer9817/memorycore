"""Unit tests for the structured user profile layer (storage/profile.py)."""
import json

import pytest

from memorycore.models import load_config
from memorycore.storage.profile import (
    _parse_profile_response,
    _upsert_profile_attrs,
    extract_profile,
    get_user_profile,
    profile_snapshot,
    schema_from_config,
)

_SAMPLE_SCHEMA = [
    {"name": "姓名", "description": "用户的姓名"},
    {"name": "技术栈", "description": "技术背景", "immutable": True},
]


@pytest.fixture()
def cfg():
    """Config with user_profile enabled and a 2-attr schema."""
    base = load_config()
    base = dict(base)
    base["user_profile"] = {
        "enabled": True,
        "extract_limit": 100,
        "max_snapshot_chars": 800,
        "min_confidence": 0.6,
        "schema": _SAMPLE_SCHEMA,
    }
    return base


def test_schema_from_config_empty_default():
    """Missing user_profile.schema should not raise and returns []."""
    from memorycore.models import DEFAULT_CONFIG

    assert schema_from_config(DEFAULT_CONFIG) == []


def test_upsert_confidence_rule(cfg):
    """Higher-confidence new value overrides; lower-confidence keeps old."""
    updated = _upsert_profile_attrs(
        "t-user", [{"name": "姓名", "value": "张三", "confidence": 0.8}],
        cfg=cfg, source_ids=["m1"],
    )
    assert updated == 1

    updated = _upsert_profile_attrs(
        "t-user", [{"name": "姓名", "value": "张三丰", "confidence": 0.9}],
        cfg=cfg, source_ids=["m2"],
    )
    assert updated == 1
    rows = get_user_profile("t-user")
    match = [r for r in rows if r["attribute"] == "姓名"][0]
    assert match["value"] == "张三丰"
    assert match["confidence"] == 0.9
    assert "m2" in match["source_ids"]

    # Lower confidence should NOT override
    updated = _upsert_profile_attrs(
        "t-user", [{"name": "姓名", "value": "错误值", "confidence": 0.5}],
        cfg=cfg, source_ids=["m3"],
    )
    assert updated == 0
    match = [r for r in get_user_profile("t-user") if r["attribute"] == "姓名"][0]
    assert match["value"] == "张三丰"


def test_upsert_immutable(cfg):
    """Immutable attribute with existing value never gets overwritten."""
    _upsert_profile_attrs(
        "t-user2", [{"name": "技术栈", "value": "Java", "confidence": 0.9}],
        cfg=cfg, source_ids=["m1"],
    )
    updated = _upsert_profile_attrs(
        "t-user2", [{"name": "技术栈", "value": "Python", "confidence": 0.99}],
        cfg=cfg, source_ids=["m2"],
    )
    assert updated == 0
    match = [r for r in get_user_profile("t-user2") if r["attribute"] == "技术栈"][0]
    assert match["value"] == "Java"


def test_parse_response_whitelist():
    """Non-schema attributes filtered; confidence clamped; unknown fields ignored."""
    raw = json.dumps({"attributes": [
        {"name": "姓名", "value": "李四", "confidence": 0.8},
        {"name": "不存在的属性", "value": "x", "confidence": 1.0},
        {"name": "技术栈", "value": "Go", "confidence": 2.5},
        "junk",
    ]}, ensure_ascii=False)
    out = _parse_profile_response(raw, _SAMPLE_SCHEMA)
    names = {a["name"] for a in out}
    assert "姓名" in names
    assert "不存在的属性" not in names
    tech = [a for a in out if a["name"] == "技术栈"][0]
    assert tech["confidence"] == 1.0  # clamped from 2.5
    assert len(out) == 2


def test_snapshot_format_no_attrs(cfg):
    """Empty profile -> empty snapshot string (caller skips injection)."""
    assert profile_snapshot(user_id="t-empty", cfg=cfg) == ""


def test_snapshot_format_with_attrs(cfg):
    """Snapshot has expected header/line shape and max_chars cap."""
    _upsert_profile_attrs(
        "t-user3",
        [{"name": "姓名", "value": "王五", "confidence": 0.85}],
        cfg=cfg, source_ids=["m1"],
    )
    snap = profile_snapshot(user_id="t-user3", cfg=cfg, max_chars=200)
    assert snap.startswith("## user_profile_snapshot")
    assert "- 姓名: 王五" in snap
    assert len(snap) <= 200

    short = profile_snapshot(user_id="t-user3", cfg=cfg, max_chars=30)
    assert short.endswith("...") or len(short) <= 30


def test_extract_dry_run_no_write(monkeypatch, cfg):
    """Dry-run should not write; apply should write via _summarize_fn mock."""
    import memorycore.storage.db as db_mod
    import memorycore.storage.profile as profile_mod

    def fake_summarize(rows):
        return [{"name": "姓名", "value": "赵六", "confidence": 0.9}]

    def fake_query(sql, params):
        # Only the memories scan is faked; user_profile_attrs queries hit the real DB.
        if "FROM memories" in sql:
            return [{"id": "mem-1", "title": "姓名测试", "content": "用户叫赵六", "created_at": "2026-08-01T00:00:00"}]
        return db_mod._managed_query(sql, params)

    monkeypatch.setattr(profile_mod, "_managed_query", fake_query)

    dry = extract_profile(user_id="t-dry", apply=False, cfg=cfg, _summarize_fn=fake_summarize)
    assert dry["dry_run"] is True
    assert dry["scanned"] == 1
    assert dry["updated"] == 0
    assert get_user_profile("t-dry") == []  # nothing written

    applied = extract_profile(user_id="t-applied", apply=True, cfg=cfg, _summarize_fn=fake_summarize)
    assert applied["updated"] == 1
    rows = get_user_profile("t-applied")
    assert rows and rows[0]["attribute"] == "姓名" and rows[0]["value"] == "赵六"