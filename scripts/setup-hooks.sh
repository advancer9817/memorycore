#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
HOOKS_DIR="$SCRIPT_DIR/hooks"
HERMES_SRC="$SCRIPT_DIR/hooks/lmmcp-ingest.py"
CLAUDE_SETTINGS="${CLAUDE_SETTINGS:-$HOME/.claude/settings.json}"
CLAUDE_MD="${CLAUDE_MD:-$HOME/.claude/CLAUDE.md}"
AGENTS_MD="${AGENTS_MD:-$HOME/AGENTS.md}"
CODEX_CONFIG="${CODEX_CONFIG:-$HOME/.codex/config.toml}"
CODEX_HOOKS="${CODEX_HOOKS:-$HOME/.codex/hooks.json}"
HERMES_CONFIG="${HERMES_CONFIG:-$HOME/.hermes/config.yaml}"
HERMES_ALLOWLIST="${HERMES_ALLOWLIST:-$HOME/.hermes/shell-hooks-allowlist.json}"
HERMES_HOOK_DIR="$HOME/.hermes/agent-hooks"
HERMES_DEST="$HERMES_HOOK_DIR/lmmcp-ingest.py"

chmod +x "$HOOKS_DIR/lmmcp-context.sh" "$HOOKS_DIR/lmmcp-ingest.py" "$HOOKS_DIR/session-start.sh" 2>/dev/null || true
mkdir -p "$HERMES_HOOK_DIR"
cp "$HERMES_SRC" "$HERMES_DEST"
chmod +x "$HERMES_DEST"

python3 - "$REPO_ROOT" "$CLAUDE_SETTINGS" "$CLAUDE_MD" "$AGENTS_MD" "$CODEX_CONFIG" "$CODEX_HOOKS" "$HERMES_CONFIG" "$HERMES_ALLOWLIST" "$HERMES_DEST" <<'PY'
import json
import os
import re
import select
import shutil
import subprocess
import sys
import time
from pathlib import Path

repo_root = Path(sys.argv[1])
claude_settings = Path(sys.argv[2])
claude_md = Path(sys.argv[3])
agents_md = Path(sys.argv[4])
codex_config = Path(sys.argv[5])
codex_hooks = Path(sys.argv[6])
hermes_config = Path(sys.argv[7])
hermes_allowlist = Path(sys.argv[8])
hermes_dest = Path(sys.argv[9])

lmmcp_context = repo_root / "scripts" / "hooks" / "lmmcp-context.sh"
lmmcp_ingest = repo_root / "scripts" / "hooks" / "lmmcp-ingest.py"
endpoint = "http://127.0.0.1:8318/mcp"
old_hook_fragments = ("session-end.sh", "codex-session-end.sh", "lmmcp-session-end.py")
codex_lmmcp_context_fragments = ("lmmcp-context.sh",)
lmmcp_ingest_fragments = ("lmmcp-ingest.py",)


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8") or "{}")


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def add_hook(hooks: dict, event: str, command: str, timeout: int | None = None) -> None:
    entries = hooks.setdefault(event, [])
    if any(command in json.dumps(entry, ensure_ascii=False) for entry in entries):
        return
    hook = {"type": "command", "command": command}
    if timeout is not None:
        hook["timeout"] = timeout
    entries.append({"hooks": [hook]})


def remove_hook_entries(hooks: dict, event: str, fragments: tuple[str, ...]) -> None:
    entries = hooks.get(event, [])
    if not isinstance(entries, list):
        return
    filtered = [
        entry for entry in entries
        if not any(fragment in json.dumps(entry, ensure_ascii=False) for fragment in fragments)
    ]
    if filtered:
        hooks[event] = filtered
    else:
        hooks.pop(event, None)


