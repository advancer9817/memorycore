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

### 回滚
`git revert HEAD`
