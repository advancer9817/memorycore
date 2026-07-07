"""Knowledge graph link discovery judge."""
from __future__ import annotations

import json
import logging
from typing import Any

from memorycore.extraction import _language_instruction
from memorycore.storage.curator_llm.core import (
    _call_llm_with_thinking, _get_recently_reviewed_ids, _fetch_memories_by_ids, _temporal_tag,
)

logger = logging.getLogger(__name__)

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
                "action": "create_link", "source_id": source_id, "target_id": target_id,
                "relation_type": relation, "score": score, "reason": item.get("reason", ""),
                "llm_thinking": thinking, "llm_raw": raw, "llm_prompt": prompt,
            })
    return results, evaluated_ids
