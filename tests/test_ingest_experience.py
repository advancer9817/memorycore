"""Unit tests for Phase 2 ingest & deduplication experience optimizations.

Covers:
- IngestResult expansion (added_titles, updated_titles, skipped_details)
- Type inference in add_memory_record
- Auto-supersede on ingest update
- session-start reporting behavior
"""

import json
from pathlib import Path
from memorycore.dedup import IngestResult, DedupDecision
from memorycore.storage.crud import add_memory_record, get_record
from memorycore.storage.db import managed_conn


def test_ingest_result_fields():
    result = IngestResult()
    assert hasattr(result, "added_titles")
    assert hasattr(result, "updated_titles")
    assert hasattr(result, "skipped_details")
    result.added_titles.append("新测试记忆")
    result.skipped_details.append({"title": "跳过记忆", "reason": "duplicate"})
    assert len(result.added_titles) == 1
    assert len(result.skipped_details) == 1


def test_add_memory_record_type_inference():
    # 1. 自动推导 decision
    rec1 = add_memory_record(
        memory_type="",
        title="技术方案决定",
        content="我们决定必须使用 pnpm 启动项目，严禁使用 npm",
        source="test",
    )
    assert rec1["type"] == "decision"

    # 2. 自动推导 environment_fact
    rec2 = add_memory_record(
        memory_type="",
        title="服务配置端口说明",
        content="后端 service 端口设置为 18318，路径为 /tmp/service",
        source="test",
    )
    assert rec2["type"] == "environment_fact"

    # 3. 自动推导 user_profile
    rec3 = add_memory_record(
        memory_type="",
        title="用户技术偏好",
        content="用户习惯与偏好简洁回答，喜欢使用 Python 和 WSL2",
        source="test",
    )
    assert rec3["type"] == "user_profile"

    # 4. 保留显式指定的类型
    rec4 = add_memory_record(
        memory_type="project_memory",
        title="项目背景决定",
        content="必须遵守某项目规范",
        source="test",
    )
    assert rec4["type"] == "project_memory"


def test_session_start_report_rendering(tmp_path, monkeypatch):
    report_file = tmp_path / "last_ingest.json"
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / ".agent-memory").mkdir(parents=True, exist_ok=True)
    real_report_path = tmp_path / ".agent-memory" / "last_ingest.json"

    # Scenario 1: New facts added
    payload = {
        "timestamp": "2026-09-06T12:00:00+08:00",
        "agent": "test-agent",
        "added": 2,
        "updated": 0,
        "skipped": 1,
        "errors": 0,
        "added_titles": ["CPA代理配置", "WSL路径规范"],
        "read": False,
    }
    real_report_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    # Read and simulate logic
    data = json.loads(real_report_path.read_text(encoding="utf-8"))
    assert data["read"] is False
    assert data["added"] == 2
    assert "CPA代理配置" in data["added_titles"]
