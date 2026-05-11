import json

import local_memory_mcp as lm


def read_json(capsys):
    return json.loads(capsys.readouterr().out)


def test_main_init_add_search_context_curator_semantic_status_and_html(tmp_path, capsys):
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

    assert lm.main(["semantic-status"]) == 0
    semantic = read_json(capsys)
    assert semantic["total_records"] == 1

    out = tmp_path / "cli-dashboard.html"
    assert lm.main(["html", str(out)]) == 0
    html_out = capsys.readouterr().out.strip()
    assert html_out == str(out)
    assert out.exists()
