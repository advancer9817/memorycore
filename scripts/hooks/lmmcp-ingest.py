#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

MARK = Path("/tmp/lmmcp-session-mark")
LOG = Path(os.environ.get("LMMCP_INGEST_LOG", "/tmp/lmmcp-ingest.log"))


def _log(message: str) -> None:
    try:
        stamp = datetime.now().astimezone().isoformat(timespec="seconds")
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(f"{stamp} {message}\n")
    except Exception:
        pass


def _spawn_background(agent: str, force: bool) -> None:
    cmd = [sys.executable or "python3", str(Path(__file__).resolve()), "--agent", agent]
    if force:
        cmd.append("--force")
    env = os.environ.copy()
    env["LMMCP_INGEST_BACKGROUND_CHILD"] = "1"
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            close_fds=True,
            start_new_session=True,
        )
        _log(f"background_spawned agent={agent} pid={proc.pid}")
    except Exception as exc:
        _log(f"background_spawn_failed agent={agent} error={type(exc).__name__}")


def _lmmcp_url() -> str:
    host = os.environ.get("LMMCP_HOST", "127.0.0.1")
    port = os.environ.get("LMMCP_PORT", "8318")
    return f"http://{host}:{port}/mcp"


def _curl_post(payload: dict, session_id: str = "", timeout: float = 10.0) -> tuple[dict, str]:
    cmd = [
        "curl",
        "-sS",
        "-i",
        "--max-time",
        str(timeout),
        "-X",
        "POST",
        _lmmcp_url(),
        "-H",
        "Content-Type: application/json",
        "-H",
        "Accept: application/json, text/event-stream",
    ]
    if session_id:
        cmd.extend(["-H", f"Mcp-Session-Id: {session_id}"])
    cmd.extend(["-d", json.dumps(payload, ensure_ascii=False)])

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout + 2,
    )
    if proc.returncode != 0:
        _log(f"curl_failed rc={proc.returncode} stderr={proc.stderr.strip()[:300]}")
        return {}, ""

    raw = proc.stdout.replace("\r\n", "\n")
    if "\n\n" in raw:
        header_text, body = raw.split("\n\n", 1)
    else:
        header_text, body = raw, ""
    headers: dict[str, str] = {}
    for line in header_text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        headers[key.strip().lower()] = value.strip()
    return headers, body


def _find_transcript(root: Path, env_key: str, pattern: str) -> Path | None:
    explicit = os.environ.get(env_key, "")
    if explicit:
        path = Path(explicit)
        if path.is_file():
            return path

    try:
        candidates = [p for p in root.glob(pattern) if p.is_file()]
    except Exception:
        return None

    if not candidates:
        return None

    if MARK.exists():
        try:
            mark_time = MARK.stat().st_mtime
            recent = [p for p in candidates if p.stat().st_mtime >= mark_time]
        except Exception:
            recent = []
        if recent:
            return max(recent, key=lambda p: p.stat().st_mtime)

    return max(candidates, key=lambda p: p.stat().st_mtime)


