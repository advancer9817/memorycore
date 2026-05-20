"""Documentation consistency checks for MCP tool listings."""
from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
SERVER = ROOT / "local_memory_mcp" / "server.py"


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