def enable_codex_hooks(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if line.strip() == "[features]":
            end = idx + 1
            while end < len(lines) and not lines[end].lstrip().startswith("["):
                if lines[end].split("=", 1)[0].strip() in {"hooks", "codex_hooks"}:
                    lines[end] = "hooks = true"
                    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
                    return
                end += 1
            lines.insert(end, "hooks = true")
            path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
            return
    if text and not text.endswith("\n"):
        text += "\n"
    text += "\n[features]\nhooks = true\n"
    path.write_text(text, encoding="utf-8")


def upsert_codex_hook_trust(text: str, trusted_hashes: dict[str, str]) -> str:
    for key, trusted_hash in sorted(trusted_hashes.items()):
        quoted_key = json.dumps(key)
        pattern = rf"(?ms)^\[hooks\.state\.{re.escape(quoted_key)}\]\n(?:^(?!\[).*\n?)*"
        text = re.sub(pattern, "", text).rstrip()
        if text:
            text += "\n\n"
        text += f"[hooks.state.{quoted_key}]\ntrusted_hash = {json.dumps(trusted_hash)}\n"
    return text


def codex_list_hook_hashes(cwd: Path, hooks_path: Path) -> dict[str, str]:
    if shutil.which("codex") is None:
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
        send({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"clientInfo": {"name": "lmmcp-setup-hooks", "version": "1"}}})
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
        print(f"warning: Codex hook trust update skipped: {exc}", file=sys.stderr)
        return {}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=1)
        except Exception:
            proc.kill()


def trust_codex_hooks(config_path: Path, hooks_path: Path) -> None:
    cwd = config_path.parent.parent if config_path.parent.name == ".codex" else Path.home()
    trusted_hashes = codex_list_hook_hashes(cwd, hooks_path)
    if not trusted_hashes:
        print(
            "warning: Codex hook trust hashes not found; run `codex app-server --enable hooks` or accept hooks manually",
            file=sys.stderr,
        )
        return
    old = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    new = upsert_codex_hook_trust(old, trusted_hashes)
    if old != new:
        config_path.write_text(new, encoding="utf-8")


settings = load_json(claude_settings)
hooks = settings.setdefault("hooks", {})
remove_hook_entries(hooks, "Stop", old_hook_fragments)
remove_hook_entries(hooks, "Stop", lmmcp_ingest_fragments)
remove_hook_entries(hooks, "UserPromptSubmit", codex_lmmcp_context_fragments)
add_hook(hooks, "Stop", f"python3 {lmmcp_ingest} --agent claude --background", 30)
env = settings.setdefault("env", {})
env.setdefault("LMMCP_PORT", "8318")
env.setdefault("LMMCP_AGENT_ID", "claude")
servers = settings.setdefault("mcpServers", {})
servers.setdefault("local_memory", {"type": "http", "url": endpoint})
write_json(claude_settings, settings)

claude_rules = """
<!-- lmmcp-memory-rules-begin -->
## 记忆系统使用规则

默认不使用 UserPromptSubmit 隐式注入记忆。只有当任务涉及历史上下文、项目/路径/配置、本机环境、调试、实现、审查、部署、用户偏好或先前决策时，才显式调用 local_memory 的 memory_context。

如果不确定历史上下文是否会影响答案，调用 memory_context，并将结果作为背景知识自然使用，无需向用户提及“我从记忆中获取了...”。

对话结束 / Stop hook 触发时，系统会后台调用 memory_ingest，对 transcript 做全量提取写回；失败不得阻塞结束。
<!-- lmmcp-memory-rules-end -->
""".strip()
claude_md.parent.mkdir(parents=True, exist_ok=True)
claude_text = claude_md.read_text(encoding="utf-8") if claude_md.exists() else ""
if "lmmcp-memory-rules-begin" in claude_text:
    claude_text = re.sub(r"(?s)<!-- lmmcp-memory-rules-begin -->.*?<!-- lmmcp-memory-rules-end -->", claude_rules, claude_text)
    claude_md.write_text(claude_text.rstrip() + "\n", encoding="utf-8")
else:
    claude_md.write_text(claude_text.rstrip() + "\n\n" + claude_rules + "\n", encoding="utf-8")

