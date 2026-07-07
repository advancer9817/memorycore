"""Contradiction detection judge."""
from __future__ import annotations

import json
import logging
from typing import Any

from memorycore.extraction import _language_instruction
from memorycore.storage.curator_llm.core import (
    _PROMPT_STYLES, _call_llm_with_thinking, _temporal_tag,
)

logger = logging.getLogger(__name__)


def _llm_judge_contradictions(
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
                    "action": "mark_contradicted", "newer_id": newer_id, "older_id": older_id,
                    "score": score, "reason": item.get("reason", "semantic contradiction"),
                    "newer_title": a["title"] if newer_id == a["id"] else b["title"],
                    "older_title": b["title"] if older_id == b["id"] else a["title"],
                    "llm_thinking": thinking, "llm_raw": raw, "llm_prompt": prompt,
                })
    return results, evaluated_ids
