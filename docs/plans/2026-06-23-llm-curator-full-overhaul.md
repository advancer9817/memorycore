# LLM Curator + Rule Curator 全面优化方案

> 日期: 2026-06-23
> 状态: 待实施
> 关联: [时间感知架构](2026-06-23-temporal-awareness-architecture.md)

---

## 背景

对 LLM Curator (`curator_llm.py`, 1276 行) 和 Rule Curator (`curator.py`) 做了全面深度审计，发现 **6 个系统性问题、18 个具体缺陷**。当前 LLM Curator 整体效果不佳，核心表现：

- **71% 记忆零图谱链接**（238/334 条孤立）
- **651 条链接中 634 条是机械性 split 副产物**，仅 11 条 `related_to`
- **keep_id/newer_id 判断完全无效** — LLM 返回 8 字符截断 ID，代码比对完整 UUID，永远不匹配
- **无发现的记忆不进 cooldown** — 每次运行对同一批"无问题"记忆重复向量搜索 + LLM 调用
- **去重和矛盾检测做两轮独立全量向量扫描** — 搜索量翻倍
- **两套调度机制重叠** — systemd timer (每小时) 和进程内线程 (每 6 小时) 参数冲突

---

## 系统数据快照

| 指标 | 当前值 |
|------|--------|
| 活跃/候选记忆 | 334 |
| 图谱链接总数 | 651 |
| `related_to` 链接 | 11 (1.7%) |
| `supports` / `part_of` | 318 / 316 (全是 split 副产物) |
| 孤立记忆（零链接） | 238 / 334 = **71%** |
| Cooldown 注册数 | 174 |
| 最近一次运行 dedup_pairs | 414 |
| 最近一次运行 contradiction_pairs | 529 |
| 提取模型 | gemini-pro-agent (本地代理) |
| 触发频率 | systemd 每小时 (rule+LLM) + 后台线程每 6 小时 (仅 rule) |

---

## Phase A：修复数据损坏风险（P0，最紧急）

### A1. 修复 ID 截断 — 让 LLM 返回 "A"/"B" 而非 UUID

**问题**: Prompt 传 `id=abcd1234`（8 字符），代码期望完整 36 字符 UUID。`_llm_judge_duplicates` line 423 `if llm_keep_id in (a["id"], b["id"])` 永远 False，keep_id 判断完全废弃。矛盾检测的 `newer_id` 同理，导致 `older_id` 恒为 `a["id"]` — **静默数据损坏**。

**改动**:

文件: `memorycore/storage/curator_llm.py`

- `_llm_judge_duplicates` — Prompt 改为 `记忆A: ...` / `记忆B: ...`，要求 LLM 返回 `keep: "A"` 或 `keep: "B"`
- 代码侧：`keep_label = item.get("keep")` → 映射 `"A"→a["id"]`, `"B"→b["id"]`
- 保留时间/importance fallback 作为兜底

- `_llm_judge_contradictions` — 同理，返回 `newer: "A"` 或 `newer: "B"`
- 增加校验：如果 label 无法识别，用 `updated_at` 时间戳 fallback

### A2. Batch 级 JSON 容错

**问题**: `json.loads(raw)` 失败时 `raise`，一个 batch 失败导致整个类别结果丢失。

**改动**:

文件: `memorycore/storage/curator_llm.py`

- 所有 `_llm_judge_*` 函数：在 batch 循环内 `try/except json.JSONDecodeError`
- 捕获后 `logger.warning` 记录，继续下一个 batch
- 将 parse 失败次数追加到 diagnostics

---

## Phase B：消除性能浪费（P0，减少 50%+ 消耗）

### B1. 合并向量扫描 — 去重和矛盾共用一轮搜索

**问题**: `_find_semantic_duplicate_candidates` (top_k=6) 和 `_find_contradiction_candidates` (top_k=5) 逻辑 90% 重复，独立执行两轮全量向量搜索。

**改动**:

文件: `memorycore/storage/curator_llm.py`

- 新增 `_find_candidate_pairs(vs, memories, sim_threshold)` — 一次扫描，top_k=6
- 返回 `list[tuple[dict, dict, float]]`，调用方按分数区间分流：
  - `>= sim_threshold` → 送去重判断
  - `>= sim_threshold * 0.8` → 送矛盾判断（移除 `max(0.60, ...)` 硬下限）
- 删除旧的 `_find_semantic_duplicate_candidates` 和 `_find_contradiction_candidates`

### B2. 全量冷却 — 所有经 LLM 评判的记忆都进 cooldown

**问题**: 只有有发现的记忆进冷却（line 866-879），无发现的反复扫描。

**改动**:

文件: `memorycore/storage/curator_llm.py`

- 每个 `_llm_judge_*` 函数增加返回值：`(results, evaluated_ids)`
- `llm_curator_report()` 中汇总所有 `evaluated_ids`（包括无发现的）
- 统一 `_mark_reviewed(all_evaluated_ids)`

### B3. `load_config()` 统一调用

**问题**: 单次运行中 `load_config()` 被调用 10+ 次，每次从磁盘读取。

**改动**:

文件: `memorycore/storage/curator_llm.py`

- `llm_curator_report()` 入口读一次 `full_config`
- 传递给所有 `_llm_judge_*` 函数（增加 `config` 参数）
- 移除函数内部的 `from memorycore.models import load_config` 重复调用

---

## Phase C：Prompt 质量提升（P1）

### C1. 填充 `_PROMPT_STYLES["aggressive"]`

**问题**: `"aggressive": {}` 是空字典，所有 aggressive prompt 靠函数内硬编码 fallback。

**改动**:

文件: `memorycore/storage/curator_llm.py`

- 把 `_llm_judge_duplicates` / `_llm_judge_contradictions` / `_llm_reassess_importance` / `_llm_detect_splittable` 中的硬编码 prompt 字符串移入 `_PROMPT_STYLES["aggressive"]`
- 消除 `if not system:` fallback 分支

### C2. 统一 `_language_instruction()` 到所有能力

**问题**: `_language_instruction()` 只在 duplicate 和 split 中使用，contradiction 和 importance 缺失。

**改动**:

文件: `memorycore/storage/curator_llm.py`

- `_llm_judge_contradictions` 追加 `_language_instruction()` 后缀
- `_llm_reassess_importance` 追加 `_language_instruction()` 后缀
- 后续新增的 `_llm_discover_links` 也需包含

### C3. Importance 保护正面 feedback 记忆

**问题**: LLM 可能 archive 有正面 feedback (>0) 的记忆，忽略用户信号。

**改动**:

文件: `memorycore/storage/curator_llm.py` — `_llm_reassess_importance` prompt

- 所有三套 prompt style 追加规则：
  - "feedback_score > 0 的记忆已被用户验证，不应 archive 或 downgrade，除非内容明显过时"

### C4. Temporal 标签语言统一

**问题**: 英文 system prompt + 中文 temporal 规则 + 中文数据标签 = 三种语言切换。

**改动**:

文件: `memorycore/storage/curator_llm.py`

- `_temporal_tag()` 根据 `output_language` 生成中文或英文标签
  - zh: `[时间: 创建=..., 更新=..., 距今=...天]`
  - en: `[Time: created=..., updated=..., age=...d]`
- Temporal 推理规则同理根据 `output_language` 切换语言

---

## Phase D：新增图谱建链能力（P1）

### D1. `_find_link_candidates` — 候选发现

**文件**: `memorycore/storage/curator_llm.py`

```
_find_link_candidates(
    vs, memories, sim_threshold,
    link_upper=0.75, max_pairs=100
) -> list[tuple[dict, dict, float]]
```

- 取向量相似度在 `[sim_threshold, link_upper]` 之间的对
  - 高于 link_upper 的已被去重处理
  - 低于 sim_threshold 的关联太弱
- **排除已有链接关系的对**（查 memory_links 表）
- **优先孤立记忆**（零链接的 238 条优先扫描）
- 每次最多 `max_pairs` 对

### D2. `_llm_discover_links` — LLM 判断关系类型

**文件**: `memorycore/storage/curator_llm.py`

```
_llm_discover_links(
    pairs, llm_config, batch_size, content_max_chars, prompt_style, config
) -> list[dict]
```

Prompt 设计：
```
你是一个知识图谱构建专家。分析每对记忆之间是否存在语义关系。
可选关系类型：
- related_to: 相关主题，互相提供上下文
- supports: A 为 B 提供证据或细节
- part_of: A 是 B 的组成部分
- supersedes: A 取代了 B（更新版本）
- none: 无有意义的关系

返回 JSON: {"results": [{"index": int, "relation": str, "direction": "A->B"|"B->A", "reason": str}]}
relation 为 "none" 时跳过。
```

三套 prompt_style 差异：
- conservative: 只建 related_to 和 supports，门槛高
- balanced: 全部关系类型
- aggressive: 积极建链，"宁可多建不可遗漏"

### D3. `_append_link_discovery_requests` — 执行建链

**文件**: `memorycore/storage/curator_llm.py`

复用现有 `memory_link_insert` MutationRequest 格式：
```python
MutationRequest(
    action_type="memory_link_insert",
    target_type="memory_link",
    payload={
        "source_id": ...,
        "target_id": ...,
        "relation_type": ...,
        "weight": 0.8,
        "note": f"LLM curator link discovery: {reason}",
    },
    risk_level="low",
    confidence=0.85,
    idempotency_key=f"llm-curator:link:{source}:{target}:{relation}",
)
```

### D4. 主流程集成

**文件**: `memorycore/storage/curator_llm.py` — `llm_curator_report()`

在去重、矛盾之后，split 之前执行：
```python
# --- Link discovery (knowledge graph) ---
link_discoveries = []
if vs_available:
    link_pairs = _find_link_candidates(vs, memories, effective_sim)
    diagnostics["link_pairs_found"] = len(link_pairs)
    if link_pairs:
        link_discoveries = _llm_discover_links(link_pairs, ...)
```

报告新增 `link_discoveries` 字段，summary 新增 `link_discoveries` 计数。
`apply_llm_curator` 新增 `_append_link_discovery_requests` 调用。
`applied` 字典新增 `links_created` 计数。

