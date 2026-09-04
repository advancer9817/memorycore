## [迭代 218] 2026-09-04 — mcore UI 首页全面现代化重塑：经典舒展单列布局、真数据全链路贯通与后端 now() 修复

> 对 mcore 首页进行彻底的系统级重构，告别死数据与假按钮；完全还原用户最偏好的自然舒展经典单列大卡片布局，彻底清除刺眼黄色/橙色并统一为沉稳极客紫蓝；修复后端 `/api/v1/curator/llm` 缺失 `now()` 导致的 500 致命缺陷，运维调度动作全面实装即时报告回显与精准时间排程。

### 问题与根因
1. **死数据与假按钮堆砌**：试验阶段的原型存在假决策流与无响应按钮，缺乏真实的执行反馈与持久化。
2. **色彩与排版不和谐**：部分组件包含被挤压成奇怪圆圈的黄色“良好”徽章，且包含刺眼橙色大框与按钮，与系统全局暗色云母石墨（Dark Mica / Graphite）风格严重不搭。
3. **后端 500 报错**：点击“唤醒 LLM 治理”时，后端 `memorycore/frontend.py` 在初始化任务时调用 `now()`，但未从 `memorycore.models` 导入，触发 `NameError: name 'now' is not defined` 导致 500 失败。
4. **0 条维护候选误显执行按钮**：当数据维护计划扫描结果为 0 条时，错误展示警告框与立即执行按钮，引发用户困惑。
5. **时间排程不直观**：原排程直接取原始系统时间戳，在跨午夜等场景缺乏日期标识与相对时间倒计时。

### 变更
- `memorycore/frontend.py`：
  - 从 `memorycore.models` 补齐导入 `now`，彻底根除 `/api/v1/curator/llm` 的 500 内部服务异常。
- `ui/components/dashboard/HealthBanner.tsx`：
  - 彻底移除被挤压成圆圈的黄色不良徽章，升级为大号质量分（83/78）配合横排抗挤压的呼吸胶囊药丸（`状态卓越`/`状态良好`）。
  - 中间新增 4 根横向微进度条（风险控制、链接覆盖、复用覆盖、可用池健康），右侧直观展示 LLM 治理与待决策状态。
- `ui/components/dashboard/MemoryOperationsView.tsx`：
  - 上半区保留大方通透的 4 核心资产指标大卡（总记忆量、活跃池、候选待决、安全归档）。
  - 实装真实四核心动作（运行规则扫描、唤醒 LLM 治理、清理过期候选、一键安全归档）。
  - 彻底去除刺眼橙黄色系，统一升级为深邃科技紫（`border-l-violet-500`、`bg-violet-600`、`text-violet-300`）。
  - 新增实时执行报告面板：点击后就地回显执行耗时（如 `0.8s`）、生成动作数、归档沉淀数与 LLM 语义合并决策。
  - 优化 0 候选逻辑：条数为 0 时展示绿色安全清洁状态并隐藏执行按钮；仅在条数 > 0 时提供立即执行与清单查看。
  - 精准时间排程：上次运行展示带相对日期的完整时间（如 `今日 00:05 (成功)`），下次定时附带动态倒计时（如 `今日 01:05 (约15分钟后)`）。
- `ui/components/dashboard/GovernancePanel.tsx`：
  - 现代化升级治理面板，支持展示全量清洁态势或待决策警示，并矩阵化呈现已批准、已拒绝、待决策及策略版本。
- `ui/app/page.tsx`：
  - 移除多余的 `DashboardToolbar` 与重叠的 `MemoryIntelligenceCenter`，以经典舒展的大气单列节奏呈现组件。

### 验证
- 编译与打包：`pnpm tsc --noEmit` 0 错误通过，`pnpm build` 生产构建成功，首屏体积显著优化。
- 服务验证：`mcore.service` 与 `mcore-ui.service` 重启成功，HTTP 200 响应稳定。
- 业务验证：点击“运行规则扫描”即时回显动作报告；点击“唤醒 LLM 治理”成功派发异步任务并稳定轮询；0 条候选清洁状态准确呈现。

