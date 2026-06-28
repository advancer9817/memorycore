"""LLM-enhanced curator — semantic analysis on top of the rule-based curator.

Three capabilities:
  1. Semantic deduplication  — find near-duplicate memories by vector similarity,
     then ask the LLM to confirm whether they truly duplicate each other.
  2. Contradiction detection — cluster semantically similar memories and ask the
     LLM whether any pair contradicts another.
  3. Importance re-evaluation — batch-ask the LLM to re-score memories whose
     importance or confidence has drifted, then surface candidates for archiving
     or promotion.

All LLM calls are batched to minimise round-trips.  Results are returned as
structured dicts so callers can decide whether to apply changes (dry-run safe).

Public API
----------
llm_curator_report(config, limit, similarity_threshold) -> dict
    Returns {semantic_duplicates, contradictions, importance_reassessments, errors}.

apply_llm_curator(report, dry_run) -> dict
    Applies the planned actions and returns a summary.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os as _os
import time as _time
import uuid
from typing import Any

from memorycore.models import as_json, row_to_dict
from memorycore.storage.mutation_executor import execute_batch, query_ledger
from memorycore.storage.mutations import MutationContext, MutationRequest

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
    """生成紧凑的时间标签供 LLM 消费。

    示例: [时间: 创建=2026-01-15, 更新=2026-06-20, 距今=154天]
    当 temporal.enabled=False 时返回空字符串。
    """
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


def _call_llm_with_thinking(prompt: str, system: str, config: Any) -> tuple[str, str]:
    """Call LLM and return (json_content, thinking).

    DeepSeek v3 and R1 wrap chain-of-thought in <think>...</think> before the JSON.
    Claude returns markdown-fenced JSON (```json...```).
    We extract thinking separately and return the clean JSON string.
    """
    from memorycore.extraction import _call_llm as _base_call
    import re as _re
    raw = _base_call(system, prompt, config)
    # Extract <think>...</think> block if present
    thinking_match = _re.search(r"<think>(.*?)</think>", raw, _re.DOTALL)
    thinking = thinking_match.group(1).strip() if thinking_match else ""
    # Strip thinking block from the JSON content
    content = _re.sub(r"<think>.*?</think>", "", raw, flags=_re.DOTALL).strip()
    # Strip markdown code fences: ```json...``` or ```...```
    fence_match = _re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
    if fence_match:
        content = fence_match.group(1).strip()
    # If still not clean JSON, try to find the outermost { ... }
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


def _fetch_active_memories(limit: int) -> list[dict[str, Any]]:
    from memorycore.storage.db import _managed_query
    return _managed_query(
        "SELECT id, title, content, type, importance, confidence, feedback_score, "
        "injected_count, updated_at, created_at, valid_from, valid_until, "
        "last_accessed_at, last_injected_at FROM memories "
        "WHERE status IN ('active', 'candidate') "
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
    """One vector scan returning all pairs >= sim_threshold*0.8.

    Only pairs where BOTH sides are in the active memories list are returned.
    Qdrant may contain stale vectors for archived/superseded records — those
    are silently skipped here so callers never see non-active candidates.
    """
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


def _llm_judge_duplicates(
    pairs: list[tuple[dict, dict, float]],
    llm_config: Any,
    batch_size: int = 10,
    content_max_chars: int = 2000,
    prompt_style: str = "aggressive",
    config: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], set[str]]:
    """Ask LLM to confirm which pairs are true duplicates."""
    full_config = config or {}
    results = []
    evaluated_ids: set[str] = set()
    for i in range(0, len(pairs), batch_size):
        batch = pairs[i: i + batch_size]
        items_text = ""
        for idx, (a, b, score) in enumerate(batch):
            evaluated_ids.add(a["id"])
            evaluated_ids.add(b["id"])
            items_text += (
                f"\n[{idx}]\n"
                f"A: title={a.get('title')!r} {_temporal_tag(a)}\n"
                f"  content={a.get('content', '')[:content_max_chars]!r}\n"
                f"B: title={b.get('title')!r} {_temporal_tag(b)}\n"
                f"  content={b.get('content', '')[:content_max_chars]!r}\n"
                f"vector_similarity={score:.3f}\n"
            )
        system = _PROMPT_STYLES.get(prompt_style, {}).get("duplicate") or _PROMPT_STYLES["balanced"]["duplicate"]
        prompt = f"Evaluate these memory pairs for semantic duplication:{items_text}"
        output_language = full_config.get("output_language", "auto")
        lang_suffix = _language_instruction(output_language)
        if lang_suffix:
            system += lang_suffix
        if full_config.get("temporal", {}).get("llm_temporal_prompts", False):
            system += (
                "\n\n# 时间推理规则\n"
                "- 每条记忆的[时间:]标签显示创建和更新日期，请务必参考\n"
                "- 当两条记忆重复时，优先保留(keep=A或B)更新日期更近的那条\n"
                "- 若更新日期相差超过30天，更新日期更近的记忆很可能是事实演变后的最新版本，而非真正重复\n"
            )
        try:
            raw, thinking = _call_llm_with_thinking(prompt, system, llm_config)
        except Exception as exc:
            logger.error("LLM duplicate call failed (batch %d): %s\n", i, exc, exc_info=True)
            raise
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("LLM duplicate JSON parse failed (batch %d), skipping: %s\nraw=%s", i, exc, raw[:200])
            continue
        for item in data.get("results", []):
            idx = item.get("index", 0)
            if not isinstance(idx, int) or idx >= len(batch):
                continue
            a, b, score = batch[idx]
            if item.get("is_duplicate"):
                keep_label = str(item.get("keep") or item.get("keep_id") or "").upper().strip()
                if keep_label == "A":
                    keep_id, drop_id = a["id"], b["id"]
                elif keep_label == "B":
                    keep_id, drop_id = b["id"], a["id"]
                else:
                    use_temporal = full_config.get("temporal", {}).get("enabled", False)
                    if use_temporal and (a.get("updated_at") or b.get("updated_at")):
                        a_ts = a.get("updated_at") or a.get("created_at") or ""
                        b_ts = b.get("updated_at") or b.get("created_at") or ""
                        keep_id = a["id"] if a_ts >= b_ts else b["id"]
                    else:
                        keep_id = a["id"] if a.get("importance", 0) >= b.get("importance", 0) else b["id"]
                    drop_id = b["id"] if keep_id == a["id"] else a["id"]
                merge_info = item.get("merge_info", "")
                action = "archive_and_merge_duplicate" if merge_info else "archive_duplicate"
                results.append({
                    "action": action,
                    "keep_id": keep_id,
                    "drop_id": drop_id,
                    "score": score,
                    "reason": item.get("reason", "semantic duplicate"),
                    "keep_title": a["title"] if keep_id == a["id"] else b["title"],
                    "drop_title": b["title"] if drop_id == b["id"] else a["title"],
                    "merge_info": merge_info,
                    "llm_thinking": thinking,
                    "llm_raw": raw,
                    "llm_prompt": prompt,
                })
    return results, evaluated_ids


# ---------------------------------------------------------------------------
# 2. Contradiction detection
# ---------------------------------------------------------------------------

def _llm_judge_contradictions(
    pairs: list[tuple[dict, dict, float]],
    llm_config: Any,
    batch_size: int = 10,
    content_max_chars: int = 2000,
    prompt_style: str = "aggressive",
    config: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], set[str]]:
    """Ask LLM to detect contradictions in memory pairs."""
    full_config = config or {}
    results = []
    evaluated_ids: set[str] = set()
    for i in range(0, len(pairs), batch_size):
        batch = pairs[i: i + batch_size]
        items_text = ""
        for idx, (a, b, score) in enumerate(batch):
            evaluated_ids.add(a["id"])
            evaluated_ids.add(b["id"])
            items_text += (
                f"\n[{idx}]\n"
                f"A: {a.get('title')!r} {_temporal_tag(a)}\n"
                f"  — {a.get('content', '')[:content_max_chars]!r}\n"
                f"B: {b.get('title')!r} {_temporal_tag(b)}\n"
                f"  — {b.get('content', '')[:content_max_chars]!r}\n"
            )
        system = _PROMPT_STYLES.get(prompt_style, {}).get("contradiction") or _PROMPT_STYLES["balanced"]["contradiction"]
        prompt = f"Check these memory pairs for contradictions:{items_text}"
        output_language = full_config.get("output_language", "auto")
        lang_suffix = _language_instruction(output_language)
        if lang_suffix:
            system += lang_suffix
        if full_config.get("temporal", {}).get("llm_temporal_prompts", False):
            system += (
                "\n\n# 时间推理规则\n"
                "- 每条记忆的[时间:]标签显示创建和更新日期，请务必参考\n"
                "- 更新日期更近的记忆更可能正确，newer 应指向 A 或 B 中 updated 字段更新的那条\n"
                "- 时间相差超过30天的相同主题记忆很可能是时间演变（temporal supersession），而非真正的矛盾\n"
                "- 若时间差超过180天，优先标记为 supersession 而非 contradiction\n"
            )
        try:
            raw, thinking = _call_llm_with_thinking(prompt, system, llm_config)
        except Exception as exc:
            logger.error("LLM contradiction call failed (batch %d): %s\n", i, exc, exc_info=True)
            raise
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("LLM contradiction JSON parse failed (batch %d), skipping: %s\nraw=%s", i, exc, raw[:200])
            continue
        for item in data.get("results", []):
            idx = item.get("index", 0)
            if not isinstance(idx, int) or idx >= len(batch):
                continue
            a, b, score = batch[idx]
            if item.get("contradicts"):
                newer_label = str(item.get("newer") or item.get("newer_id") or "").upper().strip()
                if newer_label == "A":
                    newer_id, older_id = a["id"], b["id"]
                elif newer_label == "B":
                    newer_id, older_id = b["id"], a["id"]
                else:
                    a_ts = a.get("updated_at") or a.get("created_at") or ""
                    b_ts = b.get("updated_at") or b.get("created_at") or ""
                    newer_id = a["id"] if a_ts >= b_ts else b["id"]
                    older_id = b["id"] if newer_id == a["id"] else a["id"]
                results.append({
                    "action": "mark_contradicted",
                    "newer_id": newer_id,
                    "older_id": older_id,
                    "score": score,
                    "reason": item.get("reason", "semantic contradiction"),
                    "newer_title": a["title"] if newer_id == a["id"] else b["title"],
                    "older_title": b["title"] if older_id == b["id"] else a["title"],
                    "llm_thinking": thinking,
                    "llm_raw": raw,
                    "llm_prompt": prompt,
                })
    return results, evaluated_ids


# ---------------------------------------------------------------------------
# 3. Importance re-evaluation
# ---------------------------------------------------------------------------

def _llm_reassess_importance(
    memories: list[dict[str, Any]],
    llm_config: Any,
    batch_size: int = 10,
    content_max_chars: int = 2000,
    prompt_style: str = "aggressive",
    keep_threshold: float = 0.02,
    config: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], set[str]]:
    """Ask LLM to re-score importance for memories that may be stale or over-valued."""
    full_config = config or {}
    results = []
    evaluated_ids: set[str] = set()
    for i in range(0, len(memories), batch_size):
        batch = memories[i: i + batch_size]
        items_text = ""
        for idx, m in enumerate(batch):
            evaluated_ids.add(m["id"])
            items_text += (
                f"[{idx}] id={m['id'][:8]} type={m.get('type')} "
                f"importance={m.get('importance', 0.5):.2f} "
                f"injected={m.get('injected_count', 0)} "
                f"feedback={m.get('feedback_score', 0):.1f} "
                f"{_temporal_tag(m)}\n"
                f"  title: {m.get('title')!r}\n"
                f"  content: {m.get('content', '')[:content_max_chars]!r}\n"
            )
        system = _PROMPT_STYLES.get(prompt_style, {}).get("importance") or _PROMPT_STYLES["balanced"]["importance"]
        prompt = f"Re-evaluate the long-term importance of these memories:\n{items_text}"
        output_language = full_config.get("output_language", "auto")
        lang_suffix = _language_instruction(output_language)
        if lang_suffix:
            system += lang_suffix
        if full_config.get("temporal", {}).get("llm_temporal_prompts", False):
            system += (
                "\n\n# 时间推理规则\n"
                "- 每条记忆的[时间:]标签显示创建、更新日期及距今天数，请务必参考\n"
                "- 距今超过180天且从未被访问(injected=0)的记忆应大幅降低重要性(downgrade或archive)\n"
                "- 最近30天内更新的记忆不应轻易降级，即使注入次数为0\n"
                "- 有最后访问记录的记忆说明仍在被使用，应维持或提升重要性\n"
            )
        try:
            raw, thinking = _call_llm_with_thinking(prompt, system, llm_config)
        except Exception as exc:
            logger.error("LLM importance call failed (batch %d): %s\n", i, exc, exc_info=True)
            raise
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("LLM importance JSON parse failed (batch %d), skipping: %s\nraw=%s", i, exc, raw[:200])
            continue
        for item in data.get("results", []):
            idx = item.get("index", 0)
            if not isinstance(idx, int) or idx >= len(batch):
                continue
            m = batch[idx]
            action = item.get("action", "keep")
            new_imp = float(item.get("new_importance", m.get("importance", 0.5)))
            new_imp = max(0.0, min(1.0, new_imp))
            if action == "keep" and abs(new_imp - m.get("importance", 0.5)) < keep_threshold:
                continue
            results.append({
                "action": action,
                "id": m["id"],
                "title": m.get("title"),
                "old_importance": m.get("importance", 0.5),
                "new_importance": new_imp,
                "reason": item.get("reason", ""),
                "llm_thinking": thinking,
                "llm_raw": raw,
                "llm_prompt": prompt,
            })
    return results, evaluated_ids


# ---------------------------------------------------------------------------
# 4. Long-content split detection
# ---------------------------------------------------------------------------

def _llm_detect_splittable(
    memories: list[dict[str, Any]],
    llm_config: Any,
    batch_size: int = 10,
    content_max_chars: int = 2000,
    prompt_style: str = "aggressive",
    config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Ask LLM to identify memories whose content bundles multiple distinct facts
    that would be better stored as separate atomic memories."""
    full_config = config or {}
    results = []
    for i in range(0, len(memories), batch_size):
        batch = memories[i: i + batch_size]
        items_text = ""
        for idx, m in enumerate(batch):
            items_text += (
                f"\n[{idx}] id={m['id'][:8]} type={m.get('type')} {_temporal_tag(m)}\n"
                f"  title: {m.get('title')!r}\n"
                f"  content ({len(m.get('content',''))} chars): {m.get('content', '')[:content_max_chars]!r}\n"
            )
        system = _PROMPT_STYLES.get(prompt_style, {}).get("split") or _PROMPT_STYLES["balanced"]["split"]
        prompt = f"Analyse these memories for split opportunities:{items_text}"
        output_language = full_config.get("output_language", "auto")
        lang_suffix = _language_instruction(output_language)
        if lang_suffix:
            system += lang_suffix
        try:
            raw, thinking = _call_llm_with_thinking(prompt, system, llm_config)
        except Exception as exc:
            logger.error("LLM split call failed (batch %d): %s\n", i, exc, exc_info=True)
            raise
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("LLM split JSON parse failed (batch %d), skipping: %s\nraw=%s", i, exc, raw[:200])
            continue
        for item in data.get("results", []):
            idx = item.get("index", 0)
            if not isinstance(idx, int) or idx >= len(batch):
                continue
            if not item.get("splittable"):
                continue
            m = batch[idx]
            results.append({
                "action": "split",
                "id": m["id"],
                "title": m.get("title"),
                "reason": item.get("reason", "compound memory"),
                "sub_memories": item.get("sub_memories", []),
                "llm_thinking": thinking,
                "llm_raw": raw,
                "llm_prompt": prompt,
            })
    return results


