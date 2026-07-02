"""FTS5 search, context pack, and active-warning helpers."""
from __future__ import annotations

import atexit
import logging
import queue
import re
import threading
import uuid
from typing import Any

from memorycore.injection_guard import (
    BOUNDARY_NOTICE,
    check_memory_for_injection,
    warning_for_filtered_memory,
)
from memorycore.models import as_json, fts_phrase, load_config, local_now, normalize_list, now, parse_ts, row_to_dict
from memorycore.storage.db import _managed_query, managed_conn, read_conn
from memorycore.storage.entities import entity_search

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared write queue for deferred DB updates (injected_count, last_accessed_at)
# ---------------------------------------------------------------------------
_write_queue: queue.Queue = queue.Queue(maxsize=2000)
_write_queue_started = False
_write_queue_lock = threading.Lock()


def _write_consumer() -> None:
    """Single daemon consumer: drains _write_queue and batch-writes to DB."""
    while True:
        batch: list[tuple] = []
        try:
            item = _write_queue.get(timeout=1.0)
            batch.append(item)
        except queue.Empty:
            continue
        # Drain up to 49 more items without blocking
        while len(batch) < 50:
            try:
                batch.append(_write_queue.get_nowait())
            except queue.Empty:
                break
        _flush_write_batch(batch)


def _flush_write_batch(batch: list[tuple]) -> None:
    """Write a batch of (memory_id, field, value) tuples to DB."""
    if not batch:
        return
    last_accessed: list[tuple[str, str]] = []
    injected: list[tuple[str, str, str]] = []
    for item in batch:
        kind = item[0]
        if kind == "last_accessed":
            _, ts, mid = item
            last_accessed.append((ts, mid))
        elif kind == "injected":
            _, ts, mid = item
            injected.append((ts, ts, mid))
    try:
        if last_accessed or injected:
            with managed_conn() as conn:
                if last_accessed:
                    conn.executemany(
                        "UPDATE memories SET last_accessed_at=? WHERE id=?",
                        last_accessed,
                    )
                if injected:
                    conn.executemany(
                        "UPDATE memories SET injected_count = injected_count + 1,"
                        " last_injected_at = ?, last_accessed_at = ? WHERE id = ?",
                        injected,
                    )
    except Exception:
        logger.warning("write-queue flush: injected_count update failed", exc_info=True)


def _drain_write_queue_on_exit() -> None:
    """atexit handler: flush remaining items (wait up to 2 seconds)."""
    import time
    deadline = time.monotonic() + 2.0
    batch: list[tuple] = []
    while time.monotonic() < deadline:
        try:
            batch.append(_write_queue.get_nowait())
        except queue.Empty:
            break
    _flush_write_batch(batch)


def _ensure_write_consumer() -> None:
    global _write_queue_started
    if _write_queue_started:
        return
    with _write_queue_lock:
        if _write_queue_started:
            return
        t = threading.Thread(target=_write_consumer, daemon=True, name="search-write-consumer")
        t.start()
        atexit.register(_drain_write_queue_on_exit)
        _write_queue_started = True


_ensure_write_consumer()

_GREETINGS = {"hi", "hello", "hey", "你好", "嗯", "好", "ok", "okay", "yes", "no"}
_VECTOR_SEARCH_THRESHOLD = 0.35
_MIN_CONTEXT_RELEVANCE_SCORE = 0.15
_MIN_VECTOR_ONLY_RELEVANCE_SCORE = 0.35
_MIN_KEYWORD_LEXICAL_RELEVANCE_SCORE = 0.08
_STOP_TERMS = {
    "a", "an", "and", "are", "as", "at", "be", "for", "from", "how", "i", "in",
    "is", "it", "of", "on", "or", "that", "the", "this", "to", "with", "you",
}
_CJK_FUNCTIONAL_CHARS = set(
    "的一是在了不有和与及或把给让被到过着对从用以将又也都还就"
    "很太可会能要想得已正才只这那个么什为而且但如所跟比被"
    "吗呢吧啊哦嗯啦呀哈吧嘛"
    "我你他她它们您咱自己"
    "上下来去前后中里外"
    "帮看查找做说问想用需继续使用关于进行实现开始"
)


def _is_cjk_stopword(term: str) -> bool:
    if not term:
        return True
    if all("一" <= c <= "鿿" for c in term):
        if len(term) <= 2 and all(c in _CJK_FUNCTIONAL_CHARS for c in term):
            return True
    return False

_TASK_TYPE_WEIGHTS: dict[str, dict[str, float]] = {
    "feedback": {"feedback": 1.5, "user_profile": 1.2, "project_memory": 0.9},
    "implementation": {"project_memory": 1.4, "decision": 1.2, "feedback": 1.0},
    "debugging": {"feedback": 1.3, "timeline_event": 1.2, "project_memory": 1.1},
    "general": {},
}