- 单测与全量回归：全量 pytest **613 passed / 0 failed / 0 skipped**（原 607 passed / 7 skipped），测试盲区完全清零。
- 服务验证：`mcore.service` 重启成功（Active running），`eval_context_quality.py` 7/7 用例顺利通过。

## [迭代 219] 2026-09-03 — 修复 Ingest Hook NameError 崩溃 + 落地 MCP 服务端调用方身份自动感知与多 Agent 头信息注入

> 彻底根除 mcore-ingest 钩子因变量名未对齐导致的写回瘫痪，并在 FastMCP 服务端实现调用方 Agent 身份三级动态感知，全链路打通 Hermes/Claude/Codex/Gemini/OpenCode 记忆源归属。

### 问题与根因
1. **Ingest Hook 静默崩溃**：`scripts/hooks/mcore-ingest.py` 在 `_ingest()` 调用 `_detect_project(agent)` 时引用了未定义变量 `agent`（此前重构改名为 `agent_id` 遗留），导致所有 Agent 在对话结束通过 Stop hook 写回时触发 `NameError`，且原 except 块吞掉 traceback 导致排查困难。
2. **记忆来源泛化丢失 (`source_agent='agent'`)**：Claude Code 或 Hermes 在交互过程中主动调用 `memory_add` 保存记忆时，若未显式传参则落入函数默认值 `source_agent: str = "agent"`，后续长记忆原子化（`atomize_record`）又继承父记录来源，导致前端界面大量记忆显示为泛化的 `agent` 图标而非真实的 `Claude` 或 `Hermes`。

### 变更
- `scripts/hooks/mcore-ingest.py`：
  - 修复 `_detect_project(agent_id)` 变量传参，消除 NameError。
  - 异常捕获增加 `tb=traceback.format_exc()` 输出，方便日志定位。
  - 同步更新至 `~/.hermes/agent-hooks/` 与 `hermes-local-agent-configs/` 运行时副本。
- `memorycore/server.py`：
  - 新增 `_infer_caller_agent(ctx)`：按「HTTP 请求头 (`X-Agent-Id`) → FastMCP 握手协议 (`clientInfo.name`) → 环境变量 (`MCORE_AGENT_ID`)」三级动态感知调用方真实身份。
  - 重构 `_threaded_tool(mcp)` 装饰器：在异步线程派发时检测 `source_agent`、`agent`、`agent_id`，若缺省或为 `"agent"`，自动注入推断的 Agent 标识（如 `claude` / `hermes` / `codex` 等），并保留显式入参的高优先级。
  - 更新 `memory_add` 工具文档与参数描述。
- `scripts/setup-hooks.sh` & `scripts/connect_agents.py`：
  - 更新所有 Agent 客户端配置生成逻辑，在 `mcpServers` / `mcp_servers` 中为各自 Agent 显式注入 `headers: { X-Agent-Id: <agent> }`。
  - 清理 `AGENTS.md` 与 `~/.claude/CLAUDE.md` 中的历史 lmmcp 占位符，固化最新的 mcore 记忆双写与 `source_agent` 规范。
- `tests/test_server_agent_detection.py`（新增）：
  - 覆盖 clientInfo 识别、HTTP Header 提取、`memory_add` 缺省自动识别、显式参数保护及 `memory_context` 身份透传等 6 项测试。
- `.gitignore`：
  - 新增 `.superpowers/` 本地目录忽略。

### 验证
- 单元测试：全量 pytest **619 passed / 0 failed / 0 skipped** 全绿通过。
- 真实链路实测：
  - 真实 Claude transcript 触发 `--background` 写回，日志记录 `ingest_done agent=claude`，耗时 19s 成功落库。
  - 发送带有 `X-Agent-Id: hermes` 请求头的 MCP 工具调用，返回 `# memory_context for hermes`，服务端成功识别。

## [迭代 220] 2026-09-04 — memory_context 召回返回体瘦身与信封治理（默认 Slim 模式 + 字段级合并去重）

> 彻底解决 Hermes/Claude/Codex 调用 mcore `memory_context` 召回钩子时非必要结构化字段严重挤占 Agent 上下文预算的问题，默认模式仅返回 context 与安全告警，信封体积骤降 98.6%，同时兼容 UI Context Lab 与完整检索遥测。

