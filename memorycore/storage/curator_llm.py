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

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Cosine similarity threshold for candidate pairs fed to the LLM
_SIM_THRESHOLD = 0.72
# Max pairs per LLM call to keep prompts manageable
_BATCH_SIZE = 10
# Max memories evaluated for importance re-assessment per run
_IMPORTANCE_LIMIT = 50


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _call_llm(prompt: str, system: str, config: Any) -> str:
    from memorycore.extraction import _call_llm as _base_call
    return _base_call(system, prompt, config)


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
        "injected_count, updated_at FROM memories "
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
        f"injected_count, updated_at FROM memories WHERE id IN ({placeholders})",
        tuple(ids),
    )
    return {r["id"]: r for r in rows}


# ---------------------------------------------------------------------------
# 1. Semantic deduplication
# ---------------------------------------------------------------------------

def _find_semantic_duplicate_candidates(
    vs: Any,
    memories: list[dict[str, Any]],
    sim_threshold: float,
) -> list[tuple[dict, dict, float]]:
    """Return (mem_a, mem_b, score) pairs above sim_threshold, deduplicated."""
    seen: set[frozenset[str]] = set()
    pairs: list[tuple[dict, dict, float]] = []
    by_id = {m["id"]: m for m in memories}
    missing_ids: set[str] = set()

    for mem in memories:
        text = f"{mem.get('title', '')} {mem.get('content', '')}".strip()
        if not text:
            continue
        try:
            results = vs.search(text, top_k=6, score_threshold=sim_threshold)
        except Exception as exc:
            logger.debug("vector search failed for %s: %s", mem["id"], exc)
            continue
        for r in results:
            other_id = r.id
            if other_id == mem["id"]:
                continue
            key = frozenset([mem["id"], other_id])
            if key in seen:
                continue
            seen.add(key)
            if other_id not in by_id:
                missing_ids.add(other_id)
                pairs.append((mem, {"id": other_id, "_score": r.score}, r.score))
            else:
                pairs.append((mem, by_id[other_id], r.score))

    # Fetch any missing memories from DB
    if missing_ids:
        fetched = _fetch_memories_by_ids(list(missing_ids))
        resolved = []
        for a, b, score in pairs:
            if "_score" in b:
                b_full = fetched.get(b["id"])
                if b_full:
                    resolved.append((a, b_full, score))
                # Skip if not found in DB (deleted/archived since index)
            else:
                resolved.append((a, b, score))
        pairs = resolved

    return sorted(pairs, key=lambda x: x[2], reverse=True)


def _llm_judge_duplicates(
    pairs: list[tuple[dict, dict, float]],
    llm_config: Any,
) -> list[dict[str, Any]]:
    """Ask LLM to confirm which pairs are true duplicates."""
    results = []
    for i in range(0, len(pairs), _BATCH_SIZE):
        batch = pairs[i: i + _BATCH_SIZE]
        items_text = ""
        for idx, (a, b, score) in enumerate(batch):
            items_text += (
                f"\n[{idx}]\n"
                f"A: title={a.get('title')!r} content={a.get('content', '')[:200]!r}\n"
                f"B: title={b.get('title')!r} content={b.get('content', '')[:200]!r}\n"
                f"vector_similarity={score:.3f}\n"
            )
        system = (
            "You are a memory curator. Analyse each pair of memories and decide "
            "whether they are true semantic duplicates (same fact, same meaning). "
            "Return a JSON object with key 'results': a list where each element has "
            "'index' (int), 'is_duplicate' (bool), 'reason' (str, ≤30 words), "
            "and 'keep_id' (the id of the memory to keep, or null if unsure)."
        )
        prompt = f"Evaluate these memory pairs for semantic duplication:{items_text}"
        try:
            raw = _call_llm(prompt, system, llm_config)
            data = json.loads(raw)
            for item in data.get("results", []):
                idx = item.get("index", 0)
                if not isinstance(idx, int) or idx >= len(batch):
                    continue
                a, b, score = batch[idx]
                if item.get("is_duplicate"):
                    keep_id = item.get("keep_id")
                    drop_id = b["id"] if keep_id == a["id"] else a["id"]
                    if keep_id not in (a["id"], b["id"]):
                        keep_id = a["id"] if a.get("importance", 0) >= b.get("importance", 0) else b["id"]
                        drop_id = b["id"] if keep_id == a["id"] else a["id"]
                    results.append({
                        "action": "archive_duplicate",
                        "keep_id": keep_id,
                        "drop_id": drop_id,
                        "score": score,
                        "reason": item.get("reason", "semantic duplicate"),
                        "keep_title": a["title"] if keep_id == a["id"] else b["title"],
                        "drop_title": b["title"] if drop_id == b["id"] else a["title"],
                    })
        except Exception as exc:
            logger.warning("LLM duplicate judgement failed: %s", exc)
    return results


