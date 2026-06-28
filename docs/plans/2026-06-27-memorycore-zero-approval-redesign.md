# MemoryCore 审批精简方案：只审批真正重要的

Date: 2026-06-27
Last revised: 2026-06-27

## 设计哲学

保留现有页面结构，大幅减少审批量。只有 merge（合并）、split（拆分）、mark_contradicted（标记矛盾）需要人工审批，其余全部自动执行。

用户与 MemoryCore 的唯一交互应该是：
1. Agent 对话时自动获得准确的上下文
2. 偶尔打开 Context Lab 看看"mcore 记住了什么"，标记"有用/没用"
3. 出问题时看 Dashboard 一眼，知道发生了什么

其他一切——治理、清理、去重、建链、过期、合并、降级——全部自动。

## 当前问题的根因分析

从数据库实际数据看：

| 指标 | 当前值 | 问题 |
|---|---|---|
| active memories | 849 | 合理 |
| needs_review 积压 | 915 条 | 超过 active 数量，严重不合理 |
| auto_approved 未执行 | 94 条 | 已批准但没执行 |
| needs_review 中 action=keep | 181 条 | "保持不变"也进了审批队列 |

915 条 needs_review 积压的根因不是治理策略太松，而是 **policy_gate 太保守**：

1. **precious_memory_type 一刀切**：`user_profile`、`decision`、`project_memory` 被标记为 precious，任何涉及它们的操作都进 `needs_review`。但这三种类型占 active 记忆的 70%（600/849），导致绝大多数治理建议都被拦截。
2. **confidence_below_auto_threshold 门槛太高**：`AUTO_CONFIDENCE_THRESHOLD = 0.90`，LLM curator 很少能给出 0.90+ 的 confidence，导致大量合理建议被拦截。
3. **recently_created_memory 范围太广**：7 天内创建/更新的记忆的破坏性操作全部进审查，但 Agent 系统每天都在写入，几乎所有记忆都是"最近创建的"。
4. **keep 动作也进 needs_review**：LLM 说"保持不变"但 confidence 不够高，也被拦截——但"保持不变"根本不需要审批。
5. **auto_approved 没有自动执行**：94 条已批准的变更等着手动 apply，形成了另一个死队列。

## 核心策略变更

### 1. 消灭审批队列

**目标：needs_review 归零，永久为零。**

具体变更：

#### 1.1 `keep` 动作直接丢弃，不创建 governance decision

当 LLM curator 判断一条记忆"保持不变"时，不需要创建任何 decision。当前 181 条 keep 类型的 needs_review 是纯噪音。

```
变更位置：memorycore/storage/governance.py - policy_gate()
规则：action == "keep" → 不创建 decision，直接返回
```

#### 1.2 取消 precious_memory_type 作为审批理由

precious 类型（user_profile、decision、project_memory）不再自动进入 needs_review。改为：

- 低风险操作（downgrade、promote、archive_duplicate）+ confidence ≥ 0.70 → auto_approved
- 中风险操作（supersede、archive）+ confidence ≥ 0.80 → auto_approved
- 高风险操作（merge、split）→ 仍然 auto_approved，但 **延迟执行 + 可回滚**（见 1.5）
- delete → 仍然 rejected（永远不自动删除）

```
变更位置：memorycore/storage/governance.py - policy_gate()
删除：is_precious 作为 needs_review 的单独理由
保留：delete 操作的 rejected 逻辑
```

#### 1.3 降低 auto-approval confidence 门槛

```
当前值：
  AUTO_CONFIDENCE_THRESHOLD = 0.90
  REVIEW_CONFIDENCE_THRESHOLD = 0.55（低于此直接 rejected）
  
新值：
  AUTO_CONFIDENCE_THRESHOLD = 0.65（所有非破坏性操作）
  DESTRUCTIVE_AUTO_THRESHOLD = 0.75（archive、supersede、merge）
  REJECT_THRESHOLD = 0.45（低于此直接丢弃，不创建 decision）
```

