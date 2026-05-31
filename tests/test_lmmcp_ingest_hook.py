from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOOK_PATH = ROOT / "scripts" / "hooks" / "lmmcp-ingest.py"


def _load_hook():
    spec = importlib.util.spec_from_file_location("lmmcp_ingest_hook", HOOK_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_extract_opencode_from_sqlite_db(tmp_path, monkeypatch):
    hook = _load_hook()
    db = tmp_path / "opencode.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE session (
          id TEXT PRIMARY KEY,
          time_updated INTEGER NOT NULL
        );
        CREATE TABLE message (
          id TEXT PRIMARY KEY,
          session_id TEXT NOT NULL,
          time_created INTEGER NOT NULL,
          data TEXT NOT NULL
        );
        CREATE TABLE part (
          id TEXT PRIMARY KEY,
          message_id TEXT NOT NULL,
          session_id TEXT NOT NULL,
          time_created INTEGER NOT NULL,
          data TEXT NOT NULL
        );
        """
    )
    conn.execute("INSERT INTO session VALUES (?, ?)", ("ses-new", 20))
    conn.execute(
        "INSERT INTO message VALUES (?, ?, ?, ?)",
        ("msg-user", "ses-new", 1, json.dumps({"role": "user"})),
    )
    conn.execute(
        "INSERT INTO part VALUES (?, ?, ?, ?, ?)",
        ("part-user", "msg-user", "ses-new", 1, json.dumps({"type": "text", "text": "请记住这个 opencode 测试偏好"})),
    )
    conn.execute(
        "INSERT INTO message VALUES (?, ?, ?, ?)",
        ("msg-assistant", "ses-new", 2, json.dumps({"role": "assistant"})),
    )
    conn.execute(
        "INSERT INTO part VALUES (?, ?, ?, ?, ?)",
        ("part-tool", "msg-assistant", "ses-new", 2, json.dumps({"type": "tool", "output": "ignore me"})),
    )
    conn.execute(
        "INSERT INTO part VALUES (?, ?, ?, ?, ?)",
        ("part-assistant", "msg-assistant", "ses-new", 3, json.dumps({"type": "text", "text": "已记录并会写回 lmmcp"})),
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("OPENCODE_DB", str(db))

    messages = hook._extract_opencode_from_db("ses-new")

    assert messages == [
        {"role": "user", "content": "请记住这个 opencode 测试偏好"},
        {"role": "assistant", "content": "已记录并会写回 lmmcp"},
    ]


def test_generic_jsonl_extractor_supports_gemini_model_role(tmp_path):
    hook = _load_hook()
    transcript = tmp_path / "gemini.jsonl"
    transcript.write_text(
        "\n".join(
            [
                json.dumps({"role": "user", "content": "用户的问题"}),
                json.dumps({"role": "model", "content": "模型回答"}),
            ]
        ),
        encoding="utf-8",
    )

    assert hook._extract_gemini(transcript) == [
        {"role": "user", "content": "用户的问题"},
        {"role": "assistant", "content": "模型回答"},
    ]


def test_gemini_json_transcript_and_hook_payload_path(tmp_path, monkeypatch):
    hook = _load_hook()
    transcript = tmp_path / "gemini-transcript.json"
    transcript.write_text(
        json.dumps(
            {
                "messages": [
                    {"role": "user", "parts": [{"text": "Gemini 用户提示"}]},
                    {"role": "model", "parts": [{"text": "Gemini 模型回答"}]},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LMMCP_INGEST_HOOK_PAYLOAD", json.dumps({"transcript_path": str(transcript)}))

    assert hook._messages_for_agent("gemini") == [
        {"role": "user", "content": "Gemini 用户提示"},
        {"role": "assistant", "content": "Gemini 模型回答"},
    ]