# ---------------------------------------------------------------------------
# 2. Contradiction detection
# ---------------------------------------------------------------------------

def _find_contradiction_candidates(
    vs: Any,
    memories: list[dict[str, Any]],
    sim_threshold: float,
) -> list[tuple[dict, dict, float]]:
    """Same as duplicate search but focused on same-type pairs for contradiction check."""
    seen: set[frozenset[str]] = set()
    pairs: list[tuple[dict, dict, float]] = []
    by_id = {m["id"]: m for m in memories}
    missing_ids: set[str] = set()

    for mem in memories:
        text = f"{mem.get('title', '')} {mem.get('content', '')}".strip()
        if not text:
            continue
        try:
            results = vs.search(
                text, top_k=5,
                score_threshold=max(0.60, sim_threshold - 0.12),
            )
        except Exception as exc:
            logger.debug("vector search failed: %s", exc)
            continue
        for r in results:
            other_id = r.id
            if other_id == mem["id"]:
                continue
            key = frozenset([mem["id"], other_id])
            if key in seen:
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

    return pairs


def _llm_judge_contradictions(
    pairs: list[tuple[dict, dict, float]],
    llm_config: Any,
) -> list[dict[str, Any]]:
    """Ask LLM to detect contradictions in memory pairs."""
    results = []
    for i in range(0, len(pairs), _BATCH_SIZE):
        batch = pairs[i: i + _BATCH_SIZE]
        items_text = ""
        for idx, (a, b, score) in enumerate(batch):
            items_text += (
                f"\n[{idx}]\n"
                f"A (id={a['id'][:8]}): {a.get('title')!r} — {a.get('content', '')[:200]!r}\n"
                f"B (id={b['id'][:8]}): {b.get('title')!r} — {b.get('content', '')[:200]!r}\n"
            )
        system = (
            "You are a memory curator. Check each memory pair for semantic contradiction "
            "(one memory states something that conflicts with or invalidates the other). "
            "Similarity alone is NOT contradiction. "
            "Return JSON with key 'results': list of objects with "
            "'index' (int), 'contradicts' (bool), 'reason' (str ≤30 words), "
            "'newer_id' (id of the more recent/correct memory, or null)."
        )
        prompt = f"Check these memory pairs for contradictions:{items_text}"
        try:
            raw = _call_llm(prompt, system, llm_config)
            data = json.loads(raw)
            for item in data.get("results", []):
                idx = item.get("index", 0)
                if not isinstance(idx, int) or idx >= len(batch):
                    continue
                a, b, score = batch[idx]
                if item.get("contradicts"):
                    newer_id = item.get("newer_id")
                    older_id = b["id"] if newer_id == a["id"] else a["id"]
                    results.append({
                        "action": "mark_contradicted",
                        "newer_id": newer_id,
                        "older_id": older_id,
                        "score": score,
                        "reason": item.get("reason", "semantic contradiction"),
                        "newer_title": a["title"] if newer_id == a["id"] else b["title"],
                        "older_title": b["title"] if older_id == b["id"] else a["title"],
                    })
        except Exception as exc:
            logger.warning("LLM contradiction judgement failed: %s", exc)
    return results


