"""Tests for batch-3 profile-driven retrieval aids (F1 rerank / F2 query expansion / F4 conflict filter).

Covers the pure-local helpers in memorycore/storage/profile.py plus their
wiring in context_pack.build_context_pack.
"""
import json

import pytest

from memorycore.models import DEFAULT_CONFIG, load_config
from memorycore.storage.profile import (
    _tokenize_value,
    profile_conflict_for_record,
    profile_feature_words,
    profile_overlap_ratio,
    profile_query_expansion,
)

_SAMPLE_SCHEMA = [
    {"name": "姓名", "description": "用户的姓名"},
    {"name": "技术栈", "description": "技术背景", "immutable": True},
    {"name": "工作领域", "description": "工作领域"},
    {"name": "沟通偏好", "description": "沟通偏好"},
]


@pytest.fixture()
def profile_cfg():
    base = dict(load_config())
    base["user_profile"] = {
        "enabled": True,
        "extract_limit": 100,
        "max_snapshot_chars": 800,
        "min_confidence": 0.6,
        "schema": _SAMPLE_SCHEMA,
    }
    return base


# ---------------------------------------------------------------------------
# F1 helpers
# ---------------------------------------------------------------------------


def test_tokenize_value_latin_and_cjk():
    tokens = _tokenize_value("Java 全栈 千帆平台 ai-api")
    # latin tokens
    assert "java" in tokens
    assert "ai-api" in tokens
    # cjk span kept whole when short + grams
    assert "千帆平台" in tokens
    # cjk 2-grams present
    assert any(t == "千帆" for t in tokens)
    assert any(t == "平台" for t in tokens)


def test_tokenize_value_empty_and_urls_skipped():
    assert _tokenize_value("") == []
    tokens = _tokenize_value("http://127.0.0.1:8318")
    assert "http" not in tokens
    assert "127.0.0.1" in tokens  # ip token still extracted


def test_profile_feature_words_only_signal_attrs(profile_cfg, monkeypatch):
    _patch_attrs(monkeypatch, [
        {"attribute": "技术栈", "value": "Java 千帆", "confidence": 0.9},
        {"attribute": "沟通偏好", "value": "kawaii 风格", "confidence": 0.9},
        {"attribute": "低置信", "value": "should-not-appear", "confidence": 0.1},
    ])
    words = profile_feature_words(cfg=profile_cfg)
    assert "java" in words
    assert "千帆" in words
    # non-signal attr (沟通偏好) and low-confidence value excluded
    assert "kawaii" not in words
    assert "should-not-appear" not in words


def test_profile_overlap_ratio_capped():
    words = ["java", "千帆", "平台", "全栈"]
    assert profile_overlap_ratio("", words) == 0.0
    assert profile_overlap_ratio("no match here", words) == 0.0
    assert profile_overlap_ratio("java 千帆 平台 全栈 一堆", words) == pytest.approx(1.0)
    # single match -> 1/3
    assert profile_overlap_ratio("java only", words) == pytest.approx(1 / 3)


# ---------------------------------------------------------------------------
# F2 helpers
# ---------------------------------------------------------------------------


def test_profile_query_expansion_attribute_name_in_task(profile_cfg, monkeypatch):
    _patch_attrs(monkeypatch, [
        {"attribute": "技术栈", "value": "Java 千帆平台", "confidence": 0.9},
        {"attribute": "工作领域", "value": "得帆 AI 网关", "confidence": 0.9},
    ])
    exps = profile_query_expansion("技术栈 相关方案", cfg=profile_cfg)
    assert "Java 千帆平台" in exps


def test_profile_query_expansion_value_token_overlap(profile_cfg, monkeypatch):
    _patch_attrs(monkeypatch, [
        {"attribute": "工作领域", "value": "千帆平台 技术支持", "confidence": 0.9},
    ])
    exps = profile_query_expansion("千帆 那边的事", cfg=profile_cfg)
    assert "千帆平台 技术支持" in exps


def test_profile_query_expansion_no_overlap_returns_empty(profile_cfg, monkeypatch):
    _patch_attrs(monkeypatch, [
        {"attribute": "技术栈", "value": "Java", "confidence": 0.9},
    ])
    assert profile_query_expansion("如何煮咖啡", cfg=profile_cfg) == []


def test_profile_query_expansion_max_terms(profile_cfg, monkeypatch):
    _patch_attrs(monkeypatch, [
        {"attribute": "技术栈", "value": "Java", "confidence": 0.9},
        {"attribute": "工作领域", "value": "千帆", "confidence": 0.9},
        {"attribute": "当前项目", "value": "mcore", "confidence": 0.9},
        {"attribute": "学习方向", "value": "AI 应用", "confidence": 0.9},
    ])
    exps = profile_query_expansion("Java 千帆 mcore AI 应用", cfg=profile_cfg, max_terms=3)
    assert len(exps) <= 3


