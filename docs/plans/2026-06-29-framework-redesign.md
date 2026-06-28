# MemoryCore 框架重设计 — 完整改动方案

> 本方案基于 2026-06-28/29 会话中对 10+ 核心文件的逐行审计、数据库实际数据分析、5 组端到端召回测试的结论。
> 当前会话已完成四轮代码优化（13 files, +317/-101 lines），本方案是在此基础上的框架级重设计。

---

## 一、当前框架问题总结

| 维度 | 问题 | 数据证据 |
|------|------|----------|
| 架构过重 | 46 个 MCP 工具、24 张表，为"多 agent 平台"设计 | agent_messages 0 条、handoff 0 次 |
| 治理投入产出比低 | 三层流水线（Rule→LLM→Governance 审批） | 68% split 产出是死重、180 条 needs_review 积压 |
| 提取-召回断裂 | 提取不知道召回需要什么格式 | extraction 产出全是 episodic_memory（已修复 prompt） |
| 60% 记忆死重 | active 记忆中 473/791 从未被注入 | governance_split 317 条、atomizer 103 条从未使用 |
| 前端错配 | 8 页中多数是运维面板 | 用户实际只用 Memories 和 Graph |

---

## 二、新框架设计

### 核心理念

**从"功能堆叠的平台"转向"精简闭环的引擎"**

```
                    ┌──────────────────┐
                    │   对话 Agent      │
                    │ (Claude/Codex)   │
                    └──┬───────────┬───┘
                       │           │
              读（注入） │           │ 写（提取）
                       ▼           ▼
                 ┌─────────┐ ┌──────────┐
                 │ Context │ │ Ingest   │
                 │ Pack    │ │ Pipeline │
                 └────┬────┘ └────┬─────┘
                      │           │
                      │  feedback │
                      │◄──────────┤
                      ▼           ▼
                 ┌────────────────────┐
                 │    Memory Store    │
                 │ SQLite+FTS5+Qdrant │
                 └────────┬───────────┘
                          │
                     治（后台）
                          ▼
                 ┌────────────────────┐
                 │  Auto Curator      │
                 │ (Rule + 轻量LLM)   │
                 └────────────────────┘
```

---

## 三、分阶段改动清单

### Phase 1: MCP 工具精简（46→~22）

**保留（核心，直接服务读写治）**：
1. `memory_add` — 写入记忆
2. `memory_search` — 搜索记忆
3. `memory_context` — 对话前召回（核心中的核心）
4. `memory_get` — 获取单条
5. `memory_update` — 更新记忆
6. `memory_list_recent` — 最近记忆
7. `memory_feedback` — 反馈（闭环关键）
8. `memory_timeline` — 时间线
9. `memory_stats` — 统计
10. `memory_ingest` — 对话后提取（核心中的核心）
11. `memory_context_stats` — 召回质量可观测
12. `memory_export` / `memory_import` — 多设备同步
13. `memory_backup` — 备份
14. `memory_vector_search` / `memory_vector_status` — 向量操作
15. `memory_link_add` / `memory_link_query` — 图谱链接
16. `memory_lineage` — 版本链
17. `memory_supersede` — 版本替代
18. `memory_warnings` — 冲突告警
19. `memory_entity_search` — 实体搜索
20. `memory_audit_log` — 审计日志
21. `memory_rebuild_vectors` — 向量重建
22. `memory_vector_audit` — 向量审计

**移除注册（代码保留，只从 server.py 的 @mcp.tool 移除）**：
- `memory_atomize_report` — atomization 改为写入时自动触发，不需要独立工具
- `memory_curator_report` — rule curator 由 timer 直接调用，不需要 MCP 入口
- `memory_rollup_report` — rollup 由 auto_curator 线程调用，不需要 MCP 入口
- `governance_decisions` / `governance_apply` / `governance_apply_batch` / `governance_reject` / `governance_rollback` / `governance_recalibrate_queue` / `governance_metrics` / `governance_ledger` — 治理审批全部自动化，不暴露 MCP
- `agent_send` / `agent_inbox` / `agent_messages_cleanup` — 邮箱协作，零使用
- `agent_handoff_create` / `agent_handoff_update` — 任务交接，零使用
- `agent_capability_register` / `agent_capability_search` — 能力路由，零使用
- `agent_presence_update` / `agent_presence_list` — presence 保留在 session-start hook 中但不暴露 MCP

**文件**：`memorycore/server.py` — 移除 ~24 个 @mcp.tool 装饰器（函数代码保留）

### Phase 2: 治理层简化

#### 2.1 Rule curator 直接执行，不经过 governance

**当前**：rule curator → 生成 action_plan → governance_decision → 等待 apply
**新方案**：rule curator → 直接 update_status_batch

**文件**：`memorycore/storage/curator.py`
- `curator_report(dry_run=False)` 的执行路径改为直接调用 `update_status_batch`
- 保留 audit_events 记录（可追溯）
- 不再创建 governance_decision

#### 2.2 LLM curator 精简：只做去重和矛盾

**当前**：LLM curator 做 5 件事（dedup、contradiction、importance、split、link_discovery）
**新方案**：只做 dedup 和 contradiction。原因：
- split 产出 68% 死重（已验证），且写入时 atomization 已覆盖
- importance 重评估靠 usage_rate + feedback 自动调整（已实现）
- link_discovery 保留但降为可选

**文件**：`memorycore/storage/curator_llm.py`
- `llm_curator_report()` 删除 split 和 importance 阶段
- `run_llm_curator_incremental()` 同步精简

