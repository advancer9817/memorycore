# Phase 4：提取-召回闭环增强 — 详细设计

> 日期：2026-06-30
> 状态：草案
> 依赖：Phase 1 (MCP 精简) ✅, Phase 2 (治理简化) ✅

## 1. 问题诊断

基于当前 memory.sqlite3 数据分析：

| 指标 | 当前值 | 目标值 | 差距 |
|------|--------|--------|------|
| active 记忆未被注入率 | 52% (422/808) | <30% | 提取产出不适配召回 |
| effectiveness_score 高分率 | 6.7% (54/808) | >40% | 反馈信号太弱 |
| cross_retrieval_rate | 0.015 | >0.3 | FTS 和向量各找各的 |
| vector_avg_score | 0.167 | >0.4 | 向量召回质量差 |
| avg_hit_rate | 0.926 | >0.9 | ✅ 已达标 |

**根因分析**：

1. **提取与召回脱节**：提取时不考虑召回需求，产出的 title 和 content 格式对 FTS5 不友好
2. **原子化时机错误**：当前在 `add_memory_record` 后由 `atomize_record` 做事后拆分，但拆分质量依赖正则，丢失语义
3. **反馈信号未反哺**：`feedback_score` 和 `effectiveness_score` 虽然参与了排序权重，但不影响提取策略
4. **向量质量差**：嵌入文本是 `title + content` 的拼接，title 被截断到 80 字符常常语义不完整

## 2. 设计目标

> 核心理念：**提取为召回服务，召回反馈指导提取**

- **记得准**：extraction 后 type 分类准确率 > 90%、自包含率 > 95%
- **读得准**：Top-3 命中率 > 80%
- **治得好**：active 记忆中 injected_count > 0 的比例 > 60%（当前 48%）
- **闭环转**：effectiveness_score 高分率 > 40%

## 3. 四个子模块设计

### 3.1 写入时原子化（替代事后拆分）

**现状**：
- `extraction.py` 提取出一整条事实 → `dedup.py` 写入 → `crud.py:add_memory_record()` 判断 `should_atomize` → 事后调 `atomize_record` 做正则拆分
- 拆分阈值 min_chars=600，用正则按标点/列表项拆分，丢失语义边界

**改造**：
将拆分逻辑前移到提取阶段，让 LLM 直接产出原子化事实。

```
当前流程：
  LLM → 长文本事实 → dedup → write → 正则拆分 → 子记忆

新流程：
  LLM → 原子化事实列表（每条50-300字符） → dedup → write（不再拆分）
```

**实现方案**：

1. **修改 extraction prompt**：在 ADDITIVE_EXTRACTION_PROMPT 中增加原子化约束：
   ```
   # 原子化要求
   - 每条事实必须是独立的原子事实，长度 50-300 字符
   - 一个复杂决策拆分为多条：决策本身、原因、影响分别记录
   - 禁止产出超过 300 字符的单条事实
   - title 字段必须是完整的语义摘要（不截断）
   ```

2. **在 extraction.py 增加 `title` 字段输出**：
   - 当前 LLM 只输出 `text`，title 在 dedup.py 中被硬截断 `fact.text[:80]`
   - 改为让 LLM 同时输出 `title`（≤80字符的语义完整摘要）和 `content`（完整描述）
   - 新的 JSON schema：
     ```json
     {
       "memory": [{
         "id": "0",
         "title": "mcore 选择 SQLite 的原因",
         "content": "项目选择 SQLite 而非 PostgreSQL 作为数据库，原因是单机部署场景，且数据量不大",
         "type": "decision",
         "importance": 0.9,
         "linked_memory_ids": []
       }]
     }
     ```

3. **禁用事后 atomize**：
   - `add_memory_record` 中当 `source == "extraction"` 时跳过 `atomize_record` 调用
   - 保留 `atomize_record` 供手动写入的长文本使用

**影响文件**：
- `memorycore/extraction.py` — 修改 prompt 和 `ExtractedFact` dataclass
- `memorycore/dedup.py` — 使用 LLM 输出的 title 而非截断
- `memorycore/storage/crud.py` — extraction 来源跳过事后 atomize

### 3.2 提取 prompt 个性化（基于召回反馈）

**现状**：
- `ADDITIVE_EXTRACTION_PROMPT` 是固定的通用 prompt
- 没有利用用户实际记忆库的分布特征来调整提取策略

**改造**：
在提取时注入一份"记忆画像摘要"，让 LLM 了解该用户的记忆特征。

**实现方案**：

