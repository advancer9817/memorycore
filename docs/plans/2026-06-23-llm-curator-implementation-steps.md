# LLM Curator 全面优化 — 逐步实施文档

> 日期: 2026-06-23 | 状态: 待实施
> 目标文件: `memorycore/storage/curator_llm.py` (1276行) 为主
> 关联: [优化方案](2026-06-23-llm-curator-full-overhaul.md) | [时间感知架构](2026-06-23-temporal-awareness-architecture.md)

---

## 实施总览

共 **21 个步骤**，分 6 Phase，按依赖关系排序。每步给出精确的代码位置、before/after diff、验证命令。

**约定**:
- 文件路径均相对于 `/home/advancer/project/memorycore/`
- 行号基于当前代码快照（2026-06-23）
- Python 运行: `.venv/bin/python`
- 每个 Phase 完成后运行验证再进入下一个

---

# Phase A：修复数据损坏风险（P0）

## 步骤 A1：修改 _PROMPT_STYLES 中的输出格式 — keep_id → keep

**位置**: `memorycore/storage/curator_llm.py` line 40-114

**原因**: 所有三套 prompt style 的 duplicate 和 contradiction prompt 都要求 LLM 返回 `keep_id` / `newer_id`（完整 UUID），但 prompt 只传 8 字符截断 ID，LLM 不可能返回匹配的完整 UUID。

**改动**: 将所有 duplicate prompt 中的 `'keep_id'` 改为 `'keep' ("A" or "B")`，将所有 contradiction prompt 中的 `'newer_id'` 改为 `'newer' ("A" or "B")`。

### A1.1 conservative.duplicate (line 42-50)

```python
# BEFORE (line 46-49)
"Return a JSON object with key 'results': a list where each element has "
"'index' (int), 'is_duplicate' (bool), 'reason' (str, ≤30 words), "
"'keep_id' (the id of the memory to keep, or null if unsure), and "
"'merge_info' (str, ≤40 words; empty string if nothing needs merging)."

# AFTER
"Return a JSON object with key 'results': a list where each element has "
"'index' (int), 'is_duplicate' (bool), 'reason' (str, ≤30 words), "
"'keep' (str, \"A\" or \"B\" — the memory to keep, or null if unsure), and "
"'merge_info' (str, ≤40 words; empty string if nothing needs merging)."
```

### A1.2 conservative.contradiction (line 51-58)

```python
# BEFORE (line 55-57)
"Return JSON with key 'results': list of objects with "
"'index' (int), 'contradicts' (bool), 'reason' (str ≤30 words), "
"'newer_id' (id of the more recent/correct memory, or null)."

# AFTER
"Return JSON with key 'results': list of objects with "
"'index' (int), 'contradicts' (bool), 'reason' (str ≤30 words), "
"'newer' (str, \"A\" or \"B\" — the more recent/correct memory, or null)."
```

### A1.3 balanced.duplicate (line 77-85)

```python
# BEFORE (line 81-84)
"Return a JSON object with key 'results': a list where each element has "
"'index' (int), 'is_duplicate' (bool), 'reason' (str, ≤30 words), "
"'keep_id' (the id of the memory to keep, or null if unsure), and "
"'merge_info' (str, ≤40 words; empty string if nothing needs merging)."

# AFTER
"Return a JSON object with key 'results': a list where each element has "
"'index' (int), 'is_duplicate' (bool), 'reason' (str, ≤30 words), "
"'keep' (str, \"A\" or \"B\" — the memory to keep, or null if unsure), and "
"'merge_info' (str, ≤40 words; empty string if nothing needs merging)."
```

### A1.4 balanced.contradiction (line 86-94)

```python
# BEFORE (line 91-93)
"Return JSON with key 'results': list of objects with "
"'index' (int), 'contradicts' (bool), 'reason' (str ≤30 words), "
"'newer_id' (id of the more recent/correct memory, or null)."

# AFTER
"Return JSON with key 'results': list of objects with "
"'index' (int), 'contradicts' (bool), 'reason' (str ≤30 words), "
"'newer' (str, \"A\" or \"B\" — the more recent/correct memory, or null)."
```

---

## 步骤 A2：填充 `_PROMPT_STYLES["aggressive"]` 并统一格式

**位置**: `memorycore/storage/curator_llm.py` line 113

**原因**: `"aggressive": {}` 是空字典，所有 aggressive prompt 靠各函数内硬编码 fallback。把它们集中到 `_PROMPT_STYLES` 中，同时将输出格式统一为 `keep: "A"/"B"` 和 `newer: "A"/"B"`。

