"""LLM curator infrastructure: prompt styles, LLM calling, reviewed ID management,
text normalization, vector store access, memory fetching, candidate pair finding."""
from __future__ import annotations

import hashlib
import json
import logging
import os as _os
import time as _time
from typing import Any

from memorycore.models import as_json, row_to_dict
from memorycore.extraction import _language_instruction

logger = logging.getLogger(__name__)

_PROMPT_STYLES = {
    "conservative": {
        "duplicate": (
            "You are a careful memory curator. Only mark pairs as duplicates when they express "
            "the exact same fact with no additional unique information in either memory. "
            "Partial overlap or related topics are NOT duplicates. "
            "Return a JSON object with key 'results': a list where each element has "
            "'index' (int), 'is_duplicate' (bool), 'reason' (str, ≤30 words), "
            "'keep' (str, \"A\" or \"B\" — the memory to keep, or null if unsure), and "
            "'merge_info' (str, ≤40 words; empty string if nothing needs merging)."
        ),
        "contradiction": (
            "You are a careful memory curator. Only flag contradictions when two memories "
            "make directly incompatible claims about the same specific fact. "
            "Different perspectives or supplementary information are NOT contradictions. "
            "Return JSON with key 'results': list of objects with "
            "'index' (int), 'contradicts' (bool), 'reason' (str ≤30 words), "
            "'newer' (str, \"A\" or \"B\" — the more recent/correct memory, or null)."
        ),
        "importance": (
            "You are a careful memory curator. Evaluate each memory's importance conservatively. "
            "Only change importance if there is a clear reason. Prefer 'keep' when uncertain. "
            "Memories with positive feedback_score (> 0) have been validated by the user — "
            "do NOT archive or downgrade these unless the content is demonstrably outdated. "
            "Actions: 'keep', 'promote', 'downgrade', 'archive'. "
            "Return JSON with key 'results': list of "
            "{'index': int, 'new_importance': float, 'action': str, 'reason': str ≤20 words}."
        ),
        "split": (
            "You are a careful memory curator. Only flag memories for splitting if they contain "
            "clearly independent facts that would be more useful as separate entries. "
            "Do not split memories that form a coherent narrative. "
            "Return JSON with key 'results': list of "
            "{'index': int, 'splittable': bool, 'reason': str ≤20 words, "
            "'sub_memories': [{'title': str, 'content': str, 'importance': float}]}. "
            "If not splittable, set splittable=false."
        ),
    },
    "balanced": {
        "duplicate": (
            "You are a memory curator balancing thoroughness with precision. "
            "Mark pairs as duplicates when they convey substantially the same information, "
            "even if worded differently. Partial overlaps where one adds significant new detail are NOT duplicates. "
            "Return a JSON object with key 'results': a list where each element has "
            "'index' (int), 'is_duplicate' (bool), 'reason' (str, ≤30 words), "
            "'keep' (str, \"A\" or \"B\" — the memory to keep, or null if unsure), and "
            "'merge_info' (str, ≤40 words; empty string if nothing needs merging)."
        ),
        "contradiction": (
            "You are a memory curator checking for contradictions. "
            "Flag pairs where the memories make conflicting claims, including temporal supersession "
            "(an older version replaced by a newer one). "
            "Different but compatible perspectives are NOT contradictions. "
            "Return JSON with key 'results': list of objects with "
            "'index' (int), 'contradicts' (bool), 'reason' (str ≤30 words), "
            "'newer' (str, \"A\" or \"B\" — the more recent/correct memory, or null)."
        ),
        "importance": (
            "You are a memory curator optimizing knowledge base quality. "
            "Reassess each memory's importance based on its current relevance and utility. "
            "Consider recency, actionability, and uniqueness. Make changes when justified. "
            "Memories with positive feedback_score (> 0) have been validated by the user — "
            "do NOT archive or downgrade these unless the content is demonstrably outdated. "
            "Actions: 'keep', 'promote', 'downgrade', 'archive'. "
            "Return JSON with key 'results': list of "
            "{'index': int, 'new_importance': float, 'action': str, 'reason': str ≤20 words}."
        ),
        "split": (
            "You are a memory curator improving retrieval quality. "
            "Flag memories that contain multiple distinct facts which would be individually more useful. "
            "Each proposed sub-memory should be self-contained. "
            "Return JSON with key 'results': list of "
            "{'index': int, 'splittable': bool, 'reason': str ≤20 words, "
            "'sub_memories': [{'title': str, 'content': str, 'importance': float}]}. "
            "If not splittable, set splittable=false."
        ),
    },
    "aggressive": {
        "duplicate": (
            "You are an aggressive memory curator whose primary goal is to eliminate redundancy. "
            "Analyse each pair of memories and determine whether they are duplicates. "
            "Consider ALL of the following as duplicates:\n"
            "- Exact same fact stated differently\n"
            "- One memory is a subset of the other (the shorter adds nothing new)\n"
            "- Both memories describe the same decision, preference, or configuration\n"
            "- Overlapping information where merging into one would lose nothing\n"
            "- Same topic with trivially different wording or formatting\n"
            "When in doubt, mark as duplicate — redundancy hurts retrieval quality.\n"
            "Return a JSON object with key 'results': a list where each element has "
            "'index' (int), 'is_duplicate' (bool), 'reason' (str, ≤30 words), "
            "'keep' (str, \"A\" or \"B\" — the memory to keep, or null if unsure), and "
            "'merge_info' (str, ≤40 words describing information from the discarded memory "
            "that should be merged into the kept memory; empty string if nothing needs merging)."
        ),
        "contradiction": (
            "You are an aggressive memory curator focused on detecting contradictions. "
            "Check each memory pair for ANY form of conflict:\n"
            "- Direct contradiction: one states X, the other states NOT X\n"
            "- Temporal supersession: one is an outdated version of the same decision/preference\n"
            "- Conditional conflict: they give different answers for overlapping conditions\n"
            "- Implicit contradiction: their logical implications are incompatible\n"
            "- Stale vs current: one reflects an old state that has been updated by the other\n"
            "When memories describe the same topic with different conclusions, that IS a contradiction. "
            "Return JSON with key 'results': list of objects with "
            "'index' (int), 'contradicts' (bool), 'reason' (str ≤30 words), "
            "'newer' (str, \"A\" or \"B\" — the more recent/correct memory, or null)."
        ),
        "importance": (
            "You are an aggressive memory curator optimizing a knowledge base for maximum utility. "
            "For each memory, critically evaluate its long-term value and output a revised importance score 0.0–1.0. "
            "Be decisive — most memories decay in value over time. Consider:\n"
            "- Is this still actionable or relevant, or is it historical noise?\n"
            "- Does it contain a unique insight, or is it generic/obvious?\n"
            "- Would losing this memory actually harm future conversations?\n"
            "- Is the current importance score justified by the content quality?\n"
            "- Memories with 0 injections and 0 feedback are likely unused — downgrade aggressively.\n"
            "- Memories with positive feedback_score (> 0) have been validated by the user — "
            "do NOT archive or downgrade these unless the content is demonstrably outdated.\n"
            "Actions: 'keep' (no change needed), 'promote' (raise importance, make active), "
            "'downgrade' (lower importance), 'archive' (low value, should be archived). "
            "Default to action rather than 'keep' — if you can justify any change, make it.\n"
            "Return JSON with key 'results': list of "
            "{'index': int, 'new_importance': float, 'action': str, 'reason': str ≤20 words}."
        ),
        "split": (
            "You are a memory curator focused on atomizing compound memories for better retrieval. "
            "Identify memories that contain multiple distinct, separable facts. "
            "A memory is splittable if:\n"
            "- It lists multiple independent decisions, preferences, or facts\n"
            "- It covers multiple topics that could each stand alone\n"
            "- It contains both a rule AND its context/reasoning as separable units\n"
            "- It bundles configuration details with behavioral preferences\n"
            "For each splittable memory, propose 2-4 concise atomic sub-memories. "
            "Each sub-memory should be self-contained and useful in isolation.\n"
            "Return JSON with key 'results': list of "
            "{'index': int, 'splittable': bool, 'reason': str ≤20 words, "
            "'sub_memories': [{'title': str, 'content': str, 'importance': float}]}. "
            "The 'importance' field (0.0-1.0) reflects the long-term value of each sub-memory independently. "
            "If a memory is already atomic or splitting would lose context, set splittable=false."
        ),
    },
}

