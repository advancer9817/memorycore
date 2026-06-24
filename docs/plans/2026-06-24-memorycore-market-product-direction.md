# MemoryCore 产品重设计方案：本地优先 Agent Memory OS

Date: 2026-06-24
Last revised: 2026-06-24

## 设计结论

MemoryCore 不应继续被设计成“记忆管理后台”或“治理待办列表”。它应该被重设计为一个本地优先的 Agent Memory OS：系统在后台自动采集、整理、合并、过期、建链和注入记忆；用户只在系统不确定、风险较高、或需要校正偏好的地方介入。

这与用户原始要求一致：

- 低心智负担：默认自动运行，不要求用户每天手动清队列。
- 自治理：LLM curator、rule curator、temporal governance、rollup、atomization 和 graph repair 应形成闭环。
- 多 Agent 共享：Hermes、Codex、Claude Code、Gemini、opencode 等都通过同一套记忆中枢读写。
- 本地优先：个人使用场景优先，不引入复杂企业 RBAC；权限和策略以 source/policy 为粒度轻量控制。
- 可解释：用户必须能看到“为什么这条记忆会被召回、注入、归档或覆盖”。
- 可回滚：自动治理可以激进，但每个 mutation 必须可审计、可解释、可撤销。

因此，新的产品设计不是增加更多页面，而是把现有能力组织成一条清晰闭环：

```text
Capture -> Normalize -> Retrieve -> Explain -> Feedback -> Govern -> Repair -> Monitor
```

## 当前文档的问题

上一版文档已经指出 MemoryCore 应定位为 local-first Agent Memory OS，也列出了 Context Lab、治理队列压缩、Graph Quality、Operations Console、Source Policy 五个方向。问题是它仍停留在市场扫描和原则层：

- 没有把“低心智负担”翻译成具体默认行为。
- 没有定义用户每天打开 mcore 应该先看什么、做什么、不需要做什么。
- 没有区分后台自动流程和人工介入流程。
- 没有给出前端导航与页面职责边界。
- 没有把当前已有 API/后端能力映射到产品模块。
- 没有定义可量化验收指标。

本重设计文档补齐这些缺口。

## 产品北极星

MemoryCore 的北极星不是“记住更多”，而是：

> 在用户不需要管理记忆的前提下，让多个 Agent 始终拿到少量、准确、可解释、最新、可回滚的上下文。

判断方向是否正确，看四个问题：

1. 用户是否仍需要手动阅读大批治理项？
2. Agent 是否仍会拿到过期、矛盾或弱相关记忆？
3. 用户是否能解释一条记忆为什么被注入？
4. 自动治理出错后是否能快速定位并回滚？

如果答案不是“否、否、是、是”，产品设计就还没完成。

## 核心用户路径

### 1. 默认后台自治理路径

这是主路径，用户不应该频繁介入。

1. Agent 对话结束后写回 transcript。
2. `memory_ingest` 抽取候选事实，写入 SQLite 并同步 Qdrant。
3. Dedup/temporal governance 判断是否应新增、链接、supersede 或进入 review。
4. Atomization 把长叙述拆成 atomic facts。
5. LLM curator 周期性执行 duplicate、contradiction、importance、split、link discovery。
6. Policy gate 自动应用低风险高置信 mutation。
7. 高风险、近期、高重要性、正反馈、跨 scope/project 的 mutation 进入人工 review。
8. Dashboard 只展示健康状态、自动处理量、待介入量和异常。

设计原则：自动处理应该是默认，人工 review 是例外。

### 2. 任务前记忆解释路径

这是当前最大产品缺口，也是一阶段最高优先级。

用户打开 Context Lab，输入一个任务，例如：

```text
帮我检查 mcore 的治理队列为什么还多。
```

系统展示：

- 将注入哪些记忆。
- 每条记忆来自 FTS、Vector、Entity、Temporal 还是交叉召回。
- 相关分、向量分、recency 权重、importance、feedback、scope/project 匹配情况。
- 哪些候选被过滤，以及原因。
- token budget 占用。
- 该记忆最近是否被注入、是否被反馈无效、是否有 contradiction/superseded warning。

用户可以直接标记：

- helpful
- not helpful
- stale
- wrong
- private
- over-injected
- should expire
- should link to another memory

这些反馈进入 governance/curator，不只是 UI 标记。

### 3. 少量人工治理路径

Governance 页面不再是“待办收件箱”，而是“异常处置台”。

默认展示：

- 系统已自动处理了多少。
- 有多少被 policy 拦截。
- 为什么拦截。
- 哪些需要用户确认。
- 是否有 degraded warning。

用户只处理三类事项：