```python
# BEFORE (line 113)
"aggressive": {},  # Will use the existing hardcoded prompts as fallback

# AFTER — 替换为完整定义:
"aggressive": {
    "duplicate": (
        "You are an aggressive memory curator whose primary goal is to eliminate redundancy. "
        "Analyse each pair of memories and determine whether they are duplicates. "
        "Consider ALL of the following as duplicates:\n"
        "- Exact same fact stated differently\n"
        "- One memory is a subset of the other (the shorter adds nothing new)\n"
        "- Both memories describe the same decision, preference, or configuration\n"
        "- Overlapping information where merging into one would lose nothing\n"
        "- Same topic with trivially different wording or formatting\n"
        "When in doubt, mark as duplicate — redundancy hurts retrieval quality.\n"
        "Return a JSON object with key 'results': a list where each element has "
        "'index' (int), 'is_duplicate' (bool), 'reason' (str, ≤30 words), "
        "'keep' (str, \"A\" or \"B\" — the memory to keep, or null if unsure), and "
        "'merge_info' (str, ≤40 words describing information from the discarded memory "
        "that should be merged into the kept memory; empty string if nothing needs merging)."
    ),
    "contradiction": (
        "You are an aggressive memory curator focused on detecting contradictions. "
        "Check each memory pair for ANY form of conflict:\n"
        "- Direct contradiction: one states X, the other states NOT X\n"
        "- Temporal supersession: one is an outdated version of the same decision/preference\n"
        "- Conditional conflict: they give different answers for overlapping conditions\n"
        "- Implicit contradiction: their logical implications are incompatible\n"
        "- Stale vs current: one reflects an old state that has been updated by the other\n"
        "When memories describe the same topic with different conclusions, that IS a contradiction. "
        "Return JSON with key 'results': list of objects with "
        "'index' (int), 'contradicts' (bool), 'reason' (str ≤30 words), "
        "'newer' (str, \"A\" or \"B\" — the more recent/correct memory, or null)."
    ),
    "importance": (
        "You are an aggressive memory curator optimizing a knowledge base for maximum utility. "
        "For each memory, critically evaluate its long-term value and output a revised importance score 0.0–1.0. "
        "Be decisive — most memories decay in value over time. Consider:\n"
        "- Is this still actionable or relevant, or is it historical noise?\n"
        "- Does it contain a unique insight, or is it generic/obvious?\n"
        "- Would losing this memory actually harm future conversations?\n"
        "- Is the current importance score justified by the content quality?\n"
        "- Memories with 0 injections and 0 feedback are likely unused — downgrade aggressively.\n"
        "- Memories with positive feedback_score (> 0) have been validated by the user — "
        "do NOT archive or downgrade these unless the content is demonstrably outdated.\n"
        "Actions: 'keep' (no change needed), 'promote' (raise importance, make active), "
        "'downgrade' (lower importance), 'archive' (low value, should be archived). "
        "Default to action rather than 'keep' — if you can justify any change, make it.\n"
        "Return JSON with key 'results': list of "
        "{'index': int, 'new_importance': float, 'action': str, 'reason': str ≤20 words}."
    ),
    "split": (
        "You are a memory curator focused on atomizing compound memories for better retrieval. "
        "Identify memories that contain multiple distinct, separable facts. "
        "A memory is splittable if:\n"
        "- It lists multiple independent decisions, preferences, or facts\n"
        "- It covers multiple topics that could each stand alone\n"
        "- It contains both a rule AND its context/reasoning as separable units\n"
        "- It bundles configuration details with behavioral preferences\n"
        "For each splittable memory, propose 2-4 concise atomic sub-memories. "
        "Each sub-memory should be self-contained and useful in isolation.\n"
        "Return JSON with key 'results': list of "
        "{'index': int, 'splittable': bool, 'reason': str ≤20 words, "
        "'sub_memories': [{'title': str, 'content': str, 'importance': float}]}. "
        "The 'importance' field (0.0-1.0) reflects the long-term value of each sub-memory independently. "
        "If a memory is already atomic or splitting would lose context, set splittable=false."
    ),
},
```

**注意**: 此步骤同时完成了 Phase C1（填充 aggressive）和 C3（importance 保护 feedback 记忆）的 aggressive 部分。

---

## 步骤 A3：修改 `_llm_judge_duplicates` 的 prompt 构建和结果解析

**位置**: `memorycore/storage/curator_llm.py` line 359-455

### A3.1 修改 items_text 构建 (line 370-379)

```python
# BEFORE
items_text = ""
for idx, (a, b, score) in enumerate(batch):
    items_text += (
        f"\n[{idx}]\n"
        f"A (id={a['id'][:8]}): title={a.get('title')!r} {_temporal_tag(a)}\n"
        f"  content={a.get('content', '')[:content_max_chars]!r}\n"
        f"B (id={b['id'][:8]}): title={b.get('title')!r} {_temporal_tag(b)}\n"
        f"  content={b.get('content', '')[:content_max_chars]!r}\n"
        f"vector_similarity={score:.3f}\n"
    )

# AFTER
items_text = ""
for idx, (a, b, score) in enumerate(batch):
    items_text += (
        f"\n[{idx}]\n"
        f"A: title={a.get('title')!r} {_temporal_tag(a)}\n"
        f"  content={a.get('content', '')[:content_max_chars]!r}\n"
        f"B: title={b.get('title')!r} {_temporal_tag(b)}\n"
        f"  content={b.get('content', '')[:content_max_chars]!r}\n"
        f"vector_similarity={score:.3f}\n"
    )
```

### A3.2 删除硬编码 fallback system prompt (line 382-398)

```python
# BEFORE (line 380-398)
style_prompts = _PROMPT_STYLES.get(prompt_style, {})
system = style_prompts.get("duplicate")
if not system:
    system = (
        "You are an aggressive memory curator..."
        ...长达 16 行的硬编码 prompt...
    )

# AFTER — 由于 A2 步骤已填充 aggressive，改为 fallback 到 balanced:
style_prompts = _PROMPT_STYLES.get(prompt_style, {})
system = style_prompts.get("duplicate") or _PROMPT_STYLES["balanced"]["duplicate"]
```