# ---------------------------------------------------------------------------
# 5. Knowledge graph link discovery
# ---------------------------------------------------------------------------

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


def _find_link_candidates(
    vs: Any,
    memories: list[dict[str, Any]],
    sim_threshold: float,
    link_upper: float = 0.75,
    max_pairs: int = 100,
) -> list[tuple[dict, dict, float]]:
    """Find memory pairs suitable for graph linking: similarity in [sim_threshold, link_upper],
    no existing link, orphan memories prioritized."""
    from memorycore.storage.db import read_conn

    with read_conn() as conn:
        existing_links: set[frozenset[str]] = set()
        for row in conn.execute("SELECT source_id, target_id FROM memory_links").fetchall():
            existing_links.add(frozenset([row["source_id"], row["target_id"]]))
        orphan_ids: set[str] = set()
        for row in conn.execute(
            "SELECT m.id FROM memories m WHERE m.status IN ('active','candidate') "
            "AND NOT EXISTS (SELECT 1 FROM memory_links ml WHERE ml.source_id = m.id OR ml.target_id = m.id)"
        ).fetchall():
            orphan_ids.add(row["id"])

    recently_reviewed = _get_recently_reviewed_ids("llm_link_discovery")
    eligible = [m for m in memories if m["id"] not in recently_reviewed]
    orphans_first = sorted(eligible, key=lambda m: m["id"] not in orphan_ids)

    seen: set[frozenset[str]] = set()
    pairs: list[tuple[dict, dict, float]] = []
    by_id = {m["id"]: m for m in eligible}
    missing_ids: set[str] = set()

    for mem in orphans_first:
        if len(pairs) >= max_pairs * 3:
            break
        text = f"{mem.get('title', '')} {mem.get('content', '')}".strip()
        if not text:
            continue
        try:
            results = vs.search(text, top_k=6, score_threshold=sim_threshold)
        except Exception:
            continue
        for r in results:
            other_id = r.id
            if other_id == mem["id"] or r.score > link_upper:
                continue
            key = frozenset([mem["id"], other_id])
            if key in seen or key in existing_links:
                continue
            seen.add(key)
            if other_id not in by_id:
                missing_ids.add(other_id)
                pairs.append((mem, {"id": other_id, "_score": r.score}, r.score))
            else:
                pairs.append((mem, by_id[other_id], r.score))

    if missing_ids:
        fetched = _fetch_memories_by_ids(list(missing_ids))
        resolved = []
        for a, b, score in pairs:
            if "_score" in b:
                b_full = fetched.get(b["id"])
                if b_full:
                    resolved.append((a, b_full, score))
            else:
                resolved.append((a, b, score))
        pairs = resolved

    return sorted(pairs, key=lambda x: x[2], reverse=True)[:max_pairs]