#### 2.3 去掉 governance 审批队列

**当前**：180 条 needs_review 积压，用户不想手动审批
**新方案**：
- LLM curator 的 dedup/contradiction 结果高于 0.7 置信度直接执行
- 低于 0.7 的写入 audit_log 但不阻塞（"记录但不阻拦"）
- 删除 `MANUAL_ONLY_ACTIONS` 概念
- governance 页面改为"自动处理日志"（只读）

**文件**：`memorycore/storage/governance.py`、`config.yaml`

### Phase 3: 前端重设计（8→4 页）

#### 3.1 保留的页面

| 页面 | 内容 | 改动 |
|------|------|------|
| **Dashboard** | 记忆健康概览 + Context Lab 召回调试器 | 移除 MemoryOperationsPanel 和 CuratorTuningPanel，保留 MemoryIntelligenceCenter；新增 Context Lab 区域 |
| **Memories** | 记忆列表/搜索/编辑 | 保持，优化搜索和批量操作 |
| **Graph** | 关系图谱 | 保持 |
| **Settings** | 配置 | 保持 |

#### 3.2 移除/内联的页面

| 页面 | 处理方式 |
|------|----------|
| **Apps** | 移除。agent 活动信息内联到 Dashboard 的一行统计中 |
| **Governance** | 降级为 Dashboard 的"自动处理日志"折叠区域（只读时间线） |

#### 3.3 Context Lab（新增，Dashboard 内）

**目的**：让用户能实时测试和调试记忆召回质量

功能：
- 输入框：输入任意 prompt，实时显示 memory_context 返回的记忆列表
- 每条记忆显示：rank_score、retrieval_source（FTS/vector/entity）、type、importance
- 底部显示 trace：vector_avg_score、cross_retrieval_rate、hit_rate
- "为什么没召回 X"调试模式：输入记忆 ID，显示它在当前查询下的 rank_score 和被过滤的原因

**文件**：`ui/app/page.tsx`（Dashboard）或新建 `ui/components/dashboard/ContextLab.tsx`

### Phase 4: 提取-召回闭环增强

#### 4.1 extraction 写入时自动 atomization

**当前**：extraction 写入完整事实 → 后续 LLM curator split 拆分（产出大量碎片）
**新方案**：extraction prompt 直接产出适当粒度的事实（50-300 字符），不需要后续 split

在 `dedup.py` 的 `ingest()` 中，如果提取的事实 > 400 字符，在写入前按句号/分号自动拆分为多条。不用 LLM，纯规则拆分。

**文件**：`memorycore/dedup.py`

#### 4.2 feedback 驱动提取策略

在 `build_context_pack` 返回的 trace 中统计：
- 被高频召回的记忆的平均 content 长度、type 分布
- 这些信息写入 `context_quality_events`

extraction prompt 可以从中读取"理想记忆"的特征，动态调整提取策略。

**文件**：`memorycore/storage/search.py`（trace 增强）、`memorycore/extraction.py`（读取历史）

#### 4.3 写入后立即 feedback 种子

新提取的记忆在下一次 `memory_context` 被召回时才会获得 feedback。但如果记忆库很大，新记忆可能很久不被召回。

新方案：`ingest()` 完成后，对每条新记忆主动做一次 `memory_context(title)` 的 dry-run 检查——如果新记忆出现在 top-10，说明它有召回价值，给 +0.3 种子分。

**文件**：`memorycore/dedup.py`（ingest 末尾）

---

## 四、实施顺序

```
Phase 1（MCP 精简）     → 半天，低风险，不影响功能
Phase 2（治理简化）     → 1 天，需要更新测试
Phase 3（前端重设计）   → 2-3 天，主要是 UI 工作
Phase 4（闭环增强）     → 1 天，提取和反馈机制
```

建议顺序：Phase 1 → Phase 2 → Phase 4 → Phase 3

Phase 1 和 2 先做，立即降低系统复杂度。Phase 4 增强核心闭环。Phase 3 前端最后做（依赖后端稳定）。

---

## 五、验证矩阵

| 阶段 | 验证方法 | 通过标准 |
|------|----------|----------|
| Phase 1 | `mcp.tool` 注册数量 | ≤ 22 个 |
| Phase 1 | 现有 hook（context/ingest/session-start）正常工作 | 无功能中断 |
| Phase 2 | `governance_decisions` 新增量 | 不再增长（rule curator 直接执行） |
| Phase 2 | `needs_review` 积压 | 降为 0 |
| Phase 2 | LLM curator 执行时间 | < 10 分钟（去掉 split/importance） |
| Phase 3 | UI 页面数 | 4 个 |
| Phase 3 | Context Lab 功能 | 输入 prompt 实时返回召回结果 |
| Phase 4 | extraction 产出 content 长度 | 50-300 字符占 90%+ |
| Phase 4 | active 记忆使用率 | injected_count > 0 占比 > 60% |
| 全量 | pytest | 无新增失败 |
| 全量 | 5 组查询 Top-3 命中率 | > 80% |

---

## 六、不做的事（显式排除）

1. 不从零重写 — 在现有代码基础上瘦身和重组
2. 不更换存储引擎 — SQLite + Qdrant 组合已验证可靠
3. 不更换 LLM provider — extraction 和 curator 的 LLM 调用链保持现有
4. 不删除 agent 协作代码 — 只移除 MCP 注册，函数代码保留（万一未来需要）
5. 不删除 governance 代码 — 只改变调用路径（直接执行 vs 审批队列）
