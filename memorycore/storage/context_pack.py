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

from memorycore.storage import search as _search

logger = logging.getLogger(__name__)

_MIN_CONTEXT_RELEVANCE_SCORE = _search._MIN_CONTEXT_RELEVANCE_SCORE
_MIN_VECTOR_ONLY_RELEVANCE_SCORE = _search._MIN_VECTOR_ONLY_RELEVANCE_SCORE
_MIN_KEYWORD_LEXICAL_RELEVANCE_SCORE = _search._MIN_KEYWORD_LEXICAL_RELEVANCE_SCORE


def _search_memory_records(*args, **kwargs):
    return _search.search_memory_records(*args, **kwargs)


def _keyword_records(*args, **kwargs):
    return _search._keyword_scan_records(*args, **kwargs)


def _vector_ids(*args, **kwargs):
    return _search._vector_search_ids(*args, **kwargs)


def _write_injected(ids: list[str], ts: str) -> None:
    _search._write_injected_counts(ids, ts)


def _record_quality(*args, **kwargs) -> None:
    _search._record_context_quality_event(*args, **kwargs)


_is_greeting = _search._is_greeting
_fallback_candidate_count = _search._fallback_candidate_count
_lexical_relevance = _search._lexical_relevance
_classify_task = _search._classify_task
_type_weights = _search._type_weights
get_active_warnings = _search.get_active_warnings

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
            "vector_search_threshold": 0.35,
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

    # --- Profile-driven retrieval config (F1 rerank / F2 query expansion / F4 conflict filter) ---
    _pcfg = load_config()  # module-level name — overridable in tests
    _profile_enabled = bool((_pcfg.get("user_profile") or {}).get("enabled", False))
    _cp_profile = _pcfg.get("context_pack", {}) if _pcfg.get("context_pack") else {}
    _profile_boost_weight = float(_cp_profile.get("profile_boost_weight", 0.15) or 0.0) if _profile_enabled else 0.0
    _profile_conflict_penalty = float(_cp_profile.get("profile_conflict_penalty", 0.6) or 1.0) if _profile_enabled else 1.0
    _profile_expand_on = bool(_cp_profile.get("profile_query_expand_enabled", True)) if _profile_enabled else False
    _profile_conflict_filter = bool(_cp_profile.get("profile_conflict_filter_enabled", True)) if _profile_enabled else False

    _profile_words: list[str] = []
    _profile_expansions: list[str] = []
    _profile_overlap_ratio: Any = lambda *a, **k: 0.0
    _profile_conflict_for_record: Any = lambda *a, **k: None
    if _profile_enabled:
        try:
            from memorycore.storage.profile import (
                profile_query_expansion,
                profile_overlap_ratio as _profile_overlap_ratio,
                profile_conflict_for_record as _profile_conflict_for_record,
            )
            if _profile_boost_weight > 0.0:
                from memorycore.storage.profile import profile_feature_words
                _profile_words = profile_feature_words(cfg=_pcfg)
            if _profile_expand_on:
                _profile_expansions = profile_query_expansion(
                    task,
                    cfg=_pcfg,
                    max_terms=int(_cp_profile.get("profile_query_expand_max_terms", 3)),
                    min_overlap=int(_cp_profile.get("profile_query_expand_min_overlap", 1)),
                )
        except Exception as _prof_exc:
            logger.debug("profile retrieval aids disabled: %s", _prof_exc)
            _profile_words, _profile_expansions = [], []

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
        rows = _search_memory_records(task, scope=scope, project_path=project_path, status="active", limit=fts_limit)
        if not rows:
            rows = _search_memory_records(task, scope=scope, project_path=project_path, status="candidate", limit=20)
        else:
            candidate_rows = _search_memory_records(task, scope=scope, project_path=project_path, status="candidate", limit=10)
            rows.extend(candidate_rows)
        if not rows:
            rows = _keyword_records(task, scope=scope, project_path=project_path, limit=40)
        # F2: profile-driven query expansion — run a SEPARATE retrieval with the
        # expansion phrase and merge results, so short AND-queries are not made
        # stricter (which would shrink recall instead of expanding it).
        if _profile_expansions and rows:
            try:
                expand_query = " ".join(_profile_expansions)
                ext_rows = _search_memory_records(
                    expand_query, scope=scope, project_path=project_path,
                    status="active", limit=12,
                )
                ext_ids = {r["id"] for r in rows}
                for r in ext_rows:
                    if r["id"] not in ext_ids:
                        ext_ids.add(r["id"])
                        r["_retrieval_sources"] = (r.get("_retrieval_sources") or []) + ["profile_expand"]
                        rows.append(r)
            except Exception:
                logger.debug("profile query expansion merge failed", exc_info=True)
        return rows

    def _fetch_vector():
        try:
            return dict(_vector_ids(task, top_k=mode_settings["vector_top_k"], score_threshold=mode_settings["vector_search_threshold"]))
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
        cross_retrieval_multiplier = 1.5 if ("fts" in sources and "vector" in sources) else 1.0

        high_lexical_bonus = 0.15 if lexical >= 0.5 else 0.0

        parent_penalty = -0.05 if prefer_atomic and not include_parent and _metadata(r).get("kind") == "parent_memory" else 0.0
        content_len = len(r.get("content") or "")
        has_strong_relevance = lexical >= 0.4 or vector_score >= 0.8 or "entity" in sources
        short_content_penalty = (
            1.0 if has_strong_relevance
            else 0.5 if content_len < 50
            else 0.85 if content_len < 80
            else 1.0
        )
        candidate_discount = 0.85 if r.get("status") == "candidate" else 1.0
        feedback = max(-1.0, min(1.0, float(r.get("feedback_score") or 0)))
        usage_rate = min(1.0, float(r.get("injected_count") or 0) / 10.0)

        # F1: profile-driven rerank (pure-local).  Records whose text overlaps
        # stored profile signal words get a bounded additive boost; a
        # user_profile memory that contradicts the current profile is punished.
        profile_boost = 0.0
        if _profile_boost_weight > 0.0 and _profile_words:
            haystack = f"{r.get('title') or ''} {r.get('content') or ''}"
            profile_boost = _profile_overlap_ratio(haystack, _profile_words) * _profile_boost_weight

        profile_multiplier = 1.0
        if _profile_conflict_penalty < 1.0 and r.get("type") == "user_profile":
            try:
                conflict = _profile_conflict_for_record(r, user_id="default")
                if conflict is not None:
                    profile_multiplier = _profile_conflict_penalty
                    r["_profile_conflict"] = conflict
            except Exception:
                pass

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
            + _recency_score(r) * recency_weight
            + profile_boost)
            * candidate_discount
            * short_content_penalty
            * cross_retrieval_multiplier
            * profile_multiplier
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
    cfg = load_config()  # module-level (top of file) — overridable in tests
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
    # Fixed structured user-profile snapshot — always injected (no retrieval dependency)
    try:
        from memorycore.storage.profile import profile_snapshot
        if cfg.get("user_profile", {}).get("enabled", False):
            snap = profile_snapshot(user_id="default", cfg=cfg, max_chars=int(cfg.get("user_profile", {}).get("max_snapshot_chars", 800)))
            if snap:
                lines.append(f"{snap}\n")
    except Exception as exc:
        logger.debug("user_profile snapshot injection skipped: %s", exc)
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
        # F4: user_profile memories that contradict the stored profile are not
        # injected into the body; they surface as warnings with current value.
        if _profile_conflict_filter and item.get("type") == "user_profile":
            try:
                _pc = _profile_conflict_for_record(item, user_id="default")
            except Exception:
                _pc = None
            if _pc:
                filtered_ids.append(item["id"])
                injection_warnings.append({
                    "type": "profile_conflict",
                    "severity": "medium",
                    "memory_id": item["id"],
                    "title": str(item.get("title", "")).replace("\r", " ").replace("\n", " ")[:80],
                    "attribute": _pc.get("attribute"),
                    "profile_value": _pc.get("profile_value"),
                    "reason": (
                        f"Memory contradicts current profile value for "
                        f"'{_pc.get('attribute')}' and was excluded from normal context."
                    ),
                })
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
        _write_injected(ids_snapshot, ts)
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
    _record_quality(task, task_type, agent, project_path, scope, quality, type_weights)
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
            "profile_boost_weight": _profile_boost_weight,
            "profile_query_expansions": _profile_expansions,
            "profile_conflict_filtered": sum(
                1 for w in injection_warnings if w.get("type") == "profile_conflict"
            ),
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