def _llm_discover_links(
    pairs: list[tuple[dict, dict, float]],
    llm_config: Any,
    batch_size: int = 10,
    content_max_chars: int = 2000,
    prompt_style: str = "aggressive",
    config: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], set[str]]:
    """Ask LLM to classify semantic relationships between memory pairs for graph linking."""
    full_config = config or {}
    results = []
    evaluated_ids: set[str] = set()
    valid_relations = {"related_to", "supports", "part_of", "supersedes"}

    for i in range(0, len(pairs), batch_size):
        batch = pairs[i: i + batch_size]
        items_text = ""
        for idx, (a, b, score) in enumerate(batch):
            evaluated_ids.add(a["id"])
            evaluated_ids.add(b["id"])
            items_text += (
                f"\n[{idx}]\n"
                f"A: title={a.get('title')!r} {_temporal_tag(a)}\n"
                f"  content={a.get('content', '')[:content_max_chars]!r}\n"
                f"B: title={b.get('title')!r} {_temporal_tag(b)}\n"
                f"  content={b.get('content', '')[:content_max_chars]!r}\n"
                f"similarity={score:.3f}\n"
            )
        system = _LINK_DISCOVERY_PROMPTS.get(prompt_style) or _LINK_DISCOVERY_PROMPTS["balanced"]
        prompt = f"Analyze these memory pairs for semantic relationships:\n{items_text}"
        output_language = full_config.get("output_language", "auto")
        lang_suffix = _language_instruction(output_language)
        if lang_suffix:
            system += lang_suffix
        try:
            raw, thinking = _call_llm_with_thinking(prompt, system, llm_config)
        except Exception as exc:
            logger.error("LLM link discovery call failed (batch %d): %s", i, exc, exc_info=True)
            raise
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("LLM link discovery JSON parse failed (batch %d), skipping: %s\nraw=%s", i, exc, raw[:200])
            continue
        for item in data.get("results", []):
            idx = item.get("index", 0)
            if not isinstance(idx, int) or idx >= len(batch):
                continue
            relation = str(item.get("relation") or "none").lower().strip()
            if relation not in valid_relations:
                continue
            a, b, score = batch[idx]
            direction = str(item.get("direction") or "A->B").upper()
            if direction.startswith("B"):
                source_id, target_id = b["id"], a["id"]
            else:
                source_id, target_id = a["id"], b["id"]
            results.append({
                "action": "create_link",
                "source_id": source_id,
                "target_id": target_id,
                "relation_type": relation,
                "score": score,
                "reason": item.get("reason", ""),
                "llm_thinking": thinking,
                "llm_raw": raw,
                "llm_prompt": prompt,
            })

    return results, evaluated_ids