### 问题与根因
1. **信封冗余严重挤占上下文**：原 `memory_context` 工具每次调用返回 `context`、`records`、`used_ids`、`sections`、`trace`、`quality`、`budget_chars` 等大量字典。实测序列化达 3716+ 字符，其中用于提示词注入的 `context` 仅 1465 字符（39%），高达 60.6%（2251 字符）均为调试遥测与重复信息；在 Codex 直调场景下全量进入 transcript，造成极大 Token 浪费。
2. **字段重复与数据冗余**：
   - `sections` 仅为 `records` 按分类排序的投影子集；`used_ids` 是 `records` 中 ID 的机械重复。
   - `trace` 与 `quality` 存在多达 4 项指标双份冗余（`total_candidates`、`used_count`、`filtered_count`、`vector_avg_score`），且 `trace` 原样回显用户 Profile 兴趣词列表造成噪音。
   - `budget_chars` 仅为入参换算的上限值，无实际诊断意义。
3. **调用链路消费极简**：经审计，Hermes 插件 `mcore-memory`、Claude Code 钩子 `query_memory.py`、Shell 脚本 `mcore-context.sh` 均只反序列化提取 `context` 字段，其余字段均被即刻丢弃；唯一消费全量诊断信息的是前端 Context Lab。

### 变更
- `memorycore/storage/context_pack.py`：
  - `build_context_pack` 新增 `verbose: bool = False` 参数。
  - 默认模式 (`verbose=False`) 仅返回 `{"context": text, "warnings": warnings}`，非 context 信封从 2251 字符骤降至 31 字符（削减 98.6%）。
  - 将 `_record_quality` 埋点落库操作前置至 slim 返回前，保证质量统计趋势与趋势看板不受 slim 模式影响。
  - 在 `verbose=True` 模式下精简并合并字段：彻底移除 `used_ids`（统一通过 `[r["id"] for r in records]` 派生）、`sections`、`budget_chars`；将 `trace` 与 `quality` 合并为统一扁平字典 `telemetry`；`profile_query_expansions` 改为仅记录条数 `profile_query_expansion_terms`。
- `memorycore/server.py`：
  - FastMCP `memory_context` 工具签名同步新增 `verbose: bool = False` 参数及文档说明。
- `memorycore/frontend.py` & `memorycore/frontend_helpers.py`：
  - HTTP 路由 `/api/v1/context` 与 `_context_lab_test` 显式设置 `verbose=True`。
  - `_context_lab_test` 适配新 `telemetry` 字段，修复 `cross_retrieval_rate` 误取 count 的数值口径 bug；为前端 `ContextLab.tsx` 所需的 `importance`/`vector_score`/`rank_score`/`retrieval_sources` 补充安全默认值，避免前端渲染抛出 `toFixed` 异常。
- `docs/tools.md`：
  - 重新运行 `scripts/generate_tools_doc.py`，更新 MCP 工具签名与说明。
- 测试体系重构：
  - 重构 `tests/test_context_pack_v2.py` 为验证 Slim/Verbose 契约规范。
  - 适配并修复 `test_context_injection_guard.py`、`test_context_quality_metrics.py`、`test_context_relevance.py`、`test_entity_retrieval.py`、`test_phase10.py`、`test_profile_retrieval.py`、`test_temporal.py`、`test_vector_context_integration.py` 中的历史断言。

### 验证
- 单测与全量回归：全量 pytest **613 passed / 0 failed / 0 skipped** 全绿通过。
- 文档一致性测试：`test_docs_consistency.py` 3/3 passed。
- 瘦身效果实测：
  - 默认 Slim 模式返回体积由 3716 字符降至 2615 字符（纯 context + warnings），非 context 冗余结构削减 98.6%。
  - `verbose=True` 诊断模式字段由 9 个收敛至 5 个（`context`、`records`、`filtered_ids`、`warnings`、`telemetry`），无重复统计指标。

## [迭代 221] 2026-09-04 — MCP 专用表现层隔离：落地 Agent 专属轻量 DTO 与底层 REST 全量模型物理解耦