_LINK_DISCOVERY_PROMPTS: dict[str, str] = {
    "conservative": (
        "You are a careful knowledge graph curator. Only establish links when there is "
        "a clear, direct semantic relationship between two memories. "
        "Allowed relations: 'related_to' (same topic area), 'supports' (A provides evidence for B). "
        "If uncertain, set relation to 'none'. "
        "Return JSON with key 'results': list of "
        "{'index': int, 'relation': str, 'direction': 'A->B' or 'B->A', 'reason': str ≤20 words}. "
        "Set relation='none' if no meaningful relationship exists."
    ),
    "balanced": (
        "You are a knowledge graph curator building a useful relationship network. "
        "Establish links when two memories share meaningful semantic connections. "
        "Allowed relations: 'related_to', 'supports', 'part_of', 'supersedes', 'none'. "
        "Return JSON with key 'results': list of "
        "{'index': int, 'relation': str, 'direction': 'A->B' or 'B->A', 'reason': str ≤20 words}."
    ),
    "aggressive": (
        "You are an aggressive knowledge graph curator. Your goal is to maximize useful connections. "
        "Err on the side of linking — an extra link is cheaper than a missing one. "
        "Allowed relations: 'related_to' (any topical overlap), 'supports', 'part_of', 'supersedes', 'none' (truly unrelated). "
        "When in doubt, use 'related_to'. Only use 'none' for clearly unrelated pairs.\n"
        "Return JSON with key 'results': list of "
        "{'index': int, 'relation': str, 'direction': 'A->B' or 'B->A', 'reason': str ≤20 words}."
    ),
}


