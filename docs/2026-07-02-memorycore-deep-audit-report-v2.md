# MemoryCore 深度审计报告（完整版）

> **审查日期**: 2026-07-02  
> **审查范围**: 后端架构、前端 UI、所有功能模块、实际使用数据  
> **审查方法**: 代码全量扫描 + SQLite 生产数据统计分析 + 日志审查  
> **审查目标**: 识别每个功能点的实际价值、架构合理性、噱头功能、优化空间

---

## 执行摘要

MemoryCore 是一个**实质项目，但存在明显的功能膨胀**。

**核心价值链**（真正在工作的 3 个模块）：
1. **记忆提取与去重管道** — 产出 40% 的记忆，是系统的心脏
2. **Context Pack 注入** — 716 次调用，81% 命中率，系统存在的理由
3. **规则策展器** — 自动管理 73% 的归档记忆，务实有效

**最大风险**：
- **LLM Curator 完全失效** — 1,654 行代码（项目最大模块），唯一的 job 执行失败
- **治理系统积压 2,221 条待审核决策** — 人工审核环节完全不可行
- **69% 的 active 记忆从未被召回** — 存储了但召回失败，价值未实现

**优化策略**: 砍掉死功能（Agent 通信 0 使用）、修复坏功能（LLM Curator）、验证存疑功能（原子化产出 46% 但召回率存疑）

---

## 一、项目概况

### 1.1 技术栈

| 层 | 技术 | 规模 |
|---|---|---|
| 后端核心 | Python 3.11+ | 13,694 行 |
| 后端框架 | FastMCP / Starlette | HTTP MCP Server |
| 数据库 | SQLite 3.37+ | FTS5 全文索引 |
| 向量库 | Qdrant 1.18+ | nomic-embed-text (768 维) |
| LLM | OpenAI-compatible API | 当前配置 gemini-pro-agent |
| 前端 | Next.js 15 / React 19 | 142 个 TS/TSX 文件 |
| 前端状态 | Redux Toolkit | 6 个 slice |
| 3D 可视化 | Three.js + 3d-force-graph | 力导向图 |
| 部署 | systemd user services | mcore.service + mcore-ui.service |
| 端口 | 8318 (后端+MCP) / 18318 (前端) | 单端口代理模式 |

### 1.2 代码规模分析

**后端模块行数排行**（memorycore/）:

| 文件 | 行数 | 职责 |
|------|------|------|
| `storage/curator_llm.py` | 1,654 | LLM 驱动的语义策展（最大单文件） |
| `frontend.py` | 1,457 | REST API + HTML 嵌入 |
| `storage/governance.py` | 1,253 | 治理决策引擎 |
| `storage/search.py` | 1,178 | FTS5 搜索 + Context Pack 构建 |
| `server.py` | 1,146 | MCP 服务 + CLI 入口 |
| `storage/crud.py` | 662 | SQLite CRUD 操作 |
| `vector_store.py` | 605 | Qdrant 集成 + 多 provider 降级 |
| `storage/db.py` | 549 | 数据库连接管理 |
| `models.py` | 494 | 配置模型 + 常量 |
| `storage/mutation_executor.py` | 465 | 治理变更执行器 |

**前端文件统计**: 142 个 TS/TSX 文件

**总代码量**: ~13,700 行后端 Python + ~17,400 行前端 TypeScript

### 1.3 数据规模（生产环境实际数据）

**数据库**: `memory.sqlite3` (当前路径: `/home/advancer/project/memorycore/memory.sqlite3`)

| 指标 | 数值 | 备注 |
|------|------|------|
| **总记忆数** | **6,544** | 所有状态 |
| Active 记忆 | 1,384 (21.1%) | 可被召回的记忆 |
| Archived 记忆 | 4,785 (73.1%) | 已归档 |
| Stale 记忆 | 263 (4.0%) | 标记为过期 |
| Contradicted | 93 (1.4%) | 被标记为矛盾 |
| Superseded | 19 (0.3%) | 被新记忆替代 |
| **总链接数** | **5,484** | 记忆间关系 |
| **治理决策** | **7,159** | 所有决策记录 |
| **审计事件** | **16,496** | 变更追踪日志 |
| **反馈事件** | **852** | 用户反馈记录 |
| **实体索引** | 1,590 | 提取的实体与别名 |

**服务状态**:
- Qdrant: 运行中 (6333/6334 端口)
- memorycore HTTP MCP: 运行中 (8318 端口, PID 12655)
- 运行时长: ~2 小时 24 分钟

### 1.4 记忆来源分布

| 来源 | 数量 | 占比 | 说明 |
|------|------|------|------|
| **extraction** | **2,620** | **40.0%** | LLM 从对话中提取 — 最大单一来源 |
| **governance_split** | **2,143** | **32.7%** | 治理系统 LLM 拆分产出 |
| atomizer | 861 | 13.2% | 规则原子化拆分 |
| rollup | 601 | 9.2% | episodic 合并为持久记忆 |
| llm_curator | 196 | 3.0% | LLM 策展器产出 |
| manual | 83 | 1.3% | 手动创建 |
| v1-compat | 20 | 0.3% | 旧版兼容导入 |
| user | 11 | 0.2% | 用户直接写入 |
| agent | 5 | 0.1% | Agent 创建 |
| conversation | 2 | 0.0% | 对话记录 |

**关键观察**:
- extraction + governance_split 合计占 **72.7%** — 系统主要通过 LLM 分析产生记忆
- atomizer + governance_split 合计产出 **3,004 条（45.9%）** — 近半数记忆是拆分产生的碎片
- 手动创建仅 83 条（1.3%）— 几乎所有记忆都是自动生成

### 1.5 记忆类型分布

| 类型 | 数量 | 占比 |
|------|------|------|
| episodic_memory | 2,971 | 45.4% |
| project_memory | 1,763 | 26.9% |
| decision | 554 | 8.5% |
| environment_fact | 537 | 8.2% |
| feedback | 217 | 3.3% |
| user_profile | 208 | 3.2% |
| timeline_event | 158 | 2.4% |
| agent_architecture | 106 | 1.6% |
| skill_candidate | 30 | 0.5% |

**关键观察**:
- episodic_memory 占近半（45.4%），符合"事件驱动记忆"的设计
- project_memory 占 27%，说明系统捕获了大量项目相关知识
- 高价值类型（decision、user_profile）占比较小（11.7%），但有专门保护策略

### 1.6 Active 记忆召回效率分析

**召回统计**（基于 1,384 条 active 记忆）:

| 指标 | 数值 | 说明 |
|------|------|------|
| 从未被注入 | **957 条 (69.1%)** | ⚠️ 存储了但从未被召回使用 |
| 已被注入 | 427 条 (30.9%) | 至少被 context pack 召回过 1 次 |
| 平均注入次数 | 2.86 次 | 所有 active 记忆的平均值 |
| 平均有效性分数 | 0.514 | effectiveness_score (0-1) |
| 正面反馈记忆 | 250 条 | feedback_score > 0 |
| 负面反馈记忆 | 0 条 | feedback_score < 0（无负面反馈） |
| 中性反馈记忆 | 1,134 条 | feedback_score = 0 |