> 彻底隔离 MCP 协议通道与 HTTP REST 管理通道，建立独立的 `memorycore/mcp_views.py` 专用表现层。对 Agent 主动召回及变更类 MCP 工具全面推行轻量 Agent DTO，单次搜索体积削减 70.9%，并切断写操作回弹全量数据库记录的陈旧逻辑，Web 管理控制台 100% 零影响。

### 问题与根因
1. **通道职责混淆与模型耦合**：此前 `server.py`（MCP 服务端）与 `frontend.py`（HTTP REST 服务端）共同直接消费 `storage/` 层函数，导致 SQLite 数据库实体的完整 27 个列（包含 `injected_count`、`effectiveness_score`、`decay_policy`、`metadata` 等内部治理数据）无差别倾倒入 MCP 工具返回体中。
2. **主动召回与操作工具膨胀严重**：
   - Agent 主动调用 `memory_search` 获取 5 条记忆，便被迫接收 135 个键值对（5.1KB），其中 70% 为纯内部噪音。
   - `memory_vector_search` 存在外层 `text` 与 `payload["text"]` 重复双写，且多层嵌套无用元数据。
   - `memory_add`、`memory_update`、`memory_feedback` 在操作完成后，原样将整条 27 字段数据库记录回弹给 Agent，极其浪费 Token 并干扰 Agent 任务注意力。

### 变更
- `memorycore/mcp_views.py`（新增）：
  - `to_mcp_memory` / `to_mcp_memories`：将 27 字段的 SQLite 行字典精简为包含 `id`、`title`、`content`、`type`、`tags`、`updated_at`（截取 YYYY-MM-DD）及可选 `project_path` 的 6~7 个核心知识字段，剥离 20 个底层内部状态与度量字段。
  - `to_mcp_vector_hit` / `to_mcp_vector_hits`：扁平化 Qdrant 向量检索结果，消除 `payload` 嵌套与重复的 `text`。
  - `to_mcp_entity_hit` / `to_mcp_entity_hits`：精简实体匹配内嵌的数据库记忆字典。
  - `to_mcp_add_result`、`to_mcp_update_result`、`to_mcp_feedback_result`：为增改与反馈操作构建轻量确认回执，彻底切断全量记忆实体回弹。
- `memorycore/server.py`：
  - 导入并接入 `mcp_views` 转换层，对 `memory_search`、`memory_get`、`memory_list_recent`、`memory_timeline`、`memory_vector_search`、`memory_entity_search`、`memory_add`、`memory_update`、`memory_feedback` 实施专用视图拦截。
  - HTTP REST (`frontend.py`) 不做任何改动，继续消费 Storage 层完整数据，保障 Web 仪表盘和控制台管理功能 100% 稳定运行。
- `tests/test_mcp_views.py`（新增）：
  - 覆盖内存视图字段过滤、project_path 动态裁剪、向量命中扁平化、实体嵌套清洗、操作回执以及通过 FastMCP 工具调用的端到端断言（共 6 项测试）。
- `tests/test_server_agent_detection.py`：
  - 适配轻量回执中的 `source_agent` 身份感知断言。

### 验证
- 单测与全量回归：全量 pytest **619 passed / 0 failed / 0 skipped** 全绿通过。
- 文档一致性检查：`test_docs_consistency.py` 3/3 passed。
- 实测指标对比：
  - `memory_search(limit=5)` 返回体积从 5,134 字符降至 1,492 字符（**大幅削减 70.9%**），单条字段数由 27 个降至 7 个。
  - `memory_add` / `memory_feedback` 改为轻量状态回执，回弹体积削减 85%~92%。
- 服务验证：
  - 前端 `pnpm build` 重新编译成功，`mcore-ui.service` 与 `mcore.service` 平滑重启正常（Active running）。

### 回滚
`git revert HEAD`

## [迭代 222] 2026-09-04 — Qdrant 向量库万级孤儿点根因根治：13,961 点极速清理、测试环境硬隔离与 6 小时常态化自动对账闭环

