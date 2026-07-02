# MemoryCore 深度审计报告

> 审查日期：2026-07-02
> 审查范围：后端架构、前端 UI、所有功能模块、实际使用数据
> 审查方法：代码全量扫描 + SQLite 生产数据统计分析
> 审查目标：识别每个功能点的实际价值、架构合理性、噱头功能、优化空间

---

## 一、项目概况

### 1.1 技术栈

| 层 | 技术 | 规模 |
|---|---|---|
| 后端 | Python 3.11+ / FastMCP / SQLite / Qdrant | ~10,300 行核心代码 |
| 前端 | Next.js 15 / React 19 / Redux Toolkit / Three.js | ~17,400 行 |
| 向量库 | Qdrant + nomic-embed-text (768 维) | cosine distance |
| LLM | OpenAI-compatible API (当前配置 gemini-pro-agent) | 提取 + 策展 + 合并 |
| 部署 | systemd (mcore.service + mcore-ui.service) | 8318 / 18318 端口 |

### 1.2 数据规模 (生产数据)

| 指标 | 数值 |
|------|------|
| 总记忆数 | 6,513 |
| Active 记忆 | 1,379 |
| Archived | 4,759 (73%) |
| Stale | 263 |
| Contradicted | 93 |
| Superseded | 19 |
| 总链接数 | 5,464 |
| 治理决策 | 7,073 |
| 审计事件 | 16,334 |
| 反馈事件 | 801 |
| Context Pack 调用 | 716 次 |
| 实体索引 | 1,590 |

### 1.3 记忆来源分布

| 来源 | 数量 | 占比 | 说明 |
|------|------|------|------|
| extraction | 2,599 | 39.9% | LLM 从对话中提取 |
| governance_split | 2,143 | 32.9% | 治理系统拆分产出 |
| atomizer | 851 | 13.1% | 规则原子化拆分 |
| rollup | 601 | 9.2% | episodic 合并为持久记忆 |
| llm_curator | 196 | 3.0% | LLM 策展器产出 |
| manual | 83 | 1.3% | 手动创建 |
| 其他 | 40 | 0.6% | v1-compat, user, agent 等 |

---

## 二、功能模块逐项评估

### 2.1 记忆提取与去重管道

**模块**: `extraction.py` (463 行) + `dedup.py` (372 行)

**功能**: 对话 → LLM 提取结构化事实 → 向量相似度去重 → 写入 SQLite

**实际效果**:
- 2,599 条记忆来自 extraction，占总量 40%，是最大的单一记忆来源
- 去重阈值分层设计合理：SKIP ≥0.92 (近似重复)、UPDATE ≥0.78 (同主题新信息)、LINK ≥0.55 (相关但不同)
- 按记忆类型有不同阈值偏置：decision/user_profile 保守 (避免误合并)，episodic/feedback 激进 (鼓励合并)

**裁定**: **核心价值** — 这是系统的心脏

**发现的问题**:
- `memory_ingest` 工具 (完整管道: 提取→去重→写入) 的来源标记为 `ingest` 的记忆数为 **0**。所有记忆走的是 `extraction` 来源路径。需要排查 ingest 管道是否有 bug 或从未被调用。
- LLM 提取的 prompt 为中文，但 `output_language` 配置为 `zh`，对英文对话的提取质量需要关注。

---

### 2.2 Context Pack (记忆注入)

**模块**: `storage/search.py` (1,178 行)

**功能**: 根据当前任务，在 token 预算内组装最相关的记忆，按类型分组注入 Claude Code 的 prompt。通过 `UserPromptSubmit` hook 在每次回答前自动调用。

**实际效果**:
- 平均 hit_rate: **0.813** (81% 候选记忆被使用)
- 平均 used_count: **7.1** 条/次
- 总调用次数: **716** 次
- filter_rate: **0.001** (注入安全过滤几乎不触发)