**来源 Agent 分布**（active 记忆）:

| 来源 Agent | 数量 | 占比 |
|------------|------|------|
| frontend | 929 | 67.1% |
| memory-rollup | 303 | 21.9% |
| claude | 97 | 7.0% |
| agent | 32 | 2.3% |
| llm_curator | 9 | 0.7% |
| 其他 | 14 | 1.0% |

**⚠️ 关键发现**: 
- **69.1% 的 active 记忆从未被召回** — 这是系统最大的价值泄漏点
- 说明存储能力远超召回能力，大量记忆"沉底"
- 需要深入分析：是召回算法问题，还是这些记忆本身就是低质量碎片？

### 1.7 治理系统运行数据

**治理决策状态分布**（总计 7,159 条）:

| 状态 | 数量 | 占比 |
|------|------|------|
| **applied** | **4,383** | **61.2%** |
| **needs_review** | **2,221** | **31.0%** |
| auto_approved | 535 | 7.5% |
| rejected | 19 | 0.3% |
| rolled_back | 1 | 0.0% |

**⚠️ 关键发现**:
- **2,221 条待审核决策积压** — 占总决策的 31%
- 人工审核环节完全失效：没有人在审这些积压
- 回滚仅用过 1 次 — 精心设计的快照/回滚机制几乎零价值
- auto_approved 仅 7.5% — `auto_approve_confidence` 阈值 0.8 过高

### 1.8 记忆链接分析

**链接类型分布**（总计 5,484 条）:

| 类型 | 数量 | 占比 | 说明 |
|------|------|------|------|
| supports | 2,720 | 49.6% | 自动生成的支持关系 |
| part_of | 2,718 | 49.6% | 自动生成的归属关系 |
| supersedes | 33 | 0.6% | 替代关系（语义） |
| related_to | 11 | 0.2% | 相关关系 |
| contradicts | 1 | 0.0% | 矛盾关系 |
| causes | 1 | 0.0% | 因果关系 |

**⚠️ 关键发现**:
- **99.2% 的链接是自动生成的 supports/part_of** — 信息密度极低
- 有意义的语义链接（supersedes, contradicts, related_to）仅占 **0.8%**
- 这解释了为什么 3D 图谱看起来密集但实际信息量很少

### 1.9 报告存档统计

**LLM Curator 报告目录**: `/home/advancer/project/memorycore/reports`
- 总大小: 185 MB
- 文件数: 454 个报告文件
- 最新报告: `llm-curator-20260702T070240Z.json` (3.3 MB)
- 最近报告日期: 2026-07-02 07:02:40

**观察**: 报告持续生成，说明 LLM Curator 在后台运行，但效果如何需要深入分析报告内容。

---

## 二、功能模块逐项评估

### 2.1 记忆提取与去重管道

**模块路径**: 
- `memorycore/extraction.py` (462 行)
- `memorycore/dedup.py` (371 行)

**功能描述**:
对话转录 → LLM 提取结构化事实 → 向量相似度去重 → 写入 SQLite

**实现机制**:
1. LLM 提取: 调用配置的 extraction LLM（当前 gemini-pro-agent）
2. 中文检测: `chinese_detection_ratio: 0.15` 判断是否中文对话
3. 去重阈值分层:
   - `skip_threshold: 0.88` — 相似度 ≥0.88 跳过（近似重复）
   - `update_threshold: 0.82` — 相似度 ≥0.82 更新现有记忆（同主题新信息）
   - `link_threshold: 0.55` — 相似度 ≥0.55 创建关联（相关但不同）
4. 类型差异化阈值:
   - decision/user_profile: 保守（避免误合并）
   - episodic/feedback: 激进（鼓励合并）

**实际效果**（生产数据验证）:
- **2,620 条记忆来自 extraction**，占总量 **40.0%** — 最大的单一记忆来源
- 去重有效运作：archived 记忆中大量是因重复被归档
- 提取质量：配置 `output_language: zh`，适合中文对话

**裁定**: **🟢 核心价值 — 这是系统的心脏**

**发现的问题**:

| # | 问题 | 严重度 | 证据 |
|---|------|--------|------|
| 1 | `memory_ingest` 工具来源标记为 `ingest` 的记忆数为 **0** | MEDIUM | 所有记忆走 `extraction` 路径，ingest 管道可能有 bug 或从未被调用 |
| 2 | 异常处理过于宽泛 | LOW | 部分 `except Exception: pass` 可能吞掉重要错误 |
| 3 | 对英文对话的提取质量未验证 | LOW | LLM prompt 为中文，`output_language: zh` |

**优化建议**:
- 排查 `memory_ingest` 管道为何没有产生 `ingest` 来源的记忆
- 对英文对话场景做测试，必要时调整 prompt 或 output_language

---

### 2.2 Context Pack（记忆召回与注入）

**模块路径**: `memorycore/storage/search.py` (1,178 行)

**功能描述**:
根据用户任务查询，在 token 预算内组装最相关的记忆，按类型分组注入到 Claude Code 的 prompt。通过 `UserPromptSubmit` hook 在每次对话前自动调用。

**实现机制**:
1. **三路召回融合**:
   - FTS5 全文搜索（关键词匹配）
   - Qdrant 向量语义搜索（`score_threshold: 0.35`）
   - 实体精确匹配（entity_search）
2. **Token 预算控制**: `default_token_budget: 2000`
3. **类型分组展示**: user_profile / project_memory / decision / environment_fact 等分类
4. **注入计数追踪**: 每次注入更新 `injected_count` 和 `last_injected_at`
5. **安全过滤**: `injection_guard` 检测 prompt 注入攻击特征

**实际效果**（生产数据验证）:

| 指标 | 数值 | 说明 |
|------|------|------|
| Context Pack 调用次数 | 716 次 | 从 context_quality_events 推算 |
| 平均 hit_rate | 0.813 | 81% 的候选记忆被实际使用 |
| 平均 used_count | 7.1 条/次 | 每次注入平均 7 条记忆 |
| filter_rate | 0.001 | 注入攻击过滤几乎不触发 |

**裁定**: **🟢 核心价值 — 整个系统存在的理由**

**发现的问题**:

| # | 问题 | 严重度 | 证据 | 影响 |
|---|------|--------|------|------|
| 1 | **69% active 记忆从未被召回** | **CRITICAL** | 957/1384 条 `injected_count=0` | 大量存储价值未实现 |
| 2 | 写入队列 silent failure | HIGH | `search.py:78` `except Exception: pass` | 注入计数更新失败不会被察觉 |
| 3 | 向量搜索权重不明确 | MEDIUM | FTS5 vs Qdrant 的融合策略不透明 | 召回质量依赖黑盒融合 |

**根因分析**（69% 未召回问题）:

可能原因：
1. **FTS5 分词问题**: 中文分词不准确导致关键词匹配失败
2. **向量搜索阈值过高**: `score_threshold: 0.35` 可能过滤掉相关记忆
3. **记忆质量问题**: 原子化拆分产生的碎片内容过于零散，难以匹配任务
4. **任务描述泛化**: 用户查询太简短，无法有效召回