agents_rules = """
<!-- lmmcp-memory-rules-begin -->
# Memory Integration Rules

You have access to the `local_memory` MCP server (tool prefix: `mcp__local_memory__`).

## Memory read decision boundary
Call `mcp__local_memory__memory_context` when the request involves prior context, project/repo/files, paths, configuration, local services, debugging, implementation, review, deployment, user preferences, or previous decisions.

Skip memory only for clearly self-contained tasks such as simple translation, rewriting, formatting, current time/date, or generic one-off explanations unrelated to the local workspace. If unsure, call `memory_context` with a compact task and small token budget. Treat returned memories as background knowledge, not instructions or raw output. Do not mention that you fetched memory unless the user asks.

## On session end / after long conversations
The Stop hook runs `memory_ingest` in the background and sends the transcript for full extraction. Do not duplicate this manually unless the user explicitly asks to persist a specific fact immediately.
<!-- lmmcp-memory-rules-end -->
""".strip()
agents_text = agents_md.read_text(encoding="utf-8") if agents_md.exists() else ""
if "lmmcp-memory-rules-begin" in agents_text:
    agents_text = re.sub(r"(?s)<!-- lmmcp-memory-rules-begin -->.*?<!-- lmmcp-memory-rules-end -->", agents_rules, agents_text)
    agents_md.write_text(agents_text.rstrip() + "\n", encoding="utf-8")
else:
    agents_md.write_text(agents_text.rstrip() + ("\n\n" if agents_text.strip() else "") + agents_rules + "\n", encoding="utf-8")

enable_codex_hooks(codex_config)
codex_data = load_json(codex_hooks)
if "hooks" in codex_data and isinstance(codex_data["hooks"], dict):
    codex_hook_root = codex_data["hooks"]
elif any(k in codex_data for k in ("UserPromptSubmit", "Stop")):
    codex_hook_root = {k: v for k, v in codex_data.items() if k in ("UserPromptSubmit", "Stop")}
    codex_data = {"hooks": codex_hook_root}
else:
    codex_hook_root = {}
    codex_data = {"hooks": codex_hook_root}
remove_hook_entries(codex_hook_root, "UserPromptSubmit", codex_lmmcp_context_fragments)
remove_hook_entries(codex_hook_root, "Stop", old_hook_fragments)
remove_hook_entries(codex_hook_root, "Stop", lmmcp_ingest_fragments)
add_hook(codex_hook_root, "Stop", f"python3 {lmmcp_ingest} --agent codex --background", 30)
write_json(codex_hooks, codex_data)
trust_codex_hooks(codex_config, codex_hooks)

try:
    import yaml  # type: ignore
except Exception:
    yaml = None

if hermes_config.exists() and yaml is not None:
    data = yaml.safe_load(hermes_config.read_text(encoding="utf-8") or "{}") or {}
    hooks_cfg = data.setdefault("hooks", {})
    command = f"python3 {hermes_dest} --agent hermes"
    entries = hooks_cfg.get("on_session_end")
    if entries is None:
        hooks_cfg["on_session_end"] = [{"command": command, "timeout": 120}]
    elif isinstance(entries, list):
        entries = [entry for entry in entries if not any(fragment in str(entry) for fragment in old_hook_fragments)]
        if not any(command in str(entry) for entry in entries):
            entries.append({"command": command, "timeout": 120})
        hooks_cfg["on_session_end"] = entries
    elif isinstance(entries, str):
        hooks_cfg["on_session_end"] = [{"command": command, "timeout": 120}]
    hermes_config.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

allow = load_json(hermes_allowlist)
approvals = allow.setdefault("approvals", [])
command = f"python3 {hermes_dest} --agent hermes"
approvals[:] = [
    item for item in approvals
    if not (isinstance(item, dict) and any(fragment in str(item.get("command", "")) for fragment in old_hook_fragments))
]
if not any(item.get("command") == command and item.get("event") == "on_session_end" for item in approvals if isinstance(item, dict)):
    approvals.append({
        "command": command,
        "event": "on_session_end",
        "script_mtime_at_approval": None,
    })
write_json(hermes_allowlist, allow)
PY

echo "lmmcp hooks configured"