**裁定**: **核心价值** — 整个系统存在的理由

**发现的问题**:
- 1,379 条 active 记忆中，**960 条 (70%) 从未被注入过** (`injected_count=0`)。说明大量记忆存储了但从未被召回使用。
- 可能原因：FTS5 + 向量搜索的召回率不足，或这些记忆的内容与日常任务不匹配。
- 异步写入队列 (`search.py:78`) 的错误被 `except Exception: pass` 静默吞掉，注入计数更新失败不会被察觉。

---

### 2.3 治理系统 (Governance)

**模块**: `storage/governance.py` (1,253 行) + `storage/mutation_executor.py` (465 行) + `storage/mutations.py` (140 行)

**功能**: 多层决策管道 — Policy Gate 分类 → Mutation Executor 事务执行 → 快照 + 回滚 → 审计日志

**架构细节**:
- Policy Gate: 根据动作类型、置信度阈值、注入检测、记忆类型分类为 `auto_approved` / `needs_review` / `rejected`
- 删除永远不自动批准，merge/split 始终需要人工审核
- `user_profile` / `decision` / `project_memory` 有额外保护
- 回滚: 基于 pre-mutation snapshot 的真实数据恢复，不只是状态翻转
- 幂等性: 通过 idempotency key 防止重复执行

**实际数据**:

| 状态 | 数量 | 占比 |
|------|------|------|
| applied | 4,341 | 61.4% |
| auto_approved | 534 | 7.6% |
| needs_review | 2,188 | 30.9% |
| rejected | 9 | 0.1% |
| rolled_back | 1 | 0.01% |

**裁定**: **过度设计** — 有产出但人工审核环节完全失效

**关键问题**:
1. **2,188 条 needs_review 积压** (31%)：系统设计了人工审核环节，但实际上没有人在审。前端有 batch apply 按钮但显然没用起来。
2. **回滚只用过 1 次**：精心设计的快照 + 逆向操作机制几乎零实际价值。
3. **auto_approve_confidence 阈值 0.8 偏高**：导致大量决策落入 needs_review 而非 auto_approved。
4. governance_split 产出了 2,143 条记忆 (占总量 33%)，说明系统确实在做事，但审核积压暴露了人工环节不可行。

---

### 2.4 规则策展器 (Rule Curator)

**模块**: `storage/curator.py` (408 行)

**功能**: 15+ 类候选规则，后台每 6 小时自动运行：
- 低反馈 → 标记 stale
- 自动衰减 (confidence 每次 -0.05，下限 0.15)
- Episodic 生命周期管理 (stale/archive/dead 分段)
- Candidate 晋升 (importance ≥ 0.75 且 feedback ≥ 0)
- 复活 (stale + 近期被注入 + 高 effectiveness → 恢复 active)
- 标题去重
- 超替检测
- decay_policy 语义: `review` = 慢衰减, `stable` = 不衰减, `freeze` = 跳过

**实际效果**: 4,759 条 archived (73%)，263 条 stale，93 条 contradicted — 策展器确实在持续清理。

**裁定**: **扎实有效** — 系统里最务实的模块之一

**无重大问题**。建议保持现状。

---

### 2.5 LLM 策展器

**模块**: `storage/curator_llm.py` (1,654 行) — 单一最大模块

**功能**: LLM 驱动的五大分析能力：
1. 语义重复判断 (`_llm_judge_duplicates`)
2. 矛盾检测 (`_llm_judge_contradictions`)
3. 重要性重评估 (`_llm_reassess_importance`)
4. 可拆分检测 (`_llm_detect_splittable`)
5. 链接发现 (`_llm_discover_links`)

**实际效果**:
- 唯一一个 LLM curator job 状态: **failed** (2026-06-29)
- 196 条记忆标记为 `llm_curator` 来源，但来自哪个阶段不清楚
- 增量处理设计 (reviewed ID 追踪) 避免重复分析