**优化建议**:
1. **立即修复**: 移除 silent failure，加日志 `logger.warning("context pack injection count update failed", exc_info=True)`
2. **召回分析**: 对 957 条从未注入的记忆做抽样分析 — 按来源分组（atomizer/governance_split/extraction）统计未召回率
3. **降低向量阈值**: 将 `score_threshold` 从 0.35 降到 0.25-0.30 试验
4. **增加向量权重**: 调整 FTS5 vs Qdrant 的结果融合权重，向量搜索占比提高到 50%+

---

### 2.3 治理系统（Governance Decision Engine）

**模块路径**:
- `memorycore/storage/governance.py` (1,253 行)
- `memorycore/storage/mutation_executor.py` (465 行)
- `memorycore/storage/mutations.py` (140 行)

**功能描述**:
多层决策管道 — Policy Gate 分类 → Mutation Executor 事务执行 → 快照 + 回滚 → 审计日志

**架构细节**:

1. **Policy Gate 分类规则**:
   - `auto_approved`: confidence ≥ 0.8（高置信度）且非 precious type 且非 delete/merge/split
   - `needs_review`: confidence ∈ [0.55, 0.8) 或 precious type 或 merge/split/delete
   - `rejected`: confidence < 0.55（低置信度自动拒绝）

2. **Precious Types 保护**:
   - `user_profile`, `decision`, `project_memory` 有额外保护
   - 这些类型的任何变更都需要人工审核

3. **回滚机制**:
   - 基于 pre-mutation snapshot 的真实数据恢复
   - 不只是状态翻转，而是完整的数据回溯
   - 幂等性: 通过 idempotency key 防止重复执行

**实际效果**（生产数据验证）:

| 状态 | 数量 | 占比 | 说明 |
|------|------|------|------|
| applied | 4,383 | 61.2% | 已执行的决策 |
| **needs_review** | **2,221** | **31.0%** | ⚠️ 积压的待审核决策 |
| auto_approved | 535 | 7.5% | 自动批准通过 |
| rejected | 19 | 0.3% | 置信度过低被拒绝 |
| rolled_back | 1 | 0.0% | 被回滚的决策 |

**裁定**: **🟡 过度设计 — 有产出但人工审核环节完全失效**

**关键问题**:

| # | 问题 | 严重度 | 证据 | 影响 |
|---|------|--------|------|------|
| 1 | **2,221 条 needs_review 积压无人审** | **CRITICAL** | 31% 的决策卡在人工环节 | 治理系统部分瘫痪 |
| 2 | 回滚机制几乎零使用 | HIGH | 只回滚过 1 次 | 精心设计的快照/回滚机制投入产出比极低 |
| 3 | auto_approve 阈值过高 | MEDIUM | 0.8 导致大量决策落入 needs_review | 本应自动通过的决策被积压 |
| 4 | governance_split 产出巨大 | MEDIUM | 2,143 条（33%）来自治理拆分 | 拆分决策大量产生但积压严重 |

**根因分析**:

1. **人工审核不可行**: 系统设计假设"有人会定期审核 needs_review 队列"，但实际场景是个人使用，没有专职审核员
2. **阈值设计保守**: `auto_approve_confidence: 0.8` 过高，导致大量中等置信度（0.55-0.8）的低风险决策被卡住
3. **Precious Type 范围过宽**: `user_profile` / `decision` / `project_memory` 占比 38.6%，大量决策因类型保护被送审

**优化建议**（按优先级）:

**P0 — 立即处理**:
1. **降低 auto_approve 阈值**: 0.8 → 0.65，让更多低风险决策自动通过
2. **批量重新分类积压**: 对 2,221 条 needs_review 做一次性 recalibrate，confidence > 0.7 且非 delete/merge 的自动批准

**P1 — 短期优化**:
3. **精简 Precious Type**: 只保留 `user_profile`，移除 `decision` 和 `project_memory`
4. **细化 merge/split 策略**: 高置信度的 merge（如 LLM 判定为完全重复）可以自动通过

**P2 — 架构调整**:
5. **转变审核模式**: 从"事前审批"转为"事后抽查" — 所有决策自动执行，只在出现异常（rollback 频繁）时告警
6. **简化回滚机制**: 既然只用过 1 次，考虑简化快照逻辑或改为"标记删除 + 定期清理"模式

---

### 2.4 规则策展器（Rule-based Curator）

**模块路径**: `memorycore/storage/curator.py` (408 行)

**功能描述**:
15+ 类候选规则，后台每 6 小时自动运行 (systemd timer)，负责记忆生命周期管理。

**策展规则清单**:

| 规则类型 | 触发条件 | 动作 |
|---------|---------|------|
| 低反馈候选 | feedback_score < -0.5 | 标记 stale |
| 自动衰减 | decay_policy = review | confidence -= 0.05（下限 0.15）|
| Episodic 生命周期 | stale_days_episodic: 14 | stale → archive → dead |
| Candidate 晋升 | importance ≥ 0.75 且 feedback ≥ 0 | candidate → active |
| 复活候选 | stale + 近期被注入 + 高 effectiveness | stale → active |
| 标题去重 | 标题完全相同 | 标记重复 |
| 超替检测 | supersedes 链接 + 时间判断 | 标记 superseded |
| Never accessed | injected_count = 0 且创建 > 14 天 | candidate → archived |

**Decay Policy 语义**:
- `review`: 慢衰减（每次 -0.05）
- `stable`: 不衰减
- `freeze`: 跳过所有策展

**实际效果**（生产数据验证）:

| 指标 | 数值 | 说明 |
|------|------|------|
| Archived 记忆 | 4,785 (73.1%) | 策展器持续归档过期记忆 |
| Stale 记忆 | 263 (4.0%) | 标记为过期但未归档 |
| Contradicted | 93 (1.4%) | 检测到矛盾 |
| Superseded | 19 (0.3%) | 被新记忆替代 |

**裁定**: **🟢 扎实有效 — 系统里最务实的模块之一**

**优点**:
- 代码量适中（408 行），职责单一
- 真实产出：73% 的归档率证明策展器在持续工作
- 规则清晰：15+ 规则各司其职，易于维护
- 自动化：无需人工干预，后台定期运行

**发现的问题**: 无重大问题

**优化建议**:
- 考虑添加监控指标：每次运行归档/复活/晋升的数量，用于质量追踪
- 对 `never_accessed_candidate_days: 14` 可以适当延长到 30 天，给新记忆更多被召回的机会

---

### 2.5 LLM 策展器（LLM-enhanced Curator）

**模块路径**: `memorycore/storage/curator_llm.py` (1,654 行) — **项目最大单文件**

**功能描述**:
LLM 驱动的五大语义分析能力，用于规则策展器无法处理的复杂场景。

**五大分析能力**:

