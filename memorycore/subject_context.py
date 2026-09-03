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


def discover_projects(sc: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """Auto-discover git repos under configured discovery_roots as subject projects.

    Lets any repo directory (mcore, ai-learning, qai-report, …) resolve
    without hand-writing a whitelist entry. Explicit ``projects`` entries from
    config always win over discovery when names collide.
    """
    if sc is None:
        sc = subject_config()
    if not sc or not sc.get("auto_discover", False):
        return {}
    from pathlib import Path

    roots = sc.get("discovery_roots") or []
    if not roots:
        env_root = os.environ.get("MCORE_PROJECTS_ROOT")
        roots = [env_root] if env_root else [str(Path.home() / "project")]

    discovered: dict[str, dict[str, Any]] = {}
    for r in roots:
        base = Path(os.path.expandvars(os.path.expanduser(str(r).strip()))).resolve()
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if not child.is_dir():
                continue
            if (child / ".git").exists():
                name = child.name
                discovered[name.lower()] = {
                    "name": name,
                    "aliases": [name.lower()],
                    "scope": "project",
                    "path": str(child),
                }
    return discovered


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
    # Auto-discovered repos (~/project/*) act as additional projects; explicit
    # config entries below override them by name.
    discovered = discover_projects(sc)

    path = (project_path or "").strip().rstrip("/")
    name = (project_name or "").strip().lower()

    def _entry(projects: list[dict[str, Any]]) -> dict[str, Any] | None:
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

    explicit = _entry(projects)
    if explicit:
        return explicit
    if discovered:
        # Discovered projects match by exact path or directory-name alias.
        for entry in discovered.values():
            p = str(entry["path"]).rstrip("/")
            if path and p and (path == p or path.startswith(p + "/")):
                return dict(entry, path=p)
            if name and name in {str(entry["name"]).lower(), *entry["aliases"]}:
                return dict(entry)
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

# Subject Context 规则（当前对话可能属于一个项目）

- 输出 JSON 中每条 fact 必须附 "subject"（该事实归属的规范项目名）与 "entities"
  （实体名数组，可选）。subject 是主体判定的权威字段。
- 若事实属于 Active Context 中的 project_name，则 title 必须以
  「<project_name> 」为前缀（如 "mcore 迭代31 …"），使事实脱离对话后仍能看出归属。
- 若事实属于其他项目（对话常跨项目引用），不要强加本对话 project_name 前缀，
  而应在 subject 中写该事实真正归属的项目名。
- 所有 fact 的 subject 字段都必须是具体项目名或空字符串，禁止泛化占位。
"""
