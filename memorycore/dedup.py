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
import uuid
from dataclasses import dataclass, field
from typing import Any

# Module-level import so patch("memorycore.dedup.extract_facts") works in tests
from memorycore.extraction import extract_facts  # noqa: E402

logger = logging.getLogger(__name__)

# Base cosine similarity thresholds
SKIP_THRESHOLD = 0.92       # near-identical → skip
UPDATE_THRESHOLD = 0.78     # same topic, new info → update existing
LINK_THRESHOLD = 0.55       # related → add new, link to existing

# Per-type threshold overrides (skip, update, link)
# Types not listed fall back to the base thresholds above.
TYPE_THRESHOLDS: dict[str, tuple[float, float, float]] = {
    # Conservative: keep decision records separate; avoid accidental merges
    "decision":          (0.96, 0.88, 0.65),
    "user_profile":      (0.95, 0.85, 0.60),
    "environment_fact":  (0.95, 0.85, 0.60),
    "project_memory":    (0.94, 0.84, 0.60),
    # Aggressive: merge similar episodic/feedback fragments readily
    "episodic_memory":   (0.88, 0.72, 0.50),
    "feedback":          (0.88, 0.72, 0.50),
    # skill_candidate: moderate
    "skill_candidate":   (0.90, 0.78, 0.55),
}


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
    cfg: dict[str, Any] | None = None,
    # Allow injecting dependencies for testing
    _extraction_config=None,
    _vector_store=None,
    _add_memory_fn=None,
    _update_memory_fn=None,
) -> IngestResult:
    """Full pipeline: extract facts → dedup → write SQLite candidates.

    Parameters
    ----------
    messages:
        Conversation turns to extract from.
    user_id / agent_id:
        Scope for vector search filters and SQLite metadata.
    cfg:
        Parsed config.yaml dict.  Used to build ExtractionConfig and
        VectorStoreConfig if not injected.
    _extraction_config / _vector_store / _add_memory_fn / _update_memory_fn:
        Dependency injection for unit tests.
    """
    import time
    t_start = time.time()

    cfg = cfg or {}

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
    if _add_memory_fn is None:
        from memorycore.storage import add_memory_record as _add_memory_fn  # type: ignore[attr-defined]
    if _update_memory_fn is None:
        from memorycore.storage import update_memory_content as _update_memory_fn  # type: ignore[attr-defined]

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
    )
    result.extraction_elapsed_s = ext_elapsed

    if not facts:
        result.elapsed_s = time.time() - t_start
        return result

    # --- 4. Dedup each fact ---
    for fact in facts:
        try:
            fact_type = mem_type
            type_link = TYPE_THRESHOLDS.get(fact_type, (base_skip, base_update, base_link))[2]
            similar = []
            if vs.available:
                similar = vs.search(
                    fact.text,
                    top_k=dedup_top_k,
                    filters={"status": "active"},
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
                try:
                    _update_memory_fn(decision.existing_id)
                except Exception as exc:
                    logger.warning("dedup: failed to touch existing memory %s: %s", decision.existing_id, exc)

                new_id = str(uuid.uuid4())
                _add_memory_fn(
                    memory_id=new_id,
                    memory_type=mem_type,
                    title=fact.text[:title_max],
                    content=fact.text,
                    scope=mem_scope,
                    tags=["extracted", f"agent:{agent_id}", "supersedes:" + decision.existing_id],
                    source="extraction",
                    source_agent=agent_id,
                    confidence=default_conf,
                    importance=fact.importance if fact.importance != 0.5 else default_imp,
                    status=mem_status,
                    decay_policy=mem_decay,
                    related_ids=([decision.existing_id] + decision.linked_ids)[:max_related],
                    metadata={"user_id": user_id, "supersedes": decision.existing_id,
                              "similarity": round(decision.similarity, 4)},
                )
                if vs.available:
                    vs.upsert(new_id, fact.text, {
                        "status": mem_status,
                        "user_id": user_id,
                        "agent_id": agent_id,
                    })
                result.updated += 1
                logger.debug("dedup: UPDATE [%.3f] %s", decision.similarity, fact.text[:60])

            else:  # add
                new_id = str(uuid.uuid4())
                _add_memory_fn(
                    memory_id=new_id,
                    memory_type=mem_type,
                    title=fact.text[:title_max],
                    content=fact.text,
                    scope=mem_scope,
                    tags=["extracted", f"agent:{agent_id}"],
                    source="extraction",
                    source_agent=agent_id,
                    confidence=default_conf,
                    importance=fact.importance if fact.importance != 0.5 else default_imp,
                    status=mem_status,
                    decay_policy=mem_decay,
                    related_ids=decision.linked_ids[:max_related],
                    metadata={"user_id": user_id,
                              "similarity_to_nearest": round(decision.similarity, 4)},
                )
                if vs.available:
                    vs.upsert(new_id, fact.text, {
                        "status": mem_status,
                        "user_id": user_id,
                        "agent_id": agent_id,
                    })
                result.added += 1
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