### A3.3 修改结果解析 — keep_id → keep label 映射 (line 421-436)

```python
# BEFORE (line 421-436)
if item.get("is_duplicate"):
    llm_keep_id = item.get("keep_id")
    if llm_keep_id in (a["id"], b["id"]):
        keep_id = llm_keep_id
        drop_id = b["id"] if keep_id == a["id"] else a["id"]
    else:
        # 时间优先 fallback...
        from memorycore.models import load_config
        use_temporal = load_config().get("temporal", {}).get("enabled", False)
        ...

# AFTER
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
```

**注意**: `full_config` 需要通过参数传入（见 B3 步骤），临时方案可先用 `load_config()`。

### A3.4 修改 temporal prompt 中的 keep_id 引用 (line 407-412)

```python
# BEFORE (line 410)
"- 当两条记忆重复时，优先保留(keep_id)更新日期更近的那条\n"

# AFTER
"- 当两条记忆重复时，优先保留(keep=\"A\"或\"B\")更新日期更近的那条\n"
```

---

## 步骤 A4：修改 `_llm_judge_contradictions` 的 prompt 构建和结果解析

**位置**: `memorycore/storage/curator_llm.py` line 517-589

### A4.1 修改 items_text 构建 (line 528-536)

```python
# BEFORE
f"A (id={a['id'][:8]}): {a.get('title')!r} {_temporal_tag(a)}\n"
f"B (id={b['id'][:8]}): {b.get('title')!r} {_temporal_tag(b)}\n"

# AFTER
f"A: {a.get('title')!r} {_temporal_tag(a)}\n"
f"B: {b.get('title')!r} {_temporal_tag(b)}\n"
```

### A4.2 删除硬编码 fallback (line 537-552)

```python
# BEFORE
style_prompts = _PROMPT_STYLES.get(prompt_style, {})
system = style_prompts.get("contradiction")
if not system:
    system = ( ...长达 12 行硬编码... )

# AFTER
style_prompts = _PROMPT_STYLES.get(prompt_style, {})
system = style_prompts.get("contradiction") or _PROMPT_STYLES["balanced"]["contradiction"]
```

### A4.3 修改结果解析 — newer_id → newer label 映射 (line 571-574)

```python
# BEFORE
if item.get("contradicts"):
    newer_id = item.get("newer_id")
    older_id = b["id"] if newer_id == a["id"] else a["id"]

# AFTER
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
```

### A4.4 修改 temporal prompt 中的 newer_id 引用 (line 559)

```python
# BEFORE
"- 更新日期更近的记忆更可能正确，newer_id 应指向 updated 字段更新的那条\n"

# AFTER
"- 更新日期更近的记忆更可能正确，newer 应为 \"A\" 或 \"B\" 中 updated 字段更新的那条\n"
```

---

## 步骤 A5：Batch 级 JSON 容错

**位置**: 所有 `_llm_judge_*` 函数中的 `json.loads(raw)` 调用

**改动模式**: 将每个函数的 `try: raw, thinking = ... / data = json.loads(raw) / ... except Exception:` 块拆分为两层 try:

```python
# PATTERN — 应用到 _llm_judge_duplicates (line 413-454),
#           _llm_judge_contradictions (line 563-588),
#           _llm_reassess_importance (line 647-673),
#           _llm_detect_splittable (line 725-747)

# BEFORE (每个函数都类似)
try:
    raw, thinking = _call_llm_with_thinking(prompt, system, llm_config)
    data = json.loads(raw)
    for item in data.get("results", []):
        ...处理逻辑...
except Exception as exc:
    logger.error("LLM ... failed: %s\nraw=%s", exc, locals().get("raw", "N/A"), exc_info=True)
    raise

# AFTER
try:
    raw, thinking = _call_llm_with_thinking(prompt, system, llm_config)
except Exception as exc:
    logger.error("LLM call failed for batch %d: %s", i, exc, exc_info=True)
    raise
try:
    data = json.loads(raw)
except (json.JSONDecodeError, ValueError) as exc:
    logger.warning("JSON parse failed for batch %d, skipping: %s\nraw=%s", i, exc, raw[:200])
    continue
for item in data.get("results", []):
    ...处理逻辑不变...
```

**关键**: LLM 调用失败仍然 raise（可能是网络/配额问题），但 JSON 解析失败只 warning + continue，不丢弃已有结果。

---

## Phase A 验证

```bash
cd /home/advancer/project/memorycore
.venv/bin/python -c "
from memorycore.storage.curator_llm import _PROMPT_STYLES
# 验证 aggressive 不再是空字典
assert 'duplicate' in _PROMPT_STYLES['aggressive'], 'aggressive.duplicate missing'
assert 'contradiction' in _PROMPT_STYLES['aggressive'], 'aggressive.contradiction missing'
assert 'importance' in _PROMPT_STYLES['aggressive'], 'aggressive.importance missing'
assert 'split' in _PROMPT_STYLES['aggressive'], 'aggressive.split missing'

# 验证 keep_id 已被替换为 keep
for style in ('conservative', 'balanced', 'aggressive'):
    dup = _PROMPT_STYLES[style]['duplicate']
    assert 'keep_id' not in dup, f'{style}.duplicate still has keep_id'
    assert \"'keep'\" in dup or '\"keep\"' in dup, f'{style}.duplicate missing keep field'
    contra = _PROMPT_STYLES[style]['contradiction']
    assert 'newer_id' not in contra, f'{style}.contradiction still has newer_id'
    assert \"'newer'\" in contra or '\"newer\"' in contra, f'{style}.contradiction missing newer field'

# 验证 importance 保护 feedback
imp = _PROMPT_STYLES['aggressive']['importance']
assert 'feedback_score' in imp.lower() or 'feedback' in imp, 'aggressive.importance missing feedback protection'

print('Phase A 验证通过 ✓')
"
```

