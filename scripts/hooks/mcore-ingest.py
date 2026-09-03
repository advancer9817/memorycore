#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

MARK = Path("/tmp/mcore-session-mark")
LOG = Path(os.environ.get("MCORE_INGEST_LOG", "/tmp/mcore-ingest.log"))


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
    env["MCORE_INGEST_BACKGROUND_CHILD"] = "1"
    # Hermes on_session_end passes hook metadata on stdin.  A detached child
    # cannot read the parent's stdin after we redirect it to DEVNULL, so carry
    # the small JSON payload through the environment for background mode.
    try:
        payload = sys.stdin.read()
    except Exception:
        payload = ""
    if payload:
        env["MCORE_INGEST_HOOK_PAYLOAD"] = payload[:20000]
        env["MCORE_HERMES_HOOK_PAYLOAD"] = payload[:20000]
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


def _mcore_url() -> str:
    host = os.environ.get("MCORE_HOST", "127.0.0.1")
    port = os.environ.get("MCORE_PORT", "8318")
    return f"http://{host}:{port}/mcp"


def _detect_project(agent: str = "") -> dict:
    """Best-effort subject detection: which project does this conversation belong to.

    Order: MCORE_PROJECT_PATH env -> Hermes state.db session git_repo_root
    (uses the hook payload's session_id; falls back to the most recently
    active session) -> claude transcript slug -> git toplevel of the hook cwd.
    Returns {"project_path": str} (empty dict when nothing found). Resolution
    to a canonical project name happens server-side in dedup.ingest via the
    subject_context projects whitelist, so this stays generic and never
    guesses.
    """
    path = os.environ.get("MCORE_PROJECT_PATH", "").strip()
    if not path and agent == "hermes":
        # Hermes Desktop sessions record cwd / git_repo_root per session in
        # ~/.hermes/state.db — the real working dir of the conversation, which
        # the hook process cwd cannot see (it inherits the app's startup cwd).
        try:
            import sqlite3
            db = Path(os.environ.get("HERMES_STATE_DB", str(Path.home() / ".hermes" / "state.db")))
            if db.exists():
                session_id = _payload_session_id(_hook_payload())
                conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
                conn.row_factory = sqlite3.Row
                try:
                    if session_id:
                        row = conn.execute(
                            "SELECT git_repo_root, cwd FROM sessions WHERE id = ?", (session_id,)
                        ).fetchone()
                    else:
                        row = conn.execute(
                            "SELECT git_repo_root, cwd FROM sessions "
                            "WHERE ended_at IS NULL ORDER BY last_activity_at DESC LIMIT 1"
                        ).fetchone()
                    if row:
                        path = str(row["git_repo_root"] or "").strip() or str(row["cwd"] or "").strip()
                finally:
                    conn.close()
        except Exception:
            path = ""
    if not path and agent == "claude":
        # claude transcript lives at ~/.claude/projects/<slug>/<session>.jsonl
        # where <slug> is the cwd with "/" and "." replaced by "-".
        try:
            explicit = os.environ.get("CLAUDE_SESSION_FILE", "")
            source = Path(explicit) if explicit else None
            if source is None or not source.is_file():
                root = Path.home() / ".claude" / "projects"
                candidates = [p for p in root.glob("*/*.jsonl") if p.is_file()]
                if MARK.exists():
                    candidates = [p for p in candidates if p.stat().st_mtime >= MARK.stat().st_mtime]
                if candidates:
                    source = max(candidates, key=lambda p: p.stat().st_mtime)
            if source is not None:
                path = source.parent.name.replace("-", "/")
        except Exception:
            path = ""
    if not path:
        try:
            cwd = os.environ.get("MCORE_CWD") or os.getcwd()
            proc = subprocess.run(
                ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, timeout=5,
            )
            if proc.returncode == 0:
                path = proc.stdout.strip()
        except Exception:
            path = ""
    return {"project_path": path} if path else {}


def _curl_post(payload: dict, session_id: str = "", timeout: float = 10.0) -> tuple[dict, str]:
    cmd = [
        "curl",
        "-sS",
        "-i",
        "--max-time",
        str(timeout),
        "-X",
        "POST",
        _mcore_url(),
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
        if isinstance(block, dict) and (block.get("type") in (None, "text")) and block.get("text")
    )


def _parse_json_text(value: object) -> dict:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _hook_payload() -> dict:
    raw = os.environ.get("MCORE_INGEST_HOOK_PAYLOAD") or os.environ.get("MCORE_HERMES_HOOK_PAYLOAD")
    if not raw:
        try:
            raw = sys.stdin.read()
        except Exception:
            raw = ""
    return _parse_json_text(raw or "{}")


def _payload_session_id(payload: dict) -> str:
    candidates = [
        payload.get("session_id"),
        payload.get("sessionID"),
        payload.get("sessionId"),
        payload.get("id"),
    ]
    session = payload.get("session")
    if isinstance(session, dict):
        candidates.extend([session.get("id"), session.get("session_id"), session.get("sessionID")])
    for value in candidates:
        if value:
            return str(value)
    return ""


