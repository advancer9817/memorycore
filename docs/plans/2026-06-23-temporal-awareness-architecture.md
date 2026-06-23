# 全链路时间感知架构设计

> 日期：2026-06-23
> 状态：已规划，待实施
> 优先级：高
> 记忆中枢 ID：2ccc8565-05e8-4aa2-bd73-2a34dbb811b7

---

## 问题陈述

mcore 的记忆治理系统中，**规则型 curator 深度依赖时间阈值**（stale/archive/decay/revival），但 **LLM curator 在去重/矛盾检测/重要性评估/拆分四个环节中，虽然 prompt 明确要求 LLM 考虑 "recency" 和 "temporal supersession"，实际却不传任何时间戳给 LLM**，导致时间推理名存实亡。

### 现状诊断

| 组件 | 时间参与度 | 问题 |
|------|-----------|------|
| 规则型 Curator | **深度** | 所有生命周期转换基于时间阈值，工作良好 |
| Rollup 触发 | **是** | 年龄+数量双门槛，工作良好 |
| Rollup LLM 合并 | **弱** | 传了 `created_at` 但 prompt 不指导时间推理 |
| LLM 去重 | **否** | 不传时间，按 importance 选保留 |
| LLM 矛盾检测 | **名存实亡** | prompt 提到 temporal supersession 但不传时间数据 |
| LLM 重要性评估 | **名存实亡** | prompt 说 consider recency 但不传时间数据 |
| LLM 拆分 | **否** | 完全不涉及时间 |
| Context Pack 检索 | **弱** | recency 权重仅 0.05（5%），线性衰减 365 天 |
| Dedup pipeline | **否** | 纯向量相似度决策，不考虑记录年龄 |
| Governance | **否** | policy_gate 不考虑记忆年龄 |
| 前端 | **缺失** | 无日期范围筛选，`valid_from`/`valid_until` 不可编辑 |
| Config | **禁用** | `temporal.enabled: false`，配置项不完整 |

---

## 设计原则

1. **一个总开关**：所有新增时间逻辑由 `temporal.enabled` 控制，关闭时保留原有行为
2. **增量改进**：不重新设计已有组件，只在决策点注入时间信号
3. **中文优先**：所有 LLM prompt 的时间指令使用中文（遵循 `output_language: zh` 约束）
4. **复用已有基础设施**：`parse_ts()`、`local_now()`、`now()` 等时间工具已就绪，直接使用

---

## 架构设计

### 共享时间标签格式

所有 LLM 交互使用统一的紧凑时间标签：

```
[时间: 创建=2026-01-15, 更新=2026-06-20, 距今=154天, 最后访问=2026-06-18]
```

若有有效期：
```
[时间: 创建=2026-01-15, 更新=2026-06-20, 有效期=2026-01-15~2026-12-31, 距今=154天]
```

特点：
- 紧凑：单行，最小 token 开销
- 结构化：key=value 对，LLM 易解析
- 相对+绝对：`距今=N天` 免去 LLM 计算年龄
- 可选：`temporal.enabled=false` 时返回空字符串

### 实现函数

```python
# memorycore/storage/curator_llm.py
def _temporal_tag(record: dict[str, Any]) -> str:
    """生成紧凑时间标签供 LLM 消费。"""
    cfg = load_config().get("temporal", {})
    if not cfg.get("enabled", False):
        return ""
    # ... 格式化 created_at, updated_at, valid_from, valid_until, last_accessed_at
    # ... 计算 age_days
    return f"[时间: {', '.join(parts)}]"
```

---

## 分阶段实施计划

### Phase 1: 激活时间配置（前置条件）

**文件**: `memorycore/models.py`, `config.yaml`

扩展 `DEFAULT_CONFIG["temporal"]`：

