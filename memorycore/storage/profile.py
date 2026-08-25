"""Structured user profile layer — learned from Aliyun DashScope long-term memory.

Replaces the "free-text user_profile memories only" approach with a fixed-schema
structured attribute store (`user_profile_attrs`) that is:

- aggregated from active `user_profile` memories (low-frequency, 1 LLM call per run),
- injected as a fixed `## user_profile_snapshot` block into every context pack
  (no retrieval dependency — always present when configured),
- attribute-level consistent (new high-confidence facts override old; immutable
  attributes never get overwritten).

Schema lives in config.yaml `user_profile.schema` (list of {name, description,
immutable?}). Conceptually maps to Aliyun's CreateProfileSchema / GetUserProfile.

Public API
----------
schema_from_config(cfg) -> list[dict]
get_user_profile(user_id) -> list[dict]
profile_snapshot(user_id, cfg, max_chars) -> str
extract_profile(*, user_id, apply, limit, cfg, _summarize_fn) -> dict
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Callable

from memorycore.models import load_config, local_now
from memorycore.storage.db import _managed_query, managed_conn as _managed_conn

logger = logging.getLogger(__name__)

_DEFAULT_MIN_CONFIDENCE = 0.6
_DEFAULT_LIMIT = 200
_DEFAULT_MAX_SNAPSHOT_CHARS = 800
_MAX_VALUE_LEN = 200


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def schema_from_config(cfg: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return the user_profile.schema list from config (defaults to [])."""
    cfg = cfg or load_config()
    schema = (cfg.get("user_profile") or {}).get("schema") or []
    return [entry for entry in schema if isinstance(entry, dict) and str(entry.get("name", "")).strip()]


def _schema_names(cfg: dict[str, Any] | None = None) -> set[str]:
    return {str(entry["name"]).strip() for entry in schema_from_config(cfg)}


def _schema_immutable(cfg: dict[str, Any] | None = None) -> set[str]:
    return {
        str(entry["name"]).strip()
        for entry in schema_from_config(cfg)
        if bool(entry.get("immutable", False))
    }


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def get_user_profile(user_id: str = "default") -> list[dict[str, Any]]:
    """Read stored profile attributes, ordered by schema order then updated_at desc."""
    rows = _managed_query(
        "SELECT user_id, attribute, value, confidence, immutable, source_ids_json, updated_at "
        "FROM user_profile_attrs WHERE user_id = ?",
        (user_id,),
    )
    # Deterministic order: by attribute name (schema order approximated alphabetically).
    rows.sort(key=lambda r: (r.get("attribute") or "", r.get("updated_at") or ""))
    for row in rows:
        try:
            row["source_ids"] = json.loads(row.get("source_ids_json") or "[]")
        except Exception:
            row["source_ids"] = []
    return rows


