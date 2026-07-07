"""Long-content split detection judge."""
from __future__ import annotations

import json
import logging
from typing import Any

from memorycore.extraction import _language_instruction
from memorycore.storage.curator_llm.core import (
    _PROMPT_STYLES, _call_llm_with_thinking, _temporal_tag,
)

logger = logging.getLogger(__name__)


def _llm_detect_splittable(
    memories: list[dict[str, Any]],
    llm_config: Any,
    batch_size: int = 10,
    content_max_chars: int = 2000,
    prompt_style: str = "aggressive",
    config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
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
                "action": "split", "id": m["id"], "title": m.get("title"),
                "reason": item.get("reason", "compound memory"),
                "sub_memories": item.get("sub_memories", []),
                "llm_thinking": thinking, "llm_raw": raw, "llm_prompt": prompt,
            })
    return results
