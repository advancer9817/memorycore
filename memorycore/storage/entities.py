"""Entity and alias indexing for memory recall."""
from __future__ import annotations

import re
import uuid
from typing import Any

from memorycore.models import as_json, now, row_to_dict
from memorycore.storage.db import managed_conn, read_conn

_ALIAS_GROUPS = [
    ("mcore", ["mcore", "local_memory", "local-memory-mcp", "memorycore", "local memory", "local memory mcp"]),
    ("qdrant", ["qdrant", "vector store", "vector_store"]),
    ("sqlite", ["sqlite", "sqlite3", "memory.sqlite3", "fts5"]),
    ("ollama", ["ollama", "nomic-embed-text", "nomic embed text"]),
    ("mcp", ["mcp", "model context protocol"]),
    ("openmemory", ["openmemory", "open memory", "mem0"]),
]

_ALIAS_TO_CANONICAL: dict[str, str] = {}
_CANONICAL_ALIASES: dict[str, list[str]] = {}


def normalize_entity(value: str) -> str:
    text = (value or "").strip().lower()
    text = text.replace("_", " ").replace("-", " ")
    parts = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", text)
    return " ".join(parts)


for _canonical, _aliases in _ALIAS_GROUPS:
    _norm_canonical = normalize_entity(_canonical)
    _norm_aliases = sorted({normalize_entity(alias) for alias in _aliases if normalize_entity(alias)})
    _CANONICAL_ALIASES[_norm_canonical] = _norm_aliases
    for _alias in _norm_aliases:
        _ALIAS_TO_CANONICAL[_alias] = _norm_canonical


def canonical_entity(value: str) -> str:
    normalized = normalize_entity(value)
    return _ALIAS_TO_CANONICAL.get(normalized, normalized)


def _entity_type(value: str) -> str:
    if value.startswith(("http://", "https://")):
        return "url"
    if value.startswith("/"):
        return "path"
    if re.fullmatch(r"\d{2,5}", value):
        return "port"
    if "." in value and re.search(r"\.(sqlite3?|ya?ml|toml|json|db|py|md)$", value):
        return "file"
    return "concept"


def _weight(entity_type: str) -> float:
    return {
        "path": 1.0,
        "url": 0.95,
        "port": 0.9,
        "file": 0.9,
        "concept": 0.75,
    }.get(entity_type, 0.7)


def extract_entities(text: str, tags: list[str] | None = None) -> list[dict[str, Any]]:
    """Extract deterministic entities and aliases from memory text."""
    source = text or ""
    candidates: list[str] = []
    candidates.extend(re.findall(r"https?://[^\s)'\"<>]+", source))
    candidates.extend(re.findall(r"(?<!\w)/(?:[\w.@+-]+/)*[\w.@+-]+", source))
    candidates.extend(re.findall(r"\b[\w.-]+\.(?:sqlite3?|ya?ml|toml|json|db|py|md)\b", source, flags=re.I))
    candidates.extend(re.findall(r"(?::|port\s+|端口\s*)(\d{2,5})\b", source, flags=re.I))
    candidates.extend(re.findall(r"\b(?:lmmcp|local[_ -]?memory(?:[_ -]?mcp)?|local-memory-mcp|memory\.sqlite3|qdrant|ollama|nomic-embed-text|openmemory|mem0|mcp|fts5)\b", source, flags=re.I))
    candidates.extend(tags or [])

    by_norm: dict[str, dict[str, Any]] = {}
    for raw in candidates:
        raw = str(raw).strip().strip(".,;:)")
        if not raw:
            continue
        normalized = canonical_entity(raw)
        if not normalized:
            continue
        entity_type = _entity_type(raw)
        aliases = _CANONICAL_ALIASES.get(normalized, [normalize_entity(raw)])
        current = by_norm.get(normalized)
        item = {
            "entity": raw,
            "normalized_entity": normalized,
            "aliases": aliases,
            "entity_type": entity_type,
            "weight": _weight(entity_type),
        }
        if current is None or item["weight"] > current["weight"]:
            by_norm[normalized] = item
    return sorted(by_norm.values(), key=lambda item: item["weight"], reverse=True)