---

# Phase B：消除性能浪费（P0）

## 步骤 B1：合并向量扫描 — 新增 `_find_candidate_pairs`

**位置**: `memorycore/storage/curator_llm.py`，替换 line 299-356 和 line 462-514

**操作**: 删除 `_find_semantic_duplicate_candidates` 和 `_find_contradiction_candidates`，新增统一的 `_find_candidate_pairs`。

在 line 298（`# 1. Semantic deduplication` 注释之前）插入新函数:

```python
def _find_candidate_pairs(
    vs: Any,
    memories: list[dict[str, Any]],
    sim_threshold: float,
) -> list[tuple[dict, dict, float]]:
    """一次向量扫描，返回所有高于 sim_threshold*0.8 的候选对。
    
    调用方按分数区间分流：
    - >= sim_threshold → 去重候选
    - >= sim_threshold*0.8 但 < sim_threshold → 矛盾候选
    """
    recently_reviewed = _get_recently_reviewed_ids()
    memories = [m for m in memories if m["id"] not in recently_reviewed]

    seen: set[frozenset[str]] = set()
    pairs: list[tuple[dict, dict, float]] = []
    by_id = {m["id"]: m for m in memories}
    missing_ids: set[str] = set()
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

    return sorted(pairs, key=lambda x: x[2], reverse=True)
```

**然后删除** 旧的 `_find_semantic_duplicate_candidates`（line 299-356）和 `_find_contradiction_candidates`（line 462-514）。

---

## 步骤 B2：修改 `llm_curator_report` 使用合并扫描

**位置**: `memorycore/storage/curator_llm.py` — `llm_curator_report()` line 805-828

```python
# BEFORE (line 805-828)
# --- Semantic deduplication ---
semantic_duplicates: list[dict] = []
contradictions: list[dict] = []

if vs_available:
    try:
        dup_pairs = _find_semantic_duplicate_candidates(vs, memories, effective_sim)
        ...
    except: ...
    try:
        contra_pairs = _find_contradiction_candidates(vs, memories, effective_sim)
        ...
    except: ...

# AFTER
# --- Unified vector scan → dedup + contradiction ---
semantic_duplicates: list[dict] = []
contradictions: list[dict] = []
all_evaluated_ids: set[str] = set()

max_dedup = cfg.get("max_dedup_pairs", 200)
max_contra = cfg.get("max_contradiction_pairs", 200)

if vs_available:
    try:
        t0 = _time.monotonic()
        all_pairs = _find_candidate_pairs(vs, memories, effective_sim)
        timing["vector_search_ms"] = int((_time.monotonic() - t0) * 1000)

        dup_pairs = [p for p in all_pairs if p[2] >= effective_sim][:max_dedup]
        contra_pairs = [p for p in all_pairs if p[2] >= effective_sim * 0.8][:max_contra]
        diagnostics["dedup_pairs_found"] = len(dup_pairs)
        diagnostics["contradiction_pairs_found"] = len(contra_pairs)
    except Exception as exc:
        dup_pairs = []
        contra_pairs = []
        errors.append(f"Vector scan failed: {exc}")
        logger.error("vector scan error: %s", exc, exc_info=True)

    if dup_pairs:
        try:
            t0 = _time.monotonic()
            diagnostics["dedup_llm_calls"] = len(dup_pairs) // batch_size + (1 if len(dup_pairs) % batch_size else 0)
            semantic_duplicates, dedup_evaluated = _llm_judge_duplicates(
                dup_pairs, llm_config, batch_size=batch_size,
                content_max_chars=content_max_chars, prompt_style=prompt_style,
                config=full_config)
            all_evaluated_ids.update(dedup_evaluated)
            timing["dedup_llm_ms"] = int((_time.monotonic() - t0) * 1000)
        except Exception as exc:
            errors.append(f"Semantic dedup failed: {exc}")
            logger.error("semantic dedup error: %s", exc, exc_info=True)

    if contra_pairs:
        try:
            t0 = _time.monotonic()
            diagnostics["contradiction_llm_calls"] = len(contra_pairs) // batch_size + (1 if len(contra_pairs) % batch_size else 0)
            contradictions, contra_evaluated = _llm_judge_contradictions(
                contra_pairs, llm_config, batch_size=batch_size,
                content_max_chars=content_max_chars, prompt_style=prompt_style,
                config=full_config)
            all_evaluated_ids.update(contra_evaluated)
            timing["contradiction_llm_ms"] = int((_time.monotonic() - t0) * 1000)
        except Exception as exc:
            errors.append(f"Contradiction detection failed: {exc}")
            logger.error("contradiction detection error: %s", exc, exc_info=True)
else:
    errors.append("Vector store not available — skipping semantic dedup and contradiction detection")
```

