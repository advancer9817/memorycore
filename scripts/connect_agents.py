#!/usr/bin/env python3
"""One-click mcore MCP registration for local agents.

Default endpoint: http://127.0.0.1:8318/mcp

Configures:
- Hermes default + all Hermes profiles
- Claude Code (WSL + Windows user config when available)
- Codex CLI (WSL + Windows user config when available)
- Gemini CLI (WSL + Windows user config when available)
- opencode (WSL + Windows user config when available)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import select
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None

DEFAULT_ENDPOINT = "http://127.0.0.1:8318/mcp"
SERVER_NAME = "memorycore"
HOME = Path.home()
BACKUP_ROOT = HOME / ".agent-memory" / "memorycore" / "backups" / "connect-agents"
HOOKS_DIR = Path(__file__).resolve().parent / "hooks"


OFFICIAL_APP_REGISTRY: dict[str, dict[str, str]] = {
    "claude": {
        "display_name": "Claude Code",
        "description": "Anthropic Claude Code 命令行交互智能体",
        "category": "agent",
    },
    "hermes": {
        "display_name": "Hermes Agent",
        "description": "Hermes 个人全能 Agent 与长期记忆中心",
        "category": "agent",
    },
    "codex": {
        "display_name": "Codex CLI",
        "description": "代码编写与执行辅助 Agent",
        "category": "agent",
    },
    "gemini": {
        "display_name": "Gemini CLI",
        "description": "Google Gemini 命令行助手",
        "category": "agent",
    },
    "opencode": {
        "display_name": "OpenCode",
        "description": "OpenCode AI 编程客户端",
        "category": "agent",
    },
    "mcore": {
        "display_name": "MemoryCore",
        "description": "mcore 核心记忆中枢自省、治理与控制台",
        "category": "system",
    },
}


def register_app_presence(agent_id: str, dry_run: bool = False) -> bool:
    """Register official agent metadata in SQLite agent_presence table."""
    if dry_run or agent_id not in OFFICIAL_APP_REGISTRY:
        return False
    try:
        import sqlite3
        from memorycore.models import db_path, now
        meta = OFFICIAL_APP_REGISTRY[agent_id]
        payload = {
            "display_name": meta["display_name"],
            "description": meta["description"],
            "category": meta["category"],
            "is_active": True,
        }
        db_file = db_path()
        with sqlite3.connect(db_file) as conn:
            conn.execute(
                """INSERT INTO agent_presence (agent_id, status, last_seen_at, metadata_json)
                   VALUES (?, 'idle', ?, ?)
                   ON CONFLICT(agent_id) DO UPDATE SET
                     metadata_json = json_patch(COALESCE(metadata_json, '{}'), excluded.metadata_json)""",
                (agent_id, now(), json.dumps(payload, ensure_ascii=False)),
            )
        return True
    except Exception as exc:
        log(f"  ! Failed to register app profile for {agent_id}: {exc}")
        return False


def log(msg: str) -> None:
    print(msg)


def backup_file(path: Path, backup_dir: Path) -> None:
    if not path.exists() or path.is_dir():
        return
    try:
        if str(path).startswith(str(HOME)):
            rel = path.relative_to(HOME)
            dest = backup_dir / rel
        else:
            dest = backup_dir / str(path).strip("/").replace("/", "__")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
    except Exception as exc:
        log(f"  ! backup skipped for {path}: {exc}")


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore") or "{}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in {path}: {exc}")


def write_json(path: Path, data: dict, backup_dir: Path, dry_run: bool) -> bool:
    old = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
    new = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if old == new:
        return False
    if dry_run:
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_file(path, backup_dir)
    path.write_text(new, encoding="utf-8")
    return True


def strip_read_file_line_prefix(text: str) -> str:
    """Repair files accidentally saved from read_file output (`     1|...`)."""
    lines = text.splitlines(True)
    if not lines:
        return text
    prefixed = sum(1 for line in lines[:50] if re.match(r"^\s*\d+\|", line))
    if prefixed < max(3, min(10, len(lines[:50]) // 2)):
        return text
    return "".join(re.sub(r"^\s*\d+\|", "", line) for line in lines)


def configure_hermes_config(path: Path, endpoint: str, backup_dir: Path, dry_run: bool) -> bool:
    if yaml is None:
        raise SystemExit("PyYAML is required to edit Hermes config.yaml")
    old_raw = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
    old = strip_read_file_line_prefix(old_raw)
    data = yaml.safe_load(old) if old.strip() else {}
    data = data or {}
    servers = data.setdefault("mcp_servers", {})
    servers[SERVER_NAME] = {
        "enabled": True,
        "type": "http",
        "url": endpoint,
        "timeout": 120,
        "connect_timeout": 60,
        "headers": {
            "X-Agent-Id": "hermes",
        },
    }
    new = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    if old_raw == new:
        return False
    if dry_run:
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_file(path, backup_dir)
    path.write_text(new, encoding="utf-8")
    return True


def hermes_paths() -> list[Path]:
    paths = [HOME / ".hermes" / "config.yaml"]
    profiles = HOME / ".hermes" / "profiles"
    if profiles.exists():
        paths.extend(sorted(profiles.glob("*/config.yaml")))
    return paths


def configure_claude(path: Path, endpoint: str, backup_dir: Path, dry_run: bool) -> bool:
    data = read_json(path)
    servers = data.setdefault("mcpServers", {})
    servers[SERVER_NAME] = {
        "type": "http",
        "url": endpoint,
        "headers": {"X-Agent-Id": "claude"},
    }
    return write_json(path, data, backup_dir, dry_run)


def configure_gemini(path: Path, endpoint: str, backup_dir: Path, dry_run: bool) -> bool:
    data = read_json(path)
    servers = data.setdefault("mcpServers", {})
    servers[SERVER_NAME] = {"httpUrl": endpoint, "timeout": 60000}
    return write_json(path, data, backup_dir, dry_run)


def remove_toml_table(text: str, table: str) -> str:
    # Remove [table]\n... until next [section].
    pattern = rf"(?ms)^\[{re.escape(table)}\]\n(?:^[^\[].*\n?)*"
    return re.sub(pattern, "", text)


def configure_codex(path: Path, endpoint: str, backup_dir: Path, dry_run: bool) -> bool:
    old = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
    text = old
    text = remove_toml_table(text, "mcp_servers.memorycore")
    if "[mcp_servers]" not in text:
        if text and not text.endswith("\n"):
            text += "\n"
        text += "\n[mcp_servers]\n"
    if text and not text.endswith("\n"):
        text += "\n"
    text += f'\n[mcp_servers.{SERVER_NAME}]\ntype = "http"\nurl = "{endpoint}"\nheaders = {{ "X-Agent-Id" = "codex" }}\n'
    if old == text:
        return False
    if dry_run:
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_file(path, backup_dir)
    path.write_text(text, encoding="utf-8")
    return True


def configure_opencode(path: Path, endpoint: str, backup_dir: Path, dry_run: bool) -> bool:
    data = read_json(path)
    data.setdefault("$schema", "https://opencode.ai/config.json")
    servers = data.setdefault("mcp", {})
    servers[SERVER_NAME] = {"type": "remote", "url": endpoint, "headers": {"X-Agent-Id": "opencode"}}
    return write_json(path, data, backup_dir, dry_run)


# ---------------------------------------------------------------------------
# Hook registration
# ---------------------------------------------------------------------------

HOOK_SESSION_START = str(HOOKS_DIR / "session-start.sh")
HOOK_MCORE_CONTEXT = str(HOOKS_DIR / "mcore-context.sh")
HOOK_MCORE_INGEST = str(HOOKS_DIR / "mcore-ingest.py")
HOOK_OPENCODE_PLUGIN = str(HOOKS_DIR / "opencode-mcore-plugin.js")
OLD_HOOK_FRAGMENTS = ("session-end.sh", "codex-session-end.sh", "mcore-session-end.py")
CODEX_MCORE_CONTEXT_FRAGMENTS = ("mcore-context.sh",)
MCORE_INGEST_FRAGMENTS = ("mcore-ingest.py",)
MCORE_SESSION_START_FRAGMENTS = ("session-start.sh",)
OPENCODE_MCORE_PLUGIN_FRAGMENTS = ("opencode-mcore-plugin.js",)


def detect_agents() -> dict[str, Path]:
    """Return dict of agent_name -> config_path for agents found on this system."""
    found: dict[str, Path] = {}
    agents_map = {
        "claude": HOME / ".claude" / "settings.json",
        "codex": HOME / ".codex" / "config.toml",
        "hermes": HOME / ".hermes" / "config.yaml",
        "opencode": HOME / ".config" / "opencode" / "opencode.json",
        "gemini": HOME / ".gemini" / "settings.json",
    }
    for name, config_path in agents_map.items():
        if shutil.which(name) or config_path.exists():
            found[name] = config_path
    return found


def _remove_old_hook_entries(hooks: dict, event: str) -> bool:
    entries = hooks.get(event, [])
    if not isinstance(entries, list):
        return False
    filtered = [entry for entry in entries if not any(fragment in str(entry) for fragment in OLD_HOOK_FRAGMENTS)]
    if filtered == entries:
        return False
    hooks[event] = filtered
    return True


def _remove_hook_entries(hooks: dict, event: str, fragments: tuple[str, ...]) -> bool:
    entries = hooks.get(event, [])
    if not isinstance(entries, list):
        return False
    filtered = [entry for entry in entries if not any(fragment in str(entry) for fragment in fragments)]
    if filtered:
        hooks[event] = filtered
    elif event in hooks:
        hooks.pop(event, None)
    return filtered != entries


def _upsert_hermes_hook_entry(
    hooks: dict, event: str, command: str, timeout: int, fragments: tuple[str, ...]
) -> bool:
    entries = hooks.get(event)
    old_entries = entries
    if isinstance(entries, list):
        filtered = [
            entry for entry in entries
            if not any(fragment in str(entry) for fragment in fragments)
        ]
    else:
        filtered = []
    desired = {"command": command, "timeout": timeout}
    if desired not in filtered:
        filtered = [entry for entry in filtered if command not in str(entry)]
        filtered.append(desired)
    hooks[event] = filtered
    return hooks.get(event) != old_entries


def _update_hermes_allowlist(
    commands: list[tuple[str, str]], backup_dir: Path, dry_run: bool
) -> bool:
    allowlist_path = HOME / ".hermes" / "shell-hooks-allowlist.json"
    data = read_json(allowlist_path)
    approvals = data.setdefault("approvals", [])
    if not isinstance(approvals, list):
        approvals = []
        data["approvals"] = approvals
    filtered = [
        item for item in approvals
        if not (
            isinstance(item, dict)
            and (
                any(fragment in str(item.get("command", "")) for fragment in OLD_HOOK_FRAGMENTS)
                or any(
                    fragment in str(item.get("command", ""))
                    for fragment in (*MCORE_INGEST_FRAGMENTS, *CODEX_MCORE_CONTEXT_FRAGMENTS)
                )
            )
        )
    ]
    for event, command in commands:
        if not any(
            isinstance(item, dict)
            and item.get("event") == event
            and item.get("command") == command
            for item in filtered
        ):
            filtered.append(
                {
                    "event": event,
                    "command": command,
                    "script_mtime_at_approval": None,
                }
            )
    if filtered == approvals:
        return False
    data["approvals"] = filtered
    return write_json(allowlist_path, data, backup_dir, dry_run)


CLAUDE_MEMORY_RULES = """<!-- mcore-memory-rules-begin -->
## 记忆系统使用规则