def llm_curator_report(
    config: dict[str, Any] | None = None,
    limit: int = 10000,
    sim_threshold: float | None = None,
) -> dict[str, Any]:
    """Run LLM-enhanced curation analysis. Returns structured report (no writes)."""
    t_start = _time.monotonic()
    from memorycore.models import load_config
    full_config = config or load_config()
    cfg = full_config.get("llm_curator", {})

    batch_size = cfg.get("batch_size", 10)
    importance_limit = cfg.get("importance_limit", 1000)
    split_threshold = cfg.get("split_content_threshold", 400)
    content_max_chars = cfg.get("content_max_chars", 2000)
    prompt_style = cfg.get("prompt_style", "aggressive")
    keep_threshold = cfg.get("keep_threshold", 0.02)
    effective_sim = sim_threshold if sim_threshold is not None else cfg.get("sim_threshold", 0.60)
    max_dedup = cfg.get("max_dedup_pairs", 200)
    max_contra = cfg.get("max_contradiction_pairs", 200)
    max_split = cfg.get("max_split_candidates", 100)

    errors: list[str] = []
    timing: dict[str, int] = {}
    diagnostics: dict[str, Any] = {
        "total_memories_fetched": 0,
        "memories_after_cooldown_filter": 0,
        "dedup_pairs_found": 0,
        "dedup_llm_calls": 0,
        "contradiction_pairs_found": 0,
        "contradiction_llm_calls": 0,
        "importance_candidates": 0,
        "importance_skipped_keep": 0,
        "split_candidates_checked": 0,
    }

    try:
        llm_config = _load_extraction_config(full_config)
        curator_temp = cfg.get("temperature", 0.6)
        llm_config.temperature = curator_temp
    except Exception as exc:
        return {"errors": [f"LLM config load failed: {exc}"], "semantic_duplicates": [],
                "contradictions": [], "importance_reassessments": []}

    try:
        vs = _get_vector_store(full_config)
        vs_available = getattr(vs, "available", False)
    except Exception as exc:
        vs_available = False
        errors.append(f"Vector store unavailable: {exc}")

    memories = _fetch_active_memories(limit)
    diagnostics["total_memories_fetched"] = len(memories)
    if not memories:
        return {"errors": errors, "diagnostics": diagnostics, "semantic_duplicates": [], "contradictions": [],
                "importance_reassessments": []}

    _cleanup_reviewed_ids()

    all_evaluated_ids: set[str] = set()

    # --- Unified vector scan → dedup + contradiction ---
    semantic_duplicates: list[dict] = []
    contradictions: list[dict] = []

    if vs_available:
        try:
            t0 = _time.monotonic()
            all_pairs = _find_candidate_pairs(vs, memories, effective_sim)
            timing["vector_search_ms"] = int((_time.monotonic() - t0) * 1000)

            dup_pairs = [p for p in all_pairs if p[2] >= effective_sim][:max_dedup]
            contra_pairs = [p for p in all_pairs if p[2] >= effective_sim * 0.8][:max_contra]
            diagnostics["dedup_pairs_found"] = len(dup_pairs)
            diagnostics["contradiction_pairs_found"] = len(contra_pairs)
        except Exception as exc:
            dup_pairs = []
            contra_pairs = []
            errors.append(f"Vector scan failed: {exc}")
            logger.error("vector scan error: %s", exc, exc_info=True)

        if dup_pairs:
            try:
                t0 = _time.monotonic()
                diagnostics["dedup_llm_calls"] = len(dup_pairs) // batch_size + (1 if len(dup_pairs) % batch_size else 0)
                semantic_duplicates, dedup_ids = _llm_judge_duplicates(
                    dup_pairs, llm_config, batch_size=batch_size,
                    content_max_chars=content_max_chars, prompt_style=prompt_style,
                    config=full_config)
                all_evaluated_ids.update(dedup_ids)
                timing["dedup_llm_ms"] = int((_time.monotonic() - t0) * 1000)
            except Exception as exc:
                errors.append(f"Semantic dedup failed: {exc}")
                logger.error("semantic dedup error: %s", exc, exc_info=True)

        if contra_pairs:
            try:
                t0 = _time.monotonic()
                diagnostics["contradiction_llm_calls"] = len(contra_pairs) // batch_size + (1 if len(contra_pairs) % batch_size else 0)
                contradictions, contra_ids = _llm_judge_contradictions(
                    contra_pairs, llm_config, batch_size=batch_size,
                    content_max_chars=content_max_chars, prompt_style=prompt_style,
                    config=full_config)
                all_evaluated_ids.update(contra_ids)
                timing["contradiction_llm_ms"] = int((_time.monotonic() - t0) * 1000)
            except Exception as exc:
                errors.append(f"Contradiction detection failed: {exc}")
                logger.error("contradiction detection error: %s", exc, exc_info=True)
    else:
        errors.append("Vector store not available — skipping semantic dedup and contradiction detection")

    # --- Importance re-evaluation ---
    importance_reassessments: list[dict] = []
    try:
        import random as _random
        recently_reviewed = _get_recently_reviewed_ids()
        all_candidates = [m for m in memories if m["id"] not in recently_reviewed]
        diagnostics["memories_after_cooldown_filter"] = len(all_candidates)
        _random.shuffle(all_candidates)
        candidates = all_candidates[:importance_limit]
        diagnostics["importance_candidates"] = len(candidates)
        if candidates:
            t0 = _time.monotonic()
            importance_reassessments, imp_ids = _llm_reassess_importance(
                candidates, llm_config, batch_size=batch_size,
                content_max_chars=content_max_chars, prompt_style=prompt_style,
                keep_threshold=keep_threshold, config=full_config)
            all_evaluated_ids.update(imp_ids)
            diagnostics["importance_skipped_keep"] = len(candidates) - len(importance_reassessments)
            timing["importance_llm_ms"] = int((_time.monotonic() - t0) * 1000)
    except Exception as exc:
        errors.append(f"Importance reassessment failed: {exc}")
        logger.error("importance reassessment error: %s", exc, exc_info=True)

    # --- Link discovery (knowledge graph) ---
    link_discoveries: list[dict] = []
    if vs_available:
        max_link = cfg.get("max_link_pairs", 100)
        try:
            t0 = _time.monotonic()
            link_pairs = _find_link_candidates(vs, memories, effective_sim, max_pairs=max_link)
            if link_pairs:
                link_discoveries, link_ids = _llm_discover_links(
                    link_pairs, llm_config, batch_size=batch_size,
                    content_max_chars=content_max_chars, prompt_style=prompt_style,
                    config=full_config)
                all_evaluated_ids.update(link_ids)
                _mark_reviewed(list(link_ids), review_type="llm_link_discovery")
            timing["link_discovery_ms"] = int((_time.monotonic() - t0) * 1000)
        except Exception as exc:
            errors.append(f"Link discovery failed: {exc}")
            logger.error("link discovery error: %s", exc, exc_info=True)

    # --- Long-content split detection ---
    split_candidates: list[dict] = []
    try:
        long_memories = [
            m for m in memories
            if len(m.get("content", "")) > split_threshold
        ][:max_split]
        diagnostics["split_candidates_checked"] = len(long_memories)
        if long_memories:
            t0 = _time.monotonic()
            split_candidates = _llm_detect_splittable(
                long_memories, llm_config, batch_size=batch_size,
                content_max_chars=content_max_chars, prompt_style=prompt_style,
                config=full_config)
            timing["split_llm_ms"] = int((_time.monotonic() - t0) * 1000)
    except Exception as exc:
        errors.append(f"Split detection failed: {exc}")
        logger.error("split detection error: %s", exc, exc_info=True)

    # Full cooldown: mark ALL evaluated memories, not just those with findings
    all_evaluated_ids.discard("")
    diagnostics["cooldown_registered"] = len(all_evaluated_ids)
    if all_evaluated_ids:
        _mark_reviewed(list(all_evaluated_ids))

    timing["total_ms"] = int((_time.monotonic() - t_start) * 1000)
    diagnostics["timing"] = timing

    logger.info(
        "[llm-curator] report: memories=%d dedup_pairs=%d contradictions=%d importance=%d links=%d splits=%d errors=%d total_ms=%d",
        diagnostics["total_memories_fetched"],
        diagnostics["dedup_pairs_found"],
        len(contradictions),
        len(importance_reassessments),
        len(link_discoveries),
        len(split_candidates),
        len(errors),
        timing["total_ms"],
    )

    return {
        "semantic_duplicates": semantic_duplicates,
        "contradictions": contradictions,
        "importance_reassessments": importance_reassessments,
        "link_discoveries": link_discoveries,
        "split_candidates": split_candidates,
        "errors": errors,
        "diagnostics": diagnostics,
        "summary": {
            "total_memories": diagnostics["total_memories_fetched"],
            "semantic_duplicates": len(semantic_duplicates),
            "contradictions": len(contradictions),
            "importance_reassessments": len(importance_reassessments),
            "link_discoveries": len(link_discoveries),
            "split_candidates": len(split_candidates),
            "dedup_pairs_found": diagnostics["dedup_pairs_found"],
            "contradiction_pairs_found": diagnostics["contradiction_pairs_found"],
            "importance_candidates": diagnostics["importance_candidates"],
            "importance_skipped_keep": diagnostics["importance_skipped_keep"],
        },
    }