def _payload_transcript_path(payload: dict) -> Path | None:
    candidates = [
        payload.get("transcript_path"),
        payload.get("transcriptPath"),
        payload.get("transcript"),
    ]
    session = payload.get("session")
    if isinstance(session, dict):
        candidates.extend([session.get("transcript_path"), session.get("transcriptPath")])
    for value in candidates:
        if not value:
            continue
        path = Path(str(value)).expanduser()
        if path.is_file():
            return path
    return None


def _extract_claude(path: Path) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()[-5000:]:
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
            messages.append({"role": role, "content": text[:2000]})
    return messages[-500:]


def _extract_codex(path: Path) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    fallback: list[dict[str, str]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()[-5000:]:
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
        msg = {"role": role, "content": text[:2000]}
        if item.get("type") == "event_msg":
            messages.append(msg)
        else:
            fallback.append(msg)
    if not messages:
        messages = fallback
    return messages[-500:]


def _extract_hermes_from_state_db(session_id: str) -> list[dict[str, str]]:
    db_path = Path(os.environ.get("HERMES_STATE_DB", str(Path.home() / ".hermes" / "state.db")))
    if not db_path.exists():
        _log(f"hermes_state_db_missing path={db_path}")
        return []

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT role, content
            FROM messages
            WHERE session_id = ?
              AND role IN ('user', 'assistant')
              AND content IS NOT NULL
              AND trim(content) != ''
            ORDER BY id DESC
            LIMIT 800
            """,
            (session_id,),
        ).fetchall()
    except Exception as exc:
        _log(f"hermes_state_db_error type={type(exc).__name__}")
        return []
    finally:
        try:
            conn.close()  # type: ignore[name-defined]
        except Exception:
            pass

    messages: list[dict[str, str]] = []
    for row in reversed(rows):
        role = str(row["role"])
        text = str(row["content"] or "").strip()
        if text:
            messages.append({"role": role, "content": text[:2000]})
    if messages:
        _log(f"hermes_state_db_transcript session={session_id} messages={len(messages)}")
    return messages[-500:]


def _extract_hermes(session_id: str) -> list[dict[str, str]]:
    return _extract_hermes_from_state_db(session_id)


def _extract_jsonl_messages(path: Path) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()[-5000:]:
        item = _parse_json_text(line)
        if not item:
            continue
        role = str(item.get("role") or item.get("author") or item.get("speaker") or item.get("type") or "")
        if role not in ("user", "assistant", "model", "gemini"):
            continue
        content = item.get("displayContent") or item.get("content", item.get("text", item.get("message", "")))
        text = _text_from_blocks(content).strip() if isinstance(content, list) else str(content or "").strip()
        if text:
            messages.append({"role": "assistant" if role in ("model", "gemini") else role, "content": text[:2000]})
    return messages[-500:]


def _message_text_from_obj(item: dict) -> str:
    content = (
        item.get("content")
        or item.get("text")
        or item.get("message")
        or item.get("parts")
        or item.get("value")
        or ""
    )
    if isinstance(content, list):
        return _text_from_blocks(content).strip()
    if isinstance(content, dict):
        nested = content.get("text") or content.get("content") or content.get("message") or ""
        return str(nested or "").strip()
    return str(content or "").strip()


def _messages_from_json_obj(obj: object) -> list[dict[str, str]]:
    raw_items: list[object]
    if isinstance(obj, list):
        raw_items = obj
    elif isinstance(obj, dict):
        for key in ("messages", "history", "turns", "entries"):
            value = obj.get(key)
            if isinstance(value, list):
                raw_items = value
                break
        else:
            raw_items = [obj]
    else:
        raw_items = []

    messages: list[dict[str, str]] = []
    for raw in raw_items[-3000:]:
        item = raw if isinstance(raw, dict) else _parse_json_text(raw)
        if not isinstance(item, dict):
            continue
        nested = item.get("message")
        if isinstance(nested, dict):
            merged = dict(nested)
            merged.update({k: v for k, v in item.items() if k not in merged})
            item = merged
        role = str(
            item.get("role")
            or item.get("author")
            or item.get("speaker")
            or item.get("type")
            or ""
        )
        if role not in ("user", "assistant", "model", "gemini"):
            continue
        text = _message_text_from_obj(item)
        if text:
            messages.append({"role": "assistant" if role in ("model", "gemini") else role, "content": text[:2000]})
    return messages[-500:]


def _extract_gemini(path: Path) -> list[dict[str, str]]:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    try:
        parsed = json.loads(raw)
    except Exception:
        return _extract_jsonl_messages(path)
    return _messages_from_json_obj(parsed)


def _find_gemini_transcript(payload: dict) -> Path | None:
    payload_path = _payload_transcript_path(payload)
    if payload_path:
        return payload_path
    return _find_transcript(Path.home() / ".gemini", "GEMINI_SESSION_FILE", "**/*.jsonl")



def _opencode_data_dir() -> Path:
    return Path(os.environ.get("OPENCODE_DATA_DIR", str(Path.home() / ".local" / "share" / "opencode")))


def _extract_opencode_part_text(data: dict) -> str:
    part_type = data.get("type")
    if part_type != "text":
        return ""
    return str(data.get("text", "")).strip()


def _extract_opencode_from_db(session_id: str = "") -> list[dict[str, str]]:
    db_path = Path(os.environ.get("OPENCODE_DB", str(_opencode_data_dir() / "opencode.db")))
    if not db_path.exists():
        _log(f"opencode_db_missing path={db_path}")
        return []

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        if not session_id:
            row = conn.execute("SELECT id FROM session ORDER BY time_updated DESC LIMIT 1").fetchone()
            session_id = str(row["id"]) if row else ""
        if not session_id:
            _log("opencode_session_missing")
            return []
        rows = conn.execute(
            """
            SELECT m.id AS message_id, m.data AS message_data, p.data AS part_data
            FROM message m
            LEFT JOIN part p ON p.message_id = m.id
            WHERE m.session_id = ?
            ORDER BY m.time_created ASC, p.time_created ASC
            """,
            (session_id,),
        ).fetchall()
    except Exception as exc:
        _log(f"opencode_db_error type={type(exc).__name__}")
        return []
    finally:
        try:
            conn.close()  # type: ignore[name-defined]
        except Exception:
            pass

    grouped: dict[str, dict[str, object]] = {}
    order: list[str] = []
    for row in rows:
        message_id = str(row["message_id"])
        message = grouped.get(message_id)
        if message is None:
            info = _parse_json_text(row["message_data"])
            message = {"role": str(info.get("role", "")), "parts": []}
            grouped[message_id] = message
            order.append(message_id)
        part_text = _extract_opencode_part_text(_parse_json_text(row["part_data"]))
        if part_text:
            parts = message["parts"]
            if isinstance(parts, list):
                parts.append(part_text)

    messages: list[dict[str, str]] = []
    for message_id in order:
        message = grouped[message_id]
        role = str(message.get("role", ""))
        if role not in ("user", "assistant"):
            continue
        parts = message.get("parts", [])
        text = " ".join(str(part) for part in parts if str(part).strip()).strip()
        if text:
            messages.append({"role": role, "content": text[:2000]})
    if messages:
        _log(f"opencode_transcript session={session_id} messages={len(messages)}")
    return messages[-500:]


def _ingest(messages: list[dict[str, str]], agent_id: str) -> None:
    if not messages:
        _log(f"skip_empty_messages agent={agent_id}")
        return
    try:
        ingest_timeout = float(os.environ.get("MCORE_INGEST_TIMEOUT", "120"))
        _log(f"ingest_start agent={agent_id} messages={len(messages)}")
        headers, _ = _curl_post(
            {
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "mcore-ingest-hook", "version": "1.0"},
                },
            },
            # initialize can be starved while mcore serially processes a
            # concurrent memory_add/ingest (LLM extraction + embedding chain);
            # 5s was too tight and failed the whole write-back.
            timeout=20,
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
                    "arguments": {"messages": messages, "agent_id": agent_id, **_detect_project(agent_id)},
                },
            },
            session_id=session_id,
            timeout=ingest_timeout,
        )
        preview = " ".join(body.split())[:500]
        _log(f"ingest_done agent={agent_id} messages={len(messages)} response={preview}")
    except Exception:
        import traceback

        _log(f"ingest_exception agent={agent_id} tb={traceback.format_exc()[-1500:]}")


def _messages_for_agent(agent: str) -> list[dict[str, str]]:
    if agent == "hermes":
        session_id = _payload_session_id(_hook_payload())
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

    if agent == "opencode":
        session_id = _payload_session_id(_hook_payload())
        return _extract_opencode_from_db(session_id)

    if agent == "gemini":
        path = _find_gemini_transcript(_hook_payload())
        if path:
            messages = _extract_gemini(path)
            _log(f"gemini_transcript path={path} messages={len(messages)}")
            return messages
        _log("gemini_transcript_missing")
        return []

    return []


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest recent agent transcript messages into mcore")
    parser.add_argument("--agent", default=os.environ.get("MCORE_AGENT_ID", "claude"))
    parser.add_argument("--background", action="store_true", help="Spawn ingest in the background and exit immediately")
    parser.add_argument("--force", action="store_true", help="Compatibility flag; Stop ingest always sends the transcript")
    args = parser.parse_args()
    agent = args.agent.strip().lower()
    if args.background and os.environ.get("MCORE_INGEST_BACKGROUND_CHILD") != "1":
        _spawn_background(agent, args.force)
        return
    messages = _messages_for_agent(agent)
    _ingest(messages, agent)


if __name__ == "__main__":
    main()
