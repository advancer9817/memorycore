"""LLM-enhanced curator — semantic analysis on top of the rule-based curator.

Public API
----------
llm_curator_report(config, limit, similarity_threshold) -> dict
apply_llm_curator(report, dry_run) -> dict
run_llm_curator(config, limit, sim_threshold, apply, rebuild_vectors) -> dict
run_llm_curator_incremental(job_id, config, limit, sim_threshold, apply, rebuild_vectors) -> dict
"""
from .apply import apply_llm_curator
from .core import (
    _call_llm,
    _call_llm_with_thinking,
    _cleanup_reviewed_ids,
    _fetch_active_memories,
    _fetch_memories_by_ids,
    _find_candidate_pairs,
    _get_recently_reviewed_ids,
    _get_vector_store,
    _LINK_DISCOVERY_PROMPTS,
    _llm_split_fact_hash,
    _LLM_MAX_RETRIES,
    _LLM_RETRY_BACKOFF,
    _load_extraction_config,
    _mark_reviewed,
    _normalize_fact_text,
    _PROMPT_STYLES,
    _temporal_tag,
)
from .judges import (
    _find_link_candidates,
    _llm_detect_splittable,
    _llm_discover_links,
    _llm_judge_contradictions,
    _llm_judge_duplicates,
    _llm_reassess_importance,
)
from .report import (
    _batch_report,
    _summary_from_counts,
    llm_curator_report,
    run_llm_curator,
    run_llm_curator_incremental,
)

__all__ = [
    "apply_llm_curator",
    "llm_curator_report",
    "run_llm_curator",
    "run_llm_curator_incremental",
]