def _batch_report(category: str, findings: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "semantic_duplicates": findings if category == "semantic_duplicates" else [],
        "contradictions": findings if category == "contradictions" else [],
        "importance_reassessments": findings if category == "importance_reassessments" else [],
        "split_candidates": findings if category == "split_candidates" else [],
    }


def _summary_from_counts(counts: dict[str, int], total_memories: int = 0) -> dict[str, int]:
    return {
        "total_memories": total_memories,
        "semantic_duplicates": counts.get("semantic_duplicates", 0),
        "contradictions": counts.get("contradictions", 0),
        "importance_reassessments": counts.get("importance_reassessments", 0),
        "link_discoveries": counts.get("link_discoveries", 0),
        "split_candidates": counts.get("split_candidates", 0),
        "decisions_created": counts.get("decisions_created", 0),
        "batches_completed": counts.get("batches_completed", 0),
        "batches_failed": counts.get("batches_failed", 0),
    }


def run_llm_curator_incremental(
    job_id: str,
    config: dict[str, Any] | None = None,
    limit: int = 200,
    sim_threshold: float | None = None,
    apply: bool = False,
    rebuild_vectors: bool = True,
) -> dict[str, Any]:
    """Run LLM curation and persist decisions after each completed batch."""
    from memorycore.storage.llm_curator_jobs import _diag
    import os as _os
    t_start = _time.monotonic()
    _diag(f"CURATOR_START: job={job_id} pid={_os.getpid()} limit={limit} sim={sim_threshold} apply={apply}")
    from memorycore.models import load_config
    from memorycore.storage.governance import convert_llm_findings_to_decisions
    from memorycore.storage.llm_curator_jobs import (
        finish_llm_curator_batch,
        start_llm_curator_batch,
        update_llm_curator_job,
    )

    full_config = config or load_config()
    cfg = full_config.get("llm_curator", {})
    batch_size = max(1, int(cfg.get("batch_size", 10)))
    importance_limit = int(cfg.get("importance_limit", 1000))
    split_threshold = int(cfg.get("split_content_threshold", 400))
    content_max_chars = int(cfg.get("content_max_chars", 2000))
    prompt_style = cfg.get("prompt_style", "aggressive")
    keep_threshold = float(cfg.get("keep_threshold", 0.02))
    effective_sim = sim_threshold if sim_threshold is not None else float(cfg.get("sim_threshold", 0.60))
    max_dedup = int(cfg.get("max_dedup_pairs", 200))
    max_contra = int(cfg.get("max_contradiction_pairs", 200))
    max_split = int(cfg.get("max_split_candidates", 100))
    errors: list[str] = []
    counts: dict[str, int] = {}
    all_evaluated_ids: set[str] = set()

    _owner_pid = _os.getpid()

    def progress(stage: str, extra: dict[str, Any] | None = None) -> None:
        payload = {"stage": stage, "elapsed_ms": int((_time.monotonic() - t_start) * 1000), "pid": _owner_pid, **(extra or {})}
        update_llm_curator_job(job_id, progress=payload, summary=_summary_from_counts(counts, counts.get("total_memories", 0)), errors=errors)

    def persist_batch(stage: str, batch_index: int, category: str, candidates: list[Any], run_batch: Any) -> None:
        batch = start_llm_curator_batch(job_id, stage, batch_index, candidate_count=len(candidates))
        progress(stage, {"batch_index": batch_index, "candidate_count": len(candidates)})
        try:
            result = run_batch(candidates)
            if isinstance(result, tuple):
                findings, evaluated_ids = result
                all_evaluated_ids.update(evaluated_ids)
            else:
                findings = result
            report = _batch_report(category, findings)
            governance = convert_llm_findings_to_decisions(
                report,
                auto_apply=apply,
                curator_job_id=job_id,
                curator_batch_id=batch["id"],
            )
            decisions_count = int(governance.get("decisions_created", 0))
            counts[category] = counts.get(category, 0) + len(findings)
            counts["decisions_created"] = counts.get("decisions_created", 0) + decisions_count
            counts["batches_completed"] = counts.get("batches_completed", 0) + 1
            finish_llm_curator_batch(batch["id"], finding_count=len(findings), decision_count=decisions_count)
            progress(stage, {"batch_index": batch_index, "decision_count": decisions_count})
        except Exception as exc:
            message = f"{stage} batch {batch_index} failed: {exc}"
            errors.append(message)
            counts["batches_failed"] = counts.get("batches_failed", 0) + 1
            finish_llm_curator_batch(batch["id"], status="failed", error={"message": str(exc)})
            logger.error("[llm-curator job %s] %s", job_id, message, exc_info=True)
            progress(stage, {"batch_index": batch_index, "error": str(exc)})

    try:
        llm_config = _load_extraction_config(full_config)
        llm_config.temperature = cfg.get("temperature", 0.6)
    except Exception as exc:
        errors.append(f"LLM config load failed: {exc}")
        update_llm_curator_job(job_id, status="failed", errors=errors, finished=True)
        return {"errors": errors, "summary": _summary_from_counts(counts)}

    try:
        vs = _get_vector_store(full_config)
        vs_available = getattr(vs, "available", False)
    except Exception as exc:
        vs_available = False
        errors.append(f"Vector store unavailable: {exc}")

    memories = _fetch_active_memories(limit)
    counts["total_memories"] = len(memories)
    if not memories:
        summary = _summary_from_counts(counts)
        update_llm_curator_job(job_id, status="done", summary=summary, errors=errors, finished=True)
        return {"errors": errors, "summary": summary}

    _cleanup_reviewed_ids()
    progress("vector_scan")
    _diag(f"STAGE: vector_scan started, {len(memories)} memories loaded")

    if vs_available:
        try:
            all_pairs = _find_candidate_pairs(vs, memories, effective_sim)
            dup_pairs = [p for p in all_pairs if p[2] >= effective_sim][:max_dedup]
            contra_pairs = [p for p in all_pairs if p[2] >= effective_sim * 0.8][:max_contra]
            counts["dedup_pairs_found"] = len(dup_pairs)
            counts["contradiction_pairs_found"] = len(contra_pairs)
            progress("vector_scan", {"dedup_pairs_found": len(dup_pairs), "contradiction_pairs_found": len(contra_pairs)})
        except Exception as exc:
            dup_pairs = []
            contra_pairs = []
            errors.append(f"Vector scan failed: {exc}")
            logger.error("vector scan error: %s", exc, exc_info=True)
        _diag(f"STAGE: dedup starting, {len(dup_pairs)} pairs, batch_size={batch_size}")
        for batch_index, start in enumerate(range(0, len(dup_pairs), batch_size)):
            candidates = dup_pairs[start:start + batch_size]
            persist_batch(
                "dedup",
                batch_index,
                "semantic_duplicates",
                candidates,
                lambda batch: _llm_judge_duplicates(batch, llm_config, batch_size=len(batch), content_max_chars=content_max_chars, prompt_style=prompt_style, config=full_config),
            )
        _diag(f"STAGE: contradiction starting, {len(contra_pairs)} pairs")
        for batch_index, start in enumerate(range(0, len(contra_pairs), batch_size)):
            candidates = contra_pairs[start:start + batch_size]
            persist_batch(
                "contradiction",
                batch_index,
                "contradictions",
                candidates,
                lambda batch: _llm_judge_contradictions(batch, llm_config, batch_size=len(batch), content_max_chars=content_max_chars, prompt_style=prompt_style, config=full_config),
            )
    else:
        errors.append("Vector store not available — skipping semantic dedup and contradiction detection")

    _diag(f"STAGE: importance starting, elapsed={int(_time.monotonic()-t_start)}s")
    try:
        import random as _random
        recently_reviewed = _get_recently_reviewed_ids()
        all_candidates = [m for m in memories if m["id"] not in recently_reviewed]
        _random.shuffle(all_candidates)
        candidates = all_candidates[:importance_limit]
        counts["importance_candidates"] = len(candidates)
        for batch_index, start in enumerate(range(0, len(candidates), batch_size)):
            batch_candidates = candidates[start:start + batch_size]
            persist_batch(
                "importance",
                batch_index,
                "importance_reassessments",
                batch_candidates,
                lambda batch: _llm_reassess_importance(batch, llm_config, batch_size=len(batch), content_max_chars=content_max_chars, prompt_style=prompt_style, keep_threshold=keep_threshold, config=full_config),
            )
    except Exception as exc:
        errors.append(f"Importance reassessment failed: {exc}")
        logger.error("importance reassessment error: %s", exc, exc_info=True)

    _diag(f"STAGE: split starting, elapsed={int(_time.monotonic()-t_start)}s")
    try:
        long_memories = [m for m in memories if len(m.get("content", "")) > split_threshold][:max_split]
        counts["split_candidates_checked"] = len(long_memories)
        for batch_index, start in enumerate(range(0, len(long_memories), batch_size)):
            batch_candidates = long_memories[start:start + batch_size]
            persist_batch(
                "split",
                batch_index,
                "split_candidates",
                batch_candidates,
                lambda batch: _llm_detect_splittable(batch, llm_config, batch_size=len(batch), content_max_chars=content_max_chars, prompt_style=prompt_style, config=full_config),
            )
    except Exception as exc:
        errors.append(f"Split detection failed: {exc}")
        logger.error("split detection error: %s", exc, exc_info=True)

    if all_evaluated_ids:
        _mark_reviewed(list(all_evaluated_ids))

    if rebuild_vectors:
        try:
            from memorycore.storage import memory_rebuild_vectors
            memory_rebuild_vectors()
        except Exception as exc:
            errors.append(f"Vector rebuild failed: {exc}")

    summary = _summary_from_counts(counts)
    status = "failed" if errors and counts.get("decisions_created", 0) == 0 else "succeeded" if counts.get("decisions_created", 0) else "done"
    _diag(f"CURATOR_END: job={job_id} status={status} elapsed={int(_time.monotonic()-t_start)}s decisions={counts.get('decisions_created',0)} errors={len(errors)}")
    update_llm_curator_job(job_id, status=status, progress={"stage": "finished", "pid": _owner_pid}, summary=summary, errors=errors, finished=True)
    try:
        from memorycore.storage.audit import log_audit_event
        log_audit_event("llm_curator_run", agent="llm_curator", detail={"job_id": job_id, "incremental": True, "summary": summary, "errors": errors})
    except Exception:
        logger.debug("failed to log incremental llm_curator_run audit event", exc_info=True)
    return {"errors": errors, "summary": summary, "status": status}


