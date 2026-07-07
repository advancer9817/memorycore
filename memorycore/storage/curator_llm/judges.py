"""LLM judge functions: duplicate, contradiction, importance, split, and link discovery."""
from __future__ import annotations

import json
import logging
from typing import Any

from memorycore.extraction import _language_instruction

from .core import (
    _call_llm_with_thinking,
    _fetch_memories_by_ids,
    _get_recently_reviewed_ids,
    _LINK_DISCOVERY_PROMPTS,
    _PROMPT_STYLES,
    _temporal_tag,
)

logger = logging.getLogger(__name__)


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
    """Ask LLM to identify memories whose content bundles multiple distinct facts."""
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

def _find_link_candidates(
    vs: Any,
    memories: list[dict[str, Any]],
    sim_threshold: float,
    link_upper: float = 0.75,
    max_pairs: int = 100,
) -> list[tuple[dict, dict, float]]:
    """Find memory pairs suitable for graph linking."""
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