def _classify_task(task: str) -> str:
    lowered = task.lower()
    if any(word in lowered for word in ("feedback", "preference", "remember", "correction", "偏好", "反馈")):
        return "feedback"
    if any(word in lowered for word in ("bug", "debug", "error", "fail", "修复", "错误")):
        return "debugging"
    if any(word in lowered for word in ("implement", "build", "feature", "迭代", "实现")):
        return "implementation"
    return "general"


def _type_weights(task_type: str) -> dict[str, float]:
    weights = {"project_memory": 1.0, "feedback": 1.0, "user_profile": 1.0, "decision": 1.0, "timeline_event": 1.0}
    weights.update(_TASK_TYPE_WEIGHTS.get(task_type, {}))
    return weights


def _query_terms(text: str) -> list[str]:
    """Extract relevance terms for lightweight prompt/record lexical scoring."""
    lowered = text.lower()
    terms: list[str] = []
    seen: set[str] = set()

    def add(term: str) -> None:
        term = term.strip().lower()
        if not term or term in seen or term in _STOP_TERMS:
            return
        if len(term) <= 1 and not ("\u4e00" <= term <= "\u9fff"):
            return
        seen.add(term)
        terms.append(term)

    for term in re.findall(r"[a-z0-9_][a-z0-9_.+-]*", lowered):
        add(term)
        m = re.match(r"^([a-z_]+)(\d+)$", term)
        if m:
            add(m.group(1))
            add(m.group(2))

    for span in re.findall(r"[\u4e00-\u9fff]+", lowered):
        if 2 <= len(span) <= 8:
            add(span)
        for width in (3, 2):
            for idx in range(0, max(len(span) - width + 1, 0)):
                gram = span[idx:idx + width]
                if any(char in _CJK_FUNCTIONAL_CHARS for char in gram):
                    continue
                add(gram)

    return terms[:24]


def _lexical_relevance(task: str, record: dict[str, Any]) -> float:
    terms = _query_terms(task)
    if not terms:
        return 0.0
    title = str(record.get("title") or "").lower()
    content = str(record.get("content") or "").lower()
    tags = " ".join(str(t).lower() for t in record.get("tags", []))
    haystack = f"{title} {content} {tags}"
    matched_terms = [term for term in terms if term in haystack]
    matched = len(matched_terms)
    title_matched = sum(1 for term in terms if term in title)
    phrase = task.strip().lower()
    phrase_bonus = 0.15 if len(phrase) >= 4 and phrase in haystack else 0.0
    alphanumeric_phrase_bonus = 0.0
    for m in re.finditer(r"([a-z_]+)(\d+)", phrase):
        spaced = f"{m.group(1)} {m.group(2)}"
        if spaced in haystack or m.group(0) in haystack:
            alphanumeric_phrase_bonus += 0.25
    consecutive_bonus = 0.0
    if matched >= 2:
        for i in range(len(terms) - 1):
            bigram = f"{terms[i]} {terms[i+1]}" if i + 1 < len(terms) else ""
            if bigram and bigram in haystack:
                consecutive_bonus += 0.10
    return min(1.0, (matched / len(terms)) * 0.55 + (title_matched / len(terms)) * 0.20 + phrase_bonus + alphanumeric_phrase_bonus + consecutive_bonus)


