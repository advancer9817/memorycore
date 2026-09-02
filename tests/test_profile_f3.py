"""Tests for F3 — profile auto-update loop (freshness / incremental / decay)."""
from __future__ import annotations

import pytest

from memorycore.models import local_now
from memorycore.storage.crud import add_memory_record
from memorycore.storage.profile import (
    decay_profile_attributes,
    extract_profile,
    profile_freshness_warning,
)

PROFILE_CFG = {
    "user_profile": {
        "enabled": True,
        "schema": [
            {"name": "姓名", "description": "用户姓名", "immutable": True},
            {"name": "沟通偏好", "description": "沟通风格"},
            {"name": "技术栈", "description": "技术背景", "immutable": True},
        ],
        "min_confidence": 0.4,
        "max_snapshot_chars": 800,
    }
}


def _insert_attr(user_id: str, attribute: str, value: str, confidence: float, immutable: int, updated_at: str) -> None:
    from memorycore.storage.db import managed_conn

    with managed_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO user_profile_attrs "
            "(user_id, attribute, value, confidence, immutable, source_ids_json, updated_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (user_id, attribute, value, confidence, immutable, "[]", updated_at),
        )


def _read_attr(attribute: str) -> dict:
    from memorycore.storage.db import read_conn

    with read_conn() as conn:
        row = conn.execute(
            "SELECT attribute, confidence, immutable, updated_at, decayed_at "
            "FROM user_profile_attrs WHERE user_id='default' AND attribute=?",
            (attribute,),
        ).fetchone()
    return dict(row) if row else {}


def _add_profile_memory(title: str, content: str) -> dict:
    return add_memory_record(
        memory_type="user_profile",
        title=title,
        content=content,
        tags=[],
        source="manual",
        source_agent="test",
        confidence=0.8,
        importance=0.6,
        atomize=False,
    )


class TestFreshness:
    def test_warns_when_memory_newer_than_attrs(self):
        _insert_attr("default", "技术栈", "Java", 0.9, 1, "2026-01-01T00:00:00+08:00")
        _add_profile_memory("技术栈", "现在用 Java/React/Spring Boot")
        warning = profile_freshness_warning(cfg=PROFILE_CFG, max_staleness_days=7)
        assert "画像可能过时" in warning

    def test_silent_when_attrs_current(self):
        # 动态生成"接近当前时钟"的时间戳（滞后 1 天，阈值 7 天内），
        # 避免硬编码日期随真实时间流逝变成永假的时间炸弹测试。
        from datetime import timedelta
        recent = (local_now() - timedelta(days=1)).isoformat(timespec="seconds")
        _insert_attr("default", "技术栈", "Java", 0.9, 1, recent)
        _add_profile_memory("技术栈", "现在用 Java")
        warning = profile_freshness_warning(cfg=PROFILE_CFG, max_staleness_days=7)
        assert warning == ""


class TestIncremental:
    def test_only_new_scans_unreferenced_memories(self):
        m1 = _add_profile_memory("偏好旧记忆", "喜欢简洁回复")
        m2 = _add_profile_memory("偏好新记忆", "喜欢图表")

        seen: list[str] = []

        def fake_summarize(rows):
            seen.extend(row["id"] for row in rows)
            return [{"name": "沟通偏好", "value": "图表", "confidence": 0.8}]

        # Simulate that m1 is already referenced by a stored attribute.
        _insert_attr("default", "沟通偏好", "图表", 0.8, 0, "2026-08-25T00:00:00+08:00")
        from memorycore.storage.db import managed_conn

        with managed_conn() as conn:
            conn.execute(
                "UPDATE user_profile_attrs SET source_ids_json=? WHERE user_id='default' AND attribute='沟通偏好'",
                (f'["{m1["id"]}"]',),
            )

        seen.clear()
        only = extract_profile(apply=False, only_new=True, cfg=PROFILE_CFG, _summarize_fn=fake_summarize)
        assert only["scanned"] == 1
        assert seen == [m2["id"]]

        seen.clear()
        full = extract_profile(apply=False, only_new=False, cfg=PROFILE_CFG, _summarize_fn=fake_summarize)
        assert full["scanned"] == 2


class TestDecay:
    def test_decays_non_immutable_only_and_is_idempotent(self):
        _insert_attr("default", "技术栈", "Java", 0.9, 1, "2026-04-01T00:00:00+08:00")
        _insert_attr("default", "沟通偏好", "简洁", 0.9, 0, "2026-04-01T00:00:00+08:00")

        result = decay_profile_attributes(cfg=PROFILE_CFG, min_decay_days=30)
        assert result["decayed"] == 1  # only the non-immutable one

        immutable = _read_attr("技术栈")
        mutable = _read_attr("沟通偏好")
        assert immutable["confidence"] == 0.9  # untouched
        # ~145 days elapsed → factor 0.95 ** ~4.8 ≈ 0.778
        assert 0.65 < float(mutable["confidence"]) < 0.9
        assert mutable["decayed_at"]  # watermark advanced

        # Immediately re-run → no double decay within the window.
        again = decay_profile_attributes(cfg=PROFILE_CFG, min_decay_days=30)
        assert again["decayed"] == 0
        assert _read_attr("沟通偏好")["confidence"] == mutable["confidence"]

    def test_decay_ignores_fresh_attributes(self):
        _insert_attr("default", "沟通偏好", "简洁", 0.9, 0, "2026-08-25T00:00:00+08:00")
        result = decay_profile_attributes(cfg=PROFILE_CFG, min_decay_days=30)
        assert result["decayed"] == 0
        assert _read_attr("沟通偏好")["confidence"] == 0.9

    def test_decay_honors_fresh_window(self):
        # 41 days old: one decay pass (elapsed >= 30d window), then idempotent.
        _insert_attr("default", "沟通偏好", "简洁", 0.9, 0, "2026-07-16T00:00:00+08:00")
        first = decay_profile_attributes(cfg=PROFILE_CFG, min_decay_days=30)
        assert first["decayed"] == 1
        second = decay_profile_attributes(cfg=PROFILE_CFG, min_decay_days=30)
        assert second["decayed"] == 0  # watermark advanced → idempotent