#### 1.4 取消 recently_created_memory 作为审批理由

7 天内创建的记忆不再因为"太新"而阻止自动治理。时间不应该是审批的理由——如果一条记忆 2 天前写入，今天被判定为重复，就应该立即自动 archive。

```
变更位置：memorycore/storage/governance.py - policy_gate()
删除：Phase 6 时间信号整段逻辑
```

#### 1.5 auto_approved 自动立即执行

`auto_approved` 不再是一个需要手动 apply 的中间态。governance decision 创建时如果 review_status 为 `auto_approved`，立即调用 `apply_governance_decision()`。

安全网：
- 所有 auto-applied 变更写入 audit log
- 所有破坏性变更保留 rollback snapshot
- Dashboard 显示最近 24h 的自动变更摘要
- 如果 rollback_rate 超过 5%，系统自动切换到保守模式（提高 confidence 门槛 0.1）

```
变更位置：
  memorycore/storage/governance.py - create_governance_decision()
  在 decision 创建后，如果 gate["review_status"] == "auto_approved"，立即 apply
  
  memorycore/storage/temporal_governance.py - process_auto_supersession()
  已有此逻辑，保持不变
```

#### 1.6 清空历史积压

一次性处理当前 915 条 needs_review：

```
策略：
1. action=keep 的 181 条 → 直接标记为 rejected（无操作）
2. 剩余 734 条中，confidence ≥ 0.65 的 → recalibrate 为 auto_approved 并立即 apply
3. confidence < 0.45 的 → 直接 rejected
4. 0.45 ≤ confidence < 0.65 的 → auto_approved 并立即 apply（一次性宽容，因为队列太老）
5. auto_approved 未执行的 94 条 → 立即 batch apply
```

### 2. 提升召回准确率

当前 `build_context_pack` 的三路召回（FTS5 + Qdrant vector + Entity alias）架构是合理的。问题不在召回架构，而在 **记忆质量** 和 **反馈闭环**。

#### 2.1 反馈驱动的自动调权

当前 feedback_score 在排序中只占 0.02 权重（第 786 行），几乎没有影响力。

```
变更：
  feedback_score 权重从 0.02 提升到 0.10
  连续 3 次 not-helpful 的记忆 → 自动标记 stale
  连续 5 次 not-helpful 的记忆 → 自动 archive
  helpful 反馈 → importance 自动 +0.05（上限 1.0）
  
变更位置：memorycore/storage/search.py - _rank_score()
新增：memorycore/storage/search.py - _auto_feedback_actions()（在 build_context_pack 返回后异步执行）
```

#### 2.2 自动清理矛盾和过期记忆

不等 LLM curator 发现——在写入时就自动处理：

```
memory_ingest 写入后：
  1. temporal_governance 已有的 auto-supersession → 保持
  2. 新增：如果 valid_until 已过期 → 自动标记 stale
  3. 新增：如果新写入的记忆与已有 active 记忆的 vector similarity ≥ 0.92 → 自动 supersede 旧记忆（不等 curator）
  
变更位置：memorycore/storage/temporal_governance.py
调整：auto_supersede_threshold 从 0.88 降到 0.85
```

#### 2.3 不再注入低效记忆

在 `build_context_pack` 的排序和过滤中增加硬规则：

```
新增过滤规则：
  - status=stale 的记忆不参与召回（当前已实现：只查 status='active'）
  - feedback_score ≤ -2 的记忆跳过（反复标记无用）
  - injected_count > 20 但 feedback_score = 0 的记忆降权 50%（注入很多次但从没收到过反馈，可能是噪音）
  - 同一 parent 下最多召回 2 条 atomic facts（当前是 3，收紧）
  
变更位置：memorycore/storage/search.py - build_context_pack()
```

### 3. 提升记忆事实质量