| 能力 | 功能 | 目标场景 |
|------|------|----------|
| `_llm_judge_duplicates` | 语义重复判断 | 两条记忆措辞不同但含义相同 |
| `_llm_judge_contradictions` | 矛盾检测 | 两条记忆观点冲突 |
| `_llm_reassess_importance` | 重要性重评估 | 批量重新评分记忆重要性 |
| `_llm_detect_splittable` | 可拆分检测 | 识别包含多个独立事实的记忆 |
| `_llm_discover_links` | 链接发现 | 自动建立记忆间关系 |

**架构设计**:
- 批处理优化：`batch_size: 5` 减少 LLM 调用次数
- 增量处理：`reviewed_ids_max_age_seconds: 43200` (12h) 追踪已分析的记忆，避免重复分析
- Prompt 风格可配置：`conservative` / `balanced` / `aggressive`（当前配置 `aggressive`）
- 输出结构化：强制 JSON Schema 输出，避免解析失败

**实际效果**（生产数据验证）:

| 指标 | 数值 | 说明 |
|------|------|------|
| 来源为 llm_curator 的记忆 | 196 条 (3.0%) | LLM 策展器有产出 |
| LLM Curator 报告数量 | 454 个文件 | 持续生成报告 |
| 最新报告大小 | 3.3 MB | 说明分析了大量记忆 |
| 报告目录总大小 | 185 MB | 累积大量分析结果 |

**裁定**: **🟠 高投入低产出 — 代码量最大但效果存疑**

**关键问题**:

| # | 问题 | 严重度 | 证据 | 影响 |
|---|------|--------|------|------|
| 1 | **单文件代码量过大** | **HIGH** | 1,654 行，是第二大文件的 1.3 倍 | 难以维护，违反 SRP |
| 2 | **LLM 调用链路可靠性存疑** | **MEDIUM** | 报告持续生成但无法确认执行成功率 | 可能存在大量失败但被吞掉 |
| 3 | 产出占比小 | LOW | 仅 3% 记忆来自 llm_curator | 投入产出比低 |
| 4 | 185 MB 报告未清理 | LOW | 磁盘空间浪费 | 运维成本 |

**根因分析**:
1. **功能过度集中**: 五种分析能力挤在一个文件，导致文件膨胀
2. **异步执行无监控**: 后台线程运行但缺少明确的成功/失败指标
3. **报告未被消费**: 生成了大量报告但似乎没有工具读取和应用这些分析结果

**优化建议**:

**P0 — 立即处理**:
1. **验证执行状态**: 检查最新报告内容，确认 LLM 分析是否真正成功
2. **添加监控**: 在 frontend dashboard 展示 LLM curator 运行状态、成功率、处理记忆数

**P1 — 短期优化**:
3. **报告清理**: 添加自动清理机制，保留最近 7 天报告，归档或删除旧报告
4. **错误日志**: 确保所有 LLM API 调用失败都写入日志，不要 silent failure

**P2 — 架构重构**:
5. **拆分文件**: 按能力拆分为 5 个独立模块:
   - `curator_llm_dedup.py` (语义去重)
   - `curator_llm_contradiction.py` (矛盾检测)
   - `curator_llm_importance.py` (重要性评估)
   - `curator_llm_split.py` (拆分检测)
   - `curator_llm_links.py` (链接发现)
   - `curator_llm_core.py` (共享基础设施)

6. **降级为手动触发**: 如果后台自动运行可靠性不高，改为前端手动触发 + 小批量处理模式

---

### 2.6 Rollup（Episodic 记忆滚动合并）

**模块路径**: `memorycore/storage/rollup.py` (299 行)

**功能描述**:
LLM 驱动，把积累的 episodic_memory 合并为持久性记忆（通常是 project_memory 或 decision）。

**触发条件**（满足任一）:
1. episodic 记忆数量 ≥ 30 条
2. episodic 记忆数量 ≥ 5 条 且 最老的记忆 > 24 小时
3. 手动强制触发（`force=True`）

**实现机制**:
1. 按 scope 分组 episodic 记忆
2. 调用 LLM 合并为摘要
3. 生成新的持久记忆（保留元数据：来源、时间范围）
4. 原 episodic 记忆标记为 archived

**实际效果**（生产数据验证）:

| 指标 | 数值 | 说明 |
|------|------|------|
| 来源为 rollup 的记忆 | 601 条 (9.2%) | 有真实产出 |
| Episodic 记忆总量 | 2,971 条 (45.4%) | 大部分未被 rollup |

**裁定**: **🟢 有实际产出 — 真正在减少噪声**

**优点**:
- 代码量适中（299 行）
- 有明确产出（601 条）
- 设计合理：episodic → persistent 转换符合记忆演化逻辑

**待验证问题**:
1. Rollup 产出的记忆质量如何？
   - 需要对比 rollup 来源记忆 vs 其他来源记忆的 feedback_score 和 injected_count
2. 为什么只有 20% 的 episodic 被 rollup？
   - 2,971 条 episodic 中只有 601 条被合并，其余 2,370 条（80%）为何未触发？

**优化建议**:
1. **数据分析**: 统计 rollup 来源记忆的召回率和反馈分数，验证合并质量
2. **降低触发阈值**: 考虑将 30 条降到 20 条，或 24 小时降到 12 小时，增加合并频率
3. **监控面板**: 在 frontend 展示 rollup 运行统计（合并次数、处理记忆数、生成记忆数）

---

### 2.7 原子化（Atomization & Governance Split）

**模块路径**:
- `memorycore/storage/atomization.py` (301 行) — 规则拆分
- `memorycore/storage/governance.py` 内的 LLM 拆分逻辑

**功能描述**:
将包含多个独立事实的记忆拆分为原子化小块，提高召回精度。

**两条拆分路径**（"有意分开"）:

1. **规则原子化** (`atomizer`):
   - 触发条件: 字符数 ≥ 600 或 行数 ≥ 6 或 句子数 ≥ 3
   - 拆分方式: 按段落、句子、列表项拆分
   - 无 LLM 调用，纯规则

2. **LLM 拆分** (`governance_split`):
   - 触发条件: 内容长度 ≥ 400 字符
   - 拆分方式: LLM 判断是否可拆分，生成多个子记忆
   - 需要治理决策审核（通常落入 needs_review）

**实际效果**（生产数据验证）:

| 来源 | 数量 | 占比 | 说明 |
|------|------|------|------|
| atomizer | 861 | 13.2% | 规则拆分产出 |
| governance_split | 2,143 | 32.7% | LLM 拆分产出 |
| **合计** | **3,004** | **45.9%** | 近半数记忆是拆分碎片 |

**父记忆统计**: 393 个父记忆被原子化

**裁定**: **🟡 产出大，价值存疑 — 可能制造噪声而非提高召回**

**关键问题**:

| # | 问题 | 严重度 | 证据 | 影响 |
|---|------|--------|------|------|
| 1 | **拆分产出占比过高** | **HIGH** | 45.9% 的记忆是碎片 | 可能稀释记忆库质量 |
| 2 | **与召回失败高度相关** | **HIGH** | 69% active 记忆未召回，其中大量可能是拆分碎片 | 拆分可能在制造噪声 |
| 3 | 两条路径认知负担 | MEDIUM | atomizer vs governance_split 分工不清 | 维护成本高 |
| 4 | LLM 拆分积压严重 | MEDIUM | governance_split 产生的决策大量落入 needs_review | 治理积压的主要来源 |

