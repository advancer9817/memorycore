"""Semantic deduplication judge."""
from __future__ import annotations

import json
import logging
from typing import Any

from memorycore.extraction import _language_instruction
from memorycore.storage.curator_llm.core import (
    _PROMPT_STYLES, _call_llm_with_thinking, _get_recently_reviewed_ids,
    _fetch_memories_by_ids, _temporal_tag,
)

logger = logging.getLogger(__name__)


def _find_candidate_pairs(
    vs: Any,
    memories: list[dict[str, Any]],
    sim_threshold: float,
) -> list[tuple[dict, dict, float]]:
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
            if other_id == mem["id"] or other_id not in by_id:
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
                    "action": action, "keep_id": keep_id, "drop_id": drop_id,
                    "score": score, "reason": item.get("reason", "semantic duplicate"),
                    "keep_title": a["title"] if keep_id == a["id"] else b["title"],
                    "drop_title": b["title"] if drop_id == b["id"] else a["title"],
                    "merge_info": merge_info, "llm_thinking": thinking,
                    "llm_raw": raw, "llm_prompt": prompt,
                })
    return results, evaluated_ids