def run_llm_curator(
    config: dict[str, Any] | None = None,
    limit: int = 200,
    sim_threshold: float | None = None,
    apply: bool = False,
    rebuild_vectors: bool = True,
) -> dict[str, Any]:
    """Run LLM curation, optionally apply findings, and record run metadata."""
    report = llm_curator_report(config=config, limit=limit, sim_threshold=sim_threshold)
    applied: dict[str, Any] | None = None
    governance: dict[str, Any] | None = None
    try:
        from memorycore.storage.governance import convert_llm_findings_to_decisions

        governance = convert_llm_findings_to_decisions(report, auto_apply=apply)
        report = {**report, "governance": governance}
        if apply:
            applied = {"governance_auto_applied": len(governance.get("auto_applied", []))}
            report = {**report, "applied": applied}
    except Exception as exc:
        logger.warning("governance decision conversion failed: %s", exc)
        report = {**report, "governance_error": str(exc)}

    if rebuild_vectors:
        try:
            from memorycore.storage import memory_rebuild_vectors

            report = {**report, "rebuild_vectors": memory_rebuild_vectors()}
        except Exception as exc:
            report = {**report, "rebuild_vectors_error": str(exc)}

    try:
        from memorycore.storage.audit import log_audit_event

        log_audit_event(
            "llm_curator_run",
            agent="llm_curator",
            detail={
                "dry_run": not apply,
                "summary": report.get("summary", {}),
                "errors": report.get("errors", []),
                "applied": applied,
                "governance": governance,
                "rebuild_vectors_error": report.get("rebuild_vectors_error"),
            },
        )
    except Exception:
        logger.debug("failed to log llm_curator_run audit event", exc_info=True)

    return report