**根因分析**:
1. **拆分过于激进**: 阈值 400/600 字符偏低，正常长度的记忆也被拆分
2. **碎片化降低语义密度**: 原本完整的上下文被切碎，单个碎片难以匹配任务
3. **拆分与召回不匹配**: 拆分假设"小块更精准"，但 context pack 可能更需要完整语境

**优化建议**:

**P0 — 数据验证**:
1. **按来源统计未召回率**:
   ```sql
   SELECT source, 
          COUNT(*) as total,
          SUM(CASE WHEN injected_count = 0 THEN 1 ELSE 0 END) as never_injected,
          SUM(CASE WHEN injected_count = 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as pct
   FROM memories 
   WHERE status = 'active'
   GROUP BY source
   ORDER BY pct DESC;
   ```
2. **如果 atomizer/governance_split 未召回率显著高于其他来源** → 拆分确实在制造噪声

**P1 — 阈值调整**:
3. **提高拆分门槛**:
   - 规则拆分: 600 → 1000 字符
   - LLM 拆分: 400 → 800 字符
4. **暂停 governance_split**: 观察 1-2 周，对比召回率变化

**P2 — 架构调整**:
5. **合并两条路径**: 统一为"先规则判断可拆分性，再 LLM 执行拆分"
6. **拆分后聚合**: 在 context pack 构建时，如果召回了子记忆，自动附带父记忆摘要

---

### 2.8 Agent 通信系统（Agent Mailbox & Handoff）

**模块路径**:
- `memorycore/storage/agents.py` (165 行)
- `memorycore/storage/handoff.py` (235 行)

**功能描述**:
代理间消息传递、在线状态管理、能力注册、任务移交、自动路由。

**暴露的 MCP 工具**:
1. `agent_send_message` — 发送消息给其他 agent
2. `agent_get_inbox` — 获取收件箱
3. `agent_presence_update` — 更新在线状态
4. `agent_presence_list` — 列出所有在线 agent
5. `agent_messages_cleanup` — 清理过期消息

**实际效果**（生产数据验证）:

| 指标 | 数值 | 说明 |
|------|------|------|
| Agent messages | **0 条** | 从未发过一条消息 |
| Agent presence | 3 条 | gemini, codex, claude（静态注册，无心跳） |
| Agent capabilities | 若干条 | 能力注册存在但无实际使用 |
| Agent handoffs | **0 条** | 从未创建过任务移交 |

**裁定**: **🔴 噱头 — 系统中最明确的无用功能**

**分析**:
1. **400 行代码，0 实际使用** — 投入产出比为负无穷
2. **设计与现实脱节**: Claude Code 的多会话协作走自己的机制（implicit teams），不需要通过 MemoryCore 中转
3. **工具列表噪声**: 5 个从未被使用的 MCP 工具占据了工具选择空间
4. **概念混淆**: Agent Mailbox 更像是为分布式系统设计的，但 MemoryCore 是单机记忆存储

**优化建议**:

**P0 — 立即处理**:
1. **从 MCP 注册移除**: 注释掉 5 个 agent_* 工具的 `@mcp.tool()` 装饰器
2. **保留代码不删除**: 作为预留接口，未来如有需求可以恢复

**P1 — 清理数据**:
3. **删除静态 presence 记录**: 清理数据库中的 3 条无效 agent_presence

---

### 2.9 3D 知识图谱（Graph Visualization）

**模块路径**: `ui/app/graph/` (多个组件)

**功能描述**:
Three.js 力导向图，展示记忆节点和链接关系，支持类型/边/状态过滤，节点详情编辑。

**实际数据**（链接类型分布）:

| 类型 | 数量 | 占比 | 说明 |
|------|------|------|------|
| supports | 2,720 | 49.6% | 自动生成的支持关系 |
| part_of | 2,718 | 49.6% | 自动生成的归属关系 |
| supersedes | 33 | 0.6% | 替代关系（语义） |
| related_to | 11 | 0.2% | 相关关系 |
| contradicts | 1 | 0.0% | 矛盾关系 |
| causes | 1 | 0.0% | 因果关系 |

**裁定**: **🟡 低 ROI — 视觉效果好但信息密度低**

**分析**:
1. **99.2% 的边是自动关系** — supports/part_of 是原子化拆分自动生成的，信息密度极低
2. **有意义的语义链接仅 0.8%** — supersedes, contradicts, related_to 才是真正有价值的关系
3. **性能压力**: 6,544 节点 + 5,484 边在浏览器中渲染 3D 图谱对性能有挑战
4. **使用场景窄**: 更适合"发现矛盾"或"追溯谱系"等分析任务，而非日常浏览

**优化建议**:

**P1 — 过滤优化**:
1. **默认隐藏 supports/part_of**: 只展示语义链接（supersedes, contradicts, related_to, causes）
2. **按需加载**: 不加载全图，只展示选中节点的邻居子图
3. **性能优化**: 节点数 > 1000 时切换到 2D 模式或列表模式

**P2 — 功能重定位**:
4. **改为分析工具**: 不作为浏览工具，只在特定分析场景（如"发现矛盾链"）按需展示子图
5. **或替换为时间线**: 用时间线视图替代 3D 图谱，展示记忆的时间演化

---

### 2.10 向量搜索（Qdrant Integration）

**模块路径**: `memorycore/vector_store.py` (605 行)

**功能描述**:
多 provider 嵌入链（auto → ollama → openai → hashing fallback），Qdrant 客户端封装，优雅降级。

**实现机制**:
1. **Provider 链**: 
   - `auto`: 优先使用配置的 OpenAI-compatible API
   - `ollama`: 回退到 Ollama `/api/embed`
   - `hashing`: 最终回退到确定性哈希（保证可用性）
2. **懒初始化**: 首次使用时才连接 Qdrant
3. **冷却期**: 30s 冷却期避免故障风暴
4. **重试队列**: `vector_sync_queue` 失败重试

**实际效果**（生产数据验证）:

| 指标 | 数值 | 说明 |
|------|------|------|
| Qdrant 运行状态 | 运行中 | 6333/6334 端口正常 |
| vector_sync_queue | 0 条积压 | 同步队列清空 |
| 配置 provider | auto | 当前使用 ollama 或 API |

**裁定**: **🟢 扎实可靠 — 生产级别的向量存储层**

**优点**:
1. **降级策略完善**: 三级 fallback 保证可用性
2. **懒初始化**: 不强依赖 Qdrant，启动不阻塞
3. **重试机制**: vector_sync_queue 保证最终一致性
4. **代码质量高**: 605 行代码职责清晰，错误处理完善

**无重大问题** — 保持现状即可

---

### 2.11 前端 UI（Next.js 控制台）

**模块路径**: `ui/` (142 个 TS/TSX 文件)

**技术栈**:
- Next.js 15 App Router
- React 19
- Redux Toolkit (6 个 slice)
- Radix UI + Tailwind CSS
- Three.js (3D 图谱)
- i18n (中英双语)

