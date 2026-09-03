"""Deduplication engine — connects extraction layer to storage layer.

Takes ExtractedFact list from extraction.py, compares against existing
memories in Qdrant, decides ADD / UPDATE / CONTRADICTS / SKIP, then
writes candidates into SQLite.

Decision thresholds (cosine similarity):
  >= SKIP_THRESHOLD   → duplicate, skip
  >= UPDATE_THRESHOLD → likely update/refinement of existing memory
  >= LINK_THRESHOLD   → related, add as new but link to existing
  <  LINK_THRESHOLD   → genuinely new fact, add without link

Per-type overrides in TYPE_THRESHOLDS tune conservatism:
  decision / user_profile: higher thresholds (keep distinct facts separate)
  episodic_memory / feedback: lower thresholds (merge similar fragments aggressively)

Public API
----------
ingest(messages, config) -> IngestResult
    Full pipeline: extract → dedup → write SQLite candidates.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

# Module-level import so patch("memorycore.dedup.extract_facts") works in tests
from memorycore.extraction import extract_facts  # noqa: E402

logger = logging.getLogger(__name__)

_high_recall_types_cache: tuple[str, float, set[str]] = ("", 0.0, set())

# Base cosine similarity thresholds
SKIP_THRESHOLD = 0.82       # near-identical or same-fact rewording → skip
UPDATE_THRESHOLD = 0.68     # same topic, new info → update existing
LINK_THRESHOLD = 0.55       # related → add new, link to existing

# Per-type threshold overrides (skip, update, link)
# Types not listed fall back to the base thresholds above.
TYPE_THRESHOLDS: dict[str, tuple[float, float, float]] = {
    # Conservative: keep decision records separate; avoid accidental merges
    "decision":          (0.90, 0.78, 0.65),
    "user_profile":      (0.88, 0.75, 0.60),
    "environment_fact":  (0.88, 0.75, 0.60),
    "project_memory":    (0.88, 0.75, 0.60),
    # Aggressive: merge similar episodic/feedback fragments readily
    "episodic_memory":   (0.78, 0.65, 0.50),
    "feedback":          (0.78, 0.65, 0.50),
    # skill_candidate: moderate
    "skill_candidate":   (0.85, 0.72, 0.55),
}


# ---------------------------------------------------------------------------
# Batch-internal dedup (character n-gram Jaccard similarity)
# ---------------------------------------------------------------------------

def _char_ngrams(text: str, n: int = 2) -> set[str]:
    t = text.lower().strip()
    if len(t) < n:
        return {t}
    return {t[i:i + n] for i in range(len(t) - n + 1)}


def _batch_similar(text: str, seen: list[str], threshold: float = 0.55) -> bool:
    if not seen:
        return False
    ngrams_a = _char_ngrams(text)
    if not ngrams_a:
        return False
    for s in seen:
        ngrams_b = _char_ngrams(s)
        if not ngrams_b:
            continue
        jaccard = len(ngrams_a & ngrams_b) / len(ngrams_a | ngrams_b)
        if jaccard >= threshold:
            return True
    return False


def _find_active_title_match(title: str, memory_type: str) -> dict[str, Any] | None:
    """Return the strongest active record with the same exact title and type."""
    from memorycore.storage.db import _managed_query

    rows = _managed_query(
        """
        SELECT id, title, content, type
        FROM memories
        WHERE status = 'active' AND type = ? AND title = ? COLLATE NOCASE
        ORDER BY effectiveness_score DESC, updated_at DESC
        LIMIT 1
        """,
        (memory_type, title.strip()),
    )
    return rows[0] if rows else None


def _get_high_recall_types(ttl_seconds: float = 300.0) -> set[str]:
    global _high_recall_types_cache
    from memorycore.models import db_path

    cache_key = str(db_path())
    cached_key, cached_at, cached_types = _high_recall_types_cache
    if cached_key == cache_key and time.monotonic() - cached_at < ttl_seconds:
        return set(cached_types)

    from memorycore.storage.db import _managed_query

    rows = _managed_query(
        """
        SELECT type,
               SUM(CASE WHEN injected_count > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) AS recall_rate
        FROM memories
        WHERE status IN ('active', 'candidate')
        GROUP BY type
        HAVING COUNT(*) >= 3
        ORDER BY recall_rate DESC, COUNT(*) DESC
        LIMIT 3
        """,
        (),
    )
    result = {str(row["type"]) for row in rows if float(row.get("recall_rate") or 0.0) > 0.0}
    _high_recall_types_cache = (cache_key, time.monotonic(), result)
    return set(result)


def _seed_feedback(
    memory_id: str,
    fact: Any,
    decision: "DedupDecision",
    memory_type: str,
    add_feedback_fn: Any,
) -> float:
    score = 0.0
    if fact.importance >= 0.8:
        score += 0.3
    elif fact.importance >= 0.6:
        score += 0.1
    if decision.linked_ids:
        score += 0.2
    if memory_type in _get_high_recall_types():
        score += 0.15
    if 50 <= len(fact.text) <= 200:
        score += 0.1
    score = round(min(score, 1.0), 2)
    if score <= 0:
        return 0.0
    try:
        add_feedback_fn(
            memory_id,
            score,
            note="auto:seed",
            source_agent="system",
            count_as_injection=False,
        )
    except Exception:
        logger.warning("dedup: failed to seed feedback for %s", memory_id, exc_info=True)
        return 0.0
    return score


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class DedupDecision:
    action: str                          # "add" | "update" | "skip"
    fact_text: str
    existing_id: str = ""               # set for update/skip
    existing_text: str = ""
    similarity: float = 0.0
    linked_ids: list[str] = field(default_factory=list)


@dataclass
class IngestResult:
    added: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0
    decisions: list[DedupDecision] = field(default_factory=list)
    elapsed_s: float = 0.0
    extraction_elapsed_s: float = 0.0


# ---------------------------------------------------------------------------
# Core dedup logic (pure, no I/O — easy to test)
# ---------------------------------------------------------------------------

def decide(
    fact_text: str,
    similar: list[Any],          # list of SearchResult from vector_store
    linked_memory_ids: list[str] | None = None,
    memory_type: str = "",
    skip_threshold: float = SKIP_THRESHOLD,
    update_threshold: float = UPDATE_THRESHOLD,
    link_threshold: float = LINK_THRESHOLD,
) -> DedupDecision:
    """Decide what to do with a single extracted fact given similar existing memories.

    Parameters
    ----------
    fact_text:
        The new fact text from the LLM.
    similar:
        Nearest-neighbour results from VectorStore.search(), sorted by score desc.
    linked_memory_ids:
        IDs the LLM itself suggested as related (from extraction.py).
    memory_type:
        Memory type string used to look up per-type threshold overrides.
    """
    if memory_type and memory_type in TYPE_THRESHOLDS:
        skip_threshold, update_threshold, link_threshold = TYPE_THRESHOLDS[memory_type]

    linked = list(linked_memory_ids or [])

    if not similar:
        return DedupDecision(action="add", fact_text=fact_text, linked_ids=linked)

    top = similar[0]
    score = top.score

    if score >= skip_threshold:
        return DedupDecision(
            action="skip",
            fact_text=fact_text,
            existing_id=top.id,
            existing_text=top.text,
            similarity=score,
        )

    if score >= update_threshold:
        return DedupDecision(
            action="update",
            fact_text=fact_text,
            existing_id=top.id,
            existing_text=top.text,
            similarity=score,
            linked_ids=linked,
        )

    # Below update threshold — new fact; collect related ids from search results
    related = [r.id for r in similar if r.score >= link_threshold and r.score < update_threshold]
    all_linked = list(dict.fromkeys(linked + related))  # dedup, preserve order
    return DedupDecision(
        action="add",
        fact_text=fact_text,
        similarity=score,
        linked_ids=all_linked,
    )


# ---------------------------------------------------------------------------
# Full ingest pipeline
# ---------------------------------------------------------------------------

def ingest(
    messages: list[dict[str, str]],
    *,
    user_id: str = "default",
    agent_id: str = "agent",
    project_path: str = "",
    scope: str = "",
    cfg: dict[str, Any] | None = None,
    # Allow injecting dependencies for testing
    _extraction_config=None,
    _vector_store=None,
    _add_memory_fn=None,
    _update_memory_fn=None,
    _find_title_match_fn=None,
    _add_feedback_fn=None,
) -> IngestResult:
    """Full pipeline: extract facts → dedup → write SQLite candidates.

    Parameters
    ----------
    messages:
        Conversation turns to extract from.
    user_id / agent_id:
        Scope for vector search filters and SQLite metadata.
    project_path / scope:
        Subject context of the conversation (P2). When ``project_path`` resolves
        to a configured project (``subject_context.projects``), the record is
        written with project_path + resolved scope + a ``project:<name>`` tag.
    cfg:
        Parsed config.yaml dict.  Used to build ExtractionConfig and
        VectorStoreConfig if not injected.
    _extraction_config / _vector_store / _add_memory_fn / _update_memory_fn:
        Dependency injection for unit tests.
    """
    import time
    t_start = time.time()

    cfg = cfg or {}

    # --- Subject context resolution (P2) ---
    from memorycore.subject_context import resolve_project
    project = resolve_project(project_path=project_path, cfg=cfg)
    project_name = project["name"] if project else ""
    resolved_path = project["path"] if project else ""
    if project:
        mem_scope = project.get("scope") or "project"
    else:
        es_pre = cfg.get("extraction_strategy", {})
        mem_scope = scope or es_pre.get("default_scope", "global")

    # --- Load extraction strategy config ---
    es = cfg.get("extraction_strategy", {})
    base_skip = es.get("skip_threshold", SKIP_THRESHOLD)
    base_update = es.get("update_threshold", UPDATE_THRESHOLD)
    base_link = es.get("link_threshold", LINK_THRESHOLD)
    context_sample_len = es.get("context_sample_length", 200)
    context_mem_limit = es.get("context_memory_limit", 10)
    dedup_top_k = es.get("dedup_search_limit", 5)
    max_related = es.get("max_related_ids", 10)
    mem_type = es.get("default_memory_type", "episodic_memory")
    mem_status = es.get("default_status", "candidate")
    mem_decay = es.get("default_decay_policy", "review")
    if not project:  # resolved project scope wins (P2); otherwise config default
        mem_scope = es.get("default_scope", "global")
    title_max = es.get("title_max_length", 80)
    default_conf = es.get("default_confidence", 0.65)
    default_imp = es.get("default_importance", 0.5)
    min_importance = es.get("min_importance", 0.3)
    chinese_ratio = es.get("chinese_detection_ratio", 0.15)

    # --- 1. Build dependencies ---
    from memorycore.extraction import ExtractionConfig, extraction_config_from_dict
    from memorycore.vector_store import VectorStore, get_vector_store, vector_store_config_from_dict

    ext_cfg = _extraction_config or extraction_config_from_dict(cfg)
    vs: VectorStore = _vector_store or get_vector_store(cfg)

    # Default SQLite write functions (lazy import from storage module — no circular risk)
    using_default_storage = _add_memory_fn is None
    if _add_memory_fn is None:
        from memorycore.storage import add_memory_record as _add_memory_fn  # type: ignore[attr-defined]
    if _update_memory_fn is None:
        from memorycore.storage import update_memory_content as _update_memory_fn  # type: ignore[attr-defined]
    if _find_title_match_fn is None:
        _find_title_match_fn = _find_active_title_match
    if _add_feedback_fn is None:
        if using_default_storage:
            from memorycore.storage import add_feedback as _add_feedback_fn  # type: ignore[attr-defined]
        else:
            _add_feedback_fn = lambda *_args, **_kwargs: None

    result = IngestResult()

    # --- 2. Fetch existing memories for context (top-N active) ---
    existing_for_prompt: list[dict[str, Any]] = []
    if vs.available:
        # Use a broad query to get recent active memories for the LLM context
        sample_query = " ".join(m.get("content", "") for m in messages[:2])[:context_sample_len]
        existing_hits = vs.search(
            sample_query,
            top_k=context_mem_limit,
            filters={"status": "active"},
        )
        existing_for_prompt = [
            {"id": h.id, "content": h.text}
            for h in existing_hits
        ]

    # --- 3. Extract facts ---
    t_ext = time.time()
    facts, ext_elapsed = extract_facts(
        messages,
        existing_memories=existing_for_prompt,
        config=ext_cfg,
        min_importance=min_importance,
        chinese_detection_ratio=chinese_ratio,
        project_path=resolved_path,
        project_name=project_name,
        scope=mem_scope,
    )
    result.extraction_elapsed_s = ext_elapsed

    if not facts:
        result.elapsed_s = time.time() - t_start
        return result

    # --- 4. Dedup each fact ---
    batch_texts: list[str] = []
    for fact in facts:
        try:
            # Batch-internal dedup: skip if very similar to a fact already processed in this batch
            if _batch_similar(fact.text, batch_texts):
                result.skipped += 1
                logger.debug("dedup: BATCH_SKIP %s", fact.text[:60])
                continue

            fact_type = fact.memory_type if fact.memory_type else mem_type
            fact_title = str(getattr(fact, "title", "") or fact.text[:title_max]).strip()[:title_max]

            from memorycore.subject_context import infer_subject_from_title

            # 四级主体裁决引擎
            raw_subject = (getattr(fact, "subject", "") or "").strip()
            resolved_proj = None

            # 1. 优先采用 LLM 提取的 subject 归一化
            if raw_subject:
                resolved_proj = resolve_project(project_name=raw_subject, cfg=cfg)

            # 2. 其次采用会话环境探测出的 project (即前面 resolve_project(project_path, ...))
            if not resolved_proj and project:
                resolved_proj = project

            # 3. 兜底防线：从标题前缀提取反查
            if not resolved_proj:
                resolved_proj = infer_subject_from_title(fact_title, cfg=cfg)

            # 元数据增强与自动提权
            fact_tags = ["extracted", f"agent:{agent_id}"]
            fact_scope = mem_scope
            fact_project_path = resolved_path

            if resolved_proj:
                subject = resolved_proj["name"]
                fact_project_path = fact_project_path or resolved_proj.get("path", "")
                fact_scope = "project"  # 自动提权为 project 级 scope
                fact_tags.append(f"project:{subject}")
                subject_meta = {"subject": subject}
                if not fact_title.lower().startswith(subject.lower()):
                    fact_title = f"{subject} {fact_title}"[:title_max]
            else:
                subject = ""
                subject_meta = {}

            title_match = _find_title_match_fn(fact_title, fact_type)
            if title_match:
                existing_id = str(title_match["id"])
                if str(title_match.get("content") or "").strip() == fact.text.strip():
                    result.skipped += 1
                    result.decisions.append(DedupDecision(
                        action="skip",
                        fact_text=fact.text,
                        existing_id=existing_id,
                        existing_text=str(title_match.get("content") or ""),
                        similarity=1.0,
                    ))
                else:
                    _update_memory_fn(
                        existing_id,
                        new_title=fact_title,
                        new_content=fact.text,
                    )
                    if vs.available:
                        vs.upsert(existing_id, fact.text, {
                            "status": "active",
                            "user_id": user_id,
                            "agent_id": agent_id,
                        })
                    result.updated += 1
                    result.decisions.append(DedupDecision(
                        action="update",
                        fact_text=fact.text,
                        existing_id=existing_id,
                        existing_text=str(title_match.get("content") or ""),
                        similarity=1.0,
                    ))
                batch_texts.append(fact.text)
                logger.debug("dedup: TITLE_MATCH %s %s", existing_id, fact_title[:60])
                continue

            type_link = TYPE_THRESHOLDS.get(fact_type, (base_skip, base_update, base_link))[2]
            similar = []
            if vs.available:
                similar = vs.search(
                    fact.text,
                    top_k=dedup_top_k,
                    score_threshold=type_link,
                )

            decision = decide(
                fact.text,
                similar,
                linked_memory_ids=fact.linked_memory_ids,
                memory_type=fact_type,
                skip_threshold=base_skip,
                update_threshold=base_update,
                link_threshold=base_link,
            )
            result.decisions.append(decision)

            if decision.action == "skip":
                result.skipped += 1
                logger.debug("dedup: SKIP  [%.3f] %s", decision.similarity, fact.text[:60])

            elif decision.action == "update":
                # Phase 5 时间守卫: temporal 启用时，若已有记录在1小时内刚更新，降级为 add+link
                _guarded = False
                if cfg.get("temporal", {}).get("dedup_temporal_guard", False):
                    from memorycore.storage.db import _managed_query as _mq
                    from memorycore.models import local_now as _now
                    from datetime import timedelta
                    _existing_rows = _mq(
                        "SELECT updated_at FROM memories WHERE id = ?",
                        (decision.existing_id,),
                    )
                    if _existing_rows:
                        _upd = _existing_rows[0].get("updated_at") or ""
                        try:
                            from datetime import datetime, timezone
                            _upd_dt = datetime.fromisoformat(_upd.replace("Z", "+00:00"))
                            if _upd_dt.tzinfo is None:
                                _upd_dt = _upd_dt.replace(tzinfo=timezone.utc)
                            if (_now() - _upd_dt) < timedelta(hours=1):
                                _guarded = True
                                logger.debug(
                                    "dedup: temporal guard — existing %s updated <1h ago, downgrade UPDATE→ADD+link",
                                    decision.existing_id,
                                )
                        except Exception:
                            pass
                if not _guarded:
                    try:
                        _update_memory_fn(decision.existing_id)
                    except Exception as exc:
                        logger.warning("dedup: failed to touch existing memory %s: %s", decision.existing_id, exc)

                new_id = str(uuid.uuid4())
                _add_memory_fn(
                    memory_id=new_id,
                    memory_type=fact_type,
                    title=fact_title,
                    content=fact.text,
                    scope=fact_scope,
                    project_path=fact_project_path,
                    tags=fact_tags + ["supersedes:" + decision.existing_id],
                    source="extraction",
                    source_agent=agent_id,
                    confidence=default_conf,
                    importance=fact.importance if fact.importance != 0.5 else default_imp,
                    status=mem_status,
                    decay_policy=mem_decay,
                    related_ids=([decision.existing_id] + decision.linked_ids)[:max_related],
                    metadata={"user_id": user_id, "supersedes": decision.existing_id,
                              "similarity": round(decision.similarity, 4), **subject_meta},
                )
                if vs.available:
                    vs.upsert(new_id, fact.text, {
                        "status": mem_status,
                        "user_id": user_id,
                        "agent_id": agent_id,
                    })
                _seed_feedback(new_id, fact, decision, fact_type, _add_feedback_fn)
                result.updated += 1
                batch_texts.append(fact.text)
                logger.debug("dedup: UPDATE [%.3f] %s", decision.similarity, fact.text[:60])

            else:  # add
                new_id = str(uuid.uuid4())
                _add_memory_fn(
                    memory_id=new_id,
                    memory_type=fact_type,
                    title=fact_title,
                    content=fact.text,
                    scope=fact_scope,
                    project_path=fact_project_path,
                    tags=fact_tags,
                    source="extraction",
                    source_agent=agent_id,
                    confidence=default_conf,
                    importance=fact.importance if fact.importance != 0.5 else default_imp,
                    status=mem_status,
                    decay_policy=mem_decay,
                    related_ids=decision.linked_ids[:max_related],
                    metadata={"user_id": user_id,
                              "similarity_to_nearest": round(decision.similarity, 4), **subject_meta},
                )
                if vs.available:
                    vs.upsert(new_id, fact.text, {
                        "status": mem_status,
                        "user_id": user_id,
                        "agent_id": agent_id,
                    })
                _seed_feedback(new_id, fact, decision, fact_type, _add_feedback_fn)
                result.added += 1
                batch_texts.append(fact.text)
                logger.debug("dedup: ADD    [%.3f] %s", decision.similarity, fact.text[:60])

        except Exception as exc:
            logger.error("dedup: error processing fact '%s': %s", fact.text[:60], exc)
            result.errors += 1

    result.elapsed_s = round(time.time() - t_start, 2)
    logger.info(
        "dedup: ingest done — add=%d update=%d skip=%d error=%d (%.2fs)",
        result.added, result.updated, result.skipped, result.errors, result.elapsed_s,
    )
    return result