def _cleanup_reviewed_ids() -> None:
    """Remove entries older than 24 hours from the cooldown registry."""
    from memorycore.storage.db import managed_conn
    from memorycore.models import load_config, local_now
    from datetime import timedelta
    cfg = load_config().get("llm_curator", {})
    max_age = cfg.get("reviewed_ids_max_age_seconds", 86400)
    cutoff = (local_now() - timedelta(seconds=max_age)).isoformat(timespec="seconds")
    with managed_conn() as conn:
        conn.execute("DELETE FROM curator_review_log WHERE reviewed_at < ?", (cutoff,))


def _get_recently_reviewed_ids(review_type: str = "llm_curator") -> set[str]:
    """Return set of memory IDs reviewed within the cooldown window."""
    from memorycore.storage.db import read_conn
    from memorycore.models import load_config, local_now
    from datetime import timedelta
    cfg = load_config().get("llm_curator", {})
    cooldown = cfg.get("review_cooldown_seconds", 7200)
    cutoff = (local_now() - timedelta(seconds=cooldown)).isoformat(timespec="seconds")
    with read_conn() as conn:
        rows = conn.execute(
            "SELECT memory_id FROM curator_review_log WHERE review_type = ? AND reviewed_at >= ?",
            (review_type, cutoff),
        ).fetchall()
    return {row["memory_id"] for row in rows}


