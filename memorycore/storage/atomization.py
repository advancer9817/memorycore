"""Rule-based parent/child memory atomization."""
from __future__ import annotations

import hashlib
import json
import re
import threading
from typing import Any, Callable

_atomize_lock = threading.Lock()

from memorycore.models import as_json, now, row_to_dict
from memorycore.storage.db import managed_conn, read_conn
from memorycore.storage.links import add_link

ATOMIZER_VERSION = "mem0-inspired-v1"

AddMemoryFn = Callable[..., dict[str, Any]]

_SIGNAL_RE = re.compile(
    r"(/[\w.@+-]+(?:/[\w.@+-]+)*|https?://|:\d{2,5}\b|\b\d{2,5}\b|"
    r"\b(?:lmmcp|local[_ -]?memory(?:[_ -]?mcp)?|local-memory-mcp|memory\.sqlite3|"
    r"qdrant|ollama|nomic-embed-text|mcp|sqlite|fts5|service|endpoint|"
    r"config|pyproject|docker|systemd|数据库|端口|路径|服务)\b)",
    re.I,
)


def _metadata(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("metadata") or {}
    return value if isinstance(value, dict) else {}


def _normalize_fact(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def fact_hash(parent_id: str, fact: str) -> str:
    return hashlib.sha256(f"{parent_id}:{_normalize_fact(fact)}".encode()).hexdigest()


def is_atomic_fact(record: dict[str, Any]) -> bool:
    return _metadata(record).get("kind") == "atomic_fact"


def should_atomize(record: dict[str, Any], atomize: str | bool = "auto", min_chars: int = 600) -> bool:
    """Return True if the record should be split into atomic facts (rule-based path).

    Note on thresholds: this function uses min_chars=600 as its default for the
    rule-based splitting path.  The LLM-driven splitting path in curator_llm.py
    uses _SPLIT_CONTENT_THRESHOLD=400.  The two paths are intentionally separate:
    the LLM path is more aggressive because it can judge content quality; this
    rule-based path requires a higher character count to reduce false positives.
    """
    if atomize is False or str(atomize).lower() in {"false", "0", "no", "off"}:
        return False
    if is_atomic_fact(record):
        return False
    content = str(record.get("content") or "")
    if atomize is True or str(atomize).lower() in {"true", "1", "yes", "on"}:
        return bool(content.strip())
    if len(content) >= int(min_chars):
        return True
    lines = [line for line in content.splitlines() if line.strip()]
    if len(lines) >= 6:
        return True
    sentences = [s for s in re.split(r"[。.!?\n]", content) if len(s.strip()) > 20]
    return len(sentences) >= 3


def _candidate_spans(content: str) -> list[tuple[str, int, int]]:
    spans: list[tuple[str, int, int]] = []
    for match in re.finditer(r"(?m)^\s*(?:[-*]|\d+[.)])?\s*(.+?)\s*$", content):
        text = match.group(1).strip()
        if text:
            spans.append((text, match.start(1), match.end(1)))
    if len(spans) <= 1:
        spans = []
        for match in re.finditer(r"[^。.!?\n]+[。.!?]?", content):
            text = match.group(0).strip()
            if text:
                spans.append((text, match.start(), match.end()))
    return spans


def plan_child_facts(
    record: dict[str, Any],
    min_chars: int = 600,
    max_facts: int = 12,
    atomize: str | bool = "auto",
) -> list[dict[str, Any]]:
    if not should_atomize(record, atomize, min_chars=min_chars):
        return []
    content = str(record.get("content") or "")
    parent_id = record["id"]
    planned: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    for text, start, end in _candidate_spans(content):
        text = re.sub(r"\s+", " ", text).strip(" -\t")
        if len(text) < 24 or len(text) > 520:
            continue
        if not re.search(r"[一-鿿\w]{4,}", text):
            continue
        h = fact_hash(parent_id, text)
        if h in seen_hashes:
            continue
        seen_hashes.add(h)
        title = text[:88].rstrip()
        if len(text) > 88:
            title += "..."
        planned.append({
            "title": title,
            "content": text,
            "metadata": {
                "kind": "atomic_fact",
                "parent_id": parent_id,
                "fact_hash": h,
                "source_span": {"start": start, "end": end},
                "atomizer_version": ATOMIZER_VERSION,
                "source_type": "parent_memory",
            },
            "fact_hash": h,
        })
        if len(planned) >= max_facts:
            break
    return planned


def _existing_fact_hashes(parent_id: str, hashes: list[str]) -> set[str]:
    if not hashes:
        return set()
    placeholders = ",".join("?" for _ in hashes)
    with read_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT metadata_json FROM memories
            WHERE json_extract(metadata_json, '$.parent_id') = ?
              AND json_extract(metadata_json, '$.fact_hash') IN ({placeholders})
            """,
            [parent_id, *hashes],
        ).fetchall()
    existing: set[str] = set()
    for row in rows:
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
            if metadata.get("fact_hash"):
                existing.add(str(metadata["fact_hash"]))
        except Exception:
            continue
    return existing


def atomize_record(
    record_id: str,
    dry_run: bool = True,
    min_chars: int = 600,
    atomize: str | bool = "auto",
    add_memory_fn: AddMemoryFn | None = None,
    conn=None,
) -> dict[str, Any]:
    with _atomize_lock:
        return _atomize_record_impl(
            record_id=record_id,
            dry_run=dry_run,
            min_chars=min_chars,
            atomize=atomize,
            add_memory_fn=add_memory_fn,
            conn=conn,
        )


def _atomize_record_impl(
    record_id: str,
    dry_run: bool = True,
    min_chars: int = 600,
    atomize: str | bool = "auto",
    add_memory_fn: AddMemoryFn | None = None,
    conn=None,
) -> dict[str, Any]:
    with managed_conn() as _conn:
        row = _conn.execute("SELECT * FROM memories WHERE id=?", (record_id,)).fetchone()
    if row is None:
        return {"record_id": record_id, "error": "memory_not_found", "planned": 0, "created": 0}
    record = row_to_dict(row)
    facts = plan_child_facts(record, min_chars=min_chars, atomize=atomize)
    existing = _existing_fact_hashes(record_id, [fact["fact_hash"] for fact in facts])
    new_facts = [fact for fact in facts if fact["fact_hash"] not in existing]
    result: dict[str, Any] = {
        "record_id": record_id,
        "dry_run": dry_run,
        "planned": len(new_facts),
        "duplicates": len(facts) - len(new_facts),
        "facts": new_facts,
        "created": 0,
        "links_created": 0,
    }
    if dry_run or not new_facts:
        return result
    if add_memory_fn is None:
        from memorycore.storage.crud import add_memory_record as add_memory_fn

    child_ids: list[str] = []
    for fact in new_facts:
        child = add_memory_fn(
            record.get("type", "project_memory"),
            fact["title"],
            fact["content"],
            scope=record.get("scope", "global"),
            tags=list(dict.fromkeys([*(record.get("tags") or []), "atomic_fact"])),
            source="atomizer",
            source_agent=record.get("source_agent") or "atomizer",
            project_path=record.get("project_path") or "",
            confidence=record.get("confidence", 0.7),
            importance=min(1.0, float(record.get("importance") or 0.5) + 0.05),
            status=record.get("status", "active"),
            decay_policy=record.get("decay_policy", "review"),
            related_ids=[record_id],
            metadata=fact["metadata"],
            valid_from=record.get("valid_from"),
            valid_until=record.get("valid_until"),
            atomize=False,
        )
        child_ids.append(child["id"])
        add_link(child["id"], record_id, "part_of", weight=1.0, note="atomic fact of parent", source_agent="atomizer")
        add_link(record_id, child["id"], "supports", weight=0.8, note="parent supports atomic fact", source_agent="atomizer")

    parent_metadata = dict(_metadata(record))
    parent_metadata.update({
        "kind": parent_metadata.get("kind", "parent_memory"),
        "atomized_at": now(),
        "atomizer_version": ATOMIZER_VERSION,
        "child_count": int(parent_metadata.get("child_count") or 0) + len(child_ids),
    })
    if conn is not None:
        # Caller manages the transaction; do not commit here
        conn.execute(
            "UPDATE memories SET metadata_json=?, updated_at=? WHERE id=?",
            (as_json(parent_metadata), now(), record_id),
        )
        updated_row = conn.execute("SELECT * FROM memories WHERE id=?", (record_id,)).fetchone()
    else:
        with managed_conn() as _conn:
            _conn.execute(
                "UPDATE memories SET metadata_json=?, updated_at=? WHERE id=?",
                (as_json(parent_metadata), now(), record_id),
            )
            updated_row = _conn.execute("SELECT * FROM memories WHERE id=?", (record_id,)).fetchone()
    if updated_row is not None:
        try:
            from memorycore.storage.entities import sync_memory_entities

            sync_memory_entities(row_to_dict(updated_row))
        except Exception:
            pass
    result["created"] = len(child_ids)
    result["links_created"] = len(child_ids) * 2
    result["child_ids"] = child_ids
    return result


def atomize_report(
    record_id: str = "",
    dry_run: bool = True,
    limit: int = 100,
    min_chars: int = 600,
) -> dict[str, Any]:
    cap = max(1, min(int(limit), 500))
    if record_id:
        ids = [record_id]
    else:
        with managed_conn() as conn:
            rows = conn.execute(
                """
                SELECT id FROM memories
                WHERE status = 'active'
                  AND length(content) >= ?
                  AND COALESCE(json_extract(metadata_json, '$.kind'), '') != 'atomic_fact'
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (int(min_chars), cap),
            ).fetchall()
        ids = [row["id"] for row in rows]
    if dry_run:
        records = [atomize_record(mid, dry_run=dry_run, min_chars=min_chars) for mid in ids]
    else:
        with managed_conn() as shared_conn:
            records = [
                atomize_record(mid, dry_run=False, min_chars=min_chars, conn=shared_conn)
                for mid in ids
            ]
    return {
        "dry_run": dry_run,
        "limit": cap,
        "min_chars": int(min_chars),
        "records": records,
        "planned": sum(int(item.get("planned") or 0) for item in records),
        "created": sum(int(item.get("created") or 0) for item in records),
        "duplicates": sum(int(item.get("duplicates") or 0) for item in records),
        "links_created": sum(int(item.get("links_created") or 0) for item in records),
    }
