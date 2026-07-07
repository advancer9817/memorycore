"""Fulltext search implementation."""
from __future__ import annotations

import logging
from typing import Any

from memorycore.models import row_to_dict, load_config
from memorycore.storage.db import read_conn, _managed_query
from memorycore.storage.search import (
    _query_terms, _lexical_relevance, _is_cjk_stopword,
    _MIN_KEYWORD_LEXICAL_RELEVANCE_SCORE,
    _keyword_scan_records, _ensure_write_consumer, _write_queue,
)

logger = logging.getLogger(__name__)


def search_memory_records(
    query: str = "",
    types: Any = None,
    scope: str = "",
    project_path: str = "",
    tags: Any = None,
    status: str = "active",
    limit: int = 10,
    date_from: str = "",
    date_to: str = "",
) -> list[dict[str, Any]]:
    types_list = normalize_list(types)
    tags_list = [t.lower() for t in normalize_list(tags)]
    clauses = []
    params: list[Any] = []
    base = "SELECT m.* FROM memories m"
    fts_active = False
    if query.strip():
        raw_tokens = re.findall(r"[\w一-鿿]+", query, flags=re.UNICODE)
        terms: list[str] = []
        for tok in raw_tokens:
            parts = re.split(r"(?<=[一-鿿])(?=[a-zA-Z0-9])|(?<=[a-zA-Z0-9])(?=[一-鿿])", tok)
            terms.extend(parts)
        terms = [t for t in terms if len(t) > 1 or ("一" <= t <= "鿿")]
        terms = [t for t in terms if t.lower() not in _STOP_TERMS and not _is_cjk_stopword(t)]
        if not terms:
            return []
        base += " JOIN memories_fts f ON f.id = m.id"
        # Smart FTS query: short queries use AND, long queries split to avoid zero-hit
        # Expand alphanumeric tokens: phase3 → "phase3" OR "phase 3"
        def _fts_term_variants(term: str) -> str:
            variants = [fts_phrase(term)]
            m = re.match(r"^([a-zA-Z_]+)(\d+)$", term)
            if m:
                spaced = f"{m.group(1)} {m.group(2)}"
                variants.append(fts_phrase(spaced))
            return " OR ".join(variants)

        if len(terms) <= 3:
            connector = " AND " if len(terms) >= 2 else " OR "
            fts_query = connector.join(f"({_fts_term_variants(term)})" for term in terms)
        elif len(terms) <= 6:
            mid = len(terms) // 2
            left = " AND ".join(f"({_fts_term_variants(t)})" for t in terms[:mid])
            right = " AND ".join(f"({_fts_term_variants(t)})" for t in terms[mid:])
            fts_query = f"({left}) OR ({right})"
        else:
            top_terms = terms[:6]
            mid = len(top_terms) // 2
            left = " AND ".join(f"({_fts_term_variants(t)})" for t in top_terms[:mid])
            right = " AND ".join(f"({_fts_term_variants(t)})" for t in top_terms[mid:])
            fts_query = f"({left}) OR ({right})"
        clauses.append("memories_fts MATCH ?")
        params.append(fts_query)
        fts_active = True
    if types_list:
        clauses.append("m.type IN (%s)" % ",".join("?" for _ in types_list))
        params.extend(types_list)
    if scope:
        clauses.append("(m.scope = ? OR m.scope = 'global')")
        params.append(scope)
    if project_path:
        clauses.append("(m.project_path = ? OR m.project_path = '')")
        params.append(project_path)
    if tags_list:
        clauses.append(
            "EXISTS (SELECT 1 FROM json_each(m.tags_json) WHERE lower(json_each.value) IN (%s))"
            % ",".join("?" for _ in tags_list)
        )
        params.extend(tags_list)
    if status:
        clauses.append("m.status = ?")
        params.append(status)
    if date_from:
        clauses.append("m.created_at >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("m.created_at <= ?")
        params.append(date_to)
    clauses.append("(m.valid_until IS NULL OR m.valid_until > ?)")
    params.append(now())
    sql = base
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    # When FTS is active, blend text relevance (rank, lower=better) with importance/effectiveness.
    # rank is negative in FTS5 so we negate it: -rank gives a positive relevance score.
    if fts_active:
        sql += (
            " ORDER BY "
            "(-f.rank * 0.4 + m.importance * 0.3 + m.effectiveness_score * 0.2 + m.feedback_score * 0.1) DESC, "
            "m.updated_at DESC"
        )
    else:
        sql += " ORDER BY m.importance DESC, m.effectiveness_score DESC, m.feedback_score DESC, m.updated_at DESC"
    sql += " LIMIT ?"
    params.append(max(1, min(int(limit), 100)))
    with read_conn() as conn:
        rows = [row_to_dict(r) for r in conn.execute(sql, params).fetchall()]
    if rows:
        ids = [(now(), r["id"]) for r in rows]
        _write_last_accessed(ids)
    return rows


def _write_last_accessed(ids: list[tuple[str, str]]) -> None:
    for ts, mid in ids:
        try:
            _write_queue.put_nowait(("last_accessed", ts, mid))
        except queue.Full:
            pass


def _write_injected_counts(ids: list[str], ts: str) -> None:
    for mid in ids:
        try:
            _write_queue.put_nowait(("injected", ts, mid))
        except queue.Full:
            pass