def _mark_reviewed(memory_ids: list[str], review_type: str = "llm_curator") -> None:
    """Record that these memories have been reviewed."""
    from memorycore.storage.db import managed_conn
    from memorycore.models import now
    ts = now()
    with managed_conn() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO curator_review_log(memory_id, review_type, reviewed_at) VALUES (?, ?, ?)",
            [(mid, review_type, ts) for mid in memory_ids],
        )

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_fact_text(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def _temporal_tag(record: dict[str, Any]) -> str:
    from memorycore.models import load_config, local_now
    cfg = load_config()
    if not cfg.get("temporal", {}).get("enabled", False):
        return ""
    try:
        from datetime import datetime
        now_dt = local_now()

        def _fmt(ts: str | None) -> str:
            if not ts:
                return "未知"
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                return dt.strftime("%Y-%m-%d")
            except Exception:
                return str(ts)[:10]

        def _days_ago(ts: str | None) -> str:
            if not ts:
                return "?"
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    from datetime import timezone
                    dt = dt.replace(tzinfo=timezone.utc)
                delta = now_dt - dt
                return str(max(0, delta.days))
            except Exception:
                return "?"

        created = _fmt(record.get("created_at"))
        updated = _fmt(record.get("updated_at"))
        days_ago = _days_ago(record.get("updated_at") or record.get("created_at"))

        tag = f"[时间: 创建={created}, 更新={updated}, 距今={days_ago}天"

        last_access = _fmt(record.get("last_accessed_at"))
        if last_access != "未知":
            tag += f", 最后访问={last_access}"

        vf = record.get("valid_from")
        vu = record.get("valid_until")
        if vf or vu:
            tag += f", 有效期={_fmt(vf)}~{_fmt(vu)}"

        tag += "]"
        return tag
    except Exception:
        return ""


def _llm_split_fact_hash(parent_id: str, content: str) -> str:
    return hashlib.sha256(f"{parent_id}:{_normalize_fact_text(content)}".encode()).hexdigest()


_LLM_MAX_RETRIES = 3
_LLM_RETRY_BACKOFF = [2, 5, 10]


def _call_llm_with_thinking(prompt: str, system: str, config: Any) -> tuple[str, str]:
    """Call LLM and return (json_content, thinking)."""
    import time as _time_mod
    from memorycore.extraction import _call_llm as _base_call
    import re as _re

    last_exc: Exception | None = None
    for attempt in range(_LLM_MAX_RETRIES):
        try:
            raw = _base_call(system, prompt, config)
            break
        except Exception as exc:
            last_exc = exc
            exc_str = str(exc).lower()
            is_transient = any(kw in exc_str for kw in [
                "disconnected", "500", "502", "503", "504",
                "timeout", "connection", "eof", "reset",
            ])
            if not is_transient or attempt == _LLM_MAX_RETRIES - 1:
                raise
            wait = _LLM_RETRY_BACKOFF[attempt]
            logger.warning(
                "LLM call failed (attempt %d/%d), retrying in %ds: %s",
                attempt + 1, _LLM_MAX_RETRIES, wait, exc,
            )
            _time_mod.sleep(wait)
    else:
        raise last_exc  # type: ignore[misc]

    thinking_match = _re.search(r"<think>(.*?)</think>", raw, _re.DOTALL)
    thinking = thinking_match.group(1).strip() if thinking_match else ""
    content = _re.sub(r"<think>.*?</think>", "", raw, flags=_re.DOTALL).strip()
    fence_match = _re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
    if fence_match:
        content = fence_match.group(1).strip()
    if not content.startswith("{"):
        start = content.find("{")
        end = content.rfind("}") + 1
        if start >= 0 and end > start:
            content = content[start:end]
    return content, thinking


def _call_llm(prompt: str, system: str, config: Any) -> str:
    content, _ = _call_llm_with_thinking(prompt, system, config)
    return content


def _load_extraction_config(config: dict[str, Any]) -> Any:
    from memorycore.extraction import extraction_config_from_dict
    return extraction_config_from_dict(config)


def _get_vector_store(config: dict[str, Any]) -> Any:
    from memorycore.vector_store import get_vector_store
    from memorycore.models import load_config
    cfg = load_config() if not config else config
    return get_vector_store(cfg)


def _fetch_active_memories(limit: int, require_accessed: bool = False) -> list[dict[str, Any]]:
    from memorycore.storage.db import _managed_query
    accessed_clause = " AND last_accessed_at IS NOT NULL" if require_accessed else ""
    return _managed_query(
        "SELECT id, title, content, type, importance, confidence, feedback_score, "
        "injected_count, updated_at, created_at, valid_from, valid_until, "
        f"last_accessed_at, last_injected_at FROM memories "
        f"WHERE status IN ('active', 'candidate'){accessed_clause} "
        "ORDER BY updated_at DESC LIMIT ?",
        (limit,),
    )


def _fetch_memories_by_ids(ids: list[str]) -> dict[str, dict[str, Any]]:
    from memorycore.storage.db import _managed_query
    if not ids:
        return {}
    placeholders = ",".join("?" * len(ids))
    rows = _managed_query(
        f"SELECT id, title, content, type, importance, confidence, feedback_score, "
        f"injected_count, updated_at, created_at, valid_from, valid_until, "
        f"last_accessed_at, last_injected_at FROM memories WHERE id IN ({placeholders})"
        f" AND status IN ('active', 'candidate')",
        tuple(ids),
    )
    return {r["id"]: r for r in rows}


# ---------------------------------------------------------------------------
# 1. Unified vector scan (dedup + contradiction share one pass)
# ---------------------------------------------------------------------------

def _find_candidate_pairs(
    vs: Any,
    memories: list[dict[str, Any]],
    sim_threshold: float,
) -> list[tuple[dict, dict, float]]:
    """One vector scan returning all pairs >= sim_threshold*0.8."""
    recently_reviewed = _get_recently_reviewed_ids()
    memories = [m for m in memories if m["id"] not in recently_reviewed]

    seen: set[frozenset[str]] = set()
    pairs: list[tuple[dict, dict, float]] = []
    by_id = {m["id"]: m for m in memories}
    effective_floor = sim_threshold * 0.8

    for mem in memories:
        text = f"{mem.get('title', '')} {mem.get('content', '')}".strip()
        if not text:
            continue
        try:
            results = vs.search(text, top_k=6, score_threshold=effective_floor)
        except Exception as exc:
            logger.debug("vector search failed for %s: %s", mem["id"], exc)
            continue
        for r in results:
            other_id = r.id
            if other_id == mem["id"]:
                continue
            if other_id not in by_id:
                continue
            key = frozenset([mem["id"], other_id])
            if key in seen:
                continue
            seen.add(key)
            pairs.append((mem, by_id[other_id], r.score))

    return sorted(pairs, key=lambda x: x[2], reverse=True)