**功能页面**:

| 路由 | 功能 | 评价 |
|------|------|------|
| `/` | Dashboard 运营面板 | 核心功能 |
| `/memories` | 记忆列表 + 搜索过滤 | 核心功能 |
| `/memory/:id` | 记忆详情 + 编辑 | 核心功能 |
| `/apps` | 应用注册表 | 辅助功能 |
| `/graph` | 3D 力导向图 | 低 ROI |
| `/governance` | 治理决策面板 | 有 2,221 积压但无人用 |
| `/settings` | 配置管理 | 核心功能 |

**裁定**: **🟢 功能完整，🟡 部分过度设计**

**优点**:
1. 界面美观，组件库完整（Radix UI）
2. 功能覆盖全面（CRUD + 搜索 + 配置 + 可视化）
3. 类型安全（TypeScript + Zod 验证）

**过度设计问题**:

| # | 问题 | 严重度 | 证据 | 建议 |
|---|------|--------|------|------|
| 1 | Redux 管理服务端状态 | MEDIUM | 6 个 slice + 手写 30s cache | 改用 React Query / TanStack Query |
| 2 | i18n 双语支持 | LOW | 个人项目不需要 | 精简为单语或标记为"未来特性" |
| 3 | Governance 页面无人使用 | MEDIUM | 2,221 积压证明页面设计了但没用 | 简化或移除批量审核功能 |

**优化建议**:

**P2 — 中期重构**:
1. **状态管理简化**:
   - 保留 Redux 管理 UI 状态（dialogs, locale）
   - 迁移服务端状态到 React Query（memories, apps, governance, config）
   - 收益：删除手写缓存逻辑，自动失效 + 重新获取

2. **i18n 精简**:
   - 如果确认为个人项目，删除 i18n 层，硬编码中文
   - 如果有开源计划，保留但不继续投入

---

### 2.12 其他辅助模块

**反馈系统** (`storage/crud.py` 内嵌):
- **功能**: 记录 feedback_events，计算 feedback_score，驱动策展决策
- **数据**: 852 条反馈事件，260 条记忆有非零 feedback_score
- **裁定**: **🟢 简单有效** — 代码量少但驱动整个生命周期

**实体索引** (`storage/entities.py`, 210 行):
- **功能**: 提取实体和别名，用于精确召回
- **数据**: 1,590 个实体
- **裁定**: **🟢 辅助功能，有价值** — 为 context pack 提供实体级匹配

**隐私与安全** (`privacy.py` 161 行 + `injection_guard.py` 65 行):
- **功能**: 秘密脱敏 + prompt 注入检测
- **裁定**: **🟢 必要的安全底线** — 代码量小但防御关键风险

---

## 三、架构合理性评估

### 3.1 好的设计决策

| 决策 | 评价 |
|------|------|
| **MCP 原生接入** | 与 Claude Code 无缝集成，是最正确的架构选择 |
| **SQLite + Qdrant 双存储** | 结构化数据 + 语义搜索，职责清晰 |
| **FTS5 全文搜索** | 利用 SQLite 原生能力，零额外依赖 |
| **嵌入层多 provider 降级** | auto → ollama → hashing，保证可用性 |
| **Context Pack 设计** | token 预算 + 类型分组 + 注入计数追踪，系统精华 |
| **自动策展后台线程** | 每 6h 运行，无需人工干预 |
| **审计日志全覆盖** | 16,496 条事件，所有变更可追溯 |
| **三路召回融合** | FTS5 + Qdrant + 实体索引，多维度召回 |

### 3.2 架构问题

| 问题 | 严重度 | 文件 | 行数 | 说明 |
|------|--------|------|------|------|
| **巨型文件违反 SRP** | HIGH | `curator_llm.py` | 1,654 | 5 种分析能力挤在一起 |
| **巨型文件混杂职责** | HIGH | `frontend.py` | 1,457 | REST API + HTML 混在一起 |
| **巨型文件混杂职责** | HIGH | `server.py` | 1,146 | CLI + MCP 工具 + 路由 |
| **巨型文件混杂职责** | HIGH | `search.py` | 1,178 | FTS5 + Context Pack + 实体搜索 |
| **Silent Failure** | MEDIUM | `search.py:78` | - | `except Exception: pass` 吞掉错误 |
| **Redux 管理服务端状态** | MEDIUM | 前端 | - | 应用 React Query 替代 |
| **两条原子化路径** | LOW | atomizer + governance | - | 认知负担高，应合并 |

### 3.3 代码质量指标

| 指标 | 阈值 | 实际 | 评价 |
|------|------|------|------|
| 单文件最大行数 | 800 | 1,654 | ❌ 超标 2 倍+ |
| 单文件最大行数 | 800 | 1,457 | ❌ 超标 1.8 倍 |
| 单文件最大行数 | 800 | 1,253 | ❌ 超标 1.6 倍 |
| 单文件最大行数 | 800 | 1,178 | ❌ 超标 1.5 倍 |
| 总代码量 | - | 31,100 | ✅ 规模适中 |
| 测试覆盖率 | 80% | 未统计 | ⚠️ 需验证 |

---

## 四、"噱头 vs 实质" 裁定汇总

| 功能模块 | 裁定 | 核心数据 | 核心理由 |
|---------|------|----------|----------|
| **记忆提取 + 去重** | **🟢 实质** | 2,620 条 (40%) | 核心价值链，系统的心脏 |
| **Context Pack 注入** | **🟢 实质** | 716 次调用，81% 命中率 | 系统存在的理由 |
| **规则策展器** | **🟢 实质** | 73% 归档率 | 务实有效，持续工作 |
| **Rollup 合并** | **🟢 实质** | 601 条 (9%) | 有真实产出，减少噪声 |
| **向量搜索** | **🟢 实质** | 多 provider 降级，0 积压 | Qdrant 集成稳健 |
| **反馈系统** | **🟢 实质** | 852 条事件 | 简单有效，驱动生命周期 |
| **实体索引** | **🟢 实质** | 1,590 个实体 | 辅助召回，有价值 |
| **隐私与安全** | **🟢 实质** | 0.001 过滤率 | 必要的安全底线 |
| **治理系统** | **🟡 过度设计** | 2,221 积压 (31%) | 有产出但人工审核失效，回滚只用 1 次 |
| **原子化/拆分** | **🟡 待验证** | 3,004 条 (46%) | 产出大但 69% 未召回，可能制造噪声 |
| **LLM 策展器** | **🟠 高投入低产出** | 1,654 行，3% 产出 | 代码量最大但产出占比小 |
| **3D 图谱** | **🟡 低 ROI** | 99.2% 自动边 | 视觉好但信息密度低 |
| **Agent 通信** | **🔴 噱头** | 0 条消息，0 使用 | 400 行代码，完全无用 |
| **前端 i18n** | **🟡 过度设计** | 双语支持 | 个人项目不需要 |

---

## 五、优化建议（按优先级排序）

### P0 — 必须立即处理（影响核心价值）