def profile_detail(
    user_id: str = "default",
    cfg: dict[str, Any] | None = None,
    include_sources: bool = True,
    source_preview_limit: int = 5,
) -> dict[str, Any]:
    """Return a rich profile payload for the UI profile page.

    Includes schema definitions (name/description/immutable), stored attributes
    (value/confidence/source count/updated_at), per-attribute source memory
    previews, coverage stats, and the latest extract diagnostics.
    """
    cfg = cfg or load_config()
    schema = schema_from_config(cfg)
    up = cfg.get("user_profile") or {}
    attrs = get_user_profile(user_id)

    schema_by_name = {str(e["name"]).strip(): e for e in schema}
    attr_by_name = {str(a["attribute"]): a for a in attrs}

    # Enrich each attribute with schema metadata + source previews
    enriched: list[dict[str, Any]] = []
    for attr in attrs:
        name = str(attr["attribute"])
        entry = {
            "attribute": name,
            "value": attr.get("value", ""),
            "confidence": round(float(attr.get("confidence") or 0), 3),
            "immutable": bool(attr.get("immutable")),
            "description": (schema_by_name.get(name) or {}).get("description", ""),
            "source_count": len(attr.get("source_ids") or []),
            "updated_at": attr.get("updated_at", ""),
        }
        if include_sources and attr.get("source_ids"):
            ids = (attr.get("source_ids") or [])[:source_preview_limit]
            entry["sources"] = _profile_source_previews(ids)
        enriched.append(entry)

    # Schema entries with no stored value yet
    missing = [
        {
            "attribute": name,
            "value": "",
            "confidence": 0,
            "immutable": bool(entry.get("immutable", False)),
            "description": str(entry.get("description", "")).strip(),
            "source_count": 0,
            "updated_at": "",
            "filled": False,
        }
        for name, entry in schema_by_name.items()
        if name not in attr_by_name
    ]
    for entry in missing:
        enriched.append(entry)
    # Sort: filled first (schema order), then unfilled
    def _fill_rank(e):
        return 0 if e.get("value") else 1
    enriched.sort(key=_fill_rank)

    filled = [e for e in enriched if e.get("value")]
    coverage = round(len(filled) / len(schema), 3) if schema else 0
    conf_groups = {
        "high": len([e for e in filled if e["confidence"] >= 0.8]),
        "medium": len([e for e in filled if 0.6 <= e["confidence"] < 0.8]),
        "low": len([e for e in filled if e["confidence"] < 0.6]),
    }
    immutable_locked = [e["attribute"] for e in enriched if e.get("immutable") and e.get("value")]
    update_times = [e["updated_at"] for e in enriched if e.get("updated_at")]
    latest_extract = max(update_times) if update_times else ""

    return {
        "enabled": bool(up.get("enabled", False)),
        "user_id": user_id,
        "schema_count": len(schema),
        "covered": len(filled),
        "coverage": coverage,
        "confidence_groups": conf_groups,
        "immutable_locked": immutable_locked,
        "latest_extract_at": latest_extract,
        "extract_limit": int(up.get("extract_limit", 200)),
        "min_confidence": float(up.get("min_confidence", 0.6)),
        "max_snapshot_chars": int(up.get("max_snapshot_chars", 800)),
        "attributes": enriched,
    }


def _profile_source_previews(ids: list[str], limit: int = 5) -> list[dict[str, Any]]:
    """Brief previews of source memories for an attribute (id + title + snippet)."""
    if not ids:
        return []
    ids = ids[:limit]
    ph = ",".join("?" for _ in ids)
    rows = _managed_query(
        f"SELECT id, title, content, updated_at FROM memories WHERE id IN ({ph})",
        ids,
    )
    by_id = {str(r["id"]): r for r in rows}
    out: list[dict[str, Any]] = []
    for mid in ids:
        row = by_id.get(mid)
        if not row:
            continue
        content = str(row.get("content") or "")
        snippet = content[:160] + ("…" if len(content) > 160 else "")
        out.append({
            "id": mid,
            "title": row.get("title", ""),
            "snippet": snippet,
            "updated_at": row.get("updated_at", ""),
        })
    return out


def profile_snapshot(
    user_id: str = "default",
    cfg: dict[str, Any] | None = None,
    max_chars: int | None = None,
) -> str:
    """Build '## user_profile_snapshot\\n- <attr>: <value>\\n...' text.

    Returns '' when no attributes exist (caller skips injecting an empty block).
    """
    cfg = cfg or load_config()
    up = cfg.get("user_profile") or {}
    if not up.get("enabled", False):
        return ""
    if max_chars is None:
        max_chars = int(up.get("max_snapshot_chars", _DEFAULT_MAX_SNAPSHOT_CHARS))
    attrs = get_user_profile(user_id)
    if not attrs:
        return ""
    lines = ["## user_profile_snapshot"]
    for attr in attrs:
        value = str(attr.get("value") or "").strip()
        if not value:
            continue
        safe = value.replace("\n", " ").replace("\r", " ")
        line = f"- {attr['attribute']}: {safe}"
        budget = max_chars - len("\n".join(lines)) - len(line) - 2
        if budget < 0 and len(lines) > 1:
            break
        lines.append(line)
    text = "\n".join(lines).strip()
    if len(text) > max_chars:
        text = text[: max(max_chars - 3, 0)].rstrip() + "..."
    return text


# ---------------------------------------------------------------------------
# LLM extraction (aggregate active user_profile memories -> attributes)
# ---------------------------------------------------------------------------