def apply_llm_curator(report: dict[str, Any], dry_run: bool = True) -> dict[str, Any]:
    """Apply LLM curator actions through the governance mutation executor."""
    if dry_run:
        return {"dry_run": True, "planned": report.get("summary", {})}

    applied: dict[str, int] = {
        "archived": 0,
        "contradicted": 0,
        "importance_updated": 0,
        "duplicate_merge_audits": 0,
        "split_links_created": 0,
        "split_links_skipped": 0,
        "duplicate_atomic_facts_archived": 0,
        "split": 0,
        "split_children_created": 0,
        "split_children_skipped": 0,
        "links_created": 0,
    }
    duplicate_merge_audits: list[dict[str, Any]] = []
    duplicate_atomic_fact_audits: list[dict[str, Any]] = []
    requests: list[MutationRequest] = []

    _append_duplicate_requests(report, requests, applied, duplicate_merge_audits)
    _append_contradiction_requests(report, requests)
    _append_importance_requests(report, requests)
    _append_link_discovery_requests(report, requests)
    _append_split_requests(report, requests, applied)
    _append_duplicate_atomic_fact_requests(requests, duplicate_atomic_fact_audits)

    execution = None
    if requests:
        execution = execute_batch(
            requests,
            MutationContext(
                actor="llm_curator",
                origin="llm_curator",
                approval_kind="auto_policy",
                correlation_id=f"llm-curator-{uuid.uuid4()}",
            ),
            idempotency_key=f"llm-curator:{uuid.uuid4()}",
        )
        _count_applied_results(execution, applied)

    from memorycore.storage.audit import log_audit_event
    log_audit_event(
        "llm_curator_apply",
        agent="llm_curator",
        detail={
            **applied,
            "dry_run": False,
            "execution_id": execution.get("execution_id") if execution else "",
            "execution_status": execution.get("status") if execution else "no_op",
            "duplicate_merge_audits": duplicate_merge_audits,
            "duplicate_atomic_fact_audits": duplicate_atomic_fact_audits,
        },
    )
    return {"dry_run": False, "applied": applied, "execution": execution}


def _append_duplicate_requests(
    report: dict[str, Any],
    requests: list[MutationRequest],
    applied: dict[str, int],
    duplicate_merge_audits: list[dict[str, Any]],
) -> None:
    for dup in report.get("semantic_duplicates", []) or []:
        drop_id = dup.get("drop_id")
        keep_id = dup.get("keep_id")
        if drop_id:
            requests.append(_memory_archive_request(str(drop_id), "semantic_duplicate", "low", dup.get("confidence", dup.get("score", 0.95))))
        if keep_id and drop_id and (dup.get("merge_info") or dup.get("action") == "archive_and_merge_duplicate"):
            duplicate_merge_audits.append({
                "keep_id": keep_id,
                "drop_id": drop_id,
                "keep_title": dup.get("keep_title", ""),
                "drop_title": dup.get("drop_title", ""),
                "merge_info": dup.get("merge_info", ""),
                "reason": dup.get("reason", "semantic duplicate"),
            })
            applied["duplicate_merge_audits"] += 1


def _append_contradiction_requests(report: dict[str, Any], requests: list[MutationRequest]) -> None:
    for contra in report.get("contradictions", []) or []:
        older_id = contra.get("older_id")
        if older_id:
            requests.append(MutationRequest(
                action_type="memory_status_update",
                target_type="memory",
                target_id=str(older_id),
                payload={"status": "contradicted"},
                risk_level="medium",
                confidence=float(contra.get("confidence", contra.get("score", 0.9)) or 0.9),
                idempotency_key=f"llm-curator:contradiction:{older_id}",
            ))


def _append_importance_requests(report: dict[str, Any], requests: list[MutationRequest]) -> None:
    for reassess in report.get("importance_reassessments", []) or []:
        action = reassess.get("action", "keep")
        mem_id = reassess.get("id")
        new_imp = reassess.get("new_importance")
        if not mem_id:
            continue
        confidence = float(reassess.get("confidence", 0.95) or 0.95)
        if action == "archive":
            requests.append(_memory_archive_request(str(mem_id), "importance_archive", "low", confidence))
        elif action in ("promote", "downgrade") and new_imp is not None:
            payload: dict[str, Any] = {"importance": float(new_imp)}
            if action == "promote":
                payload["status"] = "active"
            requests.append(MutationRequest(
                action_type="memory_importance_update",
                target_type="memory",
                target_id=str(mem_id),
                payload=payload,
                risk_level="low",
                confidence=confidence,
                idempotency_key=f"llm-curator:importance:{mem_id}:{action}",
            ))


def _append_link_discovery_requests(report: dict[str, Any], requests: list[MutationRequest]) -> None:
    for link in report.get("link_discoveries", []) or []:
        source_id = link.get("source_id")
        target_id = link.get("target_id")
        relation = link.get("relation_type", "related_to")
        if not source_id or not target_id:
            continue
        requests.append(MutationRequest(
            action_type="memory_link_insert",
            target_type="memory_link",
            payload={
                "source_id": source_id,
                "target_id": target_id,
                "relation_type": relation,
                "weight": 0.8,
                "note": f"LLM curator link discovery: {link.get('reason', '')}",
            },
            risk_level="low",
            confidence=0.85,
            idempotency_key=f"llm-curator:link-discovery:{source_id}:{target_id}:{relation}",
        ))


