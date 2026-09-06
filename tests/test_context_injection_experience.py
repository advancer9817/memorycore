"""Unit tests for Phase 1 context injection experience optimizations.

Covers:
- Top-level hard constraints in context pack
- Dynamic task-aware profile slicing
- Hit attribution tags on injected memory lines
- HTTP hook HUD comment prefix
"""

import pytest
from memorycore.storage.context_pack import build_context_pack
from memorycore.storage.profile import profile_snapshot, _upsert_profile_attrs
from memorycore.models import load_config


_FULL_SCHEMA = [
    {"name": "姓名", "description": "用户姓名"},
    {"name": "职业", "description": "用户职业"},
    {"name": "雇主", "description": "用户雇主"},
    {"name": "技术栈", "description": "技术背景"},
    {"name": "常用工具", "description": "工具链"},
    {"name": "当前项目", "description": "项目"},
    {"name": "模型偏好", "description": "模型"},
    {"name": "沟通偏好", "description": "偏好"},
    {"name": "输出偏好", "description": "输出"},
    {"name": "语言", "description": "语言"},
    {"name": "工作领域", "description": "领域"},
]


@pytest.fixture
def exp_cfg():
    base = dict(load_config())
    base["user_profile"] = {
        "enabled": True,
        "extract_limit": 100,
        "max_snapshot_chars": 800,
        "min_confidence": 0.6,
        "task_slices": {
            "enabled": True,
            "tech_attributes": ["技术栈", "常用工具", "当前项目", "模型偏好", "沟通偏好"],
            "doc_attributes": ["输出偏好", "沟通偏好", "语言", "工作领域"],
        },
        "schema": _FULL_SCHEMA,
    }
    base["context_pack"] = {
        **base.get("context_pack", {}),
        "hard_constraints": {
            "enabled": True,
            "rules": [
                "交付文件统一输出到 /mnt/c/Users/Advancer/Desktop/output/",
                "代码提交/推送前必须在仓库根目录追加 ITERATION.md 迭代记录",
            ],
        },
    }
    return base


@pytest.fixture
def sample_profile_data(exp_cfg):
    """Populate user profile with standard attributes."""
    attrs = [
        {"name": "姓名", "value": "测试用户", "confidence": 0.9},
        {"name": "职业", "value": "系统架构师", "confidence": 0.9},
        {"name": "雇主", "value": "科技公司", "confidence": 0.9},
        {"name": "技术栈", "value": "Python, React, WSL2", "confidence": 0.9},
        {"name": "常用工具", "value": "Claude Code, uv, pnpm", "confidence": 0.9},
        {"name": "当前项目", "value": "mcore治理", "confidence": 0.9},
        {"name": "模型偏好", "value": "deepseek-v4-flash", "confidence": 0.9},
        {"name": "沟通偏好", "value": "简明扼要，直指根因", "confidence": 0.9},
        {"name": "输出偏好", "value": "统一输出到 Desktop/output", "confidence": 0.9},
        {"name": "语言", "value": "中文", "confidence": 0.9},
        {"name": "工作领域", "value": "自动化运维", "confidence": 0.9},
    ]
    user_id = "test_exp_user_phase1"
    _upsert_profile_attrs(user_id, attrs, cfg=exp_cfg, source_ids=[])
    return user_id


def test_hard_constraints_injected_on_tech_task(monkeypatch, exp_cfg):
    monkeypatch.setattr("memorycore.storage.context_pack.load_config", lambda: exp_cfg)
    pack = build_context_pack(
        task="修复 python 脚本中的 KeyError 异常并部署",
        agent="test-agent",
        token_budget=2000,
    )
    context = pack["context"]
    assert "## 强制护栏" in context
    assert "交付文件统一输出到 /mnt/c/Users/Advancer/Desktop/output/" in context
    assert "ITERATION.md" in context


def test_hard_constraints_omitted_on_greeting(monkeypatch, exp_cfg):
    monkeypatch.setattr("memorycore.storage.context_pack.load_config", lambda: exp_cfg)
    pack = build_context_pack(
        task="你好",
        agent="test-agent",
        token_budget=2000,
    )
    context = pack["context"]
    assert "## 强制护栏" not in context


def test_profile_slicing_tech_vs_doc_vs_greeting(sample_profile_data, exp_cfg):
    # 1. Tech task -> Only tech attributes
    tech_snap = profile_snapshot(user_id=sample_profile_data, cfg=exp_cfg, task="排查 bash 脚本中的路径错误")
    assert "技术栈" in tech_snap
    assert "常用工具" in tech_snap
    assert "姓名" not in tech_snap
    assert "雇主" not in tech_snap
    assert "职业" not in tech_snap

    # 2. Doc task -> Only doc attributes
    doc_snap = profile_snapshot(user_id=sample_profile_data, cfg=exp_cfg, task="编写一份季度技术总结报告")
    assert "输出偏好" in doc_snap
    assert "语言" in doc_snap
    assert "技术栈" not in doc_snap
    assert "雇主" not in doc_snap

    # 3. Greeting task -> Empty profile snapshot
    greeting_snap = profile_snapshot(user_id=sample_profile_data, cfg=exp_cfg, task="你好")
    assert greeting_snap == ""


def test_attribution_tag_format(monkeypatch, exp_cfg):
    monkeypatch.setattr("memorycore.storage.context_pack.load_config", lambda: exp_cfg)
    pack = build_context_pack(
        task="查看项目配置与架构设计",
        agent="test-agent",
        token_budget=2000,
    )
    context = pack["context"]
    lines = [l.strip() for l in context.splitlines() if l.strip().startswith("- [")]
    if lines:
        for line in lines:
            assert ("| 语义" in line or "| 词法" in line or "| 相关" in line), f"Attribution tag missing in: {line}"


def test_http_hook_hud_output(monkeypatch, exp_cfg):
    monkeypatch.setattr("memorycore.storage.context_pack.load_config", lambda: exp_cfg)
    from memorycore.frontend_v1 import _dispatch_v1_compat

    res = _dispatch_v1_compat(
        method="POST",
        parts=["hooks", "context"],
        query={},
        body={"prompt": "排查服务启动报错", "agent": "claude"},
    )
    assert "hookSpecificOutput" in res
    output = res["hookSpecificOutput"]["additionalContext"]
    assert "<!-- mcore: 上下文就绪" in output
    assert "## 强制护栏" in output