_PROFILE_EXTRACT_PROMPT = """\
你是用户画像信息抽取器。根据给定的画像字段定义与用户历史记忆，
抽取每位用户最稳定、最准确的属性值。

# 画像字段
{schema_block}

# 规则
1. 只输出 JSON: {{"attributes": [{{"name": "姓名", "value": "张三", "confidence": 0.9}}]}}
2. 属性 name 必须来自上面的画像字段（完全一致）；没有稳定证据的属性不要输出。
3. 多条记忆冲突时：取 created_at 最新的；若最新信息明确是"纠正/不要/改为"，以纠正为准。
4. 未知或无法确定的属性省略（不要填"未知"、"暂无"）。
5. value 保持简洁具体，保留专有名词、版本号、公司名等（不翻译）。
6. confidence 0.0-1.0，表示"该值在记忆中被一致支持的程度"；单条强记忆可给 0.9。
7. 仅返回合法 JSON，不要 prose，不要 markdown fence。
"""


def _build_profile_prompt(schema: list[dict[str, Any]], rows: list[dict[str, Any]]) -> tuple[str, str]:
    schema_block = "\n".join(
        f"- {entry['name']}: {str(entry.get('description', '')).strip() or '（无描述）'}"
        for entry in schema
    )
    payload = [
        {
            "id": row.get("id", ""),
            "title": row.get("title", ""),
            "content": row.get("content", ""),
            "created_at": (row.get("created_at") or "")[:10],
        }
        for row in rows
    ]
    user_prompt = "## 用户历史记忆\n" + json.dumps(payload, ensure_ascii=False)
    return _PROFILE_EXTRACT_PROMPT.format(schema_block=schema_block), user_prompt