- 高风险：contradiction、delete、merge、跨 scope/project、近期记忆变更。
- 高价值：user_profile、decision、project_memory、高 importance、正反馈记忆。
- 低置信：LLM 判断不稳定、证据不足、相似度边界模糊。

界面不应自动打开详情侧栏；进入页面时先显示队列概览和风险分布，详情由用户主动打开。

### 4. 图谱修复路径

Graph 页面不应只是可视化。它应该承担“关系质量修复”职责。

核心任务：

- 找出孤立 active memory。
- 区分 atomization 机械链接和真实语义链接。
- 展示 related_to/supports/part_of/supersedes/contradicts 的密度和质量。
- 让 LLM link discovery 生成候选，由 policy gate 自动应用低风险链接。
- 对矛盾关系、陈旧链路、断裂 lineage 给出修复建议。

Graph 的目标不是漂亮，而是让记忆网络更可用。

### 5. Source 策略路径

Apps/source_agent 页面要从“来源列表”升级为“来源策略控制台”。

每个 source_agent 应显示：

- 写入量、注入量、命中率、无效反馈率。
- 最近写入的记忆类型。
- 产生的 governance 决策数量。
- 是否经常产生 stale/contradicted/duplicate。
- capture enabled。
- injection enabled。
- retention/expiry policy。
- 默认 scope/project。
- 默认 memory type/confidence。
- 是否允许写 user_profile/decision 等高价值类型。

对个人使用场景，不需要复杂 RBAC；需要的是清晰的 source 级开关和默认策略。

## 新信息架构

### 顶层导航

```text
Dashboard
Context Lab
Memories
Governance
Graph
Sources
Operations
Settings
```

### Dashboard：健康总览，不放复杂操作

Dashboard 只回答四个问题：

- 系统现在健康吗？
- 后台治理是否在自动工作？
- 有多少事项真的需要我看？
- 最近上下文召回质量是否变好？

推荐区块：

- System Health：后端、UI、Qdrant、Ollama/Embedding、curator job 状态。
- Autonomy Score：自动应用率、review 拦截率、rollback/revival 率、队列年龄。
- Context Quality：最近 context pack hit rate、not-helpful feedback、vector fallback 次数。
- Governance Exceptions：只显示真正需要处理的高风险项数量。
- Graph Quality：孤立记忆数、semantic link density、atomization link density。
- Source Noise：最容易产生重复/矛盾/低价值记忆的 source。

Dashboard 不承担 tuning、批量治理、详细审查和图谱编辑。

### Context Lab：最高优先级的新页面

页面结构：

- 顶部任务输入框：支持 task、agent、scope、project_path、retrieval_mode、token_budget。
- 左侧结果列表：按注入顺序展示 memory cards/table rows。
- 右侧解释面板：显示选中记忆的召回来源、分数、警告、历史注入和关联治理。
- 底部候选区：显示被过滤或聚类折叠的记录。
- 操作栏：feedback、mark stale/private/wrong、create governance decision、open memory。

必须展示的后端字段：

- `records[*]._retrieval_sources`
- `records[*]._vector_score`
- `trace.vector_avg_score`
- `trace.cross_retrieval_count`
- `trace.vector_only_count`
- `trace.fts_only_count`
- `trace.clustered_count`
- `quality.hit_rate`
- `quality.estimated_tokens`
- `warnings`
- `filtered_ids`

这页是“为什么 Agent 会这样想”的解释器。

### Memories：事实库浏览与单条纠错

Memories 继续保留表格和详情页，但职责收窄：

- 搜索、筛选、查看事实。
- 编辑 content/title/type/scope/project/status/validity。
- 查看 provenance、lineage、links、audit、feedback。
- 单条 memory 的 archive/stale/promote/rollback。

Memories 不负责治理队列，也不负责 context pack 调试。

### Governance：异常处置台

Governance 的默认视图应从“全部队列”改成“需要我介入的原因”。

主要分区：

- Needs Decision：真正需要用户判断的项目。
- Policy Blocked：被当前策略阻止自动执行的项目。
- Auto Approved Pending Apply：可应用但尚未执行。
- Recently Applied：最近自动变更，可回滚。
- Recalibration：队列重分类和策略校准。

批量操作规则：

- 默认只作用于当前筛选/当前页。
- 必须显示 applied/skipped/already_applied。
- policy-blocked 不应让整批失败。
- destructive action 必须显示 reason 和 rollback availability。

### Graph：关系修复台

Graph 页面要增加三种工作模式：

- Explore：查看图谱。
- Repair：处理孤立、弱链接、矛盾、断裂 lineage。
- Explain：从某条记忆出发解释它为什么影响 context pack。

核心指标：