#### 3.1 Ingest 阶段去噪

当前 `memory_ingest` 通过 LLM 从对话中抽取事实。问题是 LLM 有时会抽取低价值信息（打招呼、确认、重复的上下文描述）。

```
新增：ingest 后的硬过滤
  - title 或 content 长度 < 20 字符 → 丢弃
  - content 与已有 active 记忆的 vector similarity ≥ 0.88 → 跳过（已有类似实现但阈值可能太高）
  - type=episodic_memory 且不包含具体事实（无日期、无数字、无专有名词）→ 降低 importance 到 0.2
  
变更位置：memorycore/extraction.py
```

#### 3.2 Curator 全自动运行

LLM curator 不再生成 needs_review。所有发现要么自动执行，要么自动丢弃。

```
curator 的输出分类：
  - duplicate + confidence ≥ 0.65 → 自动 archive 旧的
  - contradiction + confidence ≥ 0.70 → 保留更新的，标记旧的为 contradicted
  - importance_reassessment → 直接执行 promote/downgrade
  - split_candidate → 仍然不自动执行（split 需要生成新内容，风险高）→ 但也不进 needs_review，而是写入一个 "suggestions" 表，Dashboard 上展示供用户随时处理
  - link_discovery → 直接创建 link
  
变更位置：memorycore/storage/governance.py - policy_gate()
```

#### 3.3 每次 curator 运行后自动 recalibrate + apply

```
run_curator.sh 的流程改为：
  1. Rule curator（快速规则清理）
  2. LLM curator（如果启用）
  3. recalibrate_queue(dry_run=False)
  4. apply_all_auto_approved()  ← 新增
  5. 写 cooldown 标记
  
变更位置：run_curator.sh 或 memorycore/storage/llm_curator_jobs.py
```

### 4. 简化产品页面

不需要 8 个页面。用户不想管理记忆，页面越少越好。

#### 新信息架构（4 个页面）

```
Dashboard     — 系统健康 + 最近自动变更摘要
Context Lab   — 输入 task，看召回结果，标记 helpful/not helpful
Memories      — 搜索和浏览事实库（保留现有功能）
Settings      — 阈值、服务状态、source 策略
```

**砍掉的页面：**
- ~~Governance~~ → 没有审批队列就不需要治理页面。最近的自动变更摘要放在 Dashboard。
- ~~Graph~~ → 图谱修复全自动化（link discovery 自动执行）。如果用户想看图谱，放在 Memory 详情页的关联面板。
- ~~Sources~~ → source 策略放入 Settings 的一个 tab。
- ~~Operations~~ → 维护操作（vector rebuild、backup、curator 手动触发）放入 Settings 的 Advanced tab。

#### Dashboard 简化

Dashboard 只显示 5 个数字和一个列表：

```
┌─────────────────────────────────────────────────────┐
│  Active Memories: 849    Context Hit Rate: 78%      │
│  Auto Actions (24h): 23  Rollbacks (24h): 0         │
│  Stale/Expired: 12       System: Healthy ✓          │
├─────────────────────────────────────────────────────┤
│  Recent Auto Actions                                │
│  ┌──────────────────────────────────────────────────┐│
│  │ 10:23  superseded "mcore路径" → "mcore项目路径"  ││
│  │ 10:21  archived duplicate "CPA重试策略"          ││
│  │ 09:45  downgraded importance "旧会议记录"        ││
│  │ ...                                              ││
│  └──────────────────────────────────────────────────┘│
│  [Rollback] 按钮在每条旁边                          │
└─────────────────────────────────────────────────────┘
```

用户唯一可能做的操作：看到某条自动变更不对 → 点 Rollback。

#### Context Lab

这是用户最常打开的页面，设计与上一版方案一致：

- 输入 task → 看到会被注入的记忆
- 每条记忆显示：召回来源（FTS/Vector/Entity）、分数、type
- 一键标记 helpful / not helpful
- not helpful 会立即影响后续召回（feedback_score 权重 0.10）