# ---------------------------------------------------------------------------
# 3. Importance re-evaluation
# ---------------------------------------------------------------------------

def _llm_reassess_importance(
    memories: list[dict[str, Any]],
    llm_config: Any,
) -> list[dict[str, Any]]:
    """Ask LLM to re-score importance for memories that may be stale or over-valued."""
    results = []
    for i in range(0, len(memories), _BATCH_SIZE):
        batch = memories[i: i + _BATCH_SIZE]
        items_text = ""
        for idx, m in enumerate(batch):
            items_text += (
                f"[{idx}] id={m['id'][:8]} type={m.get('type')} "
                f"importance={m.get('importance', 0.5):.2f} "
                f"injected={m.get('injected_count', 0)} "
                f"feedback={m.get('feedback_score', 0):.1f}\n"
                f"  title: {m.get('title')!r}\n"
                f"  content: {m.get('content', '')[:150]!r}\n"
            )
        system = (
            "You are a memory curator scoring long-term value of stored memories. "
            "For each memory, output a revised importance score 0.0–1.0 and a suggested action. "
            "Actions: 'keep' (no change), 'promote' (raise importance, make active), "
            "'downgrade' (lower importance), 'archive' (low value, should be archived). "
            "Return JSON with key 'results': list of "
            "{'index': int, 'new_importance': float, 'action': str, 'reason': str ≤20 words}."
        )
        prompt = f"Re-evaluate the long-term importance of these memories:\n{items_text}"
        try:
            raw = _call_llm(prompt, system, llm_config)
            data = json.loads(raw)
            for item in data.get("results", []):
                idx = item.get("index", 0)
                if not isinstance(idx, int) or idx >= len(batch):
                    continue
                m = batch[idx]
                action = item.get("action", "keep")
                new_imp = float(item.get("new_importance", m.get("importance", 0.5)))
                new_imp = max(0.0, min(1.0, new_imp))
                if action == "keep" and abs(new_imp - m.get("importance", 0.5)) < 0.05:
                    continue
                results.append({
                    "action": action,
                    "id": m["id"],
                    "title": m.get("title"),
                    "old_importance": m.get("importance", 0.5),
                    "new_importance": new_imp,
                    "reason": item.get("reason", ""),
                })
        except Exception as exc:
            logger.warning("LLM importance reassessment failed: %s", exc)
    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def llm_curator_report(
    config: dict[str, Any] | None = None,
    limit: int = 200,
    sim_threshold: float = _SIM_THRESHOLD,
) -> dict[str, Any]:
    """Run LLM-enhanced curation analysis. Returns structured report (no writes)."""
    from memorycore.models import load_config
    cfg = load_config() if config is None else config

    errors: list[str] = []

    try:
        llm_config = _load_extraction_config(cfg)
    except Exception as exc:
        return {"errors": [f"LLM config load failed: {exc}"], "semantic_duplicates": [],
                "contradictions": [], "importance_reassessments": []}

    try:
        vs = _get_vector_store(cfg)
        vs_available = getattr(vs, "available", False)
    except Exception as exc:
        vs_available = False
        errors.append(f"Vector store unavailable: {exc}")

    memories = _fetch_active_memories(limit)
    if not memories:
        return {"errors": errors, "semantic_duplicates": [], "contradictions": [],
                "importance_reassessments": []}

    # --- Semantic deduplication ---
    semantic_duplicates: list[dict] = []
    contradictions: list[dict] = []

    if vs_available:
        try:
            dup_pairs = _find_semantic_duplicate_candidates(vs, memories, sim_threshold)
            if dup_pairs:
                semantic_duplicates = _llm_judge_duplicates(dup_pairs[:40], llm_config)
        except Exception as exc:
            errors.append(f"Semantic dedup failed: {exc}")
            logger.warning("semantic dedup error: %s", exc)

        try:
            contra_pairs = _find_contradiction_candidates(vs, memories, sim_threshold)
            if contra_pairs:
                contradictions = _llm_judge_contradictions(contra_pairs[:40], llm_config)
        except Exception as exc:
            errors.append(f"Contradiction detection failed: {exc}")
            logger.warning("contradiction detection error: %s", exc)
    else:
        errors.append("Vector store not available — skipping semantic dedup and contradiction detection")

    # --- Importance re-evaluation (no vector store needed) ---
    importance_reassessments: list[dict] = []
    try:
        candidates = [
            m for m in memories
            if m.get("injected_count", 0) == 0
            or m.get("feedback_score", 0) < -0.5
            or m.get("importance", 0.5) > 0.8
        ][:_IMPORTANCE_LIMIT]
        if candidates:
            importance_reassessments = _llm_reassess_importance(candidates, llm_config)
    except Exception as exc:
        errors.append(f"Importance reassessment failed: {exc}")
        logger.warning("importance reassessment error: %s", exc)

    return {
        "semantic_duplicates": semantic_duplicates,
        "contradictions": contradictions,
        "importance_reassessments": importance_reassessments,
        "errors": errors,
        "summary": {
            "semantic_duplicates": len(semantic_duplicates),
            "contradictions": len(contradictions),
            "importance_reassessments": len(importance_reassessments),
        },
    }