def test_profile_query_expansion_max_terms_name_hit_boundary(profile_cfg, monkeypatch):
    """Attribute-name hits must also respect max_terms (regression: old code
    `continue`d past the cap for name hits, returning > max_terms)."""
    _patch_attrs(monkeypatch, [
        {"attribute": "技术栈", "value": "Java", "confidence": 0.9},
        {"attribute": "工作领域", "value": "千帆", "confidence": 0.9},
        {"attribute": "当前项目", "value": "mcore", "confidence": 0.9},
        {"attribute": "学习方向", "value": "AI 应用", "confidence": 0.9},
    ])
    # task contains 4 attribute names → only max_terms values may be returned
    exps = profile_query_expansion("技术栈 工作领域 当前项目 学习方向", cfg=profile_cfg, max_terms=2)
    assert len(exps) == 2


# ---------------------------------------------------------------------------
# F4 helpers
# ---------------------------------------------------------------------------


def test_profile_conflict_for_record_matching_value_no_conflict():
    record = {"type": "user_profile", "title": "技术栈", "content": "用户使用 Java 和千帆平台"}
    profile = [{"attribute": "技术栈", "value": "Java 千帆平台", "confidence": 0.95}]
    assert profile_conflict_for_record(record, profile) is None


def test_profile_conflict_for_record_contradicts():
    record = {"type": "user_profile", "title": "技术栈", "content": "用户改用 Python 做后端"}
    profile = [{"attribute": "技术栈", "value": "Java 千帆平台", "confidence": 0.95}]
    conflict = profile_conflict_for_record(record, profile)
    assert conflict is not None
    assert conflict["attribute"] == "技术栈"
    assert "Java" in conflict["profile_value"]


def test_profile_conflict_for_record_ignores_non_profile_type():
    record = {"type": "episodic_memory", "title": "技术栈", "content": "Python 后端"}
    profile = [{"attribute": "技术栈", "value": "Java", "confidence": 0.95}]
    assert profile_conflict_for_record(record, profile) is None


def test_profile_conflict_only_immutable_and_min_conf():
    record = {"type": "user_profile", "title": "工作领域", "content": "做运维"}
    profile = [
        {"attribute": "技术栈", "value": "Java", "confidence": 0.9, "immutable": True},
        {"attribute": "工作领域", "value": "千帆", "confidence": 0.5},
    ]
    # 工作领域 low confidence -> skipped
    assert profile_conflict_for_record(record, profile) is None
    # 技术栈 not mentioned in text -> None
    assert profile_conflict_for_record(
        {"type": "user_profile", "title": "工作领域", "content": "千帆 维护"}, profile
    ) is None


# ---------------------------------------------------------------------------
# context_pack wiring
# ---------------------------------------------------------------------------


def _patch_attrs(monkeypatch, rows):
    """Patch get_user_profile used inside profile helpers to return rows."""
    import memorycore.storage.profile as prof_mod

    def fake_get(user_id="default"):
        return [{**r, "source_ids_json": "[]", "source_ids": []} for r in rows]

    monkeypatch.setattr(prof_mod, "get_user_profile", fake_get)
    return fake_get


def _seed_memories(tmp_path, conn_ids=None):
    from memorycore.storage import db

    created = []
    with db.managed_conn() as conn:
        for mid, title, content, mtype in [
            ("prof-java-1", "技术栈偏好", "用户偏好 Java 全栈开发，熟悉千帆平台", "user_profile"),
            ("prof-python-1", "技术栈变化", "用户已改用 Python 做后端开发", "user_profile"),
            ("env-ws-1", "环境", "WSL Ubuntu 开发环境", "environment_fact"),
        ]:
            conn.execute(
                "INSERT OR REPLACE INTO memories (id, title, content, type, status, importance, "
                "scope, project_path, created_at, updated_at, feedback_score, effectiveness_score, "
                "injected_count, tags_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (mid, title, content, mtype, "active", 0.5, "global", "",
                 "2026-08-01T00:00:00+08:00", "2026-08-01T00:00:00+08:00",
                 0.5, 0.5, 0, "[]"),
            )
            created.append(mid)
    return created


def test_build_context_pack_profile_boost_and_expansion(tmp_path, profile_cfg, monkeypatch):
    """F1+F2 integration: profile signal words boost matching records and
    profile queries expand retrieval; F4 filters contradicting user_profile."""
    from memorycore.storage import context_pack
    _seed_memories(tmp_path)

    # swap config so profile-driven aids are on
    real_load = context_pack.load_config

    def fake_load():
        return profile_cfg

    monkeypatch.setattr(context_pack, "load_config", fake_load)

    # profile attrs: Java 千帆 -> boosts prof-java-1; prof-python-1 contradicts
    _patch_attrs(monkeypatch, [
        {"attribute": "技术栈", "value": "Java 千帆平台", "confidence": 0.95, "immutable": True},
    ])

    result = context_pack.build_context_pack(
        "技术栈 方案", agent="test", token_budget=2000,
    )
    used = result["used_ids"]
    # Java memory is boosted and injected
    assert "prof-java-1" in used
    # contradicting user_profile memory filtered out (F4) -> in warnings
    assert "prof-python-1" not in used
    conflict_warnings = [w for w in result["warnings"] if w.get("type") == "profile_conflict"]
    assert any(w["memory_id"] == "prof-python-1" for w in conflict_warnings)
    # trace shows expansion + conflict count
    assert result["trace"]["profile_boost_weight"] == pytest.approx(0.15)
    assert result["trace"]["profile_conflict_filtered"] >= 1