**裁定**: **高投入低产出** — 代码量最大但生产未跑通

**关键问题**:
1. 1,654 行代码是项目中最大的单一模块，但唯一的 job 执行失败
2. 需要修复 LLM API 调用链路 (可能是超时、配置、或数据规模问题)
3. 或者降级为手动触发 + 小批量模式

---

### 2.6 Rollup (滚动合并)

**模块**: `storage/rollup.py` (299 行)

**功能**: LLM 驱动，把积累的 episodic 记忆合并为持久性记忆。触发条件: count ≥ 30，或 count ≥ 5 且最老 > 24h，或 force=True。

**实际效果**: 601 条记忆来自 rollup，占总量 9%。

**裁定**: **有实际产出** — 真正在减少噪声

**待验证**: rollup 产出的记忆是否比原始 episodic 记忆的 feedback_score 和 injected_count 更高。

---

### 2.7 原子化 (Atomization)

**模块**: `storage/atomization.py` (301 行) + governance_split 路径

**功能**: 
- 规则原子化: 基于字符数 (≥600)、行数 (≥6)、句子数 (≥3) 拆分
- LLM 拆分: governance_split 通过 LLM 检测可拆分记忆 (阈值 ≥400 字符)
- 两条路径"有意分开"

**实际效果**:
- atomizer 产出 851 条 (13%)
- governance_split 产出 2,143 条 (33%)
- 合计 2,994 条，占总记忆的 **46%**
- 393 个父记忆被原子化

**裁定**: **产出大，价值存疑**

**关键问题**:
- 近半数记忆是拆分产生的碎片
- 如果 70% 的 active 记忆从未被注入，而其中大量是原子化碎片，说明拆分在**制造噪声而非提高召回**
- 需要统计 atomizer/governance_split 来源记忆的 injected_count 分布来验证

---

### 2.8 Agent 通信系统

**模块**: `storage/agents.py` (165 行) + `storage/handoff.py` (235 行)

**功能**: 代理间消息、在线状态、能力注册、任务移交、自动路由

**实际数据**:
- Agent messages: **0** (从未发过一条消息)
- Agent presence: 3 条 (gemini, codex, claude — 静态注册，无实际心跳)
- 自动路由: 简单关键词匹配 (统计任务文本中出现了几个能力关键词)

**裁定**: **噱头** — 系统中最明确的无用功能

**分析**:
- 400 行代码，0 实际使用
- Claude Code 的多会话协作走自己的机制，不需要通过 MemoryCore 中转
- 作为 MCP 工具暴露增加了 Claude Code 的工具选择噪声 (5 个工具: agent_send, agent_inbox, agent_presence_update, agent_presence_list, agent_messages_cleanup)
- 建议直接删除或降级为不注册 MCP 工具的内部预留接口

---

### 2.9 3D 知识图谱

**模块**: `ui/app/graph/` (Graph3D, GraphFilterPanel, GraphNodeList, GraphNodeDetail, GraphTopbar)

**功能**: Three.js 力导向图，展示记忆节点和链接关系，支持类型/边/状态过滤，节点详情编辑。

**实际数据** — 链接类型分布:

| 类型 | 数量 | 占比 |
|------|------|------|
| supports | 2,710 | 49.6% |
| part_of | 2,708 | 49.6% |
| supersedes | 33 | 0.6% |
| related_to | 11 | 0.2% |
| contradicts | 1 | 0.02% |
| causes | 1 | 0.02% |

**裁定**: **低 ROI** — 视觉效果好但信息密度低

**分析**:
- 99.2% 的边是自动生成的 `supports` 和 `part_of` 关系，信息密度极低
- 有意义的语义链接 (related_to, contradicts, supersedes) 仅占 0.8%
- 6,500 节点 + 5,400 边的 3D 图谱对浏览器性能有压力
- 不算完全噱头 (确实能看到记忆结构)，但投入产出比不高

---

### 2.10 反馈系统

