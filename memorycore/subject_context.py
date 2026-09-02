"""Subject context — project identity resolution for memories.

Gives every ingested memory a "subject" anchor: which project it belongs to.
Resolution is driven by the ``subject_context`` config section:

    subject_context:
      enabled: true
      default_scope: global
      projects:
        - name: mcore
          paths: ["/home/advancer/project/memorycore"]
          aliases: ["memorycore", "MemoryCore"]
          scope: project

Only exact/startswith path matches and name/alias matches resolve; anything
else falls back to ``default_scope`` with no subject — never guess.

Public API
----------
resolve_project(project_path="", project_name="", cfg=None) -> dict | None
active_context_block(project_name, project_path, scope) -> str
"""
from __future__ import annotations

import os
from typing import Any


def subject_config(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the effective subject_context config section, or {} when disabled."""
    if cfg is None:
        from memorycore.models import load_config
        cfg = load_config()
    sc = cfg.get("subject_context") or {}
    if not isinstance(sc, dict) or not sc.get("enabled", False):
        return {}
    return sc


def resolve_project(
    project_path: str = "",
    project_name: str = "",
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Resolve a project_path / project_name to the configured canonical project.

    Matching rules (first hit wins, order follows config):
      1. exact path match, or path prefix match (repo subdirectory)
      2. case-insensitive name or alias match

    Returns {"name", "aliases", "scope", "path"} or None when nothing matches
    or the feature is disabled.
    """
    sc = subject_config(cfg)
    if not sc:
        return None
    projects = sc.get("projects") or []
    if not isinstance(projects, list):
        return None

    path = (project_path or "").strip().rstrip("/")
    name = (project_name or "").strip().lower()

    for entry in projects:
        if not isinstance(entry, dict):
            continue
        proj_name = str(entry.get("name") or "").strip()
        if not proj_name:
            continue
        aliases = [str(a).strip().lower() for a in (entry.get("aliases") or []) if str(a).strip()]
        names = {proj_name.lower(), *aliases}
        if name and name in names:
            return {
                "name": proj_name,
                "aliases": aliases,
                "scope": str(entry.get("scope") or "project"),
                "path": (entry.get("paths") or [""])[0] if entry.get("paths") else "",
            }
        for p in entry.get("paths") or []:
            # Portable configs may use ~/ or $VAR — expand at resolve time.
            p = os.path.expandvars(os.path.expanduser(str(p).strip())).rstrip("/")
            if path and p and (path == p or path.startswith(p + "/")):
                return {
                    "name": proj_name,
                    "aliases": aliases,
                    "scope": str(entry.get("scope") or "project"),
                    "path": p,
                }
    return None


def active_context_block(project_name: str, project_path: str, scope: str) -> str:
    """Markdown block injected into the extraction prompt (only when name known)."""
    if not project_name:
        return ""
    lines = [
        "## Active Context（当前对话主体）",
        f"- project_name: {project_name}",
    ]
    if project_path:
        lines.append(f"- project_path: {project_path}")
    lines.append(f"- scope: {scope}")
    return "\n".join(lines)


SUBJECT_PROMPT_INSTRUCTION = """

# Subject Context 规则（当前对话属于一个已知项目）

- 每条 fact 的 title 必须以「<project_name> 」为前缀（如 "mcore 迭代31 …"），
  或在 content 中明确包含项目名，使事实脱离对话后仍能看出归属。
- 输出 JSON 中每条 fact 可附选字段："subject"（规范项目名，通常即 project_name）
  与 "entities"（该事实涉及的实体名数组，可选）。
- 与该项目无关的独立事实不要强行加前缀。
"""