```yaml
temporal:
  enabled: true                      # 总开关
  recency_half_life_days: 90         # 指数衰减半衰期
  llm_temporal_prompts: true         # LLM curator 注入时间标签
  dedup_temporal_guard: true         # dedup 防止覆盖更新记录
  governance_age_risk_days: 7        # 新记忆破坏性操作审核窗口
  # 已有 keys 保留:
  auto_supersede_user_corrections: true
  auto_supersede_enabled: true
  auto_supersede_threshold: 0.96
  review_similarity_threshold: 0.82
  contradiction_detection: heuristic
```

### Phase 2: LLM Curator 时间注入（核心，最高优先级）

**文件**: `memorycore/storage/curator_llm.py`

#### 2.1 扩展数据查询

`_fetch_active_memories()` 和 `_fetch_memories_by_ids()` 的 SELECT 追加：
```sql
created_at, valid_from, valid_until, last_accessed_at, last_injected_at
```

#### 2.2 四个 LLM 能力注入时间标签

每个函数的 `items_text` 构建处追加 `_temporal_tag(record)`。

#### 2.3 时间推理指令（追加到 system prompt 尾部）

**去重**:
```
# 时间推理规则
每条记忆附有 [时间: ...] 标签，包含创建日期、更新日期和距今天数。
当两条记忆重复时，优先保留(keep)更新日期更近的那条。
'keep_id' 应设为更新时间更近的记忆 ID。
```

**矛盾检测**:
```
# 时间推理规则
每条记忆附有 [时间: ...] 标签。
如果两条记忆描述同一主题但结论不同，更新日期更近的记忆更可能正确。
'newer_id' 应设为更新时间更近的记忆 ID。
时间相差超过30天的相同主题记忆很可能是时间演变（temporal supersession），应标记为矛盾。
```

**重要性评估**:
```
# 时间推理规则
每条记忆附有 [时间: ...] 标签，包含距今天数。
- 距今超过180天且从未被访问的记忆，重要性应大幅降低
- 距今超过90天的短暂性记忆(episodic)应考虑归档
- 有效期已过(valid_until < 今天)的记忆应标记为归档
- 最近30天内创建或更新的记忆不应轻易降级
```

#### 2.4 去重 fallback 改为时间优先

当 LLM 未指定 `keep_id` 时：
- temporal 启用：按 `updated_at` 选更新的
- temporal 未启用：保留原有 importance 逻辑

### Phase 3: Rollup 时间推理指令

**文件**: `memorycore/storage/rollup.py` — `_call_rollup_llm()`

temporal 启用时追加 system prompt：
```
# 时间推理规则
每条记录包含 created_at 字段。请注意以下规则：
- 当多条记录描述同一事实的不同版本时，以最新(created_at最晚)的为准
- 在合并后的记忆中，注明事实的变化历程（例如：'用户从Python切换到Rust'而非仅记录'用户使用Rust'）
- 如果一个偏好/决定发生了变化，保留'从X改为Y'的形式以体现时间演变
- 删除明显过时且已被后续记录取代的信息
```

### Phase 4: Context Pack 检索时间权重提升

**文件**: `memorycore/storage/search.py`

#### 4.1 `_context_recency_weight()`

| 模式 | 默认值 | 上限 |
|------|--------|------|
| temporal 启用 | 0.15 | 0.30 |
| 原有模式 | 0.05 | 0.10 |

#### 4.2 `_recency_score()` 衰减曲线

| 模式 | 算法 | 特点 |
|------|------|------|
| temporal 启用 | 指数衰减 `exp(-0.693 * age_days / half_life)` | 半衰期 90 天，近期记忆优势显著 |
| 原有模式 | 线性衰减 `1 - age_days / 365` | 平缓，一年归零 |

### Phase 5: Dedup 时间守卫

**文件**: `memorycore/dedup.py` — `ingest()` update 分支

temporal 启用时，在执行 update（覆盖已有记忆）前检查已有记录 `updated_at`：若已有记录在 1 小时内更新过，降级为 "add with link" 而非覆盖。防止弱事实覆盖刚写入的强事实。

### Phase 6: 治理时间信号

**文件**: `memorycore/storage/governance.py` — `policy_gate()`