- semantic link density = related_to/supports/contradicts/supersedes 等非 atomization 链接占比。
- orphan active memories。
- contradiction components。
- supersession chain depth。
- stale but highly connected memories。

### Sources：来源策略控制台

由现有 Apps 页面演进而来，名称建议从 Apps 改成 Sources，或保留 Apps 但页面内使用 Source Policy。

必须修复并保持：

- 未知 source_agent 不能被 `_KNOWN_AGENTS` 白名单丢弃。
- source id、detail route、memories route 必须稳定一致。
- 已知 agent 只做显示名聚合，不改变底层可追溯性。

Source 详情页应包含：

- Overview：写入/注入/反馈/治理指标。
- Memories：该来源写入的记忆。
- Policies：capture/injection/retention/type/confidence/scope。
- Quality：重复率、矛盾率、not-helpful 反馈、平均召回分。
- Audit：该来源触发的治理和 mutation。

### Operations：维护执行台

Operations 承接历史 `Install` / `MemoryOperationsPanel` 的真实职责。

应包含：

- Vector：status/search/audit/rebuild。
- Curator：rule curator、LLM curator、job history、cooldown、diagnostics。
- Rollup/Atomization：dry-run、apply、parent-child 检查。
- Backup/Export/Import：SQLite backup、memory-sync、JSON 导入导出。
- Agents：presence、capability、inbox、handoff。
- System：服务状态、端口、版本、最近错误。

Operations 是执行维护任务的地方，不是 Dashboard 首屏。

### Settings：偏好与阈值

Settings 负责：

- temporal governance 阈值。
- context pack 权重与 retrieval mode 默认值。
- LLM curator style、temperature、max pairs。
- source policy 默认模板。
- UI language。
- 本地服务地址与 API key 状态。

## 后端能力映射

当前已有能力可以支撑大部分重设计，不需要大改架构。

| 产品模块 | 已有能力 | 需要补齐 |
|---|---|---|
| Context Lab | `memory_context`、trace、quality、warnings、feedback | UI 页面、反馈动作映射、被过滤候选解释 |
| Governance | decisions、policy gate、apply/reject/rollback、metrics、recalibrate | 更清晰的原因分组、自动队列压缩视图 |
| Graph | memory links、lineage、warnings、LLM link discovery | semantic link density、repair workflow |
| Sources | source_agent、Apps API、agent presence/capability | source policy 表/配置、质量指标 |
| Operations | vector audit/rebuild、backup/export/import、curator jobs | 运维入口整合、job history 可视化 |
| Dashboard | stats、metrics、context quality events | autonomy score、异常优先摘要 |

## 自动治理策略

### 默认自动处理

以下类型应尽可能自动处理：

- 低 importance、低 feedback、非 precious 的 duplicate archive。
- 明确 stale 的 importance downgrade。
- 同 scope/project/type 下高置信 supersession。
- 孤立低风险 semantic links。
- 空结果或低价值 LLM finding 的 auto-skip。

### 默认人工审查

以下类型必须进入 review：

- user_profile、decision、project_memory。
- importance 高或 feedback_score > 0。
- 近期创建/更新的记忆。
- 跨 scope/project 的 merge、archive、supersede。
- delete、merge、mark_contradicted 等破坏性动作。
- LLM confidence 边界值或证据不足。

### 激进但可回滚

用户偏好提高 LLM curator 效率和治理实用性，因此策略应允许后台更激进地产生候选和自动处理低风险项。但底线是：

- LLM 不直接写库。
- 所有 mutation 通过 policy gate。
- 所有 mutation 写 audit。
- 自动变更有 rollback snapshot。
- UI 能解释为什么自动执行或为什么被拦截。

## 视觉与交互设计

MemoryCore 是个人本地运维工具，不应做成营销页、卡片墙或轻量笔记应用。

视觉方向：

- 深色 graphite / mica operations console。
- 信息密度高，但分区清晰。
- 表格优先，卡片只用于摘要、详情、重复项和 modal。
- cyan 表示系统/向量/连接。
- amber 表示风险/时间/审查。
- emerald 表示健康/已应用/稳定。
- violet 仅表示 LLM/intelligence，不作为全局主色。

交互规则：

- 进入 Governance 不自动打开详情侧栏。
- 批量操作默认 scoped，不做全库无边界 apply。
- 详情面板只在用户主动选择对象后打开。
- destructive action 必须有明确 reason、影响范围和 rollback 状态。
- Dashboard 首屏只做摘要和路由，不塞满调参控件。

## 分阶段落地计划

### Phase 1：Context Lab MVP

目标：先解决最大产品缺口，让用户能解释“mcore 会记起什么”。

交付：