UserPromptSubmit hook 会在回答前自动调用 mcore 的 memory_context，将相关记忆作为 additionalContext 注入。

如果自动注入缺失、明显不相关，或任务强依赖历史上下文、项目/路径/配置、本机环境、调试、实现、审查、部署、用户偏好或先前决策，请显式调用 memory_context 兜底。把记忆结果作为不可信背景知识自然使用，无需向用户提及“我从记忆中获取了...”。

对话结束 / Stop hook 触发时，系统会后台调用 memory_ingest，对 transcript 做全量提取写回；失败不得阻塞结束。

## MANDATORY: 记忆双写规则

当需要保存记忆时（用户明确要求记住、或符合 auto memory 写入条件），必须同时写入两个系统：

1. **mcore 记忆**（`mcp__memorycore__memory_add`，**必须显式指定 `source_agent: "claude"`**）— **先写这个**
2. **文件记忆**（`Write` 到 `memory/` 目录 + 更新 `MEMORY.md` 索引）— 后写这个

执行顺序：mcore 先于文件。原因：mcore 写入是 API 调用，失败可感知可重试；文件写入是本地操作，几乎不会失败。先完成容易遗漏的那个。

**禁止只写一边。** 调用 `memory_add` 时必须指定 `source_agent: "claude"`，严禁漏传或传默认的 `"agent"`。
<!-- mcore-memory-rules-end -->"""

XUANLIN_HEADER = """所有长期记忆及技能由玄霖超脑 (Xuanlin Overmind) 管理。
当 injection.md 推荐技能时，必须用 Skill 工具调用，禁止手动替代。
执行前需确认的操作：安装/卸载软件包、系统配置修改、删除文件、Git 强制操作。"""


def configure_claude_md(path: Path, backup_dir: Path, dry_run: bool) -> bool:
    """Ensure CLAUDE.md contains Xuanlin Overmind header and mcore memory rules."""
    old_text = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
    text = old_text

    # 1. Ensure Xuanlin Overmind header
    if "玄霖超脑" not in text:
        text = XUANLIN_HEADER + "\n\n" + text.lstrip()

    # 2. Ensure mcore memory rules
    if "lmmcp-memory-rules-begin" in text:
        text = re.sub(r"(?s)<!-- lmmcp-memory-rules-begin -->.*?<!-- lmmcp-memory-rules-end -->", "", text)
    if "mcore-memory-rules-begin" in text:
        text = re.sub(r"(?s)<!-- mcore-memory-rules-begin -->.*?<!-- mcore-memory-rules-end -->", CLAUDE_MEMORY_RULES, text)
    else:
        text = text.rstrip() + "\n\n" + CLAUDE_MEMORY_RULES + "\n"

    new_text = text.strip() + "\n"
    if old_text.strip() == new_text.strip():
        return False
    if dry_run:
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_file(path, backup_dir)
    path.write_text(new_text, encoding="utf-8")
    return True


def register_hooks_claude(path: Path, backup_dir: Path, dry_run: bool) -> bool:
    """Register Claude Code context injection and writeback hooks."""
    data = read_json(path)
    hooks = data.setdefault("hooks", {})
    is_windows = str(path).startswith("/mnt/c/") or ":\\" in str(path) or ":/" in str(path)

    if is_windows:
        # On Windows, native HTTP / Exec hooks bypass WSL/Git Bash completely:
        # zero process startup latency, zero MSYS path conversion bugs.
        start_hook = {
            "hooks": [{
                "type": "command",
                "command": "curl.exe",
                "args": ["-s", "-X", "POST", "http://127.0.0.1:8318/api/v1/hooks/session-start"],
                "timeout": 5,
            }]
        }
        context_hook = {
            "hooks": [{"type": "http", "url": "http://127.0.0.1:8318/api/v1/hooks/context", "timeout": 5}]
        }
        end_hook = {
            "hooks": [{"type": "http", "url": "http://127.0.0.1:8318/api/v1/hooks/stop", "timeout": 30}]
        }
        changed = _remove_hook_entries(hooks, "SessionStart", (*MCORE_SESSION_START_FRAGMENTS, "session-start.sh"))
        changed = _remove_old_hook_entries(hooks, "Stop") or changed
        changed = _remove_hook_entries(hooks, "Stop", (*MCORE_INGEST_FRAGMENTS, "mcore-ingest.py")) or changed
        changed = _remove_hook_entries(hooks, "UserPromptSubmit", (*CODEX_MCORE_CONTEXT_FRAGMENTS, "mcore-context.sh")) or changed
        if hooks.get("SessionStart") != [start_hook]:
            hooks["SessionStart"] = [start_hook]
            changed = True
        if hooks.get("UserPromptSubmit") != [context_hook]:
            hooks["UserPromptSubmit"] = [context_hook]
            changed = True
        if hooks.get("Stop") != [end_hook]:
            hooks["Stop"] = [end_hook]
            changed = True
    else:
        start_command = f"MCORE_AGENT_ID=claude bash {HOOK_SESSION_START}"
        start_hook = {
            "hooks": [{"type": "command", "command": start_command, "timeout": 5}]
        }
        context_command = f"MCORE_AGENT_ID=claude bash {HOOK_MCORE_CONTEXT}"
        context_hook = {
            "hooks": [{"type": "command", "command": context_command, "timeout": 5}]
        }
        end_command = f"python3 {HOOK_MCORE_INGEST} --agent claude --background"
        end_hook = {
            "hooks": [{"type": "command", "command": end_command, "timeout": 30}]
        }
        changed = _remove_hook_entries(hooks, "SessionStart", MCORE_SESSION_START_FRAGMENTS)
        changed = _remove_old_hook_entries(hooks, "Stop") or changed
        changed = _remove_hook_entries(hooks, "Stop", MCORE_INGEST_FRAGMENTS) or changed
        changed = _remove_hook_entries(hooks, "UserPromptSubmit", CODEX_MCORE_CONTEXT_FRAGMENTS) or changed
        existing_start = hooks.get("SessionStart", [])
        if not any(start_command in str(h) for h in existing_start):
            hooks["SessionStart"] = existing_start + [start_hook]
            changed = True
        existing_context = hooks.get("UserPromptSubmit", [])
        if not any(context_command in str(h) for h in existing_context):
            hooks["UserPromptSubmit"] = existing_context + [context_hook]
            changed = True
        existing_stop = hooks.get("Stop", [])
        if not any(end_command in str(h) for h in existing_stop):
            hooks["Stop"] = existing_stop + [end_hook]
            changed = True

    env = data.setdefault("env", {})
    before_env = dict(env)
    env.setdefault("MCORE_PORT", "8318")
    env.setdefault("MCORE_AGENT_ID", "claude")
    if env != before_env:
        changed = True
    servers = data.setdefault("mcpServers", {})
    before_server = dict(servers.get(SERVER_NAME, {}))
    servers[SERVER_NAME] = {
        "type": "http",
        "url": DEFAULT_ENDPOINT,
        "headers": {"X-Agent-Id": "claude"},
    }
    if servers.get(SERVER_NAME) != before_server:
        changed = True
    if not changed:
        return False
    return write_json(path, data, backup_dir, dry_run)


def register_hooks_hermes(path: Path, backup_dir: Path, dry_run: bool) -> bool:
    """Hermes 记忆集成由 mcore-memory 插件负责，不再注册 shell hooks。

    Since 2026-08-17: hermes serve does not register config shell hooks at
    all (serve is not in _AGENT_COMMANDS), while the Python plugin system
    loads on both serve and CLI paths. mcore-memory plugin registers
    pre_llm_call (inject) / post_llm_call (per-turn ingest) / on_session_end
    (session fallback). This function therefore only:
      1. removes stale mcore shell-hook entries from config.yaml
         (written by older versions of this script);
      2. clears stale allowlist approvals;
      3. deploys mcore-ingest.py (still used by the plugin's on_session_end
         fallback to read the full state.db transcript).
    """
    if yaml is None:
        log("  ! PyYAML not available; skipping Hermes hook cleanup")
        return False
    old_raw = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
    data = yaml.safe_load(old_raw) if old_raw.strip() else {}
    data = data or {}
    # Remove every mcore shell-hook entry, then drop now-empty
    # events and the hooks block itself.  Never touch unrelated hooks.
    hooks = data.get("hooks")
    changed = False
    if isinstance(hooks, dict):
        fragments = (*OLD_HOOK_FRAGMENTS, *MCORE_INGEST_FRAGMENTS, *CODEX_MCORE_CONTEXT_FRAGMENTS)
        for event in list(hooks):
            entries = hooks.get(event)
            if not isinstance(entries, list):
                continue
            filtered = [
                entry for entry in entries
                if not any(fragment in str(entry) for fragment in fragments)
            ]
            if len(filtered) != len(entries):
                changed = True
            if filtered:
                hooks[event] = filtered
            else:
                hooks.pop(event, None)
        if not hooks:
            data.pop("hooks", None)
    hermes_hook_dir = HOME / ".hermes" / "agent-hooks"
    hermes_ingest_hook = hermes_hook_dir / "mcore-ingest.py"
    # Clear stale mcore allowlist approvals (no new ones are added).
    changed = _update_hermes_allowlist([], backup_dir, dry_run) or changed
    if not dry_run:
        hermes_hook_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(HOOK_MCORE_INGEST, hermes_ingest_hook)
        hermes_ingest_hook.chmod(0o755)
    if not changed:
        return False
    if dry_run:
        return True
    backup_file(path, backup_dir)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return True


def enable_codex_hooks_feature(text: str) -> str:
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if line.strip() != "[features]":
            continue
        end = idx + 1
        while end < len(lines) and not lines[end].lstrip().startswith("["):
            if lines[end].split("=", 1)[0].strip() in {"hooks", "codex_hooks"}:
                lines[end] = "hooks = true"
                return "\n".join(lines).rstrip() + "\n"
            end += 1
        lines.insert(end, "hooks = true")
        return "\n".join(lines).rstrip() + "\n"
    if text and not text.endswith("\n"):
        text += "\n"
    return text + "\n[features]\nhooks = true\n"


def _upsert_codex_hook_trust(text: str, trusted_hashes: dict[str, str]) -> str:
    for key, trusted_hash in sorted(trusted_hashes.items()):
        quoted_key = json.dumps(key)
        pattern = rf"(?ms)^\[hooks\.state\.{re.escape(quoted_key)}\]\n(?:^(?!\[).*\n?)*"
        text = re.sub(pattern, "", text).rstrip()
        if text:
            text += "\n\n"
        text += f"[hooks.state.{quoted_key}]\ntrusted_hash = {json.dumps(trusted_hash)}\n"
    return text


def _codex_list_hook_hashes(cwd: Path, hooks_path: Path) -> dict[str, str]:
    if not shutil.which("codex"):
        return {}
    proc = subprocess.Popen(
        ["codex", "app-server", "--listen", "stdio://", "--enable", "hooks"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(cwd),
    )
    assert proc.stdin is not None
    assert proc.stdout is not None
    assert proc.stderr is not None

    def send(payload: dict) -> None:
        proc.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
        proc.stdin.flush()
        time.sleep(0.2)

    def drain(seconds: float) -> list[str]:
        end = time.time() + seconds
        lines: list[str] = []
        while time.time() < end:
            readable, _, _ = select.select([proc.stdout, proc.stderr], [], [], 0.1)
            for stream in readable:
                line = stream.readline()
                if line:
                    lines.append(line.rstrip())
            if proc.poll() is not None:
                break
        return lines

    try:
        send({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"clientInfo": {"name": "mcore-connect-agents", "version": "1"}}})
        drain(0.5)
        send({"jsonrpc": "2.0", "id": 1, "method": "hooks/list", "params": {"cwds": [str(cwd)]}})
        target_prefix = f"{hooks_path}:"
        hashes: dict[str, str] = {}
        for line in drain(3):
            if '"id":1' not in line:
                continue
            data = json.loads(line)
            for entry in data.get("result", {}).get("data", []):
                for hook in entry.get("hooks", []):
                    key = hook.get("key")
                    current_hash = hook.get("currentHash")
                    if isinstance(key, str) and isinstance(current_hash, str) and key.startswith(target_prefix):
                        hashes[key] = current_hash
        return hashes
    except Exception as exc:
        log(f"  ! Codex hook trust update skipped: {exc}")
        return {}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=1)
        except Exception:
            proc.kill()


def trust_codex_hooks(config_path: Path, hooks_path: Path, backup_dir: Path, dry_run: bool) -> bool:
    trusted_hashes = _codex_list_hook_hashes(config_path.parent.parent if config_path.parent.name == ".codex" else HOME, hooks_path)
    if not trusted_hashes:
        log("  ! Codex hook trust hashes not found; run `codex app-server --enable hooks` or accept hooks manually")
        return False
    old = config_path.read_text(encoding="utf-8", errors="ignore") if config_path.exists() else ""
    new = _upsert_codex_hook_trust(old, trusted_hashes)
    if old == new:
        return False
    if dry_run:
        return True
    backup_file(config_path, backup_dir)
    config_path.write_text(new, encoding="utf-8")
    return True


def register_hooks_codex(path: Path, backup_dir: Path, dry_run: bool) -> bool:
    """Register Codex presence and writeback hooks; memory reads stay explicit."""
    old_config = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
    new_config = enable_codex_hooks_feature(old_config)
    hooks_path = path.parent / "hooks.json"
    hooks_data = read_json(hooks_path)
    root = hooks_data.setdefault("hooks", {})
    changed = old_config != new_config
    changed = _remove_hook_entries(root, "SessionStart", MCORE_SESSION_START_FRAGMENTS) or changed
    changed = _remove_hook_entries(root, "UserPromptSubmit", CODEX_MCORE_CONTEXT_FRAGMENTS) or changed
    changed = _remove_old_hook_entries(root, "Stop") or changed
    changed = _remove_hook_entries(root, "Stop", MCORE_INGEST_FRAGMENTS) or changed
    start_command = f"MCORE_AGENT_ID=codex bash {HOOK_SESSION_START}"
    start_entries = root.setdefault("SessionStart", [])
    if not any(start_command in json.dumps(entry, ensure_ascii=False) for entry in start_entries):
        start_entries.append({"hooks": [{"type": "command", "command": start_command, "timeout": 5}]})
        changed = True
    end_command = f"python3 {HOOK_MCORE_INGEST} --agent codex --background"
    entries = root.setdefault("Stop", [])
    if not any(end_command in json.dumps(entry, ensure_ascii=False) for entry in entries):
        entries.append({"hooks": [{"type": "command", "command": end_command, "timeout": 30}]})
        changed = True
    if not changed:
        return trust_codex_hooks(path, hooks_path, backup_dir, dry_run)
    if dry_run:
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_file(path, backup_dir)
    path.write_text(new_config, encoding="utf-8")
    write_json(hooks_path, hooks_data, backup_dir, dry_run=False)
    trust_codex_hooks(path, hooks_path, backup_dir, dry_run=False)
    return True


def register_hooks_opencode(path: Path, endpoint: str, backup_dir: Path, dry_run: bool) -> bool:
    """Register hooks in opencode config.json."""
    data = read_json(path)
    hooks = data.setdefault("hooks", {})
    changed = False
    if hooks.get("session_start") != f"MCORE_AGENT_ID=opencode bash {HOOK_SESSION_START}":
        hooks["session_start"] = f"MCORE_AGENT_ID=opencode bash {HOOK_SESSION_START}"
        changed = True
    end_command = f"python3 {HOOK_MCORE_INGEST} --agent opencode --background"
    if hooks.get("session_end") != end_command:
        hooks["session_end"] = end_command
        changed = True
    plugins = data.setdefault("plugin", [])
    if not isinstance(plugins, list):
        plugins = []
        data["plugin"] = plugins
        changed = True
    filtered_plugins = [
        entry for entry in plugins
        if not any(fragment in json.dumps(entry, ensure_ascii=False) for fragment in OPENCODE_MCORE_PLUGIN_FRAGMENTS)
    ]
    plugin_entry = [HOOK_OPENCODE_PLUGIN, {"agent": "opencode", "url": endpoint}]
    filtered_plugins.append(plugin_entry)
    if filtered_plugins != plugins:
        data["plugin"] = filtered_plugins
        changed = True
    if not changed:
        return False
    return write_json(path, data, backup_dir, dry_run)


def register_hooks_gemini(path: Path, backup_dir: Path, dry_run: bool) -> bool:
    """Register Gemini CLI session hooks for read-before and write-after memory."""
    data = read_json(path)
    hooks = data.setdefault("hooks", {})
    changed = False
    changed = _remove_hook_entries(hooks, "SessionStart", MCORE_SESSION_START_FRAGMENTS) or changed
    changed = _remove_hook_entries(hooks, "BeforeAgent", CODEX_MCORE_CONTEXT_FRAGMENTS) or changed
    changed = _remove_hook_entries(hooks, "AfterAgent", MCORE_INGEST_FRAGMENTS) or changed
    changed = _remove_hook_entries(hooks, "SessionEnd", MCORE_INGEST_FRAGMENTS) or changed

    start_command = f"MCORE_AGENT_ID=gemini bash {HOOK_SESSION_START}"
    start_entries = hooks.setdefault("SessionStart", [])
    if not any(start_command in json.dumps(entry, ensure_ascii=False) for entry in start_entries):
        start_entries.append({"hooks": [{"type": "command", "command": start_command, "timeout": 5000}]})
        changed = True

    context_command = f"MCORE_AGENT_ID=gemini bash {HOOK_MCORE_CONTEXT}"
    context_entries = hooks.setdefault("BeforeAgent", [])
    if not any(context_command in json.dumps(entry, ensure_ascii=False) for entry in context_entries):
        context_entries.append({"hooks": [{"type": "command", "command": context_command, "timeout": 5000}]})
        changed = True

    end_command = f"python3 {HOOK_MCORE_INGEST} --agent gemini --background"
    after_entries = hooks.setdefault("AfterAgent", [])
    if not any(end_command in json.dumps(entry, ensure_ascii=False) for entry in after_entries):
        after_entries.append({"hooks": [{"type": "command", "command": end_command, "timeout": 30000}]})
        changed = True

    end_entries = hooks.setdefault("SessionEnd", [])
    if not any(end_command in json.dumps(entry, ensure_ascii=False) for entry in end_entries):
        end_entries.append({"hooks": [{"type": "command", "command": end_command, "timeout": 30000}]})
        changed = True

    if not changed:
        return False
    return write_json(path, data, backup_dir, dry_run)


def register_all_hooks(agents: set[str], endpoint: str, backup_dir: Path, dry_run: bool) -> list[str]:
    """Register hooks for all detected agents. Returns list of changed paths."""
    changed: list[str] = []
    detected = detect_agents()
    log(f"Detected agents: {', '.join(sorted(detected.keys())) or 'none'}")
    if "claude" in agents:
        claude_targets = []
        if (HOME / ".claude" / "settings.json").exists():
            claude_targets.append(HOME / ".claude" / "settings.json")
        for u in windows_user_dirs():
            w_settings = u / ".claude" / "settings.json"
            if w_settings.exists() or (u / ".claude").exists():
                claude_targets.append(w_settings)
        for target in claude_targets:
            if register_hooks_claude(target, backup_dir, dry_run):
                changed.append(str(target))
            md_path = target.parent / "CLAUDE.md"
            if configure_claude_md(md_path, backup_dir, dry_run):
                changed.append(str(md_path))
    if "hermes" in agents and "hermes" in detected:
        for p in hermes_paths():
            if register_hooks_hermes(p, backup_dir, dry_run):
                changed.append(str(p))
    if "codex" in agents and "codex" in detected:
        if register_hooks_codex(detected["codex"], backup_dir, dry_run):
            changed.append(str(detected["codex"]))
    if "opencode" in agents and "opencode" in detected:
        if register_hooks_opencode(detected["opencode"], endpoint, backup_dir, dry_run):
            changed.append(str(detected["opencode"]))
    if "gemini" in agents and "gemini" in detected:
        if register_hooks_gemini(detected["gemini"], backup_dir, dry_run):
            changed.append(str(detected["gemini"]))
    return changed


def windows_user_dirs() -> list[Path]:
    users = Path("/mnt/c/Users")
    if not users.exists():
        return []
    preferred = users / "e-pengyang.DU"
    if preferred.exists():
        return [preferred]
    result = []
    for p in users.iterdir():
        if p.is_dir() and not p.name.lower().startswith(("public", "default", "all users")):
            result.append(p)
    return result


def endpoint_probe(endpoint: str) -> tuple[bool, str]:
    payload = '{"jsonrpc":"2.0","method":"initialize","id":1,"params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"mcore-connect-agents","version":"1"}}}'
    try:
        proc = subprocess.run(
            [
                "curl",
                "-sS",
                endpoint,
                "-X",
                "POST",
                "-H",
                "Content-Type: application/json",
                "-H",
                "Accept: application/json, text/event-stream",
                "-d",
                payload,
                "-w",
                "\nHTTP:%{http_code}",
            ],
            text=True,
            capture_output=True,
            timeout=10,
        )
    except Exception as exc:
        return False, str(exc)
    out = (proc.stdout + proc.stderr).strip()
    return ("HTTP:200" in out), out[:500]


def run_list_command(label: str, cmd: list[str]) -> None:
    exe = shutil.which(cmd[0])
    if not exe:
        log(f"  - {label}: command not found ({cmd[0]})")
        return
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True, timeout=20)
        output = (proc.stdout or proc.stderr).strip()
        if output:
            first = " | ".join(output.splitlines()[:4])
            log(f"  - {label}: {first}")
        else:
            log(f"  - {label}: exit {proc.returncode}")
    except Exception as exc:
        log(f"  - {label}: {exc}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Connect mcore to Hermes/Claude/Codex/Gemini/opencode")
    parser.add_argument("--endpoint", default=os.environ.get("MCORE_ENDPOINT", DEFAULT_ENDPOINT), help=f"MCP endpoint (default: {DEFAULT_ENDPOINT})")
    parser.add_argument("--agents", default="all", help="Comma-separated: hermes,claude,codex,gemini,opencode,all")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without writing")
    parser.add_argument("--no-probe", action="store_true", help="Skip endpoint health probe")
    parser.add_argument("--verify", action="store_true", help="Run agent list commands after writing")
    parser.add_argument("--register-hooks", action="store_true", help="Also register session hooks for memory extraction")
    args = parser.parse_args(argv)

    agents = {a.strip().lower() for a in args.agents.split(",") if a.strip()}
    if "all" in agents:
        agents = {"hermes", "claude", "codex", "gemini", "opencode"}

    backup_dir = BACKUP_ROOT / time.strftime("%Y%m%d-%H%M%S")
    changed: list[str] = []

    if not args.no_probe:
        ok, detail = endpoint_probe(args.endpoint)
        if ok:
            log(f"✓ Endpoint live: {args.endpoint}")
        else:
            log(f"! Endpoint probe failed for {args.endpoint}")
            log(f"  {detail}")
            log("  Continuing config write; start service with: mcore start")

    if "hermes" in agents:
        for path in hermes_paths():
            if configure_hermes_config(path, args.endpoint, backup_dir, args.dry_run):
                changed.append(str(path))

    wdirs = windows_user_dirs()

    if "claude" in agents:
        claude_configs = [
            HOME / ".claude.json",
            HOME / ".claude" / "settings.json",
        ]
        for u in wdirs:
            claude_configs.extend([
                u / ".claude.json",
                u / ".claude" / "settings.json",
            ])
        for path in claude_configs:
            if path.exists() or path == HOME / ".claude.json" or path == HOME / ".claude" / "settings.json":
                if configure_claude(path, args.endpoint, backup_dir, args.dry_run):
                    changed.append(str(path))

    if "codex" in agents:
        for path in [HOME / ".codex" / "config.toml", *[u / ".codex" / "config.toml" for u in wdirs]]:
            if path.exists() or path == HOME / ".codex" / "config.toml":
                if configure_codex(path, args.endpoint, backup_dir, args.dry_run):
                    changed.append(str(path))

    if "gemini" in agents:
        for path in [HOME / ".gemini" / "settings.json", *[u / ".gemini" / "settings.json" for u in wdirs]]:
            if path.exists() or path == HOME / ".gemini" / "settings.json":
                if configure_gemini(path, args.endpoint, backup_dir, args.dry_run):
                    changed.append(str(path))

    if "opencode" in agents:
        paths = [HOME / ".config" / "opencode" / "opencode.json"]
        paths.extend(u / "AppData" / "Roaming" / "opencode" / "opencode.json" for u in wdirs)
        for path in paths:
            if path.exists() or path == HOME / ".config" / "opencode" / "opencode.json":
                if configure_opencode(path, args.endpoint, backup_dir, args.dry_run):
                    changed.append(str(path))

    if changed:
        log(("Would update:" if args.dry_run else "Updated:") )
        for p in changed:
            log(f"  - {p}")
        if not args.dry_run:
            log(f"Backups: {backup_dir}")
    else:
        log("No changes needed; all selected agents already point to the endpoint.")

    # Register presence metadata in mcore for selected agents + mcore itself
    if not args.dry_run:
        registered = []
        for ag in {*agents, "mcore"}:
            if register_app_presence(ag, dry_run=False):
                registered.append(ag)
        if registered:
            log(f"Registered app profiles in mcore: {', '.join(sorted(registered))}")

    # Hook registration
    if args.register_hooks:
        log("\n--- Hook registration ---")
        hook_changed = register_all_hooks(agents, args.endpoint, backup_dir, args.dry_run)
        if hook_changed:
            log(("Would register hooks:" if args.dry_run else "Hooks registered:"))
            for p in hook_changed:
                log(f"  - {p}")
        else:
            log("All hooks already registered.")

    if args.verify:
        log("Verification commands:")
        run_list_command("Hermes", ["hermes", "mcp", "list"])
        run_list_command("Claude Code", ["claude", "mcp", "list"])
        run_list_command("Codex", ["codex", "mcp", "list"])
        run_list_command("opencode", ["opencode", "mcp", "list"])
        run_list_command("Gemini", ["gemini", "mcp", "list"])

    log("Done. Restart running agent sessions to reload MCP tool lists.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