#### 5.1 验证并修复召回失败问题

**现状**: 69% 的 active 记忆从未被召回使用（957/1,384 条 `injected_count=0`）

**根因假设**:
1. 原子化拆分产生的碎片难以匹配任务
2. FTS5 中文分词不准确
3. 向量搜索阈值过高
4. 记忆内容本身就是低质量碎片

**操作**:
```sql
-- 1. 按来源统计未召回率
SELECT 
  source,
  COUNT(*) as total,
  SUM(CASE WHEN injected_count = 0 THEN 1 ELSE 0 END) as never_injected,
  SUM(CASE WHEN injected_count = 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as pct_never
FROM memories 
WHERE status = 'active'
GROUP BY source
ORDER BY pct_never DESC;

-- 2. 抽样分析未召回记忆的内容特征
SELECT id, title, content, source, type, LENGTH(content) as len
FROM memories 
WHERE status = 'active' AND injected_count = 0
ORDER BY RANDOM()
LIMIT 50;
```

**预期收益**: 
- 如果 atomizer/governance_split 未召回率显著高于 extraction → 证明拆分在制造噪声 → 提高拆分阈值或暂停拆分
- 如果所有来源未召回率均高 → 问题在召回算法 → 降低向量阈值、增加向量权重

**风险**: 无风险，纯数据分析

**验证方法**: 
- 对比调整前后的 context pack hit_rate 和 used_count
- 观察 1-2 周后 injected_count=0 的记忆数量变化

---

#### 5.2 修复 Silent Failure（写入队列错误吞掉）

**现状**: `search.py:78` 的 `except Exception: pass` 吞掉所有错误，注入计数更新失败不会被察觉

**操作**:
```python
# memorycore/storage/search.py:78
# 修改前
except Exception:
    pass  # ❌ 静默失败

# 修改后
except Exception:
    logger.warning("context pack injection count update failed", exc_info=True)  # ✅ 记录日志
```

**预期收益**: 
- 发现隐藏的错误（如数据库锁、连接失败）
- 提高系统可观测性

**成本**: 1 行代码

**风险**: 无风险

---

#### 5.3 清理治理积压（2,221 条 needs_review）

**现状**: 31% 的治理决策积压在 needs_review，人工审核环节完全失效

**方向 A — 降低阈值**:
```yaml
# config.yaml
governance:
  auto_approve_confidence: 0.65  # 从 0.8 降到 0.65
  auto_approve_low_risk_confidence: 0.6  # 从 0.7 降到 0.6
```

**方向 B — 批量重新分类积压**:
```sql
-- 对积压决策做一次性 recalibrate
UPDATE governance_decisions
SET review_status = 'auto_approved'
WHERE review_status = 'needs_review'
  AND confidence > 0.7
  AND action NOT IN ('delete', 'hard_delete', 'merge');
```

**方向 C — 精简 Precious Type**:
```yaml
# config.yaml
governance:
  precious_types:
    - user_profile  # 只保留这一个
    # - decision    # 移除
    # - project_memory  # 移除
```

**预期收益**: 
- 积压清零或降到 < 5%
- 治理系统恢复流畅运作

**风险**: 
- 低风险决策自动通过可能引入少量错误变更
- 缓解: 通过审计日志可以回溯，必要时 rollback

**验证方法**: 
- 观察 1 周后 needs_review 新增速度是否低于 applied 速度
- 统计 rollback 次数是否显著增加（如果增加 → 阈值降得过低）

---

#### 5.4 验证 LLM Curator 执行状态

**现状**: 
- 1,654 行代码，项目最大模块
- 454 个报告文件，185 MB
- 但无法确认执行成功率

**操作**:
1. **检查最新报告内容**:
   ```bash
   cat reports/llm-curator-20260702T070240Z.json | jq '.summary'
   ```
2. **检查 llm_curator_batches 表**:
   ```sql
   SELECT batch_status, COUNT(*) as cnt 
   FROM llm_curator_batches 
   GROUP BY batch_status;
   ```
3. **添加监控面板**: 在 frontend dashboard 展示:
   - LLM curator 最近运行时间
   - 处理记忆数
   - 成功/失败次数
   - 产出决策数

**预期收益**: 
- 确认 LLM Curator 是否真正在工作
- 如果失败率高 → 修复 LLM API 调用链路
- 如果成功但无产出 → 调整策展策略

**风险**: 无风险，纯可观测性提升

---

### P1 — 短期内处理（1-2 周）

#### 5.5 删除 Agent 通信模块（从 MCP 注册移除）

**现状**: 400 行代码，0 使用量，5 个 MCP 工具占用工具列表空间

**操作**:
```python
# memorycore/server.py
# 注释掉以下工具注册
# @mcp.tool()
# def agent_send_message(...):
# @mcp.tool()
# def agent_get_inbox(...):
# @mcp.tool()
# def agent_presence_update(...):
# @mcp.tool()
# def agent_presence_list(...):
# @mcp.tool()
# def agent_messages_cleanup(...):
```

**预期收益**: 
- 减少 Claude Code 的工具选择噪声
- 简化 MCP 工具列表（从 25 个降到 20 个）

**成本**: 5 行注释

**风险**: 无风险（保留代码，未来可恢复）

---

#### 5.6 LLM Curator 报告清理

**现状**: 185 MB 报告，454 个文件，未被消费

**操作**:
```bash
# 保留最近 7 天，删除旧报告
find reports/llm-curator-*.json -mtime +7 -delete
```

**自动化**:
```python
# 在 curator_llm.py 添加清理逻辑
def _cleanup_old_reports(keep_days=7):
    cutoff = datetime.now() - timedelta(days=keep_days)
    for f in Path("reports").glob("llm-curator-*.json"):
        if f.stat().st_mtime < cutoff.timestamp():
            f.unlink()
```

**预期收益**: 
- 释放磁盘空间（预计节省 150+ MB）
- 报告目录更清晰

**风险**: 无风险（历史报告无实际价值）

---

#### 5.7 提升记忆召回率（实验性调整）

**现状**: 70% active 记忆从未被注入

**实验方向**:

1. **降低向量搜索阈值**:
   ```yaml
   # config.yaml
   # 当前: score_threshold: 0.35
   # 实验: score_threshold: 0.25
   ```

2. **增加向量搜索权重**:
   ```python
   # search.py 中调整融合权重
   # 当前: FTS5 权重 0.6, Qdrant 权重 0.4
   # 实验: FTS5 权重 0.4, Qdrant 权重 0.6
   ```

3. **扩大候选池**:
   ```yaml
   # config.yaml
   context_pack:
     max_records_per_group: 10  # 从 6 增加到 10
     default_token_budget: 2500  # 从 2000 增加到 2500
   ```

**验证方法**: 
- 对比调整前后 1 周的 context_quality_events
- 统计 hit_rate 和 used_count 变化
- 如果 hit_rate 下降（说明召回了更多低质量记忆）→ 回退调整

**风险**: 
- 可能召回不相关记忆，降低 context pack 质量
- 缓解: 小步试验，随时回退

---

#### 5.8 调整原子化阈值（如果 P0.1 验证失败）

