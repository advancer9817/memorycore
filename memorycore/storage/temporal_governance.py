"""Auto-supersession helpers for temporal governance."""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from memorycore.models import load_config, now, row_to_dict
from memorycore.storage.db import read_conn
from memorycore.storage.governance import HIGH_IMPORTANCE_THRESHOLD, PRECIOUS_TYPES, create_governance_decision

_WORD_RE = re.compile(r"[\w一-鿿]+", re.UNICODE)
_MAX_CANDIDATES = 50


def _temporal_config() -> dict[str, Any]:
    cfg = load_config().get("temporal", {}) or {}
    return {
        "auto_supersede_enabled": bool(cfg.get("auto_supersede_enabled", False)),
        "auto_supersede_threshold": _clamp_threshold(cfg.get("auto_supersede_threshold", 0.96), 0.96),
        "review_similarity_threshold": _clamp_threshold(cfg.get("review_similarity_threshold", 0.82), 0.82),
    }


def _clamp_threshold(value: Any, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return default


def _tokens(text: str) -> set[str]:
    return set(_WORD_RE.findall((text or "").lower()))


def _similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_text = f"{left.get('title', '')} {left.get('content', '')}".strip().lower()
    right_text = f"{right.get('title', '')} {right.get('content', '')}".strip().lower()
    sequence_score = SequenceMatcher(None, left_text, right_text).ratio()
    left_tokens = _tokens(left_text)
    right_tokens = _tokens(right_text)
    if not left_tokens or not right_tokens:
        return sequence_score
    lexical_score = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    return round((sequence_score * 0.65) + (lexical_score * 0.35), 4)


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
    candidates = []
    for old_record in _candidate_rows(new_record):
        score = _similarity(new_record, old_record)
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
        applied = None
        if decision["review_status"] == "auto_approved":
            from memorycore.storage.governance import apply_governance_decision

            applied = apply_governance_decision(decision["id"], source_agent=source_agent)
        return {"checked": True, "matched": True, "action": "auto_supersede", "decision": decision, "applied": applied}

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