### D5. 知识图谱预设参数修正

**文件**: `ui/components/dashboard/CuratorTuningPanel.tsx`

```typescript
knowledge_graph: {
    label: "knowledge_graph",
    temperature: 0.6,        // 0.5→0.6
    sim_threshold: 0.55,     // 0.45→0.55 减少噪声
    split_content_threshold: 400,  // 300→400
    importance_limit: 100,   // 1500→100 防超时
    content_max_chars: 3000,
    batch_size: 10,          // 8→10
    review_cooldown_seconds: 900,  // 1200→900
    keep_threshold: 0.02,    // 0.03→0.02
    auto_approve_confidence: 0.85,
    prompt_style: "aggressive" as PromptStyle,  // balanced→aggressive
    reviewed_ids_max_age_seconds: 43200, // 64800→43200
}
```

---

## Phase E：调度协调（P2）

### E1. 消除双重触发

**文件**: `memorycore/server.py` — `_start_auto_curator()`

移除后台线程中的 `curator_report(dry_run=False)` 调用，保留 rollup + handoff_cleanup + vector_sync_drain。规则型 curator 执行统一由 systemd timer 负责。

### E2. Rule ↔ LLM 冷却互认

**文件**: `memorycore/storage/curator.py`

Rule curator 的 title-dedup 和 supersession 检测应查询 `curator_review_log`，排除正在被 LLM curator 处理的记忆，避免矛盾决策。

---

## Phase F：收尾优化（P2）

### F1. `_request_from_result` 查询优化

**文件**: `memorycore/storage/curator_llm.py` line 1265-1276

替换全表遍历为直接 `WHERE id = ?` 单条查询。

### F2. 硬编码上限配置化

**文件**: `memorycore/storage/curator_llm.py`

- `max_dedup_pairs`（当前硬编码 200）→ `llm_curator.max_dedup_pairs`
- `max_contradiction_pairs`（当前硬编码 200）→ `llm_curator.max_contradiction_pairs`
- `max_split_candidates`（当前硬编码 100）→ `llm_curator.max_split_candidates`
- `max_link_pairs`（新增，默认 100）→ `llm_curator.max_link_pairs`

### F3. Diagnostics 追加耗时和 token 指标

**文件**: `memorycore/storage/curator_llm.py`

```python
diagnostics["timing"] = {
    "vector_search_ms": ...,
    "dedup_llm_ms": ...,
    "contradiction_llm_ms": ...,
    "importance_llm_ms": ...,
    "split_llm_ms": ...,
    "link_discovery_llm_ms": ...,
    "total_ms": ...,
}
diagnostics["cooldown_filtered_count"] = ...
diagnostics["json_parse_failures"] = ...
```

---

## 实施优先级

| 优先级 | Phase | 改动量 | 核心收益 |
|--------|-------|--------|---------|
| **P0** | A (修复数据损坏) | ~80 行 | 修复 keep_id/newer_id 无效 bug，防止静默数据损坏 |
| **P0** | B (消除浪费) | ~120 行 | 减少 50%+ 向量搜索和 LLM token 消耗 |
| **P1** | C (Prompt 质量) | ~100 行 | 提升 LLM 判断准确性，保护用户验证的记忆 |
| **P1** | D (图谱建链) | ~200 行 | 解决 71% 记忆零链接问题，真正驱动图谱增长 |
| **P2** | E (调度协调) | ~30 行 | 消除双重触发和矛盾决策 |
| **P2** | F (收尾) | ~50 行 | 性能优化和可观测性改善 |

---

## 关键文件清单

| 文件 | Phase | 改动类型 |
|------|-------|---------|
| `memorycore/storage/curator_llm.py` | A, B, C, D, F | 核心：修复 ID、合并扫描、全量冷却、prompt 质量、新增建链能力 |
| `memorycore/server.py` | E | 移除后台线程的 rule curator 调用 |
| `memorycore/storage/curator.py` | E | 冷却互认 |
| `ui/components/dashboard/CuratorTuningPanel.tsx` | D | 知识图谱预设参数修正 |
| `config.yaml` | F | 新增配置项默认值 |
| `memorycore/models.py` | F | DEFAULT_CONFIG 新增 llm_curator 上限配置 |

## 验证方案

| Phase | 验证方法 |
|-------|---------|
| A | 构造测试：两条相似记忆 → LLM 返回 keep="A" → 代码正确映射为 a["id"] |
| B | 对比改动前后 diagnostics: vector_search 次数减半，cooldown 覆盖率从 ~50% 提升至 ~90% |
| C | 创建 feedback_score=1.0 的记忆 → importance 重评估不应 archive |
| D | 运行后检查 link_discoveries > 0，孤立记忆比例从 71% 下降 |
| E | 确认后台线程不再运行 rule curator，systemd timer 是唯一执行入口 |
| F | diagnostics 包含 timing 字段，`_request_from_result` 查询耗时 <1ms |
| 全量 | `cd /home/advancer/project/memorycore && .venv/bin/python -m pytest tests/` |
