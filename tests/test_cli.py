import json
from dataclasses import dataclass, field
import sys
import types

import memorycore as lm


def read_json(capsys):
    return json.loads(capsys.readouterr().out)


def test_main_init_add_search_context_curator_and_html(tmp_path, capsys):
    assert lm.main(["init"]) == 0
    init_out = capsys.readouterr().out.strip()
    assert init_out.endswith("test_memory.sqlite3")

    assert lm.main(["add", "project_memory", "CLI Title", "CLI searchable content", "--tags", "cli"]) == 0
    added = read_json(capsys)
    assert added["title"] == "CLI Title"

    assert lm.main(["search", "searchable", "--limit", "5"]) == 0
    found = read_json(capsys)
    assert [r["title"] for r in found] == ["CLI Title"]

    assert lm.main(["context", "searchable", "--agent", "pytest", "--budget", "200"]) == 0
    context_out = capsys.readouterr().out
    assert "# memory_context for pytest" in context_out
    assert "CLI Title" in context_out

    assert lm.main(["curator", "--summary-only"]) == 0
    summary = read_json(capsys)
    assert "duplicates" in summary

    out = tmp_path / "cli-dashboard.html"
    assert lm.main(["html", str(out)]) == 0
    html_out = capsys.readouterr().out.strip()
    assert html_out == str(out)
    assert out.exists()


def test_semantic_cli_uses_qdrant_vector_store(monkeypatch, capsys):
    calls = []

    @dataclass
    class FakeHit:
        id: str = "vec-1"
        score: float = 0.87654
        text: str = "semantic memory"
        payload: dict = field(default_factory=lambda: {"status": "active"})

    class FakeVectorStore:
        def status(self):
            return {"available": True, "collection": "agent_memory", "count": 7}

        def search(self, text, top_k=10, filters=None, score_threshold=0.0):
            calls.append({
                "text": text,
                "top_k": top_k,
                "filters": filters,
                "score_threshold": score_threshold,
            })
            return [FakeHit()]

    fake_vs_mod = types.ModuleType("memorycore.vector_store")
    fake_vs_mod.get_vector_store = lambda cfg=None: FakeVectorStore()
    monkeypatch.setitem(sys.modules, "memorycore.vector_store", fake_vs_mod)

    assert lm.main(["semantic-status"]) == 0
    status = read_json(capsys)
    assert status["available"] is True
    assert status["count"] == 7

    assert lm.main(["semantic-search", "semantic query", "--limit", "3", "--score-threshold", "0.42"]) == 0
    results = read_json(capsys)
    assert results == [
        {
            "id": "vec-1",
            "score": 0.8765,
            "text": "semantic memory",
            "payload": {"status": "active"},
        }
    ]
    assert calls == [
        {
            "text": "semantic query",
            "top_k": 3,
            "filters": {"status": "active"},
            "score_threshold": 0.42,
        }
    ]


def test_semantic_index_rebuilds_vectors_only_with_force(monkeypatch, capsys):
    import memorycore.server as srv

    calls = []

    def fake_rebuild(dry_run=True, limit=5000):
        calls.append({"dry_run": dry_run, "limit": limit})
        return {"dry_run": dry_run, "planned": 2, "rebuilt": 0 if dry_run else 2}

    monkeypatch.setattr(srv, "rebuild_memory_vectors", fake_rebuild)

    assert lm.main(["semantic-index", "--limit", "2"]) == 0
    dry_run = read_json(capsys)
    assert dry_run == {"dry_run": True, "planned": 2, "rebuilt": 0}

    assert lm.main(["semantic-index", "--limit", "2", "--force"]) == 0
    applied = read_json(capsys)
    assert applied == {"dry_run": False, "planned": 2, "rebuilt": 2}
    assert calls == [
        {"dry_run": True, "limit": 2},
        {"dry_run": False, "limit": 2},
    ]
