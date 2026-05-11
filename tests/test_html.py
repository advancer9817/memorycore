import local_memory_mcp as lm


def test_export_html_writes_dashboard_with_records_and_escaped_json(tmp_path):
    out = tmp_path / "dashboard.html"
    lm.add_memory_record("project_memory", "Safe Title", "Visible content", tags=["html"])
    lm.add_memory_record("project_memory", "<script>alert(1)</script>", "Escaped content")

    lm.export_html(out)

    text = out.read_text(encoding="utf-8")
    assert text.startswith("<!doctype html>")
    assert '<script id="memory-data" type="application/json">' in text
    assert "Safe Title" in text
    assert "Visible content" in text
    assert "<script>alert(1)</script>" not in text
    assert "\\u003cscript" in text