**同时在 diagnostics 初始化处（line 769）新增**:
```python
timing: dict[str, int] = {}
```

---

## 步骤 B3：`_llm_judge_duplicates` 和 `_llm_judge_contradictions` 增加 `config` 参数并返回 evaluated_ids

### _llm_judge_duplicates 签名和返回值

```python
# BEFORE (line 359-365)
def _llm_judge_duplicates(
    pairs: list[tuple[dict, dict, float]],
    llm_config: Any,
    batch_size: int = 10,
    content_max_chars: int = 2000,
    prompt_style: str = "aggressive",
) -> list[dict[str, Any]]:
    ...
    return results

# AFTER
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
        for _, (a, b, _score) in enumerate(batch):
            evaluated_ids.add(a["id"])
            evaluated_ids.add(b["id"])
        ...其余逻辑...
    return results, evaluated_ids
```

**将函数内的所有 `load_config()` 替换为 `full_config`**:
- line 400-401: `output_language = load_config().get(...)` → `output_language = full_config.get("output_language", "auto")`
- line 405: `full_config_for_temporal = load_config()` → 直接用 `full_config`
- line 428-429: `from memorycore.models import load_config` + `load_config().get(...)` → `full_config.get(...)`

### _llm_judge_contradictions 同理

```python
# 签名
def _llm_judge_contradictions(
    pairs, llm_config, batch_size=10, content_max_chars=2000, prompt_style="aggressive",
    config: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], set[str]]:
    full_config = config or {}
    results = []
    evaluated_ids: set[str] = set()
    ...
    return results, evaluated_ids
```

- line 554: `from memorycore.models import load_config as _lc2` → 删除，用 `full_config`

### _llm_reassess_importance 同理

```python
# 签名增加 config 参数
def _llm_reassess_importance(
    memories, llm_config, batch_size=10, content_max_chars=2000,
    prompt_style="aggressive", keep_threshold=0.02,
    config: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], set[str]]:
    full_config = config or {}
    results = []
    evaluated_ids: set[str] = set()
    ...
    return results, evaluated_ids
```

---

## 步骤 B4：全量冷却 — 替换 `llm_curator_report` 中的冷却逻辑

**位置**: `memorycore/storage/curator_llm.py` line 864-879

```python
# BEFORE (line 864-879)
found_ids: set[str] = set()
for dup in semantic_duplicates:
    found_ids.add(dup.get("keep_id") or "")
    found_ids.add(dup.get("drop_id") or "")
for contra in contradictions:
    found_ids.add(contra.get("newer_id") or "")
    found_ids.add(contra.get("older_id") or "")
for reassess in importance_reassessments:
    found_ids.add(reassess.get("id") or "")
for split in split_candidates:
    found_ids.add(split.get("id") or "")
found_ids.discard("")
if found_ids:
    _mark_reviewed(list(found_ids))

# AFTER — 使用前面收集的 all_evaluated_ids
all_evaluated_ids.discard("")
diagnostics["cooldown_registered"] = len(all_evaluated_ids)
if all_evaluated_ids:
    _mark_reviewed(list(all_evaluated_ids))
```

---

## Phase B 验证

```bash
.venv/bin/python -c "
from memorycore.storage.curator_llm import _find_candidate_pairs
print('_find_candidate_pairs 函数存在 ✓')

# 验证旧函数已删除
try:
    from memorycore.storage.curator_llm import _find_semantic_duplicate_candidates
    print('ERROR: _find_semantic_duplicate_candidates 应该已删除')
except ImportError:
    print('旧函数已删除 ✓')

# 验证返回值是 tuple
import inspect
sig = inspect.signature(
    __import__('memorycore.storage.curator_llm', fromlist=['_llm_judge_duplicates'])._llm_judge_duplicates
)
print(f'_llm_judge_duplicates 参数: {list(sig.parameters.keys())}')
assert 'config' in sig.parameters, 'config 参数缺失'
print('Phase B 验证通过 ✓')
"
```

---

# Phase C：Prompt 质量提升（P1）

## 步骤 C1：给 conservative 和 balanced 的 importance prompt 追加 feedback 保护

**位置**: `memorycore/storage/curator_llm.py`

### conservative.importance (line 59-65)

```python
# BEFORE (line 60-61)
"Only change importance if there is a clear reason. Prefer 'keep' when uncertain. "

# AFTER
"Only change importance if there is a clear reason. Prefer 'keep' when uncertain. "
"Memories with positive feedback_score (> 0) have been validated by the user — "
"do NOT archive or downgrade these unless the content is demonstrably outdated. "
```

### balanced.importance (line 95-102)

```python
# BEFORE (line 98)
"Consider recency, actionability, and uniqueness. Make changes when justified. "

# AFTER
"Consider recency, actionability, and uniqueness. Make changes when justified. "
"Memories with positive feedback_score (> 0) have been validated by the user — "
"do NOT archive or downgrade these unless the content is demonstrably outdated. "
```

**注意**: aggressive.importance 已在步骤 A2 中包含。

---

## 步骤 C2：统一 `_language_instruction()` 到 contradiction 和 importance

**位置**: `_llm_judge_contradictions` (line 553 附近) 和 `_llm_reassess_importance` (line 637 附近)