temporal 启用时，在 `has_positive_feedback` 检查之后：若目标记忆创建/更新不足 `governance_age_risk_days`（默认 7 天）且操作为破坏性（archive/delete/merge），追加 `recently_created_memory` reason，强制进入人工审核。

### Phase 7: 前端时间增强

#### 7.1 日期范围筛选
- 后端 `frontend.py` 追加 `date_from`/`date_to` 查询参数
- 前端 `FilterComponent` 增加日期范围选择器

#### 7.2 `valid_from`/`valid_until` 编辑
- 后端 `crud.py` `update_memory_content()` 追加这两个可选参数
- 前端记忆详情面板追加日期输入框

#### 7.3 i18n 补充
- 中英文字典补充时间相关键

---

## 关键文件清单

| 文件 | 改动类型 |
|------|----------|
| `memorycore/models.py` | 扩展 DEFAULT_CONFIG temporal 段 |
| `config.yaml` | 启用 temporal.enabled |
| `memorycore/storage/curator_llm.py` | 核心: 新增 `_temporal_tag`，修改 4 个 LLM 函数 + 2 个查询函数 |
| `memorycore/storage/rollup.py` | 追加时间推理 prompt |
| `memorycore/storage/search.py` | 修改 `_recency_score` 和 `_context_recency_weight` |
| `memorycore/dedup.py` | ingest update 分支追加时间守卫 |
| `memorycore/storage/governance.py` | policy_gate 追加年龄检查 |
| `memorycore/frontend.py` | 追加 date_from/date_to + valid_from/valid_until PATCH |
| `memorycore/storage/crud.py` | update_memory_content 追加 valid_from/valid_until |
| `ui/app/memories/` | 日期范围筛选组件 |
| `ui/app/memory/[id]/` | valid_from/valid_until 编辑字段 |

## 复用已有函数

| 函数 | 位置 | 用途 |
|------|------|------|
| `parse_ts()` | `models.py:470` | 解析 ISO 时间戳为 datetime |
| `local_now()` | `models.py:181` | 当前 UTC+8 时间 |
| `now()` | `models.py:186` | ISO 字符串格式的当前时间 |
| `_recency_score()` | `search.py:542` | 改进而非替换 |
| `_language_instruction()` | `extraction.py` | LLM prompt 语言后缀 |
| `load_config()` | `models.py` | 读取 temporal 配置 |

---

## 实施优先级

| 优先级 | 阶段 | 预估工时 | 影响 |
|--------|------|----------|------|
| 1 | Phase 1: 配置激活 | 5min | 解锁所有后续阶段 |
| 2 | Phase 2: LLM Curator 时间注入 | 2-3h | **最高影响** — 4 个 LLM 能力获得时间推理 |
| 3 | Phase 4: Context Pack 权重提升 | 1h | 检索质量立竿见影 |
| 4 | Phase 3: Rollup 时间指令 | 30min | 小改动高 ROI |
| 5 | Phase 5: Dedup 时间守卫 | 1h | 防止覆盖更新记录 |
| 6 | Phase 6: 治理时间信号 | 1h | 安全性提升 |
| 7 | Phase 7: 前端增强 | 3-4h | 用户体验完善 |

---

## 验证方案

| 阶段 | 验证方法 |
|------|----------|
| Phase 1 | `load_config()["temporal"]["enabled"]` 返回 `True` |
| Phase 2 | `run_llm_curator(apply=False)` dry run，检查 `llm_prompt` 包含 `[时间:]` 标签；对比 `keep_id` 是否指向更新记忆 |
| Phase 3 | `memory_rollup_report(dry_run=True)` 检查合并记忆是否包含变化历程描述 |
| Phase 4 | `memory_context(task="...")` 对比前后排序，近期更新记忆应明显靠前 |
| Phase 5 | 创建两条相似记忆间隔 5 分钟，ingest 验证不覆盖更新记录 |
| Phase 6 | 提交 1 天前记忆的归档决策，policy_gate 返回 `needs_review` + `recently_created_memory` |
| Phase 7 | 手动 UI 测试 |
| 全链路 | `python -m pytest tests/` 确保无回归 |