1. **新增 `_build_memory_profile()` 函数**（在 extraction.py 中）：
   ```python
   def _build_memory_profile() -> str:
       """从 DB 统计记忆分布特征，生成 prompt 注入片段。"""
       # 查询维度：
       # - type 分布（哪类记忆最多/最少）
       # - 高效记忆的共同特征（injected_count > 5 的 type、avg content length）
       # - 低效记忆的特征（injected_count == 0 且 age > 7d 的 type）
       # - 最近 7 天 feedback_score > 0 的 type 分布
       # 输出格式：
       return """
       ## 用户记忆画像
       - 高频召回类型：project_memory(35%), decision(28%), feedback(15%)
       - 有效记忆平均长度：120 字符
       - 低效记忆集中在：episodic_memory（占未召回记忆的 62%）
       - 建议：减少 episodic_memory 类型提取，增加 decision 和 feedback 类型
       """
   ```

2. **在 `_build_user_prompt()` 中注入 profile**：
   - 加入 `## Memory Profile` section
   - 仅在 existing_memories 不为空时注入（说明用户有一定数量的记忆）

3. **缓存策略**：profile 每 10 分钟重算一次，避免每次 ingest 都查 DB

**影响文件**：
- `memorycore/extraction.py` — 新增 `_build_memory_profile()`，修改 `_build_user_prompt()`

### 3.3 写入后自动种子反馈

**现状**：
- `add_feedback` 需要外部调用（Claude Code hook 或用户手动）
- `_auto_feedback_for_used` 在 context pack 构建时给被注入记忆 +0.5 分
- 但新写入的记忆没有任何初始反馈，effectiveness_score 起始值 0.5 对所有记忆一视同仁

**改造**：
对新提取的记忆，根据其与现有高效记忆的相似度和类型匹配度，给予初始"种子分"。

**实现方案**：

1. **在 dedup.py 的 ingest 写入后增加种子反馈逻辑**：
   ```python
   def _seed_feedback(memory_id: str, fact: ExtractedFact, decision: DedupDecision):
       """根据提取质量信号给新记忆初始分数。"""
       score = 0.0
       
       # 信号 1：LLM 给出的 importance 越高，种子分越高
       if fact.importance >= 0.8:
           score += 0.3
       elif fact.importance >= 0.6:
           score += 0.1
       
       # 信号 2：有明确的 linked_memory_ids（说明与现有知识关联）
       if decision.linked_ids:
           score += 0.2
       
       # 信号 3：type 属于高召回类型（从 profile 缓存获取）
       high_recall_types = _get_high_recall_types()  # 缓存查询
       if fact.memory_type in high_recall_types:
           score += 0.15
       
       # 信号 4：content 长度在最优区间 (50-200 字符)
       content_len = len(fact.text)
       if 50 <= content_len <= 200:
           score += 0.1
       
       if score > 0:
           add_feedback(memory_id, score=score, note="auto:seed", source_agent="system")
   ```

2. **新增 `_get_high_recall_types()` 辅助函数**：
   ```python
   def _get_high_recall_types() -> set[str]:
       """返回 injected_count/total 比率最高的 top 3 type。"""
       # 从 DB 查询并缓存 5 分钟
   ```

**影响文件**：
- `memorycore/dedup.py` — 新增 `_seed_feedback()` 和 `_get_high_recall_types()`
- 需要 import `memorycore.storage.crud.add_feedback`

### 3.4 召回反馈反向调节提取阈值

**现状**：
- `extraction_strategy` 的所有阈值（skip/update/link）是 config.yaml 中的静态值
- context_quality_events 记录了每次召回的质量，但数据只用于展示，不影响行为

**改造**：
定期分析 context_quality_events，自动微调提取和去重阈值。

**实现方案**：

1. **新增 `memorycore/feedback_loop.py` 模块**：

   ```python
   """Closed-loop feedback: analyze recall quality → adjust extraction strategy."""
   
   def analyze_recall_quality(days: int = 7) -> dict:
       """分析最近 N 天的召回质量，输出调节建议。"""
       # 分析维度：
       # 1. 按 type 的召回成功率（被注入/候选）
       # 2. 被注入记忆的平均 vector_score
       # 3. 未被注入记忆的共同特征
       # 4. feedback_score 分布变化趋势
       return {
           "over_extracted_types": [...],      # 提取太多但召回率低的 type
           "under_extracted_types": [...],     # 召回率高但数量少的 type
           "optimal_content_length": (80, 200),# 被召回记忆的内容长度区间
           "suggested_skip_threshold": 0.90,   # 建议的新去重阈值
       }
   
   def apply_adjustments(analysis: dict) -> dict:
       """将分析结果写入 config.yaml 的 extraction_strategy。"""
       # 保守调整：每次最多调 ±0.02
       # 记录调整历史到 audit_events
   ```