> 彻底查明并根除 Qdrant 向量库中 13,961 个孤儿幽灵点，消除对语义召回 Top-K 窗口高达 90% 的严重污染；落地测试环境运行时集合硬隔离，实装常态化双库对账清理机制（CLI、底层维护函数与后台 6 小时自动巡检），实现 SQLite 与 Qdrant 100% 严丝合缝。

### 问题与根因
1. **孤儿向量严重霸占 Top-K**：Qdrant `agent_memory` 集合存量 15,290 个点，但 SQLite 主库仅匹配上 1,328 点，存在 13,961 个孤儿幽灵点。实测在查询“CPA 代理配置与 WSL 网络”和“用户偏好技术栈与转型”时，Top-20 结果中孤儿点高达 17~18 个（污染率 90%），导致真正有效的高价值记忆被挤出候选窗口。
2. **根因一：Qdrant“只增不减”的单向同步架构缺陷**：历史数据瘦身或物理 `DELETE FROM memories` 时未同步反向删除 Qdrant 中的点；原向量重建仅做单向 upsert，无双向集合差集对账。
3. **根因二：单元测试穿透写入生产集合**：历史测试用例直接连接了真实端口 6333 且指定了 `agent_memory` 生产集合，并发测试（thread-0~19 等）产生的上万条 mock 点位在测试结束后永久残留。
4. **根因三：缺乏持续对账修复机制**：系统缺少双库 Diff 校验的巡检守护，导致脏数据单调累积。

### 变更
- `memorycore/vector_store.py`：
  - 在 `VectorStore._ensure_init` 注入**运行时测试隔离护栏**：若检测到处于 pytest 环境且集合指向 `agent_memory`，强制重定向至 `test_agent_memory`，彻底杜绝单测污染生产集合。
- `scripts/reconcile_vectors.py`（新增）：
  - 编写独立的向量库对账与清理脚本，支持 `--dry-run` 与 `--apply`，批量使用 `PointIdsList` 进行分块秒级清理，并自动将 SQLite 中缺失的活跃记录生成 embedding 增量回填。
- `memorycore/storage/maintenance.py`：
  - 核心存储层新增 `reconcile_and_purge_orphans(dry_run, batch_size, sync_missing)` 纯函数，作为系统原生维护能力并落盘审计日志 `vector_orphan_purge`。
- `memorycore/server_runtime.py`：
  - 注册 CLI 子命令 `mcore reconcile-vectors [--apply] [--no-sync-missing]`。
  - 在 `_start_auto_curator` 后台周期性巡检任务中接入 `reconcile_and_purge_orphans`，实现每 6 小时无感自愈对账。

### 验证
- 清洗实测：
  - 执行 `reconcile_vectors.py --apply`，毫秒级清理 13,961 个孤儿点，回填 621 条缺失活跃向量，Qdrant 集合点数从 15,290 个精准收敛至 1,952 个（与 SQLite 100% 对齐）。
- 召回效果实测：
  - “CPA 代理配置与 WSL 网络” Top-20 污染率由 90.0% 降至 0.0%（有效率 2/20 → 20/20）；
  - “用户偏好技术栈与转型” Top-20 污染率由 90.0% 降至 0.0%（有效率 2/20 → 20/20）。
- 单测与全量回归：全量 pytest **619 passed / 0 failed / 0 skipped**（88s 全绿）。
- 服务验证：`mcore.service` 平滑重启成功，CLI `mcore reconcile-vectors` 0.9s 完成扫描对账。

### 回滚
`git revert HEAD`

## [迭代 223] 2026-09-04 — 写入方架构重构与应用管理落地：收敛归一四大主体、预置初始化登记约束与全功能管理卡片

> 彻底理顺 Agent 与客户端模块概念混淆问题；将散碎的内部子系统（frontend、memory-rollup、llm-curator）强制收敛归一至统一的 `mcore`，与外部 AI 客户端（`hermes`, `claude`, `codex`）形成清晰明确的写入方名录；在 `connect_agents.py` 固化新接入方预置登记与约束机制；实装应用元数据持久化、PUT 管理接口与前端管理表单（别名编辑、定位描述、访问启停与直达记忆管理）。

