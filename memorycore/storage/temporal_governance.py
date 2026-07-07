"""Auto-supersession helpers for temporal governance."""
from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from typing import Any

from memorycore.models import load_config, now, row_to_dict
from memorycore.storage.db import read_conn
from memorycore.storage.governance import HIGH_IMPORTANCE_THRESHOLD, PRECIOUS_TYPES, create_governance_decision

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[\w一-鿿]+", re.UNICODE)
_MAX_CANDIDATES = 50


def _temporal_config() -> dict[str, Any]:
    cfg = load_config().get("temporal", {}) or {}
    return {
        "auto_supersede_enabled": bool(cfg.get("auto_supersede_enabled", True)),
        "auto_supersede_threshold": _clamp_threshold(cfg.get("auto_supersede_threshold", 0.88), 0.88),
        "review_similarity_threshold": _clamp_threshold(cfg.get("review_similarity_threshold", 0.72), 0.72),
    }


def _clamp_threshold(value: Any, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return default


def _tokens(text: str) -> set[str]:
    return set(_WORD_RE.findall((text or "").lower()))


def _lexical_similarity(left_text: str, right_text: str) -> float:
    sequence_score = SequenceMatcher(None, left_text, right_text).ratio()
    left_tokens = _tokens(left_text)
    right_tokens = _tokens(right_text)
    if not left_tokens or not right_tokens:
        return sequence_score
    lexical_score = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    return round((sequence_score * 0.65) + (lexical_score * 0.35), 4)


def _vector_similarity(new_record: dict[str, Any], old_id: str, candidate_ids: set[str] | None = None) -> float | None:
    """Try Qdrant cosine similarity between new_record text and old_id's stored vector.

    candidate_ids: if provided, only scores that match a known SQLite candidate are trusted.
    This prevents false positives from unrelated records in a shared Qdrant store.
    """
    try:
        from memorycore.vector_store import get_vector_store
        vs = get_vector_store(load_config())
        query_text = f"{new_record.get('title', '')} {new_record.get('content', '')}".strip()
        if not query_text:
            return None
        results = vs.search(query_text, top_k=50, filters={})
        for r in results:
            if str(r.id) == str(old_id):
                # Only trust this score if old_id is in the SQLite candidate set
                if candidate_ids is not None and str(old_id) not in candidate_ids:
                    return None
                return float(r.score)
        return None
    except Exception as exc:
        logger.debug("vector similarity lookup failed: %s", exc)
        return None


def _similarity(left: dict[str, Any], right: dict[str, Any], candidate_ids: set[str] | None = None) -> float:
    """Compute similarity: vector cosine preferred, lexical fallback.

    candidate_ids: trusted SQLite candidate id set, passed to _vector_similarity to avoid
    false positives from unrelated records in a shared Qdrant store.

    When vector score is available, it is blended with lexical similarity to prevent
    false positives where records share identical embed content (e.g. same boilerplate)
    but have completely different titles (and should not supersede each other).
    """
    left_text = f"{left.get('title', '')} {left.get('content', '')}".strip().lower()
    right_text = f"{right.get('title', '')} {right.get('content', '')}".strip().lower()
    lex_score = _lexical_similarity(left_text, right_text)
    vec_score = _vector_similarity(left, right["id"], candidate_ids=candidate_ids)
    if vec_score is not None:
        # Blend: vector carries 60% weight, lexical 40%.
        # This prevents auto-supersession when records share identical embed content
        # but have unrelated titles (lex_score would be low in that case).
        return round(vec_score * 0.6 + lex_score * 0.4, 4)
    return lex_score


def _is_precious(record: dict[str, Any]) -> bool:
    return (
        record.get("type") in PRECIOUS_TYPES
        or float(record.get("importance") or 0.0) >= HIGH_IMPORTANCE_THRESHOLD
        or float(record.get("feedback_score") or 0.0) > 0.0
    )


def _candidate_rows(new_record: dict[str, Any]) -> list[dict[str, Any]]:
    with read_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM memories
            WHERE id != ?
              AND status = 'active'
              AND type = ?
              AND scope = ?
              AND project_path = ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (
                new_record["id"],
                new_record.get("type", ""),
                new_record.get("scope", "global") or "global",
                new_record.get("project_path", "") or "",
                _MAX_CANDIDATES,
            ),
        ).fetchall()
    return [row_to_dict(row) for row in rows]


def process_auto_supersession(new_record: dict[str, Any], source_agent: str = "agent") -> dict[str, Any]:
    """Detect same-scope supersession candidates after a new active write.

    High-confidence low-risk matches auto-supersede the older record through the
    governance decision/apply path. Mid-confidence matches create a needs-review
    governance decision and leave records unchanged.
    """
    if new_record.get("status") != "active":
        return {"checked": False, "reason": "new record is not active"}

    config = _temporal_config()
    review_threshold = min(config["review_similarity_threshold"], config["auto_supersede_threshold"])
    sqlite_candidates = _candidate_rows(new_record)
    candidate_ids = {r["id"] for r in sqlite_candidates}
    candidates = []
    for old_record in sqlite_candidates:
        score = _similarity(new_record, old_record, candidate_ids=candidate_ids)
        if score >= review_threshold:
            candidates.append({"record": old_record, "similarity": score})
    if not candidates:
        return {"checked": True, "matched": False, "candidates": []}

    candidates = sorted(candidates, key=lambda item: item["similarity"], reverse=True)
    best = candidates[0]
    old_record = best["record"]
    similarity = best["similarity"]
    finding = {
        "old_id": old_record["id"],
        "new_id": new_record["id"],
        "older_id": old_record["id"],
        "newer_id": new_record["id"],
        "similarity": similarity,
        "reason": "temporal auto-supersession candidate from write path",
        "old_title": old_record.get("title", ""),
        "new_title": new_record.get("title", ""),
    }
    source_ids = [old_record["id"], new_record["id"]]
    llm_trace = {
        "source": "deterministic_temporal_similarity",
        "similarity": similarity,
        "created_at": now(),
    }

    if (
        config["auto_supersede_enabled"]
        and similarity >= config["auto_supersede_threshold"]
        and not _is_precious(old_record)
        and not _is_precious(new_record)
    ):
        decision = create_governance_decision(
            decision_type="supersession",
            recommended_action="supersede",
            source_ids=source_ids,
            llm_confidence=similarity,
            risk_level="low",
            finding=finding,
            raw_response_ref="deterministic_temporal_similarity",
            source_agent=source_agent,
            llm_trace=llm_trace,
        )
        return {"checked": True, "matched": True, "action": "auto_supersede", "decision": decision}

    decision = create_governance_decision(
        decision_type="supersession",
        recommended_action="supersede",
        source_ids=source_ids,
        llm_confidence=similarity,
        risk_level="medium",
        finding=finding,
        raw_response_ref="deterministic_temporal_similarity",
        source_agent=source_agent,
        llm_trace=llm_trace,
    )
    return {"checked": True, "matched": True, "action": "needs_review", "decision": decision}