- 新增 `/context-lab` 页面。
- 支持输入 task/agent/scope/project_path/retrieval_mode/token_budget。
- 调用现有 `memory_context`。
- 展示 records、trace、quality、warnings、filtered_ids。
- 支持 helpful/not helpful/stale/wrong/private/expired 反馈。
- 可跳转 memory detail 和 governance decision。

验收：

- 用户能用 UI 复现一次 MCP `memory_context` 结果。
- 每条结果能看到召回来源和分数。
- not helpful 能写入 feedback 并影响后续质量统计。

### Phase 2：Dashboard 重构为自治理健康页

目标：让 Dashboard 从工具集合变成系统健康首页。

交付：

- Autonomy Score。
- Context Quality。
- Governance Exceptions。
- Graph Quality。
- Source Noise。
- System Health。

验收：

- 首页不再承载复杂 curator tuning。
- 用户一眼知道是否需要介入。
- 治理异常可以跳转到 Governance 对应筛选。

### Phase 3：Governance 异常处置重构

目标：把治理队列从“待办堆”改成“风险解释和少量人工决策”。

交付：

- 按 needs decision / policy blocked / pending apply / recently applied 分区。
- 批量操作显示 applied/skipped/already_applied。
- Recalibration 成为显式工具。
- rollback 可见性增强。

验收：

- needs_review 长期保持低位。
- policy-blocked 不导致整批中止。
- 用户能理解每个 review 项为什么没有自动执行。

### Phase 4：Sources 策略控制台

目标：让 source_agent 成为治理边界。

交付：

- Apps/Sources 页面展示未知 source_agent。
- Source detail 增加 quality、policy、audit。
- 增加 per-source capture/injection/retention/type/confidence/scope 策略。

验收：

- 任意 source_agent 都有稳定路由。
- 可关闭某来源注入而不停止写入。
- 可识别高噪音 source。

### Phase 5：Graph Repair

目标：让图谱页成为修复记忆关系的工作台。

交付：

- orphan active memories。
- semantic vs atomization link density。
- link discovery candidates。
- contradiction clusters。
- lineage chain inspector。

验收：

- related_to/supports 等真实语义链接比例上升。
- 孤立 active memory 数量下降。
- Graph 页面能直接发起低风险建链治理。

### Phase 6：Operations 整合

目标：把维护能力从散落入口合并为运维控制台。

交付：

- Vector operations。
- Curator jobs。
- Rollup/atomization。
- Backup/export/import。
- Agent inbox/handoff/capabilities。
- Service status。

验收：

- 历史 `MemoryOperationsPanel` 职责完整迁入 Operations。
- Dashboard 不再承担运维执行。
- 关键维护动作都有 dry-run/结果摘要/错误展示。

## 成功指标

### 自治理指标

- `needs_review` 长期低于 active memories 的 10%，或低于 100 条。
- auto-applied / total actionable decisions > 80%。
- rollback_rate 保持可观测；不是永远 0，而是能反映真实误判。
- degraded_warning 能在队列过大、队列过老、rollback 异常时触发。

### 召回质量指标

- Context Lab 中用户能解释每条注入结果。
- not-helpful feedback 下降。
- vector_fallback 次数可见且可处理。
- cross retrieval 命中率提升。
- 被聚类折叠的重复记忆不再挤占 token budget。

### 图谱质量指标

- semantic link density 上升。
- orphan active memories 下降。
- contradiction clusters 可见且可处理。
- supersession lineage 可追溯。

### 来源质量指标

- 每个 source_agent 都有质量画像。
- 高噪音 source 可被限流、禁注入或降低默认 confidence。
- capture 和 injection 可分别控制。

### 用户体验指标

- 用户打开 Dashboard 后 10 秒内知道是否需要介入。
- 用户能在 Context Lab 中解释任意一次注入。
- Governance 中人工处理项少而明确。
- 出错后能从 audit/rollback 找回。

## 非目标

- 不做移动端优先设计。
- 不引入企业级 RBAC 作为当前阶段重点。
- 不把 MemoryCore 变成普通笔记软件。
- 不让 LLM 绕过 policy gate 直接写数据库。
- 不追求装饰性图谱效果，优先关系质量和修复效率。
- 不把 Dashboard 设计成营销首页或卡片展示页。

## 当前优先级

1. Context Lab MVP。
2. Dashboard 自治理健康页。
3. Governance 异常处置重构。
4. Sources 策略控制台。
5. Graph Repair。
6. Operations 整合。

如果只能先做一个功能，选择 Context Lab。因为它连接召回解释、用户反馈、治理决策和质量指标，是 MemoryCore 从“后台记忆系统”升级为“可理解的 Agent Memory OS”的关键入口。