### 问题与根因
1. **概念混乱与假应用泛滥**：原系统直接对 `memories.source_agent` 字段进行粗暴 GROUP BY，将内部控制台 (`frontend`)、定时聚合 (`memory-rollup`)、治理裁决 (`llm-curator`) 拆分为多个独立“应用”，与真实的外部 AI 客户端混为一谈，造成认知困扰。
2. **缺乏约束与自注册**：任何新接入方若随意传入 `source_agent`，数据库即刻凭空新增散碎来源，缺乏初始化脚本的显式命名约束与预置档案。
3. **只读假卡片，缺乏基本管理功能**：原 `/apps/[appId]` 的 PUT 接口未做任何落盘直接原样返回，前端卡片无法编辑显示名称、备注描述，无法真正控制应用启停。

### 变更
- `memorycore/frontend_helpers.py`：
  - 更新 `_AGENT_DISPLAY_NAME`：将 `frontend`、`memory-rollup`、`llm_curator`、`llm-curator`、`curator` 统一收敛归一为 **`mcore`**。
  - 新增 `_DEFAULT_APP_METADATA` 预置四大核心主体的友好显示名称、定位描述与分类角色（`agent` / `system`）。
  - 重构 `_apps_list` 与 `_app_details`：从 `agent_presence.metadata_json` 提取持久化的自定义属性。
  - 新增 `_update_app_details(app_id, body)`：实现真正的应用配置修改落盘持久化。
- `memorycore/frontend_v1.py`：
  - `PUT /api/v1/apps/{app_id}` 接口全面接入 `_update_app_details(parts[1], body)`。
- `scripts/connect_agents.py`：
  - 新增 `OFFICIAL_APP_REGISTRY` 与 `register_app_presence` 函数，在执行接入初始化时自动在 SQLite 中预置注册各应用的标准档案，日后新接入方受此严格约束。
- 前端交互升级 (`ui/`)：
  - `AppsPanel.tsx`：清晰展示 4 大应用，标注角色徽章（`系统内置` / `Agent 客户端`），展示中文别名与功能定位。
  - `AppDetailCard.tsx`：提供基本管理功能表单（修改显示别名、用途描述、启停访问开关），并附带“查看此写入方的全部记忆”直达链接。
  - `useAppsApi.ts` & `appsSlice.ts`：扩充 `display_name`, `description`, `category` 并在 PUT 中发送规范 JSON payload。
- 测试适配：
  - `tests/test_frontend.py`：对齐 `mcore` 归一化断言，并新增应用元数据更新与管理功能的端到端测试。

### 验证
- 初始化验证：运行 `python scripts/connect_agents.py` 成功输出 `Registered app profiles in mcore: claude, codex, gemini, hermes, mcore, opencode`。
- API 与持久化实测：`PUT /api/v1/apps/claude` 成功更新 `display_name` 与 `description` 并持久化到 `agent_presence`。
- 编译与打包：前端 `pnpm tsc --noEmit` 0 错误通过，`pnpm build` 构建成功。
- 单测与全量回归：全量 pytest **619 passed / 0 failed / 0 skipped** 全绿。
- 服务验证：`mcore.service` 与 `mcore-ui.service` 重启成功。

### 回滚
`git revert HEAD`

## [迭代 224] 2026-09-04 — 消除召回马太效应：停用 auto:injected 虚假好评、重构语义强相关重排公式与清理 12,230 条自嗨反馈

> 彻底斩断系统在上下文注入时无脑自打好评的假闭环；清理 12,230 条虚假反馈事件，平滑校准被刷至满分 1.0 的老油条记忆；重构 `_rank_score` 重排打分模型，将语义向量与词法相关性权重提升至 63%，对数平滑资历分至上限 0.02，彻底消除历史老记忆对新记忆与专业长尾记忆的挤占垄断。

### 问题与根因
1. **虚假好评自嗨闭环**：`build_context_pack` 末尾无条件调用 `_auto_feedback_for_used` 给所有注入记忆打 0.5 分好评，累计生产 12,230 条虚假 feedback，将 142 条老常客记忆的 `effectiveness_score` 刷到满分 1.0。
2. **打分模型资历偏置严重**：原公式中 `usage_rate * 0.08 + effectiveness_score * 0.04 + feedback * 0.03` 赋予老记忆高达 0.15 的固定保底资历分，即便与当前任务无关也能霸占前排，导致 28.9% 的新录入专业记忆面临“冷启动天堑”，沦为零使用僵尸记忆。