### _llm_judge_contradictions — 在 temporal prompt 之前追加 (原 line 553)

```python
# 在构建 prompt 之后，temporal 检查之前，追加:
output_language = full_config.get("output_language", "auto")
lang_suffix = _language_instruction(output_language)
if lang_suffix:
    system += lang_suffix
```

### _llm_reassess_importance — 同理 (原 line 637)

```python
output_language = full_config.get("output_language", "auto")
lang_suffix = _language_instruction(output_language)
if lang_suffix:
    system += lang_suffix
```

---

## 步骤 C3：`_temporal_tag` 支持双语

**位置**: `memorycore/storage/curator_llm.py` line 163-217

在函数开头增加语言判断:

```python
def _temporal_tag(record: dict[str, Any]) -> str:
    from memorycore.models import load_config, local_now
    cfg = load_config()
    if not cfg.get("temporal", {}).get("enabled", False):
        return ""
    lang = cfg.get("output_language", "auto")
    is_zh = lang in ("zh", "auto")  # auto 默认中文（当前配置 output_language=zh）
    try:
        from datetime import datetime
        now_dt = local_now()

        def _fmt(ts: str | None) -> str:
            if not ts:
                return "未知" if is_zh else "unknown"
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                return dt.strftime("%Y-%m-%d")
            except Exception:
                return str(ts)[:10]

        def _days_ago(ts: str | None) -> str:
            if not ts:
                return "?"
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    from datetime import timezone
                    dt = dt.replace(tzinfo=timezone.utc)
                delta = now_dt - dt
                return str(max(0, delta.days))
            except Exception:
                return "?"

        created = _fmt(record.get("created_at"))
        updated = _fmt(record.get("updated_at"))
        days_ago = _days_ago(record.get("updated_at") or record.get("created_at"))

        if is_zh:
            tag = f"[时间: 创建={created}, 更新={updated}, 距今={days_ago}天"
        else:
            tag = f"[Time: created={created}, updated={updated}, age={days_ago}d"

        last_access = _fmt(record.get("last_accessed_at"))
        no_access = "未知" if is_zh else "unknown"
        if last_access != no_access:
            lbl = "最后访问" if is_zh else "last_access"
            tag += f", {lbl}={last_access}"

        vf = record.get("valid_from")
        vu = record.get("valid_until")
        if vf or vu:
            lbl = "有效期" if is_zh else "validity"
            tag += f", {lbl}={_fmt(vf)}~{_fmt(vu)}"

        tag += "]"
        return tag
    except Exception:
        return ""
```

---

# Phase D：新增图谱建链能力（P1）

## 步骤 D1：新增 `_find_link_candidates` 函数

**位置**: 在 `_find_candidate_pairs` 函数之后插入

```python
def _find_link_candidates(
    vs: Any,
    memories: list[dict[str, Any]],
    sim_threshold: float,
    link_upper: float = 0.75,
    max_pairs: int = 100,
) -> list[tuple[dict, dict, float]]:
    """找出适合建链的候选对: 相似度在 [sim_threshold, link_upper] 之间且尚无链接。"""
    from memorycore.storage.db import read_conn

    with read_conn() as conn:
        existing_links = set()
        for row in conn.execute("SELECT source_id, target_id FROM memory_links").fetchall():
            existing_links.add(frozenset([row["source_id"], row["target_id"]]))
        orphan_ids = set()
        for row in conn.execute(
            "SELECT m.id FROM memories m "
            "WHERE m.status IN ('active','candidate') "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM memory_links ml "
            "  WHERE ml.source_id = m.id OR ml.target_id = m.id"
            ")"
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
```

---

## 步骤 D2：新增 `_llm_discover_links` 函数

**位置**: 在 `_llm_detect_splittable` 之后、`llm_curator_report` 之前插入

```python
_LINK_DISCOVERY_PROMPTS = {
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
        "Allowed relations:\n"
        "- related_to: share the same topic, project, or domain\n"
        "- supports: one provides evidence, detail, or context for the other\n"
        "- part_of: one is a component or subset of the other\n"
        "- supersedes: one is a newer version that replaces the other\n"
        "- none: no meaningful relationship\n"
        "Return JSON with key 'results': list of "
        "{'index': int, 'relation': str, 'direction': 'A->B' or 'B->A', 'reason': str ≤20 words}."
    ),
    "aggressive": (
        "You are an aggressive knowledge graph curator. Your goal is to maximize useful connections. "
        "Err on the side of linking — an extra link is cheaper than a missing one. "
        "Allowed relations:\n"
        "- related_to: any topical or contextual overlap\n"
        "- supports: one provides evidence, detail, example, or context for the other\n"
        "- part_of: one is a component, subset, or instance of the other\n"
        "- supersedes: one is a newer version that replaces the other\n"
        "- none: truly unrelated memories\n"
        "When in doubt, use 'related_to'. Only use 'none' for clearly unrelated pairs.\n"
        "Return JSON with key 'results': list of "
        "{'index': int, 'relation': str, 'direction': 'A->B' or 'B->A', 'reason': str ≤20 words}."
    ),
}


def _llm_discover_links(
    pairs: list[tuple[dict, dict, float]],
    llm_config: Any,
    batch_size: int = 10,
    content_max_chars: int = 2000,
    prompt_style: str = "aggressive",
    config: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], set[str]]:
    """Ask LLM to identify semantic relationships between memory pairs for graph linking."""
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
                f"similarity={score:.3f}\n"
            )

        system = _LINK_DISCOVERY_PROMPTS.get(
            prompt_style, _LINK_DISCOVERY_PROMPTS["balanced"]
        )
        output_language = full_config.get("output_language", "auto")
        lang_suffix = _language_instruction(output_language)
        if lang_suffix:
            system += lang_suffix

        prompt = f"Analyze these memory pairs for semantic relationships:\n{items_text}"

        try:
            raw, thinking = _call_llm_with_thinking(prompt, system, llm_config)
        except Exception as exc:
            logger.error("LLM link discovery call failed batch %d: %s", i, exc)
            raise
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("JSON parse failed for link discovery batch %d: %s", i, exc)
            continue

        valid_relations = {"related_to", "supports", "part_of", "supersedes"}
        for item in data.get("results", []):
            idx = item.get("index", 0)
            if not isinstance(idx, int) or idx >= len(batch):
                continue
            relation = str(item.get("relation") or "none").lower().strip()
            if relation not in valid_relations:
                continue
            a, b, score = batch[idx]
            direction = str(item.get("direction") or "A->B").upper().strip()
            if "B" in direction and direction.startswith("B"):
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
```