def _parse_profile_response(raw: str, schema: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parse LLM JSON into [{"name", "value", "confidence"}] filtered by schema whitelist."""
    allowed = {str(entry["name"]).strip() for entry in schema}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                data = json.loads(raw[start:end])
            except json.JSONDecodeError:
                logger.warning("profile: could not parse LLM response: %s", raw[:200])
                return []
        else:
            logger.warning("profile: no JSON found in response: %s", raw[:200])
            return []
    attrs = data.get("attributes", data.get("profile", []))
    if not isinstance(attrs, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in attrs:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if name not in allowed or name in seen:
            continue
        seen.add(name)
        value = str(item.get("value") or "").strip()[: _MAX_VALUE_LEN]
        if not value:
            continue
        try:
            conf = max(0.0, min(1.0, float(item.get("confidence", 0.5))))
        except (TypeError, ValueError):
            conf = 0.5
        out.append({"name": name, "value": value, "confidence": conf})
    return out


def _upsert_profile_attrs(
    user_id: str,
    attributes: list[dict[str, Any]],
    *,
    cfg: dict[str, Any],
    source_ids: list[str],
) -> int:
    """Upsert attributes with conflict rules. Returns number of updated rows."""
    min_conf = float((cfg.get("user_profile") or {}).get("min_confidence", _DEFAULT_MIN_CONFIDENCE))
    immutable = _schema_immutable(cfg)
    now_ts = local_now().isoformat()
    updated = 0
    with _managed_conn() as conn:
        for attr in attributes:
            name = str(attr.get("name") or "").strip()
            value = str(attr.get("value") or "").strip()
            conf = float(attr.get("confidence", 0.5))
            if name not in _schema_names(cfg) or not value:
                continue
            if conf < min_conf:
                continue
            existing = conn.execute(
                "SELECT value, confidence, immutable, source_ids_json FROM user_profile_attrs "
                "WHERE user_id = ? AND attribute = ?",
                (user_id, name),
            ).fetchone()
            if existing is not None:
                if existing["immutable"] and str(existing["value"] or "").strip():
                    continue
                if conf < float(existing["confidence"] or 0.0):
                    continue
                old_ids = json.loads(existing["source_ids_json"] or "[]")
                new_ids = list(dict.fromkeys([*(old_ids or []), *source_ids]))
                conn.execute(
                    "UPDATE user_profile_attrs SET value=?, confidence=?, updated_at=?, source_ids_json=? "
                    "WHERE user_id=? AND attribute=?",
                    (value, conf, now_ts, json.dumps(new_ids, ensure_ascii=False), user_id, name),
                )
            else:
                conn.execute(
                    "INSERT INTO user_profile_attrs "
                    "(user_id, attribute, value, confidence, immutable, source_ids_json, updated_at) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (
                        user_id,
                        name,
                        value,
                        conf,
                        1 if name in immutable else 0,
                        json.dumps(source_ids, ensure_ascii=False),
                        now_ts,
                    ),
                )
            updated += 1
    return updated


def extract_profile(
    *,
    user_id: str = "default",
    apply: bool = False,
    limit: int | None = None,
    cfg: dict[str, Any] | None = None,
    _summarize_fn: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Aggregate active user_profile memories into structured profile attributes.

    Dry-run by default; pass apply=True to write to user_profile_attrs.
    """
    cfg = cfg or load_config()
    up = cfg.get("user_profile") or {}
    schema = schema_from_config(cfg)
    if not schema:
        return {"dry_run": not apply, "scanned": 0, "attributes": [], "updated": 0,
                "errors": ["user_profile.schema is empty in config.yaml"], "skipped": True}
    cap = max(1, min(int(limit or up.get("extract_limit", _DEFAULT_LIMIT)), 2000))

    rows = _managed_query(
        "SELECT id, title, content, created_at FROM memories "
        "WHERE type = 'user_profile' AND status = 'active' "
        "ORDER BY updated_at DESC LIMIT ?",
        (cap,),
    )
    if not rows:
        return {"dry_run": not apply, "scanned": 0, "attributes": [], "updated": 0,
                "errors": [], "skipped": True}

    t0 = time.time()
    errors: list[str] = []
    try:
        if _summarize_fn is not None:
            attributes = _summarize_fn(rows)
        else:
            from memorycore.extraction import _call_llm, extraction_config_from_dict
            ext_cfg = extraction_config_from_dict(cfg)
            if not ext_cfg.api_key:
                return {"dry_run": not apply, "scanned": len(rows), "attributes": [],
                        "updated": 0, "errors": ["no extraction API key configured"], "skipped": True}
            system_prompt, user_prompt = _build_profile_prompt(schema, rows)
            raw = _call_llm(system_prompt, user_prompt, ext_cfg)
            attributes = _parse_profile_response(raw, schema)
    except Exception as exc:
        logger.error("profile extract failed: %s", exc, exc_info=True)
        return {"dry_run": not apply, "scanned": len(rows), "attributes": [],
                "updated": 0, "errors": [f"{type(exc).__name__}: {exc}"], "elapsed_s": round(time.time() - t0, 2)}

    source_ids = [str(row["id"]) for row in rows]
    updated = 0
    if apply:
        updated = _upsert_profile_attrs(user_id, attributes, cfg=cfg, source_ids=source_ids)
    return {
        "dry_run": not apply,
        "scanned": len(rows),
        "attributes": attributes,
        "updated": updated,
        "errors": errors,
        "elapsed_s": round(time.time() - t0, 2),
    }


# ---------------------------------------------------------------------------
# Profile-driven retrieval aids (batch-3: F1 rerank / F2 query expansion /
# F4 conflict filter).  All pure-local string ops — zero LLM cost.
# ---------------------------------------------------------------------------

# Attribute names whose values are strong personalization signals for rerank /
# query expansion (filtered from noisy preference/schedule attrs when needed).
_PROFILE_SIGNAL_ATTRS = (
    "技术栈", "工作领域", "当前项目", "雇主", "常用工具",
    "兴趣关注", "学习方向", "职业", "模型偏好",
)
# Attribute names NOT allowed as query-expansion sources (too generic/noisy).
_PROFILE_EXPAND_SKIP_ATTRS = ("姓名", "语言", "沟通偏好", "时间偏好", "输出偏好")


def _is_cjk_char(ch: str) -> bool:
    return "\u4e00" <= ch <= "\u9fff"


def _tokenize_value(text: str) -> list[str]:
    """Lightweight tokenizer for profile values: latin tokens + CJK grams.

    CJK spans are kept whole when short (2-6 chars) plus 2-grams, mirroring
    search._query_terms so overlap detection is symmetric.
    """
    if not text:
        return []
    lowered = str(text).lower()
    tokens: list[str] = []
    for m in re.findall(r"[a-z0-9_][a-z0-9_.+/-]*", lowered):
        if len(m) >= 2 and not m.startswith("http"):
            tokens.append(m)
    for span in re.findall(r"[\u4e00-\u9fff]+", lowered):
        if 2 <= len(span) <= 6:
            tokens.append(span)
        for width in (3, 2):
            for idx in range(0, max(len(span) - width + 1, 0)):
                gram = span[idx:idx + width]
                if any(c in "的一是在了不有和与及或把给让被到过着对从用以将又也都还就很太可会能要想得已正才只这那个么什为而且但如所跟比被" for c in gram):
                    continue
                tokens.append(gram)
    # dedupe, keep order
    seen: set[str] = set()
    out: list[str] = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def profile_feature_words(
    user_id: str = "default",
    cfg: dict[str, Any] | None = None,
    min_conf: float = 0.6,
) -> list[str]:
    """Extract signal feature words from stored profile attributes (for rerank).

    Only attributes in _PROFILE_SIGNAL_ATTRS with confidence >= min_conf are
    used; values are tokenized (latin + CJK grams). Returns deduped, capped
    word list (max 200) so a noisy profile cannot dominate scoring.
    """
    attrs = get_user_profile(user_id)
    words: list[str] = []
    seen: set[str] = set()
    for attr in attrs:
        name = str(attr.get("attribute") or "").strip()
        if name not in _PROFILE_SIGNAL_ATTRS:
            continue
        if float(attr.get("confidence") or 0.0) < min_conf:
            continue
        value = str(attr.get("value") or "").strip()
        for token in _tokenize_value(value):
            if token not in seen:
                seen.add(token)
                words.append(token)
        if len(words) >= 200:
            break
    return words


def profile_overlap_ratio(text: str, profile_words: list[str]) -> float:
    """Fraction-style overlap signal: how many distinct profile features appear.

    Capped at 1.0 after 3+ matches so a single long record cannot saturate it.
    """
    if not profile_words or not text:
        return 0.0
    lowered = text.lower()
    matched = sum(1 for word in profile_words if word.lower() in lowered)
    if not matched:
        return 0.0
    return min(1.0, matched / 3.0)


def profile_query_expansion(
    task: str,
    user_id: str = "default",
    cfg: dict[str, Any] | None = None,
    max_terms: int = 3,
    min_overlap: int = 1,
) -> list[str]:
    """Derive <= max_terms expansion phrases from profile attrs overlapping task.

    An attribute contributes its full value when its name is mentioned in the
    task, or when >= min_overlap of its value tokens also appear in the task.
    Returns [] when no overlap (no drift-prone expansion).
    """
    if not task:
        return []
    attrs = get_user_profile(user_id)
    task_lower = str(task).lower()
    expansions: list[str] = []
    seen: set[str] = set()
    for attr in attrs:
        name = str(attr.get("attribute") or "").strip()
        if name in _PROFILE_EXPAND_SKIP_ATTRS:
            continue
        if float(attr.get("confidence") or 0.0) < 0.5:
            continue
        value = str(attr.get("value") or "").strip()
        if not value or len(value) > 60:
            continue
        if value in seen:
            continue
        name_in_task = name.lower() in task_lower
        if name_in_task:
            expansions.append(value)
            seen.add(value)
            continue
        tokens = _tokenize_value(value)
        overlap = sum(1 for token in tokens if len(token) >= 2 and token.lower() in task_lower)
        if overlap >= min_overlap:
            expansions.append(value)
            seen.add(value)
        if len(expansions) >= max_terms:
            break
    return expansions


def profile_conflict_for_record(
    record: dict[str, Any],
    profile: list[dict[str, Any]] | None = None,
    user_id: str = "default",
    *,
    min_conf: float = 0.8,
    only_immutable: bool = False,
) -> dict[str, Any] | None:
    """Detect user_profile memories that contradict stored profile attributes.

    Heuristic: the attribute NAME appears in the memory text, but NONE of the
    stored value's tokens appear anywhere in the memory — i.e. the memory talks
    about that attribute yet disagrees with / predates the current value.

    Default checks only high-confidence values; only_immutable=True makes it
    stricter (immutable attrs only) for low-false-positive callers.
    Returns {"attribute", "profile_value"} or None.
    """
    if not record or record.get("type") != "user_profile":
        return None
    profile = profile if profile is not None else get_user_profile(user_id)
    text = f"{record.get('title', '')}\n{record.get('content', '')}".lower()
    for attr in profile:
        name = str(attr.get("attribute") or "").strip()
        pvalue = str(attr.get("value") or "").strip()
        if not name or not pvalue or len(pvalue) > 200:
            continue
        if only_immutable and not bool(attr.get("immutable")):
            continue
        if not only_immutable and float(attr.get("confidence") or 0.0) < min_conf:
            continue
        if name.lower() not in text:
            continue
        tokens = [t for t in _tokenize_value(pvalue) if len(t) >= 2]
        if not tokens:
            continue
        if all(token not in text for token in tokens):
            return {"attribute": name, "profile_value": pvalue}
    return None