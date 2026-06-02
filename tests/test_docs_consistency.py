"""Documentation consistency checks for MCP tool listings."""
from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
SERVER = ROOT / "memorycore" / "server.py"
TOOLS_DOC = ROOT / "docs" / "tools.md"


def _actual_mcp_tools() -> set[str]:
    module = ast.parse(SERVER.read_text(encoding="utf-8"))
    tools: set[str] = set()
    for node in module.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            func = decorator.func if isinstance(decorator, ast.Call) else decorator
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "tool"
                and isinstance(func.value, ast.Name)
                and func.value.id == "mcp"
            ):
                tools.add(node.name)
    return tools


def _readme_tool_table_names() -> set[str]:
    text = README.read_text(encoding="utf-8")
    match = re.search(r"## MCP 工具列表\n(?P<section>.*?)(?:\n## |\Z)", text, re.S)
    assert match, "README must contain a '## MCP 工具列表' section"
    return set(re.findall(r"\|\s*`([^`]+)`\s*\|", match.group("section")))


def test_readme_mcp_tool_table_matches_registered_tools():
    actual = _actual_mcp_tools()
    documented = _readme_tool_table_names()

    assert documented == actual, (
        "README MCP tool table must match @mcp.tool registrations. "
        f"Missing from README: {sorted(actual - documented)}; "
        f"Documented but not registered: {sorted(documented - actual)}"
    )


def test_readme_current_status_uses_actual_tool_count():
    text = README.read_text(encoding="utf-8")
    actual_count = len(_actual_mcp_tools())
    assert f"{actual_count} 个工具" in text
    assert "16 个工具" not in text


def test_tools_reference_is_generated_and_current():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate_tools_doc.py"), "--check"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr

    text = TOOLS_DOC.read_text(encoding="utf-8")
    actual = _actual_mcp_tools()
    documented = set(re.findall(r"^### `([^`]+)`", text, re.M))
    assert documented == actual
    assert f"All {len(actual)} tools" in text