def _append_split_requests(report: dict[str, Any], requests: list[MutationRequest], applied: dict[str, int]) -> None:
    from memorycore.storage.db import read_conn

    for split in report.get("split_candidates", []) or []:
        orig_id = split.get("id")
        sub_memories = split.get("sub_memories", []) or []
        if not orig_id or not sub_memories:
            continue
        with read_conn() as conn:
            orig_row = conn.execute("SELECT * FROM memories WHERE id=?", (orig_id,)).fetchone()
            if not orig_row:
                continue
            orig = row_to_dict(orig_row)
        requests.append(_memory_archive_request(str(orig_id), "llm_split_parent", "medium", split.get("confidence", 0.95)))
        created_for_parent = 0
        for sub in sub_memories:
            sub_title = str(sub.get("title") or "")[:120].strip()
            sub_content = str(sub.get("content") or "").strip()
            if not sub_title or not sub_content:
                continue
            fact_hash = _llm_split_fact_hash(str(orig_id), sub_content)
            existing_id = _existing_split_child_id(str(orig_id), fact_hash)
            child_id = existing_id or str(uuid.uuid5(uuid.NAMESPACE_URL, f"llm-curator:{orig_id}:{fact_hash}"))
            if existing_id:
                applied["split_children_skipped"] += 1
            else:
                raw_imp = sub.get("importance")
                sub_importance = float(max(0.0, min(1.0, raw_imp))) if raw_imp is not None else float(orig.get("importance", 0.5))
                requests.append(MutationRequest(
                    action_type="memory_insert",
                    target_type="memory",
                    target_id=child_id,
                    payload={
                        "id": child_id,
                        "type": orig.get("type", "project_memory"),
                        "scope": orig.get("scope", "global"),
                        "title": sub_title,
                        "content": sub_content,
                        "tags": json.loads(orig.get("tags_json") or "[]"),
                        "source": "llm_curator",
                        "project_path": orig.get("project_path", ""),
                        "confidence": float(orig.get("confidence", 0.7)),
                        "importance": sub_importance,
                        "status": "active",
                        "decay_policy": orig.get("decay_policy", "review"),
                        "metadata": {
                            "kind": "atomic_fact",
                            "parent_id": orig_id,
                            "fact_hash": fact_hash,
                            "atomizer_version": "llm-curator-v1",
                            "source_type": "llm_split",
                        },
                    },
                    risk_level="low",
                    confidence=float(split.get("confidence", 0.95) or 0.95),
                    idempotency_key=f"llm-curator:split-child:{orig_id}:{fact_hash}",
                ))
                created_for_parent += 1
            _append_split_link_requests(requests, str(orig_id), child_id)
        if created_for_parent:
            applied["split"] += 1


def _append_split_link_requests(requests: list[MutationRequest], orig_id: str, child_id: str) -> None:
    for source_id, target_id, relation_type, note in (
        (child_id, orig_id, "part_of", "LLM curator split child fact"),
        (orig_id, child_id, "supports", "LLM curator split generated child fact"),
    ):
        requests.append(MutationRequest(
            action_type="memory_link_insert",
            target_type="memory_link",
            payload={
                "source_id": source_id,
                "target_id": target_id,
                "relation_type": relation_type,
                "weight": 1.0,
                "note": note,
            },
            risk_level="low",
            confidence=0.95,
            idempotency_key=f"llm-curator:split-link:{source_id}:{target_id}:{relation_type}",
        ))


def _append_duplicate_atomic_fact_requests(
    requests: list[MutationRequest],
    duplicate_atomic_fact_audits: list[dict[str, Any]],
) -> None:
    from memorycore.storage.db import read_conn

    with read_conn() as conn:
        duplicate_fact_rows = conn.execute(
            """
            SELECT parent_id, fact_hash, GROUP_CONCAT(id) AS memory_ids
            FROM (
                SELECT id,
                       json_extract(metadata_json, '$.parent_id') AS parent_id,
                       json_extract(metadata_json, '$.fact_hash') AS fact_hash
                FROM memories
                WHERE status NOT IN ('archived')
                  AND json_extract(metadata_json, '$.parent_id') IS NOT NULL
                  AND json_extract(metadata_json, '$.fact_hash') IS NOT NULL
                ORDER BY created_at ASC, id ASC
            )
            GROUP BY parent_id, fact_hash
            HAVING COUNT(*) > 1
            """
        ).fetchall()
    for row in duplicate_fact_rows:
        memory_ids = [mid for mid in str(row["memory_ids"] or "").split(",") if mid]
        if len(memory_ids) < 2:
            continue
        keep_id = memory_ids[0]
        drop_ids = memory_ids[1:]
        for drop_id in drop_ids:
            requests.append(_memory_archive_request(drop_id, "duplicate_atomic_fact", "low", 0.95))
        if drop_ids:
            duplicate_atomic_fact_audits.append({
                "parent_id": row["parent_id"],
                "fact_hash": row["fact_hash"],
                "keep_id": keep_id,
                "archived_ids": drop_ids,
                "reason": "duplicate atomic facts with same parent_id and fact_hash",
            })


def _memory_archive_request(memory_id: str, reason: str, risk_level: str, confidence: Any) -> MutationRequest:
    return MutationRequest(
        action_type="memory_archive",
        target_type="memory",
        target_id=memory_id,
        payload={"status": "archived", "reason": reason},
        risk_level=risk_level,
        confidence=float(confidence or 0.95),
        idempotency_key=f"llm-curator:archive:{reason}:{memory_id}",
    )


def _existing_split_child_id(parent_id: str, fact_hash: str) -> str | None:
    from memorycore.storage.db import read_conn

    with read_conn() as conn:
        row = conn.execute(
            """
            SELECT id FROM memories
            WHERE json_extract(metadata_json, '$.parent_id') = ?
              AND json_extract(metadata_json, '$.fact_hash') = ?
            LIMIT 1
            """,
            (parent_id, fact_hash),
        ).fetchone()
    return str(row["id"]) if row else None


def _count_applied_results(execution: dict[str, Any], applied: dict[str, int]) -> None:
    if execution.get("status") != "applied":
        return
    for result in execution.get("results", []) or []:
        mutation_type = result.get("mutation_type")
        before = result.get("before") or {}
        after = result.get("after") or {}
        if mutation_type == "memory_archive" and before.get("status") != "archived" and after.get("status") == "archived":
            request = _request_from_result(result)
            reason = (request.get("payload") or {}).get("reason", "")
            if reason == "duplicate_atomic_fact":
                applied["duplicate_atomic_facts_archived"] += 1
            else:
                applied["archived"] += 1
        elif mutation_type == "memory_status_update" and after.get("status") == "contradicted":
            applied["contradicted"] += 1
        elif mutation_type == "memory_importance_update":
            applied["importance_updated"] += 1
        elif mutation_type == "memory_insert":
            applied["split_children_created"] += 1
        elif mutation_type == "memory_link_insert":
            if result.get("before") is None:
                applied["split_links_created"] += 1
            else:
                applied["split_links_skipped"] += 1


def _request_from_result(result: dict[str, Any]) -> dict[str, Any]:
    log_id = result.get("log_id")
    if not log_id:
        return {}
    from memorycore.storage.db import read_conn
    with read_conn() as conn:
        row = conn.execute(
            "SELECT request_json FROM governance_mutation_log WHERE id = ? LIMIT 1",
            (log_id,),
        ).fetchone()
    if row:
        try:
            return json.loads(row["request_json"] or "{}")
        except Exception:
            return {}
    return {}