---

## 步骤 D3：主流程集成 — `llm_curator_report` 中添加 link discovery 阶段

**位置**: 在 importance reassessment 之后、split detection 之前插入

```python
    # --- Link discovery (knowledge graph) ---
    link_discoveries: list[dict] = []
    max_link = cfg.get("max_link_pairs", 100)
    if vs_available:
        try:
            t0 = _time.monotonic()
            link_pairs = _find_link_candidates(vs, memories, effective_sim, max_pairs=max_link)
            diagnostics["link_pairs_found"] = len(link_pairs)
            if link_pairs:
                diagnostics["link_llm_calls"] = len(link_pairs) // batch_size + (1 if len(link_pairs) % batch_size else 0)
                link_discoveries, link_evaluated = _llm_discover_links(
                    link_pairs, llm_config, batch_size=batch_size,
                    content_max_chars=content_max_chars, prompt_style=prompt_style,
                    config=full_config)
                all_evaluated_ids.update(link_evaluated)
                _mark_reviewed(list(link_evaluated), review_type="llm_link_discovery")
            timing["link_discovery_ms"] = int((_time.monotonic() - t0) * 1000)
        except Exception as exc:
            errors.append(f"Link discovery failed: {exc}")
            logger.error("link discovery error: %s", exc, exc_info=True)
```

**在 diagnostics 初始化处新增**:
```python
"link_pairs_found": 0,
"link_llm_calls": 0,
```

**在 return 中新增**:
```python
"link_discoveries": link_discoveries,
```

**在 summary 中新增**:
```python
"link_discoveries": len(link_discoveries),
```

---

## 步骤 D4：`apply_llm_curator` 中添加 link 执行

**位置**: `memorycore/storage/curator_llm.py` — `apply_llm_curator()` line 964-1018

### 在 applied 字典中新增 (line 969-980):
```python
"link_discoveries_created": 0,
```

### 在 `_append_split_requests` 调用之后 (line 988) 添加:
```python
_append_link_discovery_requests(report, requests)
```

### 新增 `_append_link_discovery_requests` 函数 (在 `_append_split_link_requests` 之后):

```python
def _append_link_discovery_requests(report: dict[str, Any], requests: list[MutationRequest]) -> None:
    for link in report.get("link_discoveries", []) or []:
        source_id = link.get("source_id")
        target_id = link.get("target_id")
        relation = link.get("relation_type", "related_to")
        if not source_id or not target_id:
            continue
        requests.append(MutationRequest(
            action_type="memory_link_insert",
            target_type="memory_link",
            payload={
                "source_id": source_id,
                "target_id": target_id,
                "relation_type": relation,
                "weight": 0.8,
                "note": f"LLM curator link discovery: {link.get('reason', '')}",
            },
            risk_level="low",
            confidence=0.85,
            idempotency_key=f"llm-curator:link-discovery:{source_id}:{target_id}:{relation}",
        ))
```

### 在 `_count_applied_results` 中追加计数 (line 1258 附近):
```python
elif mutation_type == "memory_link_insert":
    request = _request_from_result(result)
    note = (request.get("payload") or {}).get("note", "")
    if "link discovery" in note:
        applied["link_discoveries_created"] += 1
    elif result.get("before") is None:
        applied["split_links_created"] += 1
    else:
        applied["split_links_skipped"] += 1
```

---

## 步骤 D5：知识图谱预设参数修正

**位置**: `ui/components/dashboard/CuratorTuningPanel.tsx` line 90-106