def _record_context_quality_event(
    task: str,
    task_type: str,
    agent: str,
    project_path: str,
    scope: str,
    quality: dict[str, Any],
    type_weights: dict[str, float],
) -> None:
    # Throttle: only write when records were actually used (hit_rate > 0)
    if quality.get("used_count", 0) == 0:
        return
    import threading
    params = (
        str(uuid.uuid4()), task, task_type, agent, project_path or "", scope or "global",
        quality["total_candidates"], quality["used_count"], quality["filtered_count"],
        quality["hit_rate"], quality["filter_rate"], quality["ineffective_rate"],
        quality.get("vector_avg_score", 0.0), quality.get("cross_retrieval_rate", 0.0),
        as_json(type_weights), now(),
    )

    def _write():
        try:
            with managed_conn() as conn:
                conn.execute(
                    """
                    INSERT INTO context_quality_events (
                      id, task, task_type, agent, project_path, scope, total_candidates,
                      used_count, filtered_count, hit_rate, filter_rate, ineffective_rate,
                      vector_avg_score, cross_retrieval_rate, type_weights_json, created_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    params,
                )
        except Exception:
            logger.warning("context_quality_events write failed", exc_info=True)

    threading.Thread(target=_write, daemon=True).start()


def get_context_quality_stats(limit: int = 500) -> dict[str, Any]:
    cap = max(1, min(int(limit), 5000))
    with read_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM context_quality_events ORDER BY created_at DESC LIMIT ?",
            (cap,),
        ).fetchall()
    if not rows:
        return {
            "total_packs": 0,
            "avg_hit_rate": 0.0,
            "avg_filter_rate": 0.0,
            "avg_ineffective_rate": 0.0,
            "by_task_type": {},
        }
    by_task_type: dict[str, dict[str, Any]] = {}
    for row in rows:
        task_type = row["task_type"]
        bucket = by_task_type.setdefault(task_type, {"count": 0, "hit_rate": 0.0, "filter_rate": 0.0, "ineffective_rate": 0.0})
        bucket["count"] += 1
        bucket["hit_rate"] += float(row["hit_rate"])
        bucket["filter_rate"] += float(row["filter_rate"])
        bucket["ineffective_rate"] += float(row["ineffective_rate"])
    for bucket in by_task_type.values():
        count = max(bucket["count"], 1)
        bucket["hit_rate"] = round(bucket["hit_rate"] / count, 3)
        bucket["filter_rate"] = round(bucket["filter_rate"] / count, 3)
        bucket["ineffective_rate"] = round(bucket["ineffective_rate"] / count, 3)
    total = len(rows)
    return {
        "total_packs": total,
        "avg_hit_rate": round(sum(float(row["hit_rate"]) for row in rows) / total, 3),
        "avg_filter_rate": round(sum(float(row["filter_rate"]) for row in rows) / total, 3),
        "avg_ineffective_rate": round(sum(float(row["ineffective_rate"]) for row in rows) / total, 3),
        "by_task_type": by_task_type,
    }


def _is_greeting(task: str) -> bool:
    return task.strip().lower() in _GREETINGS


def _fallback_candidate_count(scope: str = "", project_path: str = "", limit: int = 8) -> int:
    clauses = ["status = 'active'", "(valid_until IS NULL OR valid_until > ?)"]
    params: list[Any] = [now()]
    if scope:
        clauses.append("(scope = ? OR scope = 'global')")
        params.append(scope)
    if project_path:
        clauses.append("(project_path = ? OR project_path = '')")
        params.append(project_path)
    params.append(max(1, min(int(limit), 100)))
    with read_conn() as conn:
        rows = conn.execute(
            f"SELECT id FROM memories WHERE {' AND '.join(clauses)} LIMIT ?",
            params,
        ).fetchall()
    return len(rows)


def _keyword_scan_records(
    task: str,
    scope: str = "",
    project_path: str = "",
    limit: int = 40,
) -> list[dict[str, Any]]:
    """Context-only relaxed recall when strict FTS has no hits.

    Tries FTS5 OR-query first (index-accelerated); falls back to LIKE scan only
    when FTS5 returns nothing (e.g. legacy rows missing from index).
    """
    terms = _query_terms(task)
    if not terms:
        return []

    scope_clauses: list[str] = ["status = 'active'", "(valid_until IS NULL OR valid_until > ?)"]
    scope_params: list[Any] = [now()]
    if scope:
        scope_clauses.append("(scope = ? OR scope = 'global')")
        scope_params.append(scope)
    if project_path:
        scope_clauses.append("(project_path = ? OR project_path = '')")
        scope_params.append(project_path)
    scope_where = " AND ".join(scope_clauses)

    # --- Fast path: FTS5 OR query ---
    fts_query = " OR ".join(f'"{t}"' for t in terms[:8])
    fts_params = [fts_query] + scope_params + [max(1, min(int(limit), 100))]
    try:
        with read_conn() as conn:
            rows = conn.execute(
                f"""SELECT m.* FROM memories m
                    JOIN memories_fts f ON f.id = m.id
                    WHERE memories_fts MATCH ?
                      AND {scope_where}
                    ORDER BY importance DESC, effectiveness_score DESC, updated_at DESC
                    LIMIT ?""",
                fts_params,
            ).fetchall()
        records = [row_to_dict(r) for r in rows]
    except Exception:
        records = []

    # --- Slow path: LIKE scan fallback ---
    if not records:
        like_clauses = list(scope_clauses)
        like_params = list(scope_params)
        term_clauses: list[str] = []
        for term in terms[:8]:
            term_clauses.append(
                "(lower(title) LIKE ? OR lower(content) LIKE ? OR lower(tags_json) LIKE ?)"
            )
            like = f"%{term}%"
            like_params.extend([like, like, like])
        if term_clauses:
            like_clauses.append("(" + " OR ".join(term_clauses) + ")")
        like_params.append(max(1, min(int(limit), 100)))
        with read_conn() as conn:
            rows = conn.execute(
                f"""SELECT * FROM memories
                    WHERE {' AND '.join(like_clauses)}
                    ORDER BY importance DESC, effectiveness_score DESC, feedback_score DESC, updated_at DESC
                    LIMIT ?""",
                like_params,
            ).fetchall()
        records = [row_to_dict(row) for row in rows]

    matched = [
        record for record in records
        if _lexical_relevance(task, record) >= _MIN_KEYWORD_LEXICAL_RELEVANCE_SCORE
    ]
    matched.sort(key=lambda record: _lexical_relevance(task, record), reverse=True)
    for record in matched:
        record["_retrieval_sources"] = ["keyword"]
    return matched[:limit]


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


def get_active_warnings(
    memory_ids: list[str],
    min_weight: float = 0.4,
    max_warnings: int = 5,
) -> list[dict[str, Any]]:
    if not memory_ids:
        return []
    placeholders = ",".join("?" for _ in memory_ids)
    sql = f"""
        SELECT
            ml.source_id, ml.target_id, ml.relation_type, ml.weight, ml.note,
            ms.title AS source_title, ms.feedback_score AS source_fb,
            mt.title AS target_title, mt.feedback_score AS target_fb
        FROM memory_links ml
        JOIN memories ms ON ms.id = ml.source_id
        JOIN memories mt ON mt.id = ml.target_id
        WHERE (ml.source_id IN ({placeholders}) OR ml.target_id IN ({placeholders}))
          AND ml.relation_type IN ('contradicts', 'supersedes', 'causes', 'failure_pattern')
          AND ml.weight >= ?
          AND ms.status = 'active'
          AND mt.status = 'active'
        ORDER BY ml.weight DESC
        LIMIT ?
    """
    params = memory_ids + memory_ids + [min_weight, max_warnings * 2]
    rows = _managed_query(sql, params)

    warnings: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        sig = f"{row['source_id']}→{row['target_id']}→{row['relation_type']}"
        if sig in seen:
            continue
        seen.add(sig)
        rel_type = row["relation_type"]
        if rel_type in ("causes", "failure_pattern"):
            severity = "medium"
        else:
            severity = "high" if float(row.get("weight") or 0) >= 0.7 else "medium"
            if float(row.get("target_fb") or 0) < -0.5:
                severity = "high"
        note_part = f" — {row['note']}" if row.get("note") else ""
        warnings.append({
            "source_id": row["source_id"],
            "target_id": row["target_id"],
            "relation_type": row["relation_type"],
            "severity": severity,
            "weight": row["weight"],
            "reason": (
                f"'{row['source_title']}' {row['relation_type']} "
                f"'{row['target_title']}'{note_part}"
            ),
        })
    warnings.sort(key=lambda w: (0 if w["severity"] == "high" else 1, -float(w["weight"])))
    return warnings[:max_warnings]


import time as _time

_VECTOR_SEARCH_CACHE: dict[str, tuple[float, list[tuple[str, float]]]] = {}
_VECTOR_SEARCH_CACHE_TTL = 300.0
_VECTOR_SEARCH_CACHE_MAX = 128

def _vector_search_ids(
    task: str,
    top_k: int = 20,
    score_threshold: float = _VECTOR_SEARCH_THRESHOLD,
) -> list[tuple[str, float]]:
    """Return [(id, score)] from Qdrant semantic search. Empty list if unavailable."""
    cache_key = f"{task}:{top_k}:{score_threshold}"
    now_ts = _time.monotonic()

    if cache_key in _VECTOR_SEARCH_CACHE:
        cached_ts, cached_val = _VECTOR_SEARCH_CACHE[cache_key]
        if now_ts - cached_ts < _VECTOR_SEARCH_CACHE_TTL:
            return cached_val

    try:
        from memorycore.vector_store import get_vector_store, _store
        # If singleton not yet initialized with config, load config now
        if _store is None:
            from memorycore.models import load_config
            vs = get_vector_store(load_config())
        else:
            vs = get_vector_store()

        results_list = []
        if vs.available:
            # Step 4c: Multi-segment query for long tasks
            text_len = len(task.strip())
            if text_len > 200:
                import re
                # Naive splitting on sentence boundaries, up to 3 parts
                segments = [s.strip() for s in re.split(r'[。！？.!?\n]+', task) if len(s.strip()) > 10][:3]
                if not segments:
                    segments = [task]
            else:
                segments = [task]

            best_scores: dict[str, float] = {}
            for seg in segments:
                try:
                    results = vs.search(seg, top_k=top_k, score_threshold=score_threshold)
                    for r in results:
                        best_scores[r.id] = max(best_scores.get(r.id, 0.0), r.score)
                except Exception as ex:
                    logger.debug("segment vector search unavailable: %s", ex)

            results_list = sorted(list(best_scores.items()), key=lambda x: x[1], reverse=True)[:top_k]

        if len(_VECTOR_SEARCH_CACHE) >= _VECTOR_SEARCH_CACHE_MAX:
            # simple clearing instead of full LRU to save complexity
            _VECTOR_SEARCH_CACHE.clear()
        _VECTOR_SEARCH_CACHE[cache_key] = (now_ts, results_list)
        return results_list
    except Exception as exc:
        logger.debug("vector search unavailable: %s", exc)
        return []


def _metadata(record: dict[str, Any]) -> dict[str, Any]:
    metadata = record.get("metadata") or {}
    return metadata if isinstance(metadata, dict) else {}


def _is_atomic_fact(record: dict[str, Any]) -> bool:
    return _metadata(record).get("kind") == "atomic_fact"


def _recency_score(record: dict[str, Any]) -> float:
    """Soft freshness signal for ranking: updated now=1.0, older=decreasing."""
    from memorycore.models import load_config as _lc_s
    updated_at = record.get("updated_at") or record.get("created_at")
    updated = parse_ts(str(updated_at) if updated_at else None)
    age_days = max(0.0, (local_now() - updated.astimezone(local_now().tzinfo)).total_seconds() / 86400)
    if _lc_s().get("temporal", {}).get("enabled", False):
        half_life = float(_lc_s().get("temporal", {}).get("recency_half_life_days", 90))
        import math
        return max(0.0, min(1.0, math.exp(-age_days * math.log(2) / half_life)))
    return max(0.0, min(1.0, 1.0 - age_days / 365.0))


def _parent_id(record: dict[str, Any]) -> str:
    return str(_metadata(record).get("parent_id") or "")


def _auto_feedback_for_used(ids: list[str]) -> None:
    """Auto-positive feedback for memories that were actually injected into context."""
    from memorycore.storage.crud import add_feedback
    for mid in ids:
        try:
            add_feedback(mid, score=0.5, note="auto:injected", source_agent="system")
        except Exception:
            logger.warning("auto feedback write failed for memory %s", mid, exc_info=True)


def _context_recency_weight() -> float:
    from memorycore.models import load_config as _lc_w
    cfg = _lc_w()
    value = (cfg.get("context_pack", {}) or {}).get("recency_weight", 0.05)
    if cfg.get("temporal", {}).get("enabled", False):
        try:
            return max(0.0, min(0.30, float(value) if float(value) > 0.05 else 0.15))
        except Exception:
            return 0.15
    try:
        return max(0.0, min(0.1, float(value)))
    except Exception:
        return 0.05


def build_context_pack(
    task: str,
    agent: str = "agent",
    project_path: str = "",
    scope: str = "global",
    token_budget: int = 2000,
    retrieval_mode: str = "strict",
    prefer_atomic: bool = True,
    include_parent: bool = False,
) -> dict[str, Any]:
    max_chars = max(800, int(token_budget) * 4)
    mode = str(retrieval_mode or "strict").strip().lower()
    if mode not in {"strict", "balanced", "recall"}:
        mode = "strict"
    mode_settings = {
        "strict": {
            "vector_top_k": 30,
            "entity_limit": 30,
            "min_context_score": _MIN_CONTEXT_RELEVANCE_SCORE,
            "min_vector_only_score": _MIN_VECTOR_ONLY_RELEVANCE_SCORE,
            "vector_search_threshold": 0.32,
        },
        "balanced": {
            "vector_top_k": 30,
            "entity_limit": 40,
            "min_context_score": 0.18,
            "min_vector_only_score": 0.42,
            "vector_search_threshold": 0.35,
        },
        "recall": {
            "vector_top_k": 50,
            "entity_limit": 60,
            "min_context_score": 0.14,
            "min_vector_only_score": 0.36,
            "vector_search_threshold": 0.25,
        },
    }[mode]

    # --- Hybrid retrieval: FTS5 + Qdrant vector search + entity aliases (concurrent) ---
    import concurrent.futures as _cf

    # Quick check if vector store is likely available (for FTS compensation)
    vs_available_hint = False
    try:
        from memorycore.vector_store import get_vector_store as _gvs_hint
        _vs_hint = _gvs_hint()
        vs_available_hint = getattr(_vs_hint, "available", False)
    except Exception:
        pass

    def _fetch_fts():
        fts_limit = 40
        if not vs_available_hint:
            fts_limit = 60
        rows = search_memory_records(task, scope=scope, project_path=project_path, status="active", limit=fts_limit)
        if not rows:
            rows = search_memory_records(task, scope=scope, project_path=project_path, status="candidate", limit=20)
        else:
            candidate_rows = search_memory_records(task, scope=scope, project_path=project_path, status="candidate", limit=10)
            rows.extend(candidate_rows)
        if not rows:
            rows = _keyword_scan_records(task, scope=scope, project_path=project_path, limit=40)
        return rows

    def _fetch_vector():
        try:
            return dict(_vector_search_ids(task, top_k=mode_settings["vector_top_k"], score_threshold=mode_settings["vector_search_threshold"]))
        except Exception:
            return {}

    def _fetch_entity():
        return entity_search(task, limit=mode_settings["entity_limit"], scope=scope, project_path=project_path)

    with _cf.ThreadPoolExecutor(max_workers=3) as _pool:
        _fts_fut = _pool.submit(_fetch_fts)
        _vec_fut = _pool.submit(_fetch_vector)
        _ent_fut = _pool.submit(_fetch_entity)
        fts_records: list[dict[str, Any]] = _fts_fut.result()
        vector_hits: dict[str, float] = _vec_fut.result()
        entity_hits = _ent_fut.result()

    from memorycore.vector_store import get_vector_store
    vs_available = False
    vs = None
    try:
        vs = get_vector_store()
        vs_available = getattr(vs, "available", False)
    except Exception:
        pass

    entity_boosts: dict[str, float] = {}
    for record in fts_records:
        record["_retrieval_sources"] = record.get("_retrieval_sources") or ["fts"]
        if record["id"] in vector_hits:
            record["_retrieval_sources"].append("vector")

    # Merge: start with FTS results, append any vector-only hits fetched from DB
    seen_ids: set[str] = {r["id"] for r in fts_records}
    extra_ids = [mid for mid in vector_hits if mid not in seen_ids]
    extra_records: list[dict[str, Any]] = []
    if extra_ids:
        with read_conn() as conn:
            placeholders = ",".join("?" for _ in extra_ids)
            extra_clauses = [
                f"id IN ({placeholders})",
                "status IN ('active', 'candidate')",
                "(valid_until IS NULL OR valid_until > ?)",
            ]
            extra_params: list[Any] = [*extra_ids, now()]
            if scope:
                extra_clauses.append("(scope = ? OR scope = 'global')")
                extra_params.append(scope)
            if project_path:
                extra_clauses.append("(project_path = ? OR project_path = '')")
                extra_params.append(project_path)
            rows = conn.execute(
                f"SELECT * FROM memories WHERE {' AND '.join(extra_clauses)}",
                extra_params,
            ).fetchall()
            extra_records = [row_to_dict(r) for r in rows]
            for record in extra_records:
                record["_retrieval_sources"] = ["vector"]

    records = fts_records + extra_records
    records_by_id = {record["id"]: record for record in records}
    for hit in entity_hits:
        memory_id = str(hit.get("memory_id") or "")
        if not memory_id:
            continue
        entity_boosts[memory_id] = max(entity_boosts.get(memory_id, 0.0), float(hit.get("boost") or 0.0))
        record = records_by_id.get(memory_id)
        if record is None:
            record = dict(hit["memory"])
            record["_retrieval_sources"] = ["entity"]
            records.append(record)
            records_by_id[memory_id] = record
        else:
            sources = record.get("_retrieval_sources") or []
            if "entity" not in sources:
                sources.append("entity")
            record["_retrieval_sources"] = sources
        matches = record.setdefault("_entity_matches", [])
        matches.append({
            "entity": hit.get("entity"),
            "normalized_entity": hit.get("normalized_entity"),
            "entity_type": hit.get("entity_type"),
            "weight": hit.get("weight"),
        })

    # Unified re-ranking.  Relevance evidence dominates; type weighting is a
    # small multiplier so generic high-priority memories cannot outrank clearly
    # task-matching records.
    recency_weight = _context_recency_weight()

    def _rank_score(r: dict[str, Any]) -> float:
        lexical_score = _lexical_relevance(task, r)
        sources = r.get("_retrieval_sources", [])
        text_matched = "fts" in sources or "keyword" in sources
        vector_score = vector_hits.get(r["id"], 0.0)
        lexical = lexical_score if text_matched else 0.0

        source_bonus = 0.08 if text_matched else 0.0
        source_bonus += 0.06 if "entity" in sources else 0.0
        multi_source_bonus = 0.12 if ("fts" in sources and "vector" in sources) else 0.0
        source_bonus += multi_source_bonus

        high_lexical_bonus = 0.15 if lexical >= 0.5 else 0.0

        parent_penalty = -0.05 if prefer_atomic and not include_parent and _metadata(r).get("kind") == "parent_memory" else 0.0
        candidate_discount = 0.85 if r.get("status") == "candidate" else 1.0
        feedback = max(-1.0, min(1.0, float(r.get("feedback_score") or 0)))
        usage_rate = min(1.0, float(r.get("injected_count") or 0) / 10.0)

        return max(
            0.0,
            (vector_score * 0.30
            + lexical * 0.26
            + entity_boosts.get(r["id"], 0.0)
            + source_bonus
            + high_lexical_bonus
            + parent_penalty
            + float(r.get("importance") or 0) * 0.05
            + usage_rate * 0.08
            + float(r.get("effectiveness_score") or 0) * 0.04
            + feedback * 0.03
            + _recency_score(r) * recency_weight)
            * candidate_discount
        )

    fallback_used = False
    fallback_candidates = 0
    if not records and len(task.strip()) > 10 and not _is_greeting(task):
        fallback_candidates = _fallback_candidate_count(scope=scope, project_path=project_path, limit=8)
        fallback_used = bool(fallback_candidates)
        records = []
    task_type = _classify_task(task)
    type_weights = _type_weights(task_type)
    scored_records: list[tuple[dict[str, Any], float]] = []
    for record in records:
        score = _rank_score(record)
        sources = record.get("_retrieval_sources", [])
        lexical = _lexical_relevance(task, record)
        if "keyword" in sources and lexical < _MIN_KEYWORD_LEXICAL_RELEVANCE_SCORE:
            continue
        is_vector_only = sources == ["vector"]
        min_score = (
            mode_settings["min_vector_only_score"]
            if is_vector_only
            else mode_settings["min_context_score"]
        )
        if is_vector_only and vector_hits.get(record["id"], 0.0) < min_score:
            continue
        if score >= min_score:
            scored_records.append((record, score))
    records = [record for record, _ in sorted(
        scored_records,
        key=lambda item: (
            item[1] * float(type_weights.get(item[0].get("type"), 1.0)),
            _recency_score(item[0]) * recency_weight,
            item[0].get("updated_at") or item[0].get("created_at") or "" if recency_weight > 0 else "",
        ),
        reverse=True,
    )]
    if prefer_atomic:
        child_parent_ids = {_parent_id(record) for record in records if _is_atomic_fact(record) and _parent_id(record)}
        child_counts: dict[str, int] = {}
        pruned: list[dict[str, Any]] = []
        for record in records:
            parent_id = _parent_id(record)
            if parent_id:
                if child_counts.get(parent_id, 0) >= 3:
                    continue
                child_counts[parent_id] = child_counts.get(parent_id, 0) + 1
                pruned.append(record)
                continue
            if not include_parent and record["id"] in child_parent_ids:
                continue
            pruned.append(record)
        records = pruned
    # Optional: cluster highly similar records to save token budget
    from memorycore.models import load_config
    cfg = load_config()
    cp_cfg = cfg.get("context_pack", {})
    cluster_enabled = cp_cfg.get("cluster_enabled", True)
    cluster_threshold = cp_cfg.get("cluster_similarity_threshold", 0.85)
    clustered_count = 0
    cluster_groups = 0

    if cluster_enabled and vs_available and len(records) >= 3:
        records, clustered_count, cluster_groups = _cluster_similar_records(vs, records, cluster_threshold)

    groups_order = [
        "skill_candidate", "user_profile", "environment_fact", "agent_architecture",
        "project_memory", "decision", "timeline_event", "episodic_memory", "feedback",
    ]
    # Global rank-sorted output: records are already sorted by _rank_score.
    # Apply per-type cap (max 6 each) but output in rank order, not type order.
    type_counts: dict[str, int] = {}
    rank_capped: list[dict[str, Any]] = []
    for r in records:
        t = r.get("type", "episodic_memory")
        type_counts[t] = type_counts.get(t, 0) + 1
        if t == "episodic_memory" and type_counts[t] > 4:
            continue
        if type_counts[t] > 6:
            continue
        rank_capped.append(r)

    grouped: dict[str, list[dict[str, Any]]] = {k: [] for k in groups_order}
    for r in rank_capped:
        grouped.setdefault(r.get("type", "episodic_memory"), []).append(r)
    # Output: sorted by rank_score across all types, with type labels inline
    lines = [
        f"# memory_context for {agent}",
        f"task: {task}",
        f"scope: {scope}",
        f"project_path: {project_path or '(none)'}",
        f"safety: {BOUNDARY_NOTICE}",
        "",
    ]
    used_ids: list[str] = []
    filtered_ids: list[str] = []
    injection_warnings: list[dict[str, Any]] = []
    current_type = ""
    for item in rank_capped:
        check = check_memory_for_injection(item)
        if check.is_high_risk:
            filtered_ids.append(item["id"])
            injection_warnings.append(warning_for_filtered_memory(item, check))
            continue
        item_type = item.get("type", "episodic_memory")
        if item_type != current_type:
            lines.append(f"## {item_type}")
            current_type = item_type
        snippet = item["content"].replace("\n", " ")
        if len(snippet) > 420:
            snippet = snippet[:417] + "..."
        candidate_line = f"- [{item['id']}] {item['title']}: {snippet}"
        test_text = "\n".join(lines + [candidate_line])
        if len(test_text) > max_chars:
            break
        lines.append(candidate_line)
        used_ids.append(item["id"])
    text = "\n".join(lines).strip()
    if used_ids:
        ts = now()
        ids_snapshot = list(used_ids)
        _write_injected_counts(ids_snapshot, ts)
        _auto_feedback_for_used(ids_snapshot)
    active_count = sum(1 for r in records if r["status"] == "active")
    warnings = (get_active_warnings(used_ids) if used_ids else []) + injection_warnings
    hit_rate = round(len(used_ids) / max(len(records), 1), 3)
    filter_rate = round(len(filtered_ids) / max(len(records), 1), 3)
    ineffective_rate = round(
        sum(1 for r in records if float(r.get("ineffective_count") or 0) > 0) / max(len(records), 1),
        3,
    )
    vector_only_count = 0
    fts_only_count = 0
    cross_retrieval_count = 0
    vector_scores = []
    used_id_set = set(used_ids)

    for r in records:
        if r["id"] not in used_id_set:
            continue
        srcs = r.get("_retrieval_sources", [])
        if "vector" in srcs:
            vector_scores.append(vector_hits.get(r["id"], 0.0))
            if "fts" in srcs or "keyword" in srcs:
                cross_retrieval_count += 1
            else:
                vector_only_count += 1
        elif "fts" in srcs or "keyword" in srcs:
            fts_only_count += 1

    vector_avg_score = sum(vector_scores) / max(len(vector_scores), 1) if vector_scores else 0.0
    vector_max_score = max(vector_scores) if vector_scores else 0.0
    cross_retrieval_rate = cross_retrieval_count / max(len(used_ids), 1)

    quality = {
        "total_candidates": len(records),
        "used_count": len(used_ids),
        "filtered_count": len(filtered_ids),
        "active_ratio": round(active_count / max(len(records), 1), 3),
        "avg_importance": round(sum(r["importance"] for r in records) / max(len(records), 1), 3),
        "stale_in_results": sum(1 for r in records if r["status"] == "stale"),
        "estimated_tokens": len(text) // 4,
        "hit_rate": hit_rate,
        "filter_rate": filter_rate,
        "ineffective_rate": ineffective_rate,
        "vector_avg_score": round(vector_avg_score, 3),
        "cross_retrieval_rate": round(cross_retrieval_rate, 3),
    }
    _record_context_quality_event(task, task_type, agent, project_path, scope, quality, type_weights)
    used_record_map = {r["id"]: r for r in records if r["id"] in used_id_set}
    # records: slim view of injected records only (no content field to avoid bloat)
    slim_records = [
        {
            "id": r["id"],
            "type": r["type"],
            "title": r["title"],
            "importance": r["importance"],
            "scope": r["scope"],
            "tags": r.get("tags", []),
            "_retrieval_sources": r.get("_retrieval_sources", []),
            "_vector_score": vector_hits.get(r["id"], 0.0),
        }
        for mid in used_ids
        if (r := used_record_map.get(mid))
    ]
    sections: list[dict[str, Any]] = []
    for group in groups_order:
        group_records = [r for r in grouped.get(group, []) if r["id"] in used_id_set]
        if group_records:
            sections.append({"type": group, "records": [
                {"id": r["id"], "title": r["title"], "importance": r["importance"]}
                for r in group_records
            ]})
    return {
        "context": text,
        "records": slim_records,
        "used_ids": used_ids,
        "filtered_ids": filtered_ids,
        "warnings": warnings,
        "budget_chars": max_chars,
        "quality": quality,
        "sections": sections,
        "trace": {
            "total_candidates": len(records),
            "used_count": len(used_ids),
            "filtered_count": len(filtered_ids),
            "fallback_used": fallback_used,
            "fallback_candidates": fallback_candidates,
            "vector_hits": len(vector_hits),
            "entity_hits": len(entity_hits),
            "vector_avg_score": round(vector_avg_score, 3),
            "vector_max_score": round(vector_max_score, 3),
            "cross_retrieval_count": cross_retrieval_count,
            "vector_only_count": vector_only_count,
            "fts_only_count": fts_only_count,
            "clustered_count": clustered_count,
            "cluster_groups": cluster_groups,
            "vector_fallback": not vs_available,
            "retrieval_mode": mode,
            "prefer_atomic": prefer_atomic,
            "include_parent": include_parent,
            "min_relevance_score": mode_settings["min_context_score"],
            "min_vector_only_relevance_score": mode_settings["min_vector_only_score"],
            "min_keyword_lexical_relevance_score": _MIN_KEYWORD_LEXICAL_RELEVANCE_SCORE,
            "task_type": task_type,
            "type_weights": type_weights,
        },
    }
import math
from typing import Any

def _cluster_similar_records(
    vs: Any,
    records: list[dict[str, Any]],
    threshold: float
) -> tuple[list[dict[str, Any]], int, int]:
    if not records or not getattr(vs, "_client", None):
        return records, 0, 0

    try:
        from qdrant_client.models import PointIdsList
        client = vs._client
        collection = vs.config.collection

        # Get vectors for all records
        ids = [r["id"] for r in records]
        points = client.retrieve(
            collection_name=collection,
            ids=ids,
            with_vectors=True,
            with_payload=False
        )

        # Map id to vector
        vec_map = {}
        for p in points:
            if hasattr(p, "vector") and p.vector is not None:
                vec_map[str(p.id)] = p.vector

        def cos_sim(v1, v2):
            dot = sum(a*b for a, b in zip(v1, v2))
            norm1 = math.sqrt(sum(a*a for a in v1))
            norm2 = math.sqrt(sum(b*b for b in v2))
            if norm1 == 0 or norm2 == 0: return 0.0
            return dot / (norm1 * norm2)

        clustered = []
        skip_ids = set()
        clustered_count = 0
        cluster_groups = 0

        for i, r1 in enumerate(records):
            id1 = r1["id"]
            if id1 in skip_ids:
                continue

            cluster_buddies = []
            if id1 in vec_map:
                v1 = vec_map[id1]
                for j in range(i + 1, len(records)):
                    r2 = records[j]
                    id2 = r2["id"]
                    if id2 in skip_ids:
                        continue
                    if id2 in vec_map:
                        sim = cos_sim(v1, vec_map[id2])
                        if sim >= threshold:
                            cluster_buddies.append(r2)
                            skip_ids.add(id2)

            if cluster_buddies:
                cluster_groups += 1
                clustered_count += len(cluster_buddies)
                r1["_clustered_ids"] = [b["id"] for b in cluster_buddies]
            clustered.append(r1)

        return clustered, clustered_count, cluster_groups

    except Exception:
        return records, 0, 0