def apply_llm_curator(report: dict[str, Any], dry_run: bool = True) -> dict[str, Any]:
    """Apply the actions from llm_curator_report to the database."""
    if dry_run:
        return {"dry_run": True, "planned": report.get("summary", {})}

    from memorycore.storage.db import _managed_query, managed_conn
    from memorycore.models import now

    applied: dict[str, int] = {"archived": 0, "contradicted": 0, "importance_updated": 0}
    now_ts = now()

    with managed_conn() as conn:
        for dup in report.get("semantic_duplicates", []):
            drop_id = dup.get("drop_id")
            if drop_id:
                conn.execute(
                    "UPDATE memories SET status='archived', updated_at=? WHERE id=? AND status NOT IN ('archived')",
                    (now_ts, drop_id),
                )
                applied["archived"] += 1

        for contra in report.get("contradictions", []):
            older_id = contra.get("older_id")
            if older_id:
                conn.execute(
                    "UPDATE memories SET status='contradicted', updated_at=? WHERE id=? AND status NOT IN ('archived','contradicted')",
                    (now_ts, older_id),
                )
                applied["contradicted"] += 1

        for reassess in report.get("importance_reassessments", []):
            action = reassess.get("action", "keep")
            mem_id = reassess.get("id")
            new_imp = reassess.get("new_importance")
            if not mem_id:
                continue
            if action == "archive":
                conn.execute(
                    "UPDATE memories SET status='archived', updated_at=? WHERE id=? AND status NOT IN ('archived')",
                    (now_ts, mem_id),
                )
                applied["archived"] += 1
            elif action in ("promote", "downgrade") and new_imp is not None:
                new_status = "active" if action == "promote" else None
                if new_status:
                    conn.execute(
                        "UPDATE memories SET importance=?, status=?, updated_at=? WHERE id=?",
                        (new_imp, new_status, now_ts, mem_id),
                    )
                else:
                    conn.execute(
                        "UPDATE memories SET importance=?, updated_at=? WHERE id=?",
                        (new_imp, now_ts, mem_id),
                    )
                applied["importance_updated"] += 1

    from memorycore.storage.audit import log_audit_event
    log_audit_event("llm_curator_apply", detail={**applied, "dry_run": False})
    return {"dry_run": False, "applied": applied}