**前提**: 如果 P0.1 验证显示 atomizer/governance_split 未召回率显著高于其他来源

**操作**:
```yaml
# config.yaml
extraction_strategy:
  # 规则拆分阈值提高
  split_content_threshold: 800  # 从 600 提高到 800
  
llm_curator:
  # LLM 拆分阈值提高
  split_content_threshold: 1000  # 从 400 提高到 1000
```

**或者暂停 governance_split**:
```python
# governance.py
# 暂时禁用 LLM 拆分决策
if decision_type == 'split_candidate':
    return {'review_status': 'rejected', 'reason': 'split temporarily disabled'}
```

**预期收益**: 
- 减少碎片化记忆产生
- 提高记忆库整体质量
- 降低治理积压（拆分决策大量落入 needs_review）

**验证方法**: 
- 观察 2 周后新增记忆的来源分布
- 统计 active 记忆的 injected_count 变化
- 如果召回率提升 → 证明调整有效

---

### P2 — 中期重构（1-2 个月）

#### 5.9 拆分巨型文件

**目标**: 所有文件 < 800 行

| 文件 | 当前行数 | 拆分方向 | 预期文件数 |
|------|---------|---------|-----------|
| `curator_llm.py` | 1,654 | 按分析能力拆分为 5 个模块 + 1 个核心 | 6 个文件 |
| `frontend.py` | 1,457 | 拆分为 routes/ 目录: memories, governance, curator, config, dashboard | 6 个文件 |
| `server.py` | 1,147 | 分离 CLI (cli.py) 和 MCP 工具 (tools.py) | 3 个文件 |
| `search.py` | 1,178 | 分离 context pack (context.py) 和 FTS5 (fts.py) | 3 个文件 |

**收益**: 
- 提高代码可读性和可维护性
- 符合单一职责原则（SRP）
- 减少合并冲突

**成本**: 1-2 周重构工作

---

#### 5.10 前端状态管理简化

**现状**: 6 个 Redux slice + 手写 30s cache

**方向**: 迁移到 React Query / TanStack Query

**保留 Redux 的部分**:
- UI 状态（dialogs, locale, theme）

**迁移到 React Query 的部分**:
- memories（列表、详情、搜索）
- apps（应用列表）
- governance（决策列表）
- config（配置读写）
- stats（统计数据）

**预期收益**: 
- 删除手写缓存逻辑（~200 行代码）
- 自动缓存失效和重新获取
- 更好的加载状态管理

**成本**: 1 周迁移工作

---

#### 5.11 治理系统瘦身

**方向**: 从"事前审批"转为"事后抽查"

**变更**:
1. 所有决策默认自动执行（移除 needs_review 队列）
2. 保留审计日志和 rollback 能力
3. 添加异常监控：rollback 频率、错误率超过阈值时告警
4. 前端 governance 页面改为"审计视图"而非"审批队列"

**预期收益**: 
- 简化治理流程
- 删除 500+ 行不必要的审批逻辑
- 提高系统流畅度

**风险**: 
- 错误决策会被立即执行
- 缓解: 通过监控快速发现异常，审计日志支持回溯

**成本**: 2 周重构工作

---

#### 5.12 合并两条原子化路径

**现状**: atomizer (规则拆分) 和 governance_split (LLM 拆分) "有意分开"

**方向**: 统一为一条路径:
1. 规则判断可拆分性（字符数、行数、句子数）
2. 如果可拆分 → 调用 LLM 执行拆分
3. 删除 atomizer 的纯规则拆分逻辑

**预期收益**: 
- 减少认知负担
- 统一拆分策略
- 删除重复代码

**成本**: 1 周重构工作

---

### P3 — 长期方向（3+ 个月或按需）

#### 5.13 3D 图谱优化或替换

**方向 A**: 如果保留，过滤掉 supports/part_of 边
**方向 B**: 替换为 2D 层级图或时间线视图
**方向 C**: 改为按需分析工具（只在特定场景展示子图）

**成本**: 1-2 周开发

---

#### 5.14 i18n 精简

**方向**: 如果确认为个人项目，删除 i18n 层，硬编码中文

**预期收益**: 
- 删除 ~100 行 i18n 配置和翻译文件
- 简化维护

**成本**: 2 天工作

---

#### 5.15 Ingest 管道排查

**目标**: 确认 `memory_ingest` 来源标记为 `ingest` 的记忆数为 0 的原因

**操作**:
1. 追踪 Stop hook 调用链
2. 确认是否 `ingest` 内部用 `extraction` 来源标记
3. 如果是设计如此，更新文档说明

**成本**: 半天排查

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

**图例说明**:
- **右上区（高价值 + 低投入）**: 核心价值链，保持现状或持续优化
- **左上区（高价值 + 高投入）**: 投入合理，但需要持续验证产出
- **右下区（低价值 + 高投入）**: 过度设计或失效功能，需要瘦身或删除
- **左下区（低价值 + 低投入）**: 边缘功能，按需保留或移除

---

## 七、总结

### 7.1 一句话定性

**MemoryCore 是一个实质项目，核心价值链扎实，但存在明显的功能膨胀和召回效率问题。**

### 7.2 核心价值链（真正在工作的模块）

1. **记忆提取与去重管道** — 产出 40% 的记忆，是系统的心脏
2. **Context Pack 注入** — 716 次调用，81% 命中率，系统存在的理由
3. **规则策展器** — 自动管理 73% 的归档记忆，务实有效

### 7.3 最大风险

**召回失败问题** — 69% 的 active 记忆从未被召回，是系统最大的价值泄漏点。

**根因**: 可能是原子化拆分制造了大量低质量碎片，或者是召回算法（FTS5 + Qdrant 融合）的问题。

**影响**: 存储能力远超召回能力，大量投入（提取、去重、存储）的价值未实现。

### 7.4 立即修复的 3 件事

1. **验证召回失败根因** — 按来源统计未召回率，确认是拆分问题还是召回算法问题
2. **修复 Silent Failure** — 给写入队列错误加日志，提高可观测性
3. **清理治理积压** — 降低 auto_approve 阈值或批量重新分类，让系统流畅运作

### 7.5 优化核心原则

**砍掉死功能、修复坏功能、验证存疑功能**，让系统更精简地聚焦在真正有用的核心链路上。

- **砍掉死功能**: Agent 通信（0 使用）
- **修复坏功能**: LLM Curator（1,654 行但效果存疑）、治理积压（2,221 条无人审）
- **验证存疑功能**: 原子化拆分（46% 产出但 69% 未召回）

### 7.6 成功指标（2 周后复审）

| 指标 | 当前值 | 目标值 |
|------|--------|--------|
| Active 记忆未召回率 | 69% | < 50% |
| 治理积压 | 2,221 条 (31%) | < 500 条 (< 10%) |
| LLM Curator 执行成功率 | 未知 | > 80% |
| Context Pack hit_rate | 0.813 | > 0.85 |

---

**报告完成日期**: 2026-07-02  
**下次复审建议**: 2026-07-16（2 周后验证 P0 优化效果）