**模块**: `storage/crud.py` 内嵌

**功能**: 记录 feedback_events (score -10~10)，计算 running average feedback_score，驱动 effectiveness_score 升降，影响策展器的晋升/衰减决策。

**实际数据**:
- 801 条反馈事件
- 260 条记忆有非零 feedback_score
- Active 记忆平均 effectiveness_score: 0.514

**裁定**: **简单有效** — 代码量少但驱动整个生命周期

---

### 2.11 前端 UI

**模块**: Next.js 15 App Router, 8 个路由, ~17,400 行

**功能**:
1. **Dashboard**: 运营面板 + 策展器触发 + 智能中心
2. **Memories**: 列表 + 搜索 + 过滤 + 内联编辑
3. **Memory Detail**: 详情 + 元数据 + 访问日志 + 相关记忆 + 谱系
4. **Apps**: 应用注册表 + 应用详情
5. **Graph**: 3D 力导向图
6. **Governance**: 治理决策表 + 批量操作 + 指标
7. **Settings**: LLM/嵌入/策略配置

**裁定**: **功能完整，部分过度设计**

**问题**:
- Redux 管理了过多服务端状态 (6 个 slice)，手写 30s client-side cache 是重新发明轮子。React Query / SWR 可以替代并删掉大量样板代码。
- i18n (中英双语) 对个人项目是过度设计
- Governance 页面有 2,188 条积压，说明页面设计了但没人用

---

### 2.12 向量搜索 (Qdrant 集成)

**模块**: `vector_store.py` (606 行)

**功能**: 多 provider 嵌入链 (auto → ollama → openai → hashing fallback)，Qdrant 客户端封装，优雅降级。

**裁定**: **扎实可靠** — 生产级别的向量存储层

**亮点**:
- 懒初始化 + 30s 冷却期避免故障风暴
- hashing fallback 保证无模型时也能运行
- `vector_sync_queue` 失败重试队列 (当前 0 条积压)

---

### 2.13 实体索引

**模块**: `storage/entities.py` (210 行)

**功能**: 从记忆内容提取实体和别名，建立索引用于精确召回。

**实际数据**: 1,590 个实体

**裁定**: **辅助功能，有价值** — 为 context pack 提供实体级精确匹配

---

### 2.14 隐私与安全

**模块**: `privacy.py` (161 行) + `injection_guard.py` (65 行)

**功能**:
- `privacy.py`: 写入时的秘密脱敏 (API key, token, password 等模式匹配)
- `injection_guard.py`: 检测记忆内容中的 prompt 注入攻击

**裁定**: **必要的安全底线** — 代码量小但防御关键风险

---

## 三、架构合理性评估

### 3.1 好的设计决策

| 决策 | 评价 |
|------|------|
| MCP 原生接入 | 与 Claude Code 无缝集成，是最正确的架构选择 |
| SQLite + Qdrant 双存储 | 结构化数据 + 语义搜索，职责清晰 |
| FTS5 全文搜索 | 利用 SQLite 原生能力，零额外依赖 |
| 嵌入层多 provider 降级 | auto → ollama → openai → hashing，保证可用性 |
| Context Pack 设计 | token 预算 + 类型分组 + 注入计数追踪，系统精华 |
| 自动策展后台线程 | 每 6h 运行，无需人工干预 |
| 审计日志全覆盖 | 16,334 条事件，所有变更可追溯 |

### 3.2 架构问题

| 问题 | 严重度 | 说明 |
|------|--------|------|
| `frontend.py` 1,458 行 | HIGH | REST API + HTML 嵌入混在一个文件，违反 SRP |
| `server.py` 1,147 行 | HIGH | CLI + MCP 工具 + 路由注册混杂 |
| `curator_llm.py` 1,654 行 | HIGH | 5 种分析能力挤在一个文件，应按功能拆分 |
| 写入队列 silent failure | MEDIUM | `search.py:78` 的 `except Exception: pass` 吞掉所有错误 |
| 前端 Redux 管理服务端状态 | MEDIUM | 应用 React Query/SWR 替代手写缓存 |
| 两条原子化路径 | LOW | atomizer + governance_split "有意分开"但增加了认知负担 |