### 5. 安全网设计

全自动治理的风险是误操作。安全网不是审批，而是 **自动异常检测 + 可回滚**：

#### 5.1 自动熔断

```
如果在 1 小时内：
  - auto-applied 变更数 > 50 → 暂停 curator，Dashboard 显示 warning
  - rollback 次数 > 3 → 暂停 curator，提高 confidence 门槛 0.1
  - active memories 数量下降 > 10% → 暂停 curator，Dashboard 显示 alert
  
变更位置：新增 memorycore/storage/circuit_breaker.py
```

#### 5.2 每次 mutation 保留 snapshot

当前已实现 rollback snapshot。保持不变，确保所有 auto-applied 变更都有 snapshot。

#### 5.3 Dashboard 的 "Undo Last Hour" 按钮

如果用户发现系统行为异常，一键回滚最近 1 小时的所有自动变更。

## 分阶段落地

### Phase 1：Policy Gate 放开 + 清空积压（1-2 天）

改动文件：
- `memorycore/storage/governance.py`：修改 `policy_gate()` 逻辑
- `memorycore/storage/governance.py`：`create_governance_decision()` 中 auto_approved 立即 apply
- 一次性脚本清空 915 条 needs_review + 94 条 auto_approved

验收：
- needs_review 降为 0
- 新产生的 governance decision 要么 auto_approved+applied，要么 rejected
- 不再有 needs_review 状态

### Phase 2：召回质量提升（2-3 天）

改动文件：
- `memorycore/storage/search.py`：feedback_score 权重提升、低效记忆过滤
- `memorycore/storage/temporal_governance.py`：auto_supersede 阈值调整
- `memorycore/extraction.py`：ingest 阶段去噪

验收：
- feedback_score 对排序有明显影响
- 重复写入被自动 supersede
- 低价值 ingest 被过滤

### Phase 3：安全网 + Dashboard 简化（2-3 天）

改动文件：
- 新增 `memorycore/storage/circuit_breaker.py`
- UI Dashboard 重构：只显示健康状态和最近自动变更
- UI 砍掉 Governance 页面作为独立入口

验收：
- 熔断逻辑能在异常时暂停 curator
- Dashboard 10 秒内能判断系统是否正常
- Rollback 按钮可用

### Phase 4：Context Lab MVP（3-4 天）

改动文件：
- 新增 `/context-lab` 页面
- 调用 `memory_context` 展示结果
- helpful/not helpful 反馈写入 feedback

验收：
- 用户能看到任意 task 的召回结果
- 反馈能影响后续召回

## 成功指标

| 指标 | 当前值 | 目标值 |
|---|---|---|
| needs_review 积压 | 915 | 0（永久） |
| auto_approved 未执行 | 94 | 0（永久） |
| 用户需要手动审批 | 每天 N 条 | 0 |
| feedback 对召回的影响力 | 0.02 权重 | 0.10 权重 |
| Context Lab 可用 | 否 | 是 |
| 异常自动熔断 | 否 | 是 |
| 一键回滚最近变更 | 否 | 是 |

## 与上一版方案的关系

上一版方案（2026-06-24）的方向、信息架构分析、后端能力映射表仍然有效。本方案在以下方面做出根本性调整：

1. **取消 needs_review**：上一版仍保留"少量人工审查"，本方案消灭审批队列。
2. **简化页面**：从 8 个页面砍到 4 个。
3. **安全网从审批变为熔断+回滚**：不需要人类预防错误，而是系统自动检测异常并回滚。
4. **优先级调整**：Phase 1 从 Context Lab 变为 Policy Gate 放开——先把系统跑起来不堆积，再做可视化。
5. **召回质量 > 治理流程**：把更多精力放在 feedback 闭环和 ingest 质量上，而不是治理页面的交互设计。