```typescript
// BEFORE
knowledge_graph: {
    label: "knowledge_graph",
    temperature: 0.5,
    sim_threshold: 0.45,
    split_content_threshold: 300,
    importance_limit: 1500,
    content_max_chars: 3000,
    batch_size: 8,
    review_cooldown_seconds: 1200,
    keep_threshold: 0.03,
    auto_approve_confidence: 0.85,
    prompt_style: "balanced" as PromptStyle,
    reviewed_ids_max_age_seconds: 64800,
},

// AFTER
knowledge_graph: {
    label: "knowledge_graph",
    temperature: 0.6,
    sim_threshold: 0.55,
    split_content_threshold: 400,
    importance_limit: 100,
    content_max_chars: 3000,
    batch_size: 10,
    review_cooldown_seconds: 900,
    keep_threshold: 0.02,
    auto_approve_confidence: 0.85,
    prompt_style: "aggressive" as PromptStyle,
    reviewed_ids_max_age_seconds: 43200,
},
```

---

# Phase E：调度协调（P2）

## 步骤 E1：移除后台线程中的 rule curator 调用

**位置**: `memorycore/server.py` — `_start_auto_curator()` (搜索 `_start_auto_curator`)

在后台线程循环体中找到 `curator_report(dry_run=False)` 调用并删除。保留 rollup、handoff_cleanup、vector_sync_drain。

```python
# BEFORE (server.py 后台线程循环体)
cleanup_expired_handoffs()
_drain_vector_sync_queue()
rollup_report(dry_run=False)
curator_report(dry_run=False)   # ← 删除此行

# AFTER
cleanup_expired_handoffs()
_drain_vector_sync_queue()
rollup_report(dry_run=False)
```

---

# Phase F：收尾优化（P2）

## 步骤 F1：`_request_from_result` 查询优化

**位置**: `memorycore/storage/curator_llm.py` line 1265-1276

```python
# BEFORE
def _request_from_result(result: dict[str, Any]) -> dict[str, Any]:
    log_id = result.get("log_id")
    if not log_id:
        return {}
    rows = query_ledger(limit=500)
    for row in rows:
        if row.get("id") == log_id:
            try:
                return json.loads(row.get("request_json") or "{}")
            except Exception:
                return {}
    return {}

# AFTER
def _request_from_result(result: dict[str, Any]) -> dict[str, Any]:
    log_id = result.get("log_id")
    if not log_id:
        return {}
    from memorycore.storage.db import read_conn
    with read_conn() as conn:
        row = conn.execute(
            "SELECT request_json FROM governance_ledger WHERE id = ? LIMIT 1",
            (log_id,),
        ).fetchone()
    if row:
        try:
            return json.loads(row["request_json"] or "{}")
        except Exception:
            return {}
    return {}
```

---

## 步骤 F2：硬编码上限配置化

**位置**: `memorycore/models.py` — `DEFAULT_CONFIG["llm_curator"]`

追加以下默认值:

```python
"llm_curator": {
    ...existing keys...,
    "max_dedup_pairs": 200,
    "max_contradiction_pairs": 200,
    "max_split_candidates": 100,
    "max_link_pairs": 100,
}
```

**位置**: `memorycore/storage/curator_llm.py` — `llm_curator_report()` line 760-766

在 cfg 读取处追加:
```python
max_split = cfg.get("max_split_candidates", 100)
```

在 split detection (line 856) 处:
```python
# BEFORE
][:100]  # up to 100 long memories per run

# AFTER
][:max_split]
```

---

## 步骤 F3：Diagnostics 最终汇总

**位置**: `memorycore/storage/curator_llm.py` — `llm_curator_report()` return 之前

```python
diagnostics["timing"] = timing
diagnostics["json_parse_failures"] = 0  # 各函数内可累加
timing["total_ms"] = int((_time.monotonic() - t_start) * 1000)
```

在函数入口处追加 `t_start`:
```python
t_start = _time.monotonic()
```

---

# 最终验证

```bash
cd /home/advancer/project/memorycore

# 1. 语法检查
.venv/bin/python -c "import memorycore.storage.curator_llm; print('import OK ✓')"

# 2. 新函数存在性检查
.venv/bin/python -c "
from memorycore.storage.curator_llm import (
    _find_candidate_pairs,
    _find_link_candidates,
    _llm_discover_links,
    _LINK_DISCOVERY_PROMPTS,
)
print('所有新函数存在 ✓')
"

# 3. Prompt 格式检查
.venv/bin/python -c "
from memorycore.storage.curator_llm import _PROMPT_STYLES
for style in ('conservative', 'balanced', 'aggressive'):
    d = _PROMPT_STYLES[style]
    assert 'duplicate' in d and 'contradiction' in d and 'importance' in d and 'split' in d
    assert 'keep_id' not in d['duplicate']
    assert 'newer_id' not in d['contradiction']
print('Prompt 格式验证 ✓')
"

# 4. TypeScript 编译
cd ui && npx tsc --noEmit 2>&1 | head -5

# 5. 运行测试
cd /home/advancer/project/memorycore && .venv/bin/python -m pytest tests/ -x -q 2>&1 | tail -10
```

---

# 提交与迭代文档

```bash
# 写 ITERATION.md（追加到底部）
# git add 所有改动文件
# git commit -m "feat: LLM Curator 全面优化 (Phase A-F)"
# git push
```

改动文件清单:
- `memorycore/storage/curator_llm.py` — 核心: Phase A+B+C+D+F
- `memorycore/models.py` — Phase F: DEFAULT_CONFIG 新增上限配置
- `memorycore/server.py` — Phase E: 移除后台线程 rule curator 调用
- `ui/components/dashboard/CuratorTuningPanel.tsx` — Phase D: 知识图谱预设修正