---

## 四、"噱头 vs 实质" 裁定汇总

| 功能 | 裁定 | 核心理由 |
|------|------|----------|
| 记忆提取 + 去重 | **实质** | 核心价值，产出 40% 的记忆 |
| Context Pack 注入 | **实质** | 系统存在的理由，81% hit rate |
| 规则策展器 | **实质** | 务实有效，持续管理生命周期 |
| Rollup 合并 | **实质** | 有真实产出 (601 条)，减少噪声 |
| 向量搜索 | **实质** | Qdrant 集成稳健，多 provider 降级合理 |
| 反馈系统 | **实质** | 简单有效，驱动整个生命周期 |
| 实体索引 | **实质** | 辅助召回，有价值 |
| 隐私与安全 | **实质** | 必要的安全底线 |
| 治理系统 | **过度设计** | 有产出但 2,188 积压暴露人工审核不可行，回滚只用 1 次 |
| 原子化/拆分 | **待验证** | 产出 46% 但 70% 从未被注入，可能制造噪声 |
| LLM 策展器 | **高投入低产出** | 1,654 行代码，唯一 job failed |
| Agent 通信 | **噱头** | 0 条消息，0 实际使用，可以删除 |
| 3D 图谱 | **低 ROI** | 99% 的边是自动关系，信息密度低 |
| 前端 i18n | **过度设计** | 个人项目不需要双语 |

---

## 五、优化方向

### P0 — 必须立即处理

#### 5.1 修复 LLM Curator

- **现状**: 1,654 行代码，唯一 job 执行 failed，是项目中最大的投入浪费
- **方向**: 排查 2026-06-29 job 失败原因 (LLM API 超时？数据规模？配置错误？)，修复后以小批量模式验证
- **如果修不通**: 降级为手动触发 + 单项分析模式，不做全量 job

#### 5.2 清理治理积压

- **现状**: 2,188 条 needs_review 决策积压 (31%)
- **方向 A**: 降低 `auto_approve_confidence` 阈值 (0.8 → 0.65~0.7)，让更多低风险决策自动通过
- **方向 B**: 对积压决策做一次性 batch recalibrate，把低风险项自动批准
- **方向 C**: 重新审视哪些 action type 真的需要 needs_review — merge/split 是否可以在高置信度时自动通过

#### 5.3 验证原子化 ROI

- **现状**: 46% 的记忆来自拆分，但 70% active 记忆从未被注入
- **操作**: 统计 atomizer + governance_split 来源记忆的 injected_count 分布
- **如果大部分从未注入**: 提高拆分门槛 (字符数从 600 → 1000，句子数从 3 → 5)，或暂停 governance_split
- **如果注入率正常**: 说明是其他来源的记忆质量问题，调整 context pack 的召回策略

### P1 — 短期内处理

#### 5.4 删除 Agent 通信模块

- **现状**: 400 行代码，0 使用量，5 个 MCP 工具占用工具列表空间
- **操作**: 从 `@mcp.tool()` 注册中移除 agent_send, agent_inbox, agent_presence_update, agent_presence_list, agent_messages_cleanup，保留代码但不暴露
- **收益**: 减少 Claude Code 的工具选择噪声，简化 MCP 工具列表

#### 5.5 修复 Silent Failure

- **现状**: `search.py:78` 的 `except Exception: pass` 吞掉写入队列错误
- **操作**: 加 `logger.warning("write_queue flush failed", exc_info=True)`
- **成本**: 1 行代码

#### 5.6 提升记忆召回率

