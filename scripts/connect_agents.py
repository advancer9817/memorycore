#!/usr/bin/env python3
"""One-click lmmcp MCP registration for local agents.

Default endpoint: http://127.0.0.1:8318/mcp

Configures:
- Hermes default + all Hermes profiles
- Claude Code (WSL + Windows user config when available)
- Codex CLI (WSL + Windows user config when available)
- Gemini CLI (WSL + Windows user config when available)
- opencode (WSL + Windows user config when available)

The script is intentionally idempotent and removes stale openmemory entries.
"""
from __future__ import annotations

import argparse
import json
import os
import re
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
SERVER_NAME = "local_memory"
OPENMEMORY_KEYS = {"openmemory", "open_memory"}
HOME = Path.home()
BACKUP_ROOT = HOME / ".agent-memory" / "local-memory-mcp" / "backups" / "connect-agents"
HOOKS_DIR = Path(__file__).resolve().parent / "hooks"


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
    for key in list(servers.keys()):
        if key.lower() in OPENMEMORY_KEYS:
            servers.pop(key, None)
    servers[SERVER_NAME] = {
        "enabled": True,
        "type": "http",
        "url": endpoint,
        "timeout": 120,
        "connect_timeout": 60,
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
    for key in list(servers.keys()):
        if key.lower() in OPENMEMORY_KEYS:
            servers.pop(key, None)
    servers[SERVER_NAME] = {"type": "http", "url": endpoint}
    # Remove old Windows project entry that can resurrect confusion in Claude UI.
    projects = data.get("projects")
    if isinstance(projects, dict):
        for key in list(projects.keys()):
            if "openmemory" in key.lower():
                projects.pop(key, None)
    return write_json(path, data, backup_dir, dry_run)


def configure_gemini(path: Path, endpoint: str, backup_dir: Path, dry_run: bool) -> bool:
    data = read_json(path)
    servers = data.setdefault("mcpServers", {})
    for key in list(servers.keys()):
        if key.lower() in OPENMEMORY_KEYS:
            servers.pop(key, None)
    servers[SERVER_NAME] = {"httpUrl": endpoint, "timeout": 60000}
    return write_json(path, data, backup_dir, dry_run)


def remove_toml_table(text: str, table: str) -> str:
    # Remove [table]\n... until next [section].
    pattern = rf"(?ms)^\[{re.escape(table)}\]\n(?:^[^\[].*\n?)*"
    return re.sub(pattern, "", text)


def configure_codex(path: Path, endpoint: str, backup_dir: Path, dry_run: bool) -> bool:
    old = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
    text = old
    text = remove_toml_table(text, "mcp_servers.openmemory")
    text = remove_toml_table(text, "mcp_servers.open_memory")
    text = remove_toml_table(text, "mcp_servers.local_memory")
    if "[mcp_servers]" not in text:
        if text and not text.endswith("\n"):
            text += "\n"
        text += "\n[mcp_servers]\n"
    if text and not text.endswith("\n"):
        text += "\n"
    text += f"\n[mcp_servers.{SERVER_NAME}]\ntype = \"http\"\nurl = \"{endpoint}\"\n"
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
    for key in list(servers.keys()):
        if key.lower() in OPENMEMORY_KEYS:
            servers.pop(key, None)
    servers[SERVER_NAME] = {"type": "remote", "url": endpoint}
    return write_json(path, data, backup_dir, dry_run)


# ---------------------------------------------------------------------------
# Hook registration
# ---------------------------------------------------------------------------

HOOK_SESSION_START = str(HOOKS_DIR / "session-start.sh")
HOOK_SESSION_END = str(HOOKS_DIR / "session-end.sh")


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


def register_hooks_claude(path: Path, backup_dir: Path, dry_run: bool) -> bool:
    """Register SessionStart and Stop hooks in Claude Code settings.json."""
    data = read_json(path)
    hooks = data.setdefault("hooks", {})
    start_hook = {
        "hooks": [{"type": "command", "command": f"bash {HOOK_SESSION_START}"}]
    }
    end_hook = {
        "hooks": [{"type": "command", "command": f"bash {HOOK_SESSION_END}"}]
    }
    changed = False
    existing_start = hooks.get("SessionStart", [])
    if not any(HOOK_SESSION_START in str(h) for h in existing_start):
        hooks["SessionStart"] = existing_start + [start_hook]
        changed = True
    existing_stop = hooks.get("Stop", [])
    if not any(HOOK_SESSION_END in str(h) for h in existing_stop):
        hooks["Stop"] = existing_stop + [end_hook]
        changed = True
    if not changed:
        return False
    # Inject LMMCP env vars
    env = data.setdefault("env", {})
    env.setdefault("LMMCP_PORT", "8318")
    env.setdefault("LMMCP_AGENT_ID", "claude")
    return write_json(path, data, backup_dir, dry_run)


def register_hooks_hermes(path: Path, backup_dir: Path, dry_run: bool) -> bool:
    """Register hooks in Hermes config.yaml."""
    if yaml is None:
        log("  ! PyYAML not available; skipping Hermes hook registration")
        return False
    old_raw = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
    data = yaml.safe_load(old_raw) if old_raw.strip() else {}
    data = data or {}
    hooks = data.setdefault("hooks", {})
    changed = False
    if "session_start" not in hooks or HOOK_SESSION_START not in str(hooks.get("session_start")):
        hooks["session_start"] = f"bash {HOOK_SESSION_START}"
        changed = True
    if "session_end" not in hooks or HOOK_SESSION_END not in str(hooks.get("session_end")):
        hooks["session_end"] = f"bash {HOOK_SESSION_END}"
        changed = True
    if not changed:
        return False
    if dry_run:
        return True
    backup_file(path, backup_dir)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return True


def register_hooks_codex(path: Path, backup_dir: Path, dry_run: bool) -> bool:
    """Register hooks in Codex config.toml."""
    old = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
    if HOOK_SESSION_START in old and HOOK_SESSION_END in old:
        return False
    text = old
    hook_block = f"""
[hooks]
session_start = "bash {HOOK_SESSION_START}"
session_end = "bash {HOOK_SESSION_END}"
"""
    if "[hooks]" not in text:
        text = text.rstrip() + "\n" + hook_block
    if old == text:
        return False
    if dry_run:
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_file(path, backup_dir)
    path.write_text(text, encoding="utf-8")
    return True


def register_hooks_opencode(path: Path, backup_dir: Path, dry_run: bool) -> bool:
    """Register hooks in opencode config.json."""
    data = read_json(path)
    hooks = data.setdefault("hooks", {})
    changed = False
    if hooks.get("session_start") != f"bash {HOOK_SESSION_START}":
        hooks["session_start"] = f"bash {HOOK_SESSION_START}"
        changed = True
    if hooks.get("session_end") != f"bash {HOOK_SESSION_END}":
        hooks["session_end"] = f"bash {HOOK_SESSION_END}"
        changed = True
    if not changed:
        return False
    return write_json(path, data, backup_dir, dry_run)


def register_all_hooks(agents: set[str], backup_dir: Path, dry_run: bool) -> list[str]:
    """Register hooks for all detected agents. Returns list of changed paths."""
    changed: list[str] = []
    detected = detect_agents()
    log(f"Detected agents: {', '.join(sorted(detected.keys())) or 'none'}")
    if "claude" in agents and "claude" in detected:
        if register_hooks_claude(detected["claude"], backup_dir, dry_run):
            changed.append(str(detected["claude"]))
    if "hermes" in agents and "hermes" in detected:
        for p in hermes_paths():
            if register_hooks_hermes(p, backup_dir, dry_run):
                changed.append(str(p))
    if "codex" in agents and "codex" in detected:
        if register_hooks_codex(detected["codex"], backup_dir, dry_run):
            changed.append(str(detected["codex"]))
    if "opencode" in agents and "opencode" in detected:
        if register_hooks_opencode(detected["opencode"], backup_dir, dry_run):
            changed.append(str(detected["opencode"]))
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
    payload = '{"jsonrpc":"2.0","method":"initialize","id":1,"params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"lmmcp-connect-agents","version":"1"}}}'
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
    parser = argparse.ArgumentParser(description="Connect lmmcp to Hermes/Claude/Codex/Gemini/opencode")
    parser.add_argument("--endpoint", default=os.environ.get("LMMCP_ENDPOINT", DEFAULT_ENDPOINT), help=f"MCP endpoint (default: {DEFAULT_ENDPOINT})")
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
            log("  Continuing config write; start service with: lmmcp start")

    if "hermes" in agents:
        for path in hermes_paths():
            if configure_hermes_config(path, args.endpoint, backup_dir, args.dry_run):
                changed.append(str(path))

    wdirs = windows_user_dirs()

    if "claude" in agents:
        for path in [HOME / ".claude.json", *[u / ".claude.json" for u in wdirs]]:
            if path.exists() or path == HOME / ".claude.json":
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

    # Hook registration
    if args.register_hooks:
        log("\n--- Hook registration ---")
        hook_changed = register_all_hooks(agents, backup_dir, args.dry_run)
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
