"""Importance re-evaluation judge."""
from __future__ import annotations

import json
import logging
from typing import Any

from memorycore.extraction import _language_instruction
from memorycore.storage.curator_llm.core import (
    _PROMPT_STYLES, _call_llm_with_thinking, _temporal_tag,
)

logger = logging.getLogger(__name__)


def _llm_reassess_importance(
    memories: list[dict[str, Any]],
    llm_config: Any,
    batch_size: int = 10,
    content_max_chars: int = 2000,
    prompt_style: str = "aggressive",
    keep_threshold: float = 0.02,
    config: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], set[str]]:
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
                "action": action, "id": m["id"], "title": m.get("title"),
                "old_importance": m.get("importance", 0.5), "new_importance": new_imp,
                "reason": item.get("reason", ""),
                "llm_thinking": thinking, "llm_raw": raw, "llm_prompt": prompt,
            })
    return results, evaluated_ids