- **现状**: 70% active 记忆从未被注入
- **方向**:
  - 检查 context pack 的候选生成逻辑 — FTS5 搜索是否漏掉了相关记忆
  - 增加向量搜索在 context pack 中的权重
  - 对从未被注入的记忆做抽样分析 — 它们是低质量碎片还是召回盲区

### P2 — 中期重构

#### 5.7 拆分巨型文件

| 文件 | 行数 | 拆分方向 |
|------|------|----------|
| `curator_llm.py` | 1,654 | 按分析能力拆分: dedup_judge, contradiction_judge, importance_assessor, split_detector, link_discoverer |
| `frontend.py` | 1,458 | 拆分为 routes/ 目录: memories_api, governance_api, curator_api, config_api, dashboard_api |
| `server.py` | 1,147 | 分离 CLI 命令 (cli.py) 和 MCP 工具定义 (tools.py) |
| `search.py` | 1,178 | 分离 context pack 构建 (context.py) 和 FTS5 搜索 (fts.py) |

#### 5.8 前端状态管理简化

- **现状**: 6 个 Redux slice + 手写 30s cache
- **方向**: 用 React Query / TanStack Query 替代服务端状态管理
- **保留 Redux 的**: UI 状态 (dialogs, locale)
- **迁移到 React Query 的**: memories, apps, governance, config, stats
- **收益**: 自动缓存失效、自动重新获取、减少样板代码

#### 5.9 治理系统瘦身

- **方向**: 考虑将治理系统从"人工审核"模式转变为"自动执行 + 异常告警"模式
- 大多数操作自动通过，仅在出现 rollback 或 contradicts 高频时告警
- 删除 needs_review 队列机制，或将其改为"事后抽查"而非"事前审批"
- 简化 mutation_executor 的快照/回滚复杂度 — 实际只用过 1 次

### P3 — 长期方向

#### 5.10 3D 图谱优化或替换

- **方向 A**: 如果保留，过滤掉 part_of/supports 边，只展示语义链接 (related_to, contradicts, supersedes)
- **方向 B**: 替换为 2D 层级图或时间线视图，降低性能开销和技术复杂度
- **方向 C**: 将图谱作为分析工具而非浏览工具 — 只在"发现矛盾"或"追溯谱系"时按需展示子图

#### 5.11 Ingest 管道排查

- 排查 `memory_ingest` 来源标记为 `ingest` 的记忆数为 0 的原因
- 确认 Stop hook 调用的是 `memory_ingest` 还是直接调 `extraction` 模块
- 如果是设计如此 (ingest 内部用 extraction 来源标记)，则记录为已知行为

#### 5.12 i18n 精简

- 如果确认为个人项目，删除 i18n 层，硬编码中文
- 如果有开源/多用户计划，保留但不继续投入

---

## 六、投入产出矩阵

```
                    高价值
                      │
     Context Pack ────┤──── 规则策展器
     提取+去重 ───────┤──── Rollup
     向量搜索 ────────┤──── 反馈系统
                      │
  ─────────────────── │ ───────────────────
                      │
     治理系统 ────────┤──── 原子化 (待验证)
     LLM 策展器 ──────┤──── 3D 图谱
                      │──── i18n
     Agent 通信 ──────┤
                      │
                    低价值
                      
  低投入 ────────────────────────── 高投入
```

---

## 七、总结

MemoryCore 不是噱头项目。核心管道 (提取 → 去重 → 存储 → 注入) 有真实价值：6,500+ 条记忆、81% 注入命中率、16,000+ 条审计事件证明系统在实际运转。

但存在明显的**功能膨胀**：
- Agent 通信是死代码 (0 使用)
- 治理系统过度设计 (2,188 积压无人审)
- LLM 策展器写了没跑通 (唯一 job failed)
- 原子化产出占 46% 但召回效果存疑

优化核心原则：**砍掉死功能、修复坏功能、验证存疑功能**，让系统更精简地聚焦在真正有用的核心链路上。