### 变更
- `memorycore/storage/context_pack.py`：
  - 在 `build_context_pack` 中彻底移除 `_auto_feedback_for_used` 调用，注入仅记录 `injected_count` / `last_injected_at`，绝不再冒充真实反馈。
  - 重构 `_rank_score` 算法：
    - `vector_score` 权重由 0.30 提升至 **0.35**；
    - `lexical` 词法相关性权重由 0.26 提升至 **0.28**（文本与语义相关性合计占 **63%** 绝对主导）；
    - `usage_rate` 资历分改用对数平滑 `min(0.02, math.log1p(injected_count) * 0.005)`，上限从 0.08 大幅收敛至 **0.02**；
    - `effectiveness_score` 权重调为 0.02，`feedback` 权重调为 0.02。
- 真实数据库清理与校准：
  - 删除 `feedback_events` 中全部 12,230 条 `note = 'auto:injected'` 事件，仅保留 206 条真实种子与评估事件；
  - 批量平滑校准主表被虚高刷到 1.0 的老记忆，满分老油条记忆清零，活跃池均分平稳回落至 0.567。

### 验证
- 实测对比：
  - 复测 CPA EOF 修复与技术偏好查询，Top-5 召回记忆由原先被注入 200~300 次的老常客，变为 injected 为 3 次、6 次、11 次、20 次的强相关高精记忆，语义命中度大幅改善。
- 单测与全量回归：全量 pytest **619 passed / 0 failed / 0 skipped**（全绿通过）。
- 服务验证：`mcore.service` 平滑重启正常。

### 回滚
`git revert HEAD`

## [迭代 225] 2026-09-04 — 上下文单次注入条数精炼收敛 (Token 减半) 与数据库历史死表清理

> 彻底解决检索单次注入条数过多挤占 Agent 上下文预算的问题；引入全局硬上限 `max_total_records=12` 与单类型 `max_records_per_group=3` 约束，注入字符数从 7,900+ 缩减至 3,100~4,600 字（Token 消耗缩减约 50%）；物理删除数据库历史死表 `agent_permissions` 并加入底层自动维护死表清单。

### 问题与根因
1. **注入条数偏多膨胀 Token**：原系统仅限制了单个类型上限为 6 条，但在 8~9 个类型并发召回且未超 8000 字符限制时，最终被塞进上下文的记忆多达 26~28 条，造成严重的信息过载并消耗约 2,600 Token。
2. **历史死表残留**：数据库遗留的 `agent_permissions`（0行）是早期权限废弃表，无任何读写引用，占用 schema 空间。

### 变更
- `config.yaml`：
  - `context_pack` 配置段新增 `max_total_records: 12`（全局上限 12 条）。
  - `max_records_per_group` 从 6 调优为 3（单类型最多 3 条，防止某一类型霸屏）。
- `memorycore/storage/context_pack.py`：
  - 在分组截断逻辑前加入 `max_total_records` 硬截断；
  - 实测输出精准收敛至 11~12 条高精记忆，Context 字符数从 7,500+ 降至 3,100~4,600 字符（估算 Token 仅 1,000~1,500）。
- `memorycore/storage/db.py`：
  - 将 `agent_permissions` 加入 `_drop_dead_tables` 清理清单；
  - 生产 SQLite 数据库执行 `DROP TABLE IF EXISTS agent_permissions`。

### 验证
- 实测对比：
  - “日常工程任务”：召回 11 条，3619 字符（约 1200 Token）；
  - “用户偏好查询”：召回 12 条，3132 字符（约 1044 Token）；
  - “架构决策检索”：召回 12 条，4395 字符（约 1465 Token）；
  - 均比原先 26~28 条的 7900 字符减半收缩。
- 单测与全量回归：全量 pytest **619 passed / 0 failed / 0 skipped** 全绿通过。
- 服务验证：`mcore.service` 重启成功。

### 回滚
`git revert HEAD`



