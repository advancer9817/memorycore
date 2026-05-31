from __future__ import annotations

import local_memory_mcp as lm


def test_context_pack_keeps_relevant_chinese_prompt_memory(monkeypatch):
    monkeypatch.setattr(
        "local_memory_mcp.storage.search._vector_search_ids",
        lambda task, top_k=20, score_threshold=0.35: [],
    )
    related = lm.add_memory_record(
        "project_memory",
        "记忆检索相关性优化",
        "输入提示词后 memory_context 应召回相关记忆，并过滤弱相关 fallback。",
        importance=0.5,
        memory_id="rel-chinese-prompt-relevance",
    )
    unrelated = lm.add_memory_record(
        "project_memory",
        "Docker deployment note",
        "Qdrant and Ollama are installed by the deployment script.",
        importance=1.0,
        memory_id="rel-unrelated-deploy-high-priority",
    )

    pack = lm.build_context_pack("输入提示词后 检索到的记忆相关性不强这个问题也列入进去", agent="pytest")

    assert related["id"] in pack["used_ids"]
    assert unrelated["id"] not in pack["used_ids"]


def test_context_pack_filters_weak_chinese_keyword_overlap(monkeypatch):
    monkeypatch.setattr(
        "local_memory_mcp.storage.search._vector_search_ids",
        lambda task, top_k=20, score_threshold=0.35: [],
    )
    related = lm.add_memory_record(
        "project_memory",
        "prompt 后记忆检索相关性门禁",
        "输入提示词后，memory_context 检索到的记忆相关性不强，需要持续评测和过滤弱相关结果。",
        importance=0.5,
        memory_id="rel-strong-chinese-keyword",
    )
    weak = lm.add_memory_record(
        "project_memory",
        "Claude Opus 4 官方规格与发布信息",
        "模型对比资料包含提示、问题、回答体验等泛化描述。",
        importance=1.0,
        memory_id="rel-weak-chinese-keyword-overlap",
    )

    pack = lm.build_context_pack("输入提示词后 检索到的记忆相关性不强这个问题也列入进去", agent="pytest")

    assert related["id"] in pack["used_ids"]
    assert weak["id"] not in pack["used_ids"]


def test_context_pack_does_not_inject_unrelated_fallback_memories():
    lm.add_memory_record(
        "project_memory",
        "High importance unrelated deployment note",
        "Docker and Qdrant are installed on this workstation.",
        importance=1.0,
        memory_id="rel-unrelated-deploy",
    )

    pack = lm.build_context_pack(
        "zzzz_unmatched_prompt_about_totally_different_subject_9911",
        agent="pytest",
    )

    assert pack["trace"]["fallback_used"] is True
    assert pack["trace"]["fallback_candidates"] == 1
    assert pack["used_ids"] == []
    assert pack["records"] == []
    assert "High importance unrelated deployment note" not in pack["context"]


def test_context_pack_filters_low_relevance_vector_only_hits(monkeypatch):
    record = lm.add_memory_record(
        "project_memory",
        "Generic local workflow note",
        "General local workflow setup and routine project maintenance.",
        importance=1.0,
        memory_id="rel-generic-vector-only",
    )

    monkeypatch.setattr(
        "local_memory_mcp.storage.search._vector_search_ids",
        lambda task, top_k=20, score_threshold=0.35: [(record["id"], 0.36)],
    )

    pack = lm.build_context_pack("deep qdrant semantic relevance calibration", agent="pytest")

    assert record["id"] not in pack["used_ids"]
    assert pack["records"] == []


def test_context_pack_filters_medium_score_vector_only_without_lexical_match(monkeypatch):
    record = lm.add_memory_record(
        "user_profile",
        "Generic routing preference",
        "General local workflow setup and routine project maintenance.",
        importance=1.0,
        memory_id="rel-medium-vector-only",
    )

    monkeypatch.setattr(
        "local_memory_mcp.storage.search._vector_search_ids",
        lambda task, top_k=20, score_threshold=0.35: [(record["id"], 0.66)],
    )

    pack = lm.build_context_pack("输入提示词后 检索到的记忆相关性不强", agent="pytest")

    assert record["id"] not in pack["used_ids"]
    assert pack["records"] == []


def test_context_pack_vector_only_hits_respect_scope_and_project_path(monkeypatch):
    allowed = lm.add_memory_record(
        "project_memory",
        "Allowed semantic candidate",
        "Reusable note stored only through nearest neighbor recall.",
        scope="team-a",
        project_path="/work/a",
        importance=1.0,
        memory_id="rel-vector-allowed-scope-project",
    )
    global_allowed = lm.add_memory_record(
        "project_memory",
        "Global semantic candidate",
        "Reusable note stored only through nearest neighbor recall.",
        scope="global",
        project_path="",
        importance=1.0,
        memory_id="rel-vector-global-scope-project",
    )
    wrong_scope = lm.add_memory_record(
        "project_memory",
        "Wrong scope semantic candidate",
        "Reusable note stored only through nearest neighbor recall.",
        scope="team-b",
        project_path="/work/a",
        importance=1.0,
        memory_id="rel-vector-wrong-scope",
    )
    wrong_project = lm.add_memory_record(
        "project_memory",
        "Wrong project semantic candidate",
        "Reusable note stored only through nearest neighbor recall.",
        scope="team-a",
        project_path="/work/b",
        importance=1.0,
        memory_id="rel-vector-wrong-project",
    )

    monkeypatch.setattr(
        "local_memory_mcp.storage.search._vector_search_ids",
        lambda task, top_k=20, score_threshold=0.35: [
            (wrong_scope["id"], 0.95),
            (wrong_project["id"], 0.95),
            (allowed["id"], 0.95),
            (global_allowed["id"], 0.95),
        ],
    )

    pack = lm.build_context_pack(
        "opaque neural boundary check",
        agent="pytest",
        scope="team-a",
        project_path="/work/a",
    )

    assert allowed["id"] in pack["used_ids"]
    assert global_allowed["id"] in pack["used_ids"]
    assert wrong_scope["id"] not in pack["used_ids"]
    assert wrong_project["id"] not in pack["used_ids"]
