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


def cleanup_stale_quality_events(retention_days: int = 30) -> int:
    """Delete context_quality_events older than retention_days. Returns deleted count."""
    import datetime
    cutoff = (local_now() - datetime.timedelta(days=retention_days)).isoformat(timespec="seconds")
    with managed_conn() as conn:
        cursor = conn.execute("DELETE FROM context_quality_events WHERE created_at < ?", (cutoff,))
        return cursor.rowcount if cursor is not None else 0



def _scope_project_clauses(scope: str = "", project_path: str = "", table_prefix: str = "") -> tuple[list[str], list[Any]]:
    """Build SQL clauses and parameters for safe scope and project isolation.

    When project_path is present:
      - scope is empty or 'global': allows global memories and current project memories.
      - specific scope: allows global memories and current project memories under that scope.
    When project_path is empty:
      - falls back to matching requested scope or global.
    """
    prefix = f"{table_prefix}." if table_prefix else ""
    clauses: list[str] = []
    params: list[Any] = []
    if project_path:
        if not scope or scope == "global":
            clauses.append(f"({prefix}scope = 'global' OR ({prefix}scope = 'project' AND ({prefix}project_path = ? OR {prefix}project_path = '')))")
            params.append(project_path)
        else:
            clauses.append(f"({prefix}scope = 'global' OR ({prefix}scope = ? AND ({prefix}project_path = ? OR {prefix}project_path = '')))")
            params.extend([scope, project_path])
    elif scope:
        clauses.append(f"({prefix}scope = ? OR {prefix}scope = 'global')")
        params.append(scope)
    return clauses, params


def _is_greeting(task: str) -> bool:
    return task.strip().lower() in _GREETINGS


def _fallback_candidate_count(scope: str = "", project_path: str = "", limit: int = 8) -> int:
    clauses = ["status = 'active'", "(valid_until IS NULL OR valid_until > ?)"]
    params: list[Any] = [now()]
    sp_clauses, sp_params = _scope_project_clauses(scope=scope, project_path=project_path)
    clauses.extend(sp_clauses)
    params.extend(sp_params)
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
    sp_clauses, sp_params = _scope_project_clauses(scope=scope, project_path=project_path)
    scope_clauses.extend(sp_clauses)
    scope_params.extend(sp_params)
    scope_where = " AND ".join(scope_clauses)

    # --- Fast path: PostgreSQL Trigram + ILIKE query ---
    term_conditions = []
    t_params: list[Any] = []
    for t in terms[:8]:
        term_conditions.append("(m.title ILIKE ? OR m.content ILIKE ? OR similarity(m.title, ?) > 0.15)")
        pat = f"%{t}%"
        t_params.extend([pat, pat, t])
    trgm_where = " OR ".join(term_conditions) if term_conditions else "1=1"
    query_params = t_params + scope_params + [max(1, min(int(limit), 100))]
    try:
        with read_conn() as conn:
            rows = conn.execute(
                f"""SELECT m.* FROM memories m
                    WHERE ({trgm_where})
                      AND {scope_where}
                    ORDER BY importance DESC, effectiveness_score DESC, updated_at DESC
                    LIMIT ?""",
                query_params,
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
        term_conditions = []
        for t in terms[:8]:
            term_conditions.append("(m.title ILIKE ? OR m.content ILIKE ? OR similarity(m.title, ?) > 0.15)")
            pat = f"%{t}%"
            params.extend([pat, pat, t])
        clauses.append("(" + " OR ".join(term_conditions) + ")")
        fts_active = True
    if types_list:
        clauses.append("m.type IN (%s)" % ",".join("?" for _ in types_list))
        params.extend(types_list)
    sp_clauses, sp_params = _scope_project_clauses(scope=scope, project_path=project_path, table_prefix="m")
    clauses.extend(sp_clauses)
    params.extend(sp_params)
    if tags_list:
        clauses.append(
            "EXISTS (SELECT 1 FROM unnest(m.tags) t WHERE lower(t) IN (%s))"
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
    if fts_active:
        sql += (
            " ORDER BY ("
            "similarity(m.title, ?) * 0.4 + m.importance * 0.3 + m.effectiveness_score * 0.2 + m.feedback_score * 0.1"
            ") DESC, m.updated_at DESC"
        )
        params.append(query.strip())
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
        from memorycore.vector_store import get_vector_store
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


from memorycore.storage.context_pack import build_context_pack, _cluster_similar_records  # noqa: E402,F401
