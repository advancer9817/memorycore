"""Tests for subject-context governance (迭代 196 实施).

Covers:
- resolve_project: path/name/alias resolution, prefix match, disabled fallback
- extraction: Active Context prompt injection (and absence without project)
- extraction parser: subject/entities fields
- dedup ingest: project_path + scope + project:* tag + title-prefix fallback
- entities: guaranteed project entity row for resolvable project_path
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from memorycore.dedup import ingest
from memorycore.extraction import ExtractedFact, _build_user_prompt, _parse_response, extract_facts
from memorycore.subject_context import active_context_block, resolve_project

SUBJECT_CFG = {
    "subject_context": {
        "enabled": True,
        "default_scope": "global",
        "projects": [
            {
                "name": "mcore",
                "paths": ["/home/advancer/project/memorycore"],
                "aliases": ["memorycore", "MemoryCore"],
                "scope": "project",
            }
        ],
    },
    "extraction_strategy": {"default_scope": "global"},
}


# ---------------------------------------------------------------------------
# resolve_project
# ---------------------------------------------------------------------------

class TestResolveProject:
    def test_exact_path(self):
        p = resolve_project(project_path="/home/advancer/project/memorycore", cfg=SUBJECT_CFG)
        assert p and p["name"] == "mcore" and p["scope"] == "project"

    def test_subdirectory_prefix(self):
        p = resolve_project(project_path="/home/advancer/project/memorycore/ui", cfg=SUBJECT_CFG)
        assert p and p["name"] == "mcore"

    def test_alias_name(self):
        p = resolve_project(project_name="MemoryCore", cfg=SUBJECT_CFG)
        assert p and p["name"] == "mcore"

    def test_no_match_returns_none(self):
        assert resolve_project(project_path="/home/advancer/project/other", cfg=SUBJECT_CFG) is None
        assert resolve_project(project_name="unknown", cfg=SUBJECT_CFG) is None

    def test_disabled_returns_none(self):
        cfg = {"subject_context": {"enabled": False, "projects": SUBJECT_CFG["subject_context"]["projects"]}}
        assert resolve_project(project_path="/home/advancer/project/memorycore", cfg=cfg) is None

    def test_empty_cfg_returns_none(self):
        assert resolve_project(project_path="/home/advancer/project/memorycore", cfg={}) is None

    def test_auto_discover_git_repo(self, tmp_path, monkeypatch):
        # 用一个临时 git 仓库目录模拟 ~/project/* auto-discover
        import subprocess
        from memorycore.subject_context import discover_projects
        repo = tmp_path / "my-proj"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        monkeypatch.setenv("MCORE_PROJECTS_ROOT", str(tmp_path))
        cfg = {"subject_context": {"enabled": True, "auto_discover": True, "projects": []}}
        p = resolve_project(project_path=str(repo), cfg=cfg)
        assert p and p["name"] == "my-proj" and p["scope"] == "project"
        # 名称匹配也可
        p2 = resolve_project(project_name="my-proj", cfg=cfg)
        assert p2 and p2["name"] == "my-proj"

    def test_auto_discover_off_by_default(self, tmp_path, monkeypatch):
        import subprocess
        repo = tmp_path / "my-proj"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        monkeypatch.setenv("MCORE_PROJECTS_ROOT", str(tmp_path))
        cfg = {"subject_context": {"enabled": True, "auto_discover": False, "projects": []}}
        assert resolve_project(project_path=str(repo), cfg=cfg) is None

    def test_explicit_project_wins_over_discovery(self, tmp_path, monkeypatch):
        import subprocess
        repo = tmp_path / "mcore"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        monkeypatch.setenv("MCORE_PROJECTS_ROOT", str(tmp_path))
        cfg = {
            "subject_context": {
                "enabled": True, "auto_discover": True,
                "projects": [{"name": "mcore", "paths": [str(repo)], "aliases": ["memorycore"], "scope": "project"}],
            }
        }
        p = resolve_project(project_path=str(repo), cfg=cfg)
        assert p["name"] == "mcore" and p["aliases"] == ["memorycore"]  # 显式项优先

    def test_discover_projects_multi_roots(self, tmp_path):
        import subprocess
        from memorycore.subject_context import discover_projects

        root1 = tmp_path / "root1"
        root2 = tmp_path / "root2"
        root1.mkdir()
        root2.mkdir()

        repo1 = root1 / "proj-a"
        repo1.mkdir()
        subprocess.run(["git", "init", "-q", str(repo1)], check=True)

        repo2 = root2 / "proj-b"
        repo2.mkdir()
        subprocess.run(["git", "init", "-q", str(repo2)], check=True)

        sc = {
            "enabled": True,
            "auto_discover": True,
            "discovery_roots": [str(root1), str(root2)],
        }
        discovered = discover_projects(sc)
        assert "proj-a" in discovered
        assert "proj-b" in discovered

    def test_active_context_block(self):
        block = active_context_block("mcore", "/home/advancer/project/memorycore", "project")
        assert "project_name: mcore" in block and "Active Context" in block
        assert active_context_block("", "/x", "global") == ""


# ---------------------------------------------------------------------------
# extraction: prompt injection + parser
# ---------------------------------------------------------------------------

class TestExtractionSubject:
    def test_user_prompt_contains_active_context(self):
        prompt = _build_user_prompt(
            [{"role": "user", "content": "hi"}], [],
            active_context=active_context_block("mcore", "/p", "project"),
        )
        assert "Active Context" in prompt and "project_name: mcore" in prompt

    def test_user_prompt_without_context_unchanged(self):
        prompt = _build_user_prompt([{"role": "user", "content": "hi"}], [])
        assert "Active Context" not in prompt

    def test_extract_facts_passes_subject_when_resolved(self):
        captured = {}

        def fake_call(system_prompt, user_prompt, config):
            captured["system"] = system_prompt
            captured["user"] = user_prompt
            return json.dumps({"memory": []})

        with patch("memorycore.extraction._call_llm", side_effect=fake_call):
            extract_facts(
                [{"role": "user", "content": "hello world"}],
                config=__import__("memorycore.extraction", fromlist=["ExtractionConfig"]).ExtractionConfig(api_key="k"),
                project_path="/home/advancer/project/memorycore",
                project_name="mcore",
                scope="project",
            )
        assert "Active Context" in captured["user"]
        assert "project_name: mcore" in captured["user"]
        assert "Subject Context" in captured["system"]

    def test_extract_facts_no_injection_without_project(self):
        captured = {}

        def fake_call(system_prompt, user_prompt, config):
            captured["user"] = user_prompt
            return json.dumps({"memory": []})

        with patch("memorycore.extraction._call_llm", side_effect=fake_call):
            extract_facts(
                [{"role": "user", "content": "hello world"}],
                config=__import__("memorycore.extraction", fromlist=["ExtractionConfig"]).ExtractionConfig(api_key="k"),
            )
        assert "Active Context" not in captured["user"]

    def test_parse_response_reads_subject_entities(self):
        raw = json.dumps({"memory": [{
            "id": "0", "title": "mcore 迭代31", "content": "mcore 完成迭代31",
            "type": "project_memory", "importance": 0.8,
            "subject": "mcore", "entities": ["mcore", "qdrant"],
        }]})
        facts = _parse_response(raw)
        assert facts[0].subject == "mcore"
        assert facts[0].entities == ["mcore", "qdrant"]


# ---------------------------------------------------------------------------
# dedup ingest: metadata 落库
# ---------------------------------------------------------------------------

class TestIngestSubject:
    def _run(self, fact, project_path, add_memory_fn, expect_resolve=False):
        cfg = dict(SUBJECT_CFG)
        cfg["extraction_strategy"] = {"default_memory_type": "episodic_memory"}
        with patch("memorycore.dedup.extract_facts") as mock_extract:
            mock_extract.return_value = ([fact], 0.01)
            result = ingest(
                [{"role": "user", "content": fact.text}],
                project_path=project_path,
                cfg=cfg,
                _add_memory_fn=add_memory_fn,
                _update_memory_fn=lambda *a, **k: True,
            )
        assert result.added == 1
        mock_extract.assert_called_once()
        kwargs = mock_extract.call_args.kwargs
        if expect_resolve:
            assert kwargs["project_name"] == "mcore"
            assert kwargs["project_path"] == "/home/advancer/project/memorycore"
            assert kwargs["scope"] == "project"
        else:
            assert kwargs["project_name"] == ""
            assert kwargs["scope"] == "global"

    def test_add_writes_project_metadata(self):
        captured = {}

        def add_memory_fn(**kwargs):
            captured.update(kwargs)
            return {"id": kwargs.get("memory_id")}

        fact = ExtractedFact(text="迭代31 完成归档链路", title="迭代31 完成归档链路",
                             importance=0.8, memory_type="project_memory")
        self._run(fact, "/home/advancer/project/memorycore", add_memory_fn, expect_resolve=True)
        assert captured["project_path"] == "/home/advancer/project/memorycore"
        assert captured["scope"] == "project"
        assert "project:mcore" in captured["tags"]
        assert captured["metadata"].get("subject") == "mcore"
        # title prefix fallback: LLM did not include project name
        assert captured["title"].startswith("mcore ")
        assert len(captured["title"]) <= 80

    def test_title_already_has_prefix_not_duplicated(self):
        captured = {}

        def add_memory_fn(**kwargs):
            captured.update(kwargs)
            return {"id": kwargs.get("memory_id")}

        fact = ExtractedFact(text="mcore 完成矛盾裁决", title="mcore 完成矛盾裁决",
                             importance=0.8, memory_type="project_memory")
        self._run(fact, "/home/advancer/project/memorycore", add_memory_fn, expect_resolve=True)
        assert captured["title"].startswith("mcore ")
        assert not captured["title"].startswith("mcore mcore")

    def test_unresolvable_project_stays_global(self):
        captured = {}

        def add_memory_fn(**kwargs):
            captured.update(kwargs)
            return {"id": kwargs.get("memory_id")}

        fact = ExtractedFact(text="随意记录", title="随意记录", importance=0.6)
        self._run(fact, "/somewhere/else", add_memory_fn)
        assert captured["project_path"] == ""
        assert captured["scope"] == "global"
        assert not any(t.startswith("project:") for t in captured["tags"])
        assert "subject" not in captured["metadata"]

    def test_no_project_path_at_all(self):
        captured = {}

        def add_memory_fn(**kwargs):
            captured.update(kwargs)
            return {"id": kwargs.get("memory_id")}

        fact = ExtractedFact(text="随意记录", title="随意记录", importance=0.6)
        self._run(fact, "", add_memory_fn)
        assert captured["project_path"] == ""
        assert captured["scope"] == "global"


# ---------------------------------------------------------------------------
# entities: project entity fallback
# ---------------------------------------------------------------------------

class TestEntityFallback:
    def test_sync_injects_project_entity(self, isolated_memory_db, monkeypatch):
        from memorycore import models
        from memorycore.storage.crud import add_memory_record
        from memorycore.storage.entities import entity_search, resolve_project_entity, sync_memory_entities

        real_load = models.load_config

        def patched_load():
            cfg = dict(real_load())
            cfg.update(SUBJECT_CFG)
            return cfg

        monkeypatch.setattr(models, "load_config", patched_load)

        rec = add_memory_record(
            memory_type="project_memory",
            title="完全无关的标题",
            content="这条内容不包含任何项目名，用于验证兜底。",
            project_path="/home/advancer/project/memorycore",
            scope="project",
            metadata={"subject": "mcore"},
            status="active",
        )
        record = {"id": rec["id"], "title": "完全无关的标题",
                  "content": "这条内容不包含任何项目名，用于验证兜底。",
                  "status": "active", "tags": [],
                  "project_path": "/home/advancer/project/memorycore",
                  "metadata": {"subject": "mcore"}}
        entities = sync_memory_entities(record)
        norm = {e["normalized_entity"] for e in entities}
        assert "mcore" in norm

        hits = entity_search("mcore")
        assert any(h["memory_id"] == rec["id"] for h in hits)

    def test_resolve_project_entity(self):
        from memorycore.storage.entities import resolve_project_entity
        ent = resolve_project_entity(project_path="/home/advancer/project/memorycore", cfg=SUBJECT_CFG)
        assert ent and ent["normalized_entity"] == "mcore" and ent["entity_type"] == "concept"
        assert resolve_project_entity(project_path="/other", cfg=SUBJECT_CFG) is None

    def test_no_fallback_without_project(self, isolated_memory_db):
        from memorycore.storage.entities import sync_memory_entities
        record = {"id": "x1", "title": "t", "content": "c", "status": "active",
                  "tags": [], "project_path": "", "metadata": {}}
        with patch("memorycore.storage.entities.resolve_project_entity", return_value=None):
            entities = sync_memory_entities(record, conn=_FakeConn())
        assert all(e["normalized_entity"] != "mcore" for e in entities)


class _FakeConn:
    """Minimal conn double for sync_memory_entities delete/insert calls."""

    def execute(self, *_args, **_kwargs):
        return None


# ---------------------------------------------------------------------------
# Config Validation (Task 1)
# ---------------------------------------------------------------------------

class TestSubjectConfig:
    def test_validate_config_discovery_roots_valid(self):
        from memorycore.models import validate_config
        cfg = {
            "subject_context": {
                "enabled": True,
                "discovery_roots": ["~/project", "/home/advancer/公共的"],
                "projects": [],
            }
        }
        warnings = validate_config(cfg)
        assert not any("discovery_roots" in w for w in warnings)

    def test_validate_config_discovery_roots_invalid(self):
        from memorycore.models import validate_config
        cfg = {
            "subject_context": {
                "enabled": True,
                "discovery_roots": "not-a-list",
                "projects": [],
            }
        }
        warnings = validate_config(cfg)
        assert any("discovery_roots must be a list" in w for w in warnings)