2. **自动触发机制**：
   - 在 `memory_ingest` 调用时，若距上次分析 > 24h，触发一次 `analyze_recall_quality`
   - 调整结果通过 `apply_adjustments` 写入 config，下次 ingest 生效
   - 全程记录 audit_events，支持回滚

3. **安全边界**：
   - skip_threshold 范围限制 [0.85, 0.96]
   - update_threshold 范围限制 [0.75, 0.90]
   - 每次最多调 ±0.02
   - 保留 config.yaml 中的手动覆盖能力

**影响文件**：
- `memorycore/feedback_loop.py` — 新建模块
- `memorycore/dedup.py` — ingest 末尾增加触发检查
- `memorycore/storage/audit.py` — 记录调节事件

## 4. 实施计划

### 优先级排序（按投资回报率）

| 优先级 | 子模块 | 预期收益 | 工作量 | 风险 |
|--------|--------|----------|--------|------|
| P0 | 3.1 写入时原子化 | 直接改善 52% 未注入率 | 中 | 低 |
| P0 | 3.2 提取 prompt 个性化 | 提高提取质量 | 低 | 低 |
| P1 | 3.3 种子反馈 | 加速新记忆冷启动 | 低 | 低 |
| P2 | 3.4 反向调节 | 系统自适应 | 中 | 中（需监控） |

### 执行步骤

**Step 1（P0）：修改提取 prompt 和 ExtractedFact**
- 修改 `ADDITIVE_EXTRACTION_PROMPT`，增加原子化约束和 title/content 分离
- 修改 `ExtractedFact` dataclass，增加 `title` 字段
- 修改 `_parse_response` 解析新的 JSON schema
- 修改 `dedup.py` 使用 `fact.title` 而非 `fact.text[:80]`

**Step 2（P0）：跳过 extraction 来源的事后拆分**
- 在 `crud.py:add_memory_record()` 中，当 `source == "extraction"` 时设置 `atomize=False`

**Step 3（P0）：提取 prompt 个性化**
- 新增 `_build_memory_profile()` 函数
- 在 `_build_user_prompt()` 中注入 profile

**Step 4（P1）：写入后种子反馈**
- 在 `dedup.py` 中新增 `_seed_feedback()`
- 在 ingest 写入成功后调用

**Step 5（P2）：反向调节闭环**
- 新建 `feedback_loop.py`
- 在 ingest 末尾触发定期分析

## 5. 向量质量优化（附带改进）

当前 `vector_avg_score = 0.167` 极低，根因是：
- `crud.py:_sync_to_vector` 嵌入的文本是 `title + content` 拼接
- title 被截断不完整，content 可能过长导致嵌入质量下降

**改进**：在 `_sync_to_vector` 中优化嵌入文本构建：
```python
# 当前
text = f"{record.get('title', '')} {record.get('content', '')}".strip()

# 改为：限制长度，优先保留 title 的完整性
title = record.get('title', '')
content = record.get('content', '')
# 如果 content 与 title 高度重复，只用 content
if title and title in content:
    text = content[:512]
else:
    text = f"{title}. {content}"[:512]
```

## 6. 验证指标

Phase 4 完成后的验证标准：

| 指标 | 验证方法 | 达标线 |
|------|----------|--------|
| 提取原子化率 | 新提取记忆 content 长度 < 300 的比例 | > 90% |
| title 完整性 | 新提取记忆 title 不以 "..." 结尾的比例 | > 95% |
| 注入率 | injected_count > 0 / active 总数 | > 60% |
| effectiveness 高分率 | effectiveness_score > 0.6 / active 总数 | > 30% |
| 向量召回质量 | context_quality_events 的 avg vector_avg_score | > 0.3 |
| 交叉召回率 | cross_retrieval_rate | > 0.15 |

## 7. 回滚策略

- 所有改动通过 config.yaml 中的 feature flag 控制
- `extraction_strategy.atomize_in_prompt: true/false` — 控制是否使用新的原子化 prompt
- `extraction_strategy.seed_feedback_enabled: true/false` — 控制种子反馈
- `extraction_strategy.adaptive_thresholds: true/false` — 控制反向调节
- 旧的 `atomize_record` 逻辑保留，手动写入仍走旧路径