def sync_memory_entities(record: dict[str, Any], conn: Any | None = None) -> list[dict[str, Any]]:
    """Replace entity rows for one memory. Non-active records keep no entity rows."""
    memory_id = record["id"]
    metadata = record.get("metadata") or {}
    if record.get("status") != "active":
        if conn is not None:
            conn.execute("DELETE FROM memory_entities WHERE memory_id=?", (memory_id,))
        else:
            with managed_conn() as managed:
                managed.execute("DELETE FROM memory_entities WHERE memory_id=?", (memory_id,))
        return []
    text = f"{record.get('title', '')}\n{record.get('content', '')}"
    if metadata.get("parent_id"):
        text += f"\n{metadata.get('parent_id')}"
    entities = extract_entities(text, record.get("tags") or [])
    ts = now()
    def _write(target_conn: Any) -> None:
        target_conn.execute("DELETE FROM memory_entities WHERE memory_id=?", (memory_id,))
        for entity in entities:
            target_conn.execute(
                """
                INSERT INTO memory_entities (
                  id, memory_id, entity, normalized_entity, aliases_json,
                  entity_type, weight, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(memory_id, normalized_entity) DO UPDATE SET
                  entity=excluded.entity,
                  aliases_json=excluded.aliases_json,
                  entity_type=excluded.entity_type,
                  weight=excluded.weight
                """,
                (
                    str(uuid.uuid4()), memory_id, entity["entity"], entity["normalized_entity"],
                    as_json(entity["aliases"]), entity["entity_type"], entity["weight"], ts,
                ),
            )
    if conn is not None:
        _write(conn)
    else:
        with managed_conn() as managed:
            _write(managed)
    return entities


def entity_search(
    query: str,
    limit: int = 20,
    scope: str = "",
    project_path: str = "",
) -> list[dict[str, Any]]:
    cap = max(1, min(int(limit), 100))
    query_entities = extract_entities(query)
    if not query_entities:
        normalized = canonical_entity(query)
        if normalized:
            query_entities = [{
                "entity": query,
                "normalized_entity": normalized,
                "aliases": _CANONICAL_ALIASES.get(normalized, [normalized]),
                "entity_type": "concept",
                "weight": 0.6,
            }]
    normalized_values = [item["normalized_entity"] for item in query_entities if item["normalized_entity"]]
    if not normalized_values:
        return []
    placeholders = ",".join("?" for _ in normalized_values)
    clauses = [
        f"e.normalized_entity IN ({placeholders})",
        "m.status = 'active'",
        "(m.valid_until IS NULL OR m.valid_until > ?)",
    ]
    params: list[Any] = [*normalized_values, now()]
    if scope:
        clauses.append("(m.scope = ? OR m.scope = 'global')")
        params.append(scope)
    if project_path:
        clauses.append("(m.project_path = ? OR m.project_path = '')")
        params.append(project_path)
    params.append(cap)
    with read_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT
              m.*,
              e.id AS entity_id,
              e.entity AS matched_entity,
              e.normalized_entity AS matched_normalized_entity,
              e.entity_type AS matched_entity_type,
              e.weight AS matched_weight
            FROM memory_entities e
            JOIN memories m ON m.id = e.memory_id
            WHERE {' AND '.join(clauses)}
            ORDER BY e.weight DESC, m.importance DESC, m.updated_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    results: list[dict[str, Any]] = []
    for row in rows:
        record = row_to_dict(row)
        results.append({
            "memory_id": row["id"],
            "entity": row["matched_entity"],
            "normalized_entity": row["matched_normalized_entity"],
            "entity_type": row["matched_entity_type"],
            "weight": float(row["matched_weight"]),
            "memory": record,
            "boost": round(0.12 + min(float(row["matched_weight"]), 1.0) * 0.18, 3),
            "matched_query_entities": normalized_values,
        })
    return results