def _text_from_blocks(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return " ".join(
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    )


def _extract_claude(path: Path) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()[-300:]:
        try:
            item = json.loads(line)
        except Exception:
            continue
        msg = item.get("message", item)
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", "")
        if role not in ("user", "assistant"):
            continue
        text = _text_from_blocks(msg.get("content", ""))
        text = text.strip()
        if text:
            messages.append({"role": role, "content": text[:800]})
    return messages[-40:]


def _extract_codex(path: Path) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    fallback: list[dict[str, str]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()[-300:]:
        try:
            item = json.loads(line)
        except Exception:
            continue
        payload = item.get("payload", {})
        if not isinstance(payload, dict):
            continue

        role = ""
        text = ""
        if item.get("type") == "event_msg":
            event_type = payload.get("type")
            if event_type == "user_message":
                role = "user"
                text = str(payload.get("message", ""))
            elif event_type == "agent_message":
                role = "assistant"
                text = str(payload.get("message", ""))
        elif item.get("type") == "response_item" and payload.get("type") == "message":
            role = str(payload.get("role", ""))
            if role not in ("user", "assistant"):
                continue
            parts = payload.get("content", [])
            if isinstance(parts, list):
                text = " ".join(
                    str(part.get("text") or part.get("input_text") or part.get("output_text") or "")
                    for part in parts
                    if isinstance(part, dict)
                )

        text = text.strip()
        if not (role in ("user", "assistant") and text):
            continue
        msg = {"role": role, "content": text[:800]}
        if item.get("type") == "event_msg":
            messages.append(msg)
        else:
            fallback.append(msg)
    if not messages:
        messages = fallback
    return messages[-40:]


def _extract_hermes(session_id: str) -> list[dict[str, str]]:
    session_file = Path.home() / ".hermes" / "sessions" / f"session_{session_id}.json"
    if not session_file.exists():
        return []
    try:
        data = json.loads(session_file.read_text(encoding="utf-8"))
    except Exception:
        return []

    messages: list[dict[str, str]] = []
    for msg in data.get("messages", [])[-40:]:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", "")
        if role not in ("user", "assistant"):
            continue
        text = _text_from_blocks(msg.get("content", ""))
        text = text.strip()
        if text:
            messages.append({"role": role, "content": text[:800]})
    return messages


def _ingest(messages: list[dict[str, str]], agent_id: str) -> None:
    if not messages:
        _log(f"skip_empty_messages agent={agent_id}")
        return
    try:
        ingest_timeout = float(os.environ.get("LMMCP_INGEST_TIMEOUT", "120"))
        _log(f"ingest_start agent={agent_id} messages={len(messages)}")
        headers, _ = _curl_post(
            {
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "lmmcp-ingest-hook", "version": "1.0"},
                },
            },
            timeout=5,
        )
        session_id = headers.get("mcp-session-id", "")
        if not session_id:
            _log(f"initialize_missing_session agent={agent_id}")
            return
        _, body = _curl_post(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "memory_ingest",
                    "arguments": {"messages": messages, "agent_id": agent_id},
                },
            },
            session_id=session_id,
            timeout=ingest_timeout,
        )
        preview = " ".join(body.split())[:500]
        _log(f"ingest_done agent={agent_id} messages={len(messages)} response={preview}")
    except Exception:
        _log(f"ingest_exception agent={agent_id}")


def _messages_for_agent(agent: str) -> list[dict[str, str]]:
    if agent == "hermes":
        try:
            data = json.loads(sys.stdin.read() or "{}")
        except Exception:
            return []
        session_id = str(data.get("session_id", "")) if isinstance(data, dict) else ""
        return _extract_hermes(session_id) if session_id else []

    if agent == "codex":
        path = _find_transcript(Path.home() / ".codex" / "sessions", "CODEX_SESSION_FILE", "**/*.jsonl")
        if path:
            messages = _extract_codex(path)
            _log(f"codex_transcript path={path} messages={len(messages)}")
            return messages
        _log("codex_transcript_missing")
        return []

    if agent == "claude":
        path = _find_transcript(Path.home() / ".claude" / "projects", "CLAUDE_SESSION_FILE", "*/*.jsonl")
        return _extract_claude(path) if path else []

    return []


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest recent agent transcript messages into lmmcp")
    parser.add_argument("--agent", default=os.environ.get("LMMCP_AGENT_ID", "claude"))
    parser.add_argument("--background", action="store_true", help="Spawn ingest in the background and exit immediately")
    parser.add_argument("--force", action="store_true", help="Compatibility flag; Stop ingest always sends the transcript")
    args = parser.parse_args()
    agent = args.agent.strip().lower()
    if args.background and os.environ.get("LMMCP_INGEST_BACKGROUND_CHILD") != "1":
        _spawn_background(agent, args.force)
        return
    messages = _messages_for_agent(agent)
    _ingest(messages, agent)


if __name__ == "__main__":
    main()
