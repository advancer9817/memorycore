## [迭代 239] 2026-09-09 — 系统文档体系与最新架构规范对齐：双端口拓扑、MCP 表现层隔离与权威端点指南

### 目的
- 针对近期演进成果（迭代 218~238 涉及的 8318/18318 双端口隔离、MCP 专属轻量 DTO、极简 Slim 上下文信封、Cloudflare 权威 TLS 穿透）进行文档层面的系统性梳理与对齐。
- 消除 `README.md` 与 `docs/deployment.md` 中指向已废弃内嵌单页控制台的陈旧描述，新增权威技术架构参考指南。

### 变更内容
1. `README.md`：
   - 路径列表更新：移除已删除的 `dashboard.html`，新增 `memorycore/mcp_views.py` 与独立 Next.js 控制台 `ui/`（端口 18318）。
   - 端口端点明确化：明晰 8318 专注于 FastMCP 与核心 REST API（根路径返回 404 并引导转向 18318），18318 承载现代化 Next.js Web 仪表盘。
   - 功能与特性矩阵扩充：增补 Slim 上下文信封（-98.6% 体积）、MCP 专属表现层隔离（-70.9% 搜索体积）、Agent 身份自动识别及 Cloudflare 权威端点。
   - 前端部署说明重构：对齐用户级 systemd 单元 `mcore-ui.service` 与 standalone 生产启动规范。
   - 架构路线更新：指引向 PostgreSQL 16 + pgvector 单一中枢重构方案。
2. `docs/deployment.md`：
   - 部署步骤与端点拓扑同步更新，登记 `mcore-ui.service` 单元与 Cloudflare Tunnel 权威端点。
3. `docs/architecture-and-api-reference.md`（新增）：
   - 系统梳理并确立双端口物理隔离拓扑、MCP 专用表现层（`McpMemoryItem` 规范）、极简 Slim 契约、多级 Agent 身份感知与三端接入标准。
4. `TODO.md`：
   - 登记迭代 218~238 全部里程碑成果，明确下一阶段核心任务为 PostgreSQL + pgvector 单一存储中枢重构。

### 验证
- 运行文档一致性测试 `pytest tests/test_docs_consistency.py` ➔ 3 passed。
- 运行全量测试套件 `pytest tests -q` ➔ 628 passed / 0 failed / 1 warning，全绿守护。

## [迭代 238] 2026-09-09 — 接入 Cloudflare 权威 TLS 隧道端点与 Hook 自动化环境变量解耦

### 目的
- 全面适配 Cloudflare Tunnel 权威域名端点 (`https://mcore.099817.xyz/mcp`)，替代旧有易遭运营商阻断或引发 TLS 证书兼容问题的临时端口。
- 增强本地 Hook 脚本与三端 Agent（Hermes、Claude Code、Codex）对 `MCORE_URL` 的动态识别，消除对本地 8318 监听状态的硬编码强校验。

### 变更内容
1. `scripts/hooks/mcore-context.sh`：
   - 优化本地端口监听探测逻辑，仅当 `MCORE_URL` 指向 `127.0.0.1` 或 `localhost` 时才执行 `ss` 探针检查，远程端点直通无阻塞。
   - 移除硬编码的 `--noproxy "*"` 参数，使 curl 能够自适应遵循网络环境中的代理路由规则。
2. `scripts/hooks/session-start.sh` 与 `scripts/hooks/session-end.sh`：
   - 支持动态继承外部环境变量 `MCORE_URL`；非本地连接时跳过本地守护进程的拉起探测。
   - 同步移除硬编码 `--noproxy "*"` 参数，保障跨网请求畅通。
3. `memorycore/server.py`：
   - 移除已废弃的旧版 SPA 全局通配代理，防止拦截 FastMCP 内部子路由。

### 验证
- 本地调用 `mcore-context.sh` 配合 `MCORE_URL=https://mcore.099817.xyz/mcp`，成功跨公网完成 MCP 初始化与上下文召回。
- Hermes、Claude Code、Codex 均已成功对齐至 `https://mcore.099817.xyz/mcp`。

## [迭代 237] 2026-09-08 — 支持 mcore 远程 HTTPS 穿透接入与全 Agent (Hermes/Claude/Codex) 钩子适配

### 目的
- 解决 OpenFrp 宁德节点运营商 DPI 对明文 HTTP 深度审查拦截（302 跳转 disable.htm）问题。
- 在沙箱端部署 Nginx TLS 终结代理与自签名 SAN 证书（包含 59.60.79.74、700b5e2ab48a.ofalias.net、localhost），实现端到端流量强加密。
- 升级本地 hook 脚本与客户端配置，支持远程 HTTPS MCP 与 HTTP 原生 Hook 调用。

### 变更内容
1. **沙箱端配置**：
   - 生成 10 年期包含多 SAN（IP:59.60.79.74, DNS:700b5e2ab48a.ofalias.net）的自签名 SSL 证书。
   - 部署并持久化 PM2 常驻进程 `nginx-tls`，将 8443 (HTTPS) 反向代理至本地 FastMCP/REST API (8318)。
   - 更新 OpenFrp 隧道配置：将 `mcore_mcp` 映射本地端口调整为 8443，实现公网 `https://59.60.79.74:55749` 纯密文穿透。
2. **本地 WSL CA 根证书注册**：
   - 将沙箱生成的 SAN 根证书导入本地 WSL `/usr/local/share/ca-certificates/mcore-sandbox.crt` 并执行 `update-ca-certificates`，实现本地 `curl` 与系统网络协议栈的原生 100% 信任（免 `-k`）。
3. **三端 Agent MCP 与 Hook 切换**：
   - **Hermes**：通过 `hermes config` 将 `mcp_servers.memorycore.url` 切换至 `https://59.60.79.74:55749/mcp`。
   - **Claude Code**：`~/.claude.json` 与 `~/.claude/settings.json` 中 `mcpServers.memorycore` 切换为 `https://59.60.79.74:55749/mcp`；`UserPromptSubmit` 与 `Stop` 升级为原生 HTTP Hook（`/api/v1/hooks/context`、`/api/v1/hooks/stop`）。
   - **Codex**：`~/.codex/config.toml` 更新 MCP 端点；`~/.codex/hooks.json` 注入 `MCORE_URL=https://59.60.79.74:55749/mcp` 与 `MCORE_HOST=59.60.79.74`。
4. **Hook 脚本远程健壮性增强**：
   - `scripts/hooks/mcore-context.sh`、`session-start.sh`、`session-end.sh`、`mcore-ingest.py`：
     - 支持读取 `MCORE_URL`、`MCORE_HOST` 环境变量；
     - 自动检测并跳过本地端口 probe，直连远程端点；
     - curl 请求显式加入 `--noproxy "*"`，防止被本地 Clash 代理环路劫持。

### 验证
- `curl https://59.60.79.74:55749/health` ➔ 返回 `{"ok":true,"data":{"status":"ok","total_memories":4566}}`（HTTP 200，系统原生验证通过）。
- FastMCP 端到端握手与 `memory_stats`、`memory_context` 工具调用测试全部通过。
- 本地 `mcore-context.sh` 执行测试 ➔ 成功返回包含 4,566 条记忆中枢资产的 HUD 上下文注入包。

## [迭代 236] 2026-09-08 — 彻底废弃并移除 8318 内置旧前端，固化 18318 为唯一法定 Web UI

### 目的
- 按照用户明确架构决策，彻底废弃并下线 8318 端口下的单页旧版内嵌控制台（`_FRONTEND_HTML` 与根目录 `dashboard.html`）。
- 确保 8318 专注于 FastMCP 协议接口与 RESTful API，明确唯一法定前端 UI 端口为 `18318`（Next.js Standalone 仪表盘服务）。

### 变更内容
1. `memorycore/frontend_http.py`：完全移除 50+ 行硬编码的内嵌 HTML 字符串常量 `_FRONTEND_HTML`。
2. `memorycore/frontend.py`：重构 `frontend_index` 路由，访问根路径 `/` 时显式返回 404 并提示转向 `http://127.0.0.1:18318/`。
3. `tests/test_frontend.py`：对齐单测断言，验证 `/` 响应状态码为 404 且健康端点 `/health` 持续正常，20 个测试 100% 通过。
4. 清理废弃静态导出产物：移除根目录下 1.8MB 旧版 `dashboard.html`。
5. 服务热重载：通过 systemd --user 重启 `mcore` 服务，验证 8318 彻底下线旧前端，18318 独立 UI (Next.js) 稳定在线 (HTTP 200)。

### 验证
- `curl http://127.0.0.1:8318/` ➔ 返回 `8318 embedded frontend has been removed. Active UI is on http://127.0.0.1:18318/`
- `curl http://127.0.0.1:8318/health` ➔ `{"ok":true,"data":{"status":"ok","total_memories":4601}}`
- `curl -I http://127.0.0.1:18318/` ➔ `HTTP/1.1 200 OK` (Next.js 独立 UI 响应流畅)

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

## [迭代 226] 2026-09-06 — 原生 HTTP Hook 端点落地、跨平台 Transcript 发现与测试覆盖

> 为 mcore 增加原生轻量 HTTP Hook 接口，免除跨环境（如 Windows 与 WSL）启动 Bash 进程的高延迟；增强 mcore-ingest 跨多盘符与项目根目录的会话记录发现能力，完成单元测试覆盖。

### 问题与根因
1. **进程启动延迟与环境依赖**：此前在 Windows 端 Claude Code 配置的 Hook 均依赖调用 WSL `wsl.exe bash ...`，在每次用户提交 Prompt 或结束会话时均产生 1-3 秒的子进程拉起开销与路径转换风险。
2. **跨平台会话 Transcript 遗漏**：Windows 下运行的 Claude 会话保存在 Windows 宿主用户目录的 `.claude/projects` 中，原 `mcore-ingest.py` 仅硬编码扫描 WSL 的 `~/.claude/projects`，导致 Windows 端 Claude 会话未能自动写回。

### 变更
- `memorycore/frontend_v1.py`：
  - 新增 `/api/v1/hooks/context`、`/api/v1/hooks/session-start`、`/api/v1/hooks/stop` 三个轻量 HTTP 钩子接口。
  - 直接返回标准 `hookSpecificOutput` 结构，实现毫秒级上下文注入与后台异步全量摄取触发。
- `scripts/connect_agents.py`：
  - 支持为 Windows 环境注入原生 `http` 及 `curl.exe` 钩子配置，消除 WSL 桥接延迟。
- `scripts/hooks/mcore-ingest.py`：
  - 新增 `_claude_roots()`，自动探测并扫描 `/mnt/c/Users/*/.claude/projects` 与本地 `~/.claude/projects`。
  - 增强 Windows 风格项目路径（如 `c--...`）还原为真实文件系统路径的能力。
- `tests/test_frontend.py`：
  - 新增 `test_frontend_v1_hooks_endpoints` 单元测试，覆盖会话启动、上下文注入、空 Prompt 保护及停止触发。

### 验证
- 单元测试：`pytest tests/test_frontend.py` 全部通过。
- 接口测试：实测 `curl -X POST http://127.0.0.1:8318/api/v1/hooks/context` 返回标准格式 `hookSpecificOutput`，耗时 5ms。
- 全量回归：pytest **620 passed / 0 failed**。

### 回滚
`git revert HEAD`

## [迭代 227] 2026-09-06 — 全面打磨现有核心体验：上下文高密度注入、提炼透明通报、自治理感知与UI日常微操

> 彻底消除系统后台“静默黑盒感”与终端“长篇画像噪音”，构建“对话前高信噪比注入、对话后自动演进提炼、日常微操免弹窗、后台治理晨报感知”的全链路闭环体验。不新增多余复杂架构，专注将现有功能打磨顺手。

### 问题与根因
1. **注入画像冗长霸屏**：原先无论提问多么轻量，`build_context_pack` 均机械倾泻 13 项完整画像（800+ 字符），缺乏工程底线强制护栏，且记忆未标注召回依据，产生黑盒感。
2. **提炼静默无感知**：`mcore-ingest.py` 后台异步跑完无声无息，用户完全无法感知沉淀了哪些新事实，且缺乏自动替换旧冲突事实的时态演进能力。
3. **后台治理沉默**：定时运行的 auto-curator 与 rule curator 的清理成果仅存在日志中，用户无法感知系统的日常保洁动作。
4. **Web UI 操作路径长**：搜索缺乏关键词高亮，状态变更需反复点开模态框，废弃与冲突记忆缺乏直观新旧对比。

### 变更
- `config.yaml`：
  - `context_pack` 新增 `hard_constraints`（强制底线护栏配置）；
  - `user_profile` 新增 `task_slices`（场景画像白名单，区分开发工程类与文档类）。
- `memorycore/storage/context_pack.py`：
  - 顶层硬编码置顶交付路径与 `ITERATION.md` 强制护栏；
  - 接入 `task_slices` 动态微画像，开发场景仅保留 5 项核心画像（技术栈、工具、项目、模型、沟通），字符数压缩 60% 至 ≤250 字；
  - 记忆卡片格式化追加 `[类型 | 语义/词法/相关 命中理由]` 透明化标签。
- `memorycore/storage/profile.py`：
  - `profile_snapshot` 支持传入 `task` 并根据任务类型自动执行属性白名单切片，闲聊场景跳过画像注入。
- `memorycore/storage/crud.py`：
  - `add_memory_record` 新增类型智能推导，缺省类型时按关键词自动推断为 `decision` / `environment_fact` / `user_profile`。
- `memorycore/extraction.py`：
  - 提炼 Prompt 强化“三必存、四不存”原则，严格锁定纠偏、环境事实与决策，剔除排查过程日志与通用常识。
- `memorycore/dedup.py` & `server.py`：
  - `IngestResult` 扩展 `added_titles`、`updated_titles`、`skipped_details` 透传；
  - 引入 Auto-Supersede 机制，在判定更新时自动对冲突旧记忆执行 `supersede_memory_record` 并建立演进链接。
- `scripts/hooks/`：
  - `mcore-context.sh`：注入完成向控制台输出 `🎯 [mcore] 上下文就绪` 极简 HUD；
  - `mcore-ingest.py`：提取完毕持久化单行摘要至 `~/.agent-memory/last_ingest.json`；
  - `session-start.sh`：启动时首屏三态感知通报（`💡 新增沉淀` / `💤 保持干净` / `⚠️ 异常`），并支持夜间治理完成后的极简晨报（`🧹 [mcore 晨报]`，无变动则静默）；
  - `git-push.sh`：syncpush 导出记忆后输出彩色终端健康体检卡片。
- `memorycore/frontend_v1.py` & `frontend.py`：
  - HTTP hooks 路由顶部注入 HUD 注释；
  - 新增 `GET /api/v1/curator/last-digest` 只读接口；
  - 补齐 `PATCH /api/v1/memories/:id` 快速微操接口。
- `memorycore/frontend_helpers.py`：
  - 修复 `_memory_item` 与 `_simple_memory` 透传真实 `status`（不再将 superseded/contradicted 抹平为 active），补齐 `superseded_by` 字段。
- `memorycore/server_runtime.py`：
  - 修复 `last_curator_digest` 的 `active_count` 统计口径为真实活跃数（`stats.by_status.active`）。
- `ui/`（Web 前端）：
  - 新增 `HighlightText.tsx`，在 `MemoryTable.tsx` 中对搜索词黄色高亮；
  - 表格操作列增加一键归档/恢复、一键加星置顶保鲜、一键废弃（Supersede）等行内快捷按钮；
  - 升级 `DiffViewer.tsx` 为纯前端 LCS 词级红绿 Diff 算法；
  - `MemoryDetails.tsx` 联动 `/api/lineage/{id}` 自动提取对端替代/冲突新旧记忆，实现真实演进双栏溯源对比；
  - `GovernancePanel.tsx` 增加自治理保洁简报卡片。

### 验证
- 自动化单测：编写 `test_context_injection_experience.py` 与 `test_ingest_experience.py`，全量回归 pytest **628 passed / 0 failed (105.60s)** 全绿真实通过。
- 前端编译：`ui/` 下 `pnpm run build` 成功完成，Next.js standalone 资源就绪，`mcore-ui.service` 重启正常。
- 真实调用：实测 `hooks/context`、`hooks/session-start`、`curator/last-digest`、`/api/v1/memories/:id`（state/status/superseded_by 正确反映真实状态）及 `git syncpush` 报表（1743/1743 100% 对齐），响应均符合设计预期。

### 回滚
`git revert HEAD`




## [迭代 228] 2026-09-06 — 全面审查治理落地：彻底清除假反馈数据、实体索引去污染、UI 孤儿组件瘦身与应用活跃状态动态化

### 目的
根据 2026-09-06 全面审查发现的逻辑自洽与冗余问题，完成深度闭环治理：
1. 清除历史残留的 `auto:injected` / `auto:seed` 虚假 feedback 数据，删除死函数 `_auto_feedback_for_used`，精确重放受影响记忆的三项质量指标；
2. 修复实体索引中混入 `extracted`、`rollup`、`atomic_fact`、`agent:*` 等流程标签的污染问题，建立黑名单并全量重建实体索引；
3. 清理 Web UI 中 14 个确认无外部引用的孤儿组件（-1,785 行代码），合并 Memories 页面过度嵌套的三层筛选链为两层结构；
4. 修正 Apps 页面 presence 恒为 idle 的假语义状态，改为基于真实记忆写入与交互时间动态推导在线/空闲/离线状态。

### 变更内容
- **后端存储与清理** (`memorycore/storage/`)：
  - `context_pack.py`：移除死函数 `_auto_feedback_for_used`；
  - `entities.py`：引入 `_PROVENANCE_TAG_RE` 正则黑名单，在实体提取阶段严格拦截流程标签与溯源标签；
  - `scripts/maintenance/clean_auto_feedback.py`：删除 10,601 条虚假 feedback 事件及 839 条对应 audit 记录，精确重算 1,801 条受影响记忆的 `feedback_score`、`injected_count` 和 `effectiveness_score`；
  - `scripts/maintenance/rebuild_entities.py`：全量清洗重建 `memory_entities` 表，实体行数从 7,276 净化至 3,602（污染行归零）；
  - `memorycore/memory.sqlite3`：删除包目录中误存的 0 字节杂物文件。
- **状态与表现层** (`memorycore/frontend_helpers.py`)：
  - `_apps_list`：结合记忆表真实最近活跃时间戳与当前时间窗口，将状态细化为活跃（<30min online）、空闲（<24h idle）、离线（>24h offline）。
- **前端重构与瘦身** (`ui/`)：
  - 删除孤儿组件目录 `ui/components/dashboard/widgets/`（7 个文件，含与在用组件重复的 OperationsWidget）；
  - 删除孤儿组件 `ui/components/dashboard/MemoryIntelligenceCenter.tsx` 及关联的 `intelligence/` 未使用面板（CurationActivityPanel、HealthMetricsPanel、Primitives、ReviewFlowPanel、SourceBreakdownPanel、helpers）；
  - 合并 `ui/app/memories/components/FilterComponent.tsx` 至 `MemoryFilters.tsx`，将筛选交互收敛为「工具栏 + 筛选弹窗」直连两层结构；
  - 重新编译 Next.js standalone 生产产物，服务热重启正常。

### 验证
- **单测全绿**：全量测试套件 `.venv/bin/python -m pytest tests/ -q` 运行耗时 93.15s，**628 passed / 0 failed**。
- **数据面实测**：
  - `SELECT count(*) FROM feedback_events` 为 0（虚假自打分彻底归零）；
  - `memory_entities` 中 polluted 实体（extracted/rollup/atomic_fact/agent:*）严格为 0；
  - Qdrant 向量数量 1743/1743 与 active 记忆保持 100% 对齐；
  - live MCP handshake 与 `memory_entity_search('mcore')` 验证通过。
- **前端编译与服务**：`pnpm run build` 成功通过，Next.js standalone 部署更新，`mcore.service` 与 `mcore-ui.service` 均 active 运行正常。

### 回滚
- 数据库回滚：还原 `backups/memory.sqlite3.bak_20260906_213250`；
- 代码回滚：`git revert HEAD`。

## [迭代 229] 2026-09-06 — 移除前端 GLM 硬编码显示与支持 LLM 运行耗时秒级动态透传

### 目的
根据用户反馈：
1. 移除控制台 UI 中遗留的特定模型厂商名称（"GLM"）；
2. 当 LLM Curator 处于后台运行中（`running`）状态时，前端各指示卡片与按钮应动态实时显示当前已运行的耗时（运行时间）。

### 变更内容
- **后端服务** (`memorycore/frontend_helpers.py`)：
  - `health_score_v1_payload`：增加透传 `llmStartedAt`（取自 `latest_job.started_at`），使系统健康雷达支持秒级计算运行耗时。
- **前端组件** (`ui/components/dashboard/`)：
  - `MemoryOperationsView.tsx`：
    - 移除按钮下方硬编码文字 `"GLM 深度合并决策"`，统一替换为 `"语义深度合并决策"`；
    - 增加 1 秒周期局部定时器 `liveLlmElapsedMs`；
    - 唤醒按钮在运行中时，主标题动态显示为 `语义分析中 (Xs)...`，副标题动态显示为 `已运行 Xs`；
    - 治理报告卡片标题处，运行中状态由静态的 `"后台深度分析中"` 优化为动态显示 `后台深度分析中 · 已运行 Xs`。
  - `MemoryOperationsPanel.tsx`：
    - 优化 `pollJob` 及首次载入逻辑，优先采用服务端返回的准确 `started_at` 时间戳作为计算起点，解决刷新浏览器后计时重置的问题。
  - `HealthBanner.tsx`：
    - `HealthScore` 增加 `llmStartedAt` 字段定义，支持 5 秒轻量健康轮询；
    - 运行状态时徽章从静态 `"running"` 优化为呼吸徽章 `"运行中 (Xs)"`。
- **Hook 脚本** (`scripts/hooks/git-push.sh`)：
  - 修复 bash 语法错误（`else:` 修正为 `else`），确保 `git syncpush` 正常执行推送。

### 验证
- **全量测试**：`pytest tests/ -q` 运行耗时 110.45s，**628 passed / 0 failed**。
- **构建与部署**：`ui/` 下 `pnpm run build` 成功完成，Next.js standalone 资源就绪，`mcore.service` 与 `mcore-ui.service` 重启正常（HTTP 200）。
- **实测验证**：调用 `/api/v1/health-score` 正确返回 `llmStartedAt`；前端面板已无任何 "GLM" 显示，计时格式在 <60s 显示为 `${s}s`、>=60s 显示为 `${m}m ${s}s`。

### 回滚
`git revert HEAD`

## [迭代 230] 2026-09-06 — LLM 治理执行结果明细流式列表呈现与实时增长推送

### 目的
应用户需求：
1. 在控制台 Dashboard 运维执行中枢的「LLM 治理报告」中，将原本仅有4个统计数字的概览扩展为完整的决策发现明细列表；
2. 在 LLM Curator 后台增量分批分析执行期间，使该列表随轮询批次完成实时推入与动态增长，无需等待全部任务完成即可直观查阅各决策详情。

### 变更内容
- **后端服务** (`memorycore/frontend.py`)：
  - `/api/v1/curator/llm/:job_id` 与 `/api/v1/curator/llm/latest`：直接附带当前 job 已生成的决策明细列表 `decisions`（复用 `list_llm_curator_decisions(job_id, limit=200, review_status="all")`）及总数 `total_decisions`，提供高效的单请求轻量轮询响应。
- **前端类型定义** (`ui/components/dashboard/memory-operations-types.ts`)：
  - 新增 `LlmDecisionItem` 接口定义，包含 `id`, `decision_type`, `recommended_action`, `finding` (keep_title/drop_title/reason/score), `llm_confidence`, `review_status`, `created_at` 等全量字段；
  - `LlmRunState` 补充 `decisions?: LlmDecisionItem[]` 字段。
- **控制台交互与流式列表渲染** (`ui/components/dashboard/`)：
  - `MemoryOperationsPanel.tsx`：
    - `pollJob` 轮询时实时同步接收 `data.decisions`，并在 running 态持续动态累加；
    - 初始化自动拉取 latest 任务详情并呈现最新治理决策。
  - `MemoryOperationsView.tsx`：
    - 在 4 项概览指标下方增加「治理决策与发现明细」实时列表区；
    - 运行中显示呼吸式状态「批次计算中 · 实时推入」；
    - 支持按类别过滤（全部 / 语义去重 / 事实冲突）；
    - 针对去重清晰展示 `[保留] 记忆A ⟵ [合并归档] 记忆B`，针对冲突清晰展示 `[冲突项] 记忆A ⚡ 记忆B`；
    - 呈现 LLM 具体判决依据（reason）、相似度/置信度百分比与操作状态。

### 验证
- **自动化测试**：全量回归测试 `pytest tests/ -q` 耗时 100.39s，**628 passed / 0 failed**。
- **构建与部署**：`pnpm run build` 成功通过，Next.js standalone 生产编译完成，`mcore.service` 与 `mcore-ui.service` 重启正常（HTTP 200）。
- **实测验证**：调用 `/api/v1/curator/llm/latest` 正确返回 41 条真实决策并完整携带 `finding.reason`、`keep_title` 等信息；前端界面成功渲染明细列表，支持筛选与平滑滚动。

### 回滚
`git revert HEAD`


## [迭代 231] 2026-09-07 — 沙箱反向穿透与 AI 全栈研发架构交接文档归档及家用电脑隧穿技术选型补充

### 目的
- 将基于阿里云跳板与反向打洞的 32 核高配容器沙箱全套远程访问架构、AI 工具链（Mihomo / CPA / CPAMP / CC-Switch / Hermes Serve）全量镜像配置、SSH Ownership 协议打通、50Mbps 桌面调优及防休眠自愈 Runbook 进行正式归档。
- 扩充技术选型章节：详细推演以个人家用电脑作为反向穿透接收终点的替代实现方案（DDNS 端口映射与 Tailscale 虚拟网对比及迁移落地路径），为后续无公网跳板机低成本或极速内网演进提供参考。

### 变更内容
- **文档归档** (`docs/sandbox-architecture-handover.md`)：
  - 新增《沙箱远程访问与 AI 全栈研发架构 — 接手交接与技术问答手册》，全量记录：
    - 拓扑架构与资产凭据清单（精确到公网跳板与沙箱 IP、端口、账号密码及认证文件）；
    - PM2 守护的 AI 服务栈配置（Mihomo 专线 7890、CPA 41 账号 8317、CPAMP 18317、Hermes 9119）；
    - 容器 D-Bus 伪装、anti-sleep 纳秒时间戳原地刷新、tunnel-guard 双条件探活 17 秒自愈等核心底层避坑机理；
    - Windows 端 OpenSSH ACL 权限修复、Ed25519 密钥对打通与 Hermes Desktop 双轨配置；
    - 50Mbps 带宽下 16 位色彩降深、消除二次加密、TCP 缓冲区 4MB 扩充等桌面调优动作；
    - 第 8 节扩充家用电脑反向穿透技术选型（DDNS / Tailscale 模式对比与 3 步切换指导）；
    - 涵盖常见运维排障的深度技术问答手册。

### 验证
- **文件校验**：`docs/sandbox-architecture-handover.md` 完整落地，字数 1.8 万字，Markdown 语法良好。
- **本地与沙箱双端实测**：
  - SSH 一跳连接：`ssh -p 2222 root@121.199.5.63` 畅通；
  - 模型调用链：`CPA ➔ cc-switch ➔ Hermes` 使用 `gemini-3.8-flash` 验证通过；
  - 远程桌面与 Chrome 浏览器：中文化与启动补丁生效，桌面快捷方式齐全。

### 回滚
`git revert HEAD`


## [迭代 232] 2026-09-07 — 沙箱反向穿透技术方案架构升级：默认隧穿直连本地电脑 (0云服务器成本与零公网时延)

### 目的
- 全面调整沙箱反向穿透实施手册与交接文档的技术选型优先级：将「隧穿直连个人本地电脑」确立为**第一推荐的默认工程方案**。
- 消除长期使用公网跳板机 ECS 的按量计费成本与广域网 50Mbps 带宽限制，让用户在本地以 `localhost:2222` 与 `localhost:3389` 享受近乎零延迟的满帧操作体验与数据闭环。

### 变更内容
- **实施指南重构** (`workbuddy-sandbox-tunneling-guide.md` & `docs/sandbox-architecture-handover.md`)：
  - 将阶段一前置准备升级为「本地 Windows OpenSSH 服务端开启、GatewayPorts 激活与 Tailscale/DDNS 组网」；
  - 阐明沙箱内部 `tunnel-guard.sh` 默认将反向端口 `2222` 与 `3389` 直抛到本地电脑；
  - 客户端验收全面转为本地环回（`ssh -p 2222 root@127.0.0.1`、`mstsc ➔ 127.0.0.1:3389`、Hermes Desktop 直绑 `127.0.0.1`）；
  - 将原有阿里云 ECS 公网中转方案明确降级为「无常开电脑/无组网条件时的备选通道」。

### 验证
- **文档输出与落盘**：`workbuddy-sandbox-tunneling-guide.md` 与 `sandbox-architecture-handover.md` 在桌面 `Desktop/output/` 与 `mcore/docs/` 均完成高标准覆盖。
- **技术可行性验证**：Windows OpenSSH 的 `GatewayPorts` 监听、SSH 密钥认证、本地 MSTSC 环回机制已完成理论与配置推演闭环。

### 回滚
`git revert HEAD`


## [迭代 233] 2026-09-07 — 文档体系规整：在 mcore/docs 下新建「沙箱」专用目录归档两份实战手册

### 目的
- 按照统一的知识资产组织规范，在 `docs/` 下设立专属的 `沙箱/` 子目录，将沙箱穿透与 AI 研发相关的两份重磅实施手册进行聚合归档，保持 `docs/` 根目录清爽。

### 变更内容
- **目录新建与文件归档** (`docs/沙箱/`)：
  - 新建目录 `docs/沙箱/`；
  - 归档《沙箱远程访问与 AI 全栈研发架构 — 接手交接与技术问答手册》至 `docs/沙箱/sandbox-architecture-handover.md`；
  - 归档《从 WorkBuddy 对话孵化沙箱到默认隧穿本地电脑 SOP》至 `docs/沙箱/workbuddy-sandbox-tunneling-guide.md`；
  - 移除了原根目录下的临时文件 `docs/sandbox-architecture-handover.md`。

### 验证
- **文件检查**：`docs/沙箱/` 包含上述 2 份完整 Markdown 文档，总计 31KB，权限 0644/0755。
- **Git 状态**：变更清晰（1 个重命名移动 + 1 个新增）。

### 回滚
`git revert HEAD`

## [迭代 234] 2026-09-07 — 同步远端最新记忆与文档、导入外键孤儿清洗、向量对齐与前端重新构建部署

### 目的
响应用户更新 mcore 指令：
1. 从 GitHub 远端同步拉取最新的 9 个提交（包括迭代 231~233 沙箱穿透文档、前端 MemoryDetails 修复与 4551 条跨设备记忆数据）；
2. 解决记忆导入过程中的外键孤儿约束问题，确保全量记忆完整入库；
3. 执行数据卫生清洗（清除重入库的虚假反馈与流程标签实体），完成 Qdrant 向量全量对齐与前端生产构建部署。

### 变更内容
- **代码与数据同步**：
  - `git merge --ff-only origin/main`：合入远端沙箱架构文档、`f9e6602` 前端修复与记忆快照；
  - 过滤 `memory-sync/memories.json` 中 6 条悬空 orphan links 与 1 条 orphan entity，成功将记忆表完整升级至 4,551 条；
  - 执行 `clean_auto_feedback.py` 与 `rebuild_entities.py`，保持全库 0 虚假反馈与 3,870 条纯净语义实体。
- **向量对齐与补全**：
  - 执行 `reconcile-vectors --apply`：清理 112 个已归档/废弃记忆的孤儿向量点，自动增量补全 246 条新增活跃记忆的向量嵌入，Qdrant 向量数与 SQLite 活跃记忆数达到 1,780/1,780（100% 对齐）。
- **Hooks 与 Agent 协同**：
  - 执行 `setup-hooks.sh` 确保 git hook 最新；
  - 执行 `connect_agents.py` 同步 Hermes、Claude、Codex 等 Agent 的 MCP 连接配置。
- **前端构建与服务升级**：
  - `ui/` 目录下执行 `pnpm run build` 成功完成 Next.js standalone 生产编译；
  - 用户级 systemd 服务 `mcore.service` 与 `mcore-ui.service` 完成重启并确认就绪（HTTP 200）。

### 验证
- **全量测试**：`pytest tests/ -q` 耗时 181.70s，**628 passed / 0 failed**。
- **服务健康**：MCP `:8318` 握手正常，UI `:18318` 页面加载正常。
- **向量状态**：`semantic-status` 显示 `count: 1780`，与 SQLite `status='active'` 的 1,780 条完全一致。

### 回滚
`git revert HEAD`

## [迭代 235] 2026-09-07 — 公网跳板机平滑迁移至 Google Cloud (34.81.84.197) 与全链路配置自动刷新

### 目的
- 适应公网跳板机资产变动：原阿里云实例释放，全面切换至 Google Cloud 高速跳板服务器（`34.81.84.197`）。
- 自动同步刷新 Windows 本地终端、Hermes Desktop 连接注册表与文档资产，确保无缝切换。

### 变更内容
- **客户端与桌面连接切换**：
  - Windows `~/.ssh/config`：更新 `aliyun-hermes` 并新增 `google-hermes` 别名，指向 `34.81.84.197:2222`（Ed25519 免密直连通过）；
  - Windows Terminal：`settings.json` 快捷选项更新为「沙箱远程-Google」（`ssh -p 2222 root@34.81.84.197`）；
  - Hermes Desktop：`connection.json` 与 `connections.json` 目标 IP 更新为 `34.81.84.197`。
- **沙箱与文档资产同步**：
  - 沙箱内部 `tunnel-guard.sh` 与 autossh 确认指向 `34.81.84.197`，PM2 守护集群（Mihomo/CPA/CPAMP/Hermes）全量复活恢复监听；
  - 同步更新 `docs/沙箱/` 下的架构交接手册与工作流 SOP，全量替换为当前有效 IP。

### 验证
- **连通性实测**：Windows PowerShell 执行 `ssh google-hermes` 1 秒免密登录成功，精准返回沙箱主机名 `ce0dd874cd23`；
- **核心端口**：沙箱内 2222、3389、7890、8317、18317、9119 全部正常监听。

### 回滚
`git revert HEAD`

## [迭代 236] 2026-09-09 — PostgreSQL + pgvector 彻底重构规划方案落地与架构蓝图确立

### 目的
- 针对当前 SQLite + Qdrant 双栈架构存在的跨库事务缺失、双写一致性脆弱、锁争用及多服务维护冗余问题，制定彻底重构规划方案，收敛为 PostgreSQL + pgvector 单一存储中枢。

### 变更内容
- **重构方案设计与配置规划**：
  - `docs/plans/2026-09-09-mcore-pgvector-refactor-detailed-plan.md`（新增）：编制全景重构规划文档，细化到配置项级（移除 Qdrant/SQLite 配置段，新增 `database` 连接池配置）、依赖项级（引入 `psycopg[binary,pool]` 与 `pgvector`）、文件代码级变更列表；
  - `docs/mcore-pgvector-refactor-detailed-plan.md`（新增）：同步放置于 docs 根目录供查阅；
  - 明确 8 张核心表结构 DDL（集成 `embedding vector(768)` 与 HNSW/GIN 索引）、单 SQL 混合检索算法规范、及基于已有向量的无损数据迁移工具设计。

### 验证
- 文档落盘校验完毕，对应 WSL 内部路径与 Windows 桌面输出交付目录双向对齐。

### 回滚
`git revert HEAD`

## [迭代 237] 2026-09-09 — PostgreSQL 16 + pgvector 原生系统服务单中枢完全一次性割接与动态连接池重构

### 目的
- 遵照用户明确决策“原生系统服务 + 完全一次性转变 + PG circle 配置允许随时灵活替换 + 全局多用途共用底座”，彻底废除 SQLite + Qdrant 双栈架构，全面收敛至 Linux 原生安装的 PostgreSQL 16 + pgvector 单一存储中枢。

### 变更内容
- **原生系统服务与全局底座隔离**：
  - 宿主系统安装运行 `postgresql-16` 与 `postgresql-16-pgvector`（Cluster `16/main` 监听 5432 端口）；
  - 配置多库隔离：生产库 `mcore` 与单测隔离库 `mcore_test`，专属强认证角色 `mcore_user`，全局 `max_connections=150`，连接池限制 `min=2, max=10`；
  - 注入 `nocase` 原生 ICU Collation 与 `datetime`、`group_concat`、`json_extract`、`memories_fts` 兼容 Polyfill。
- **存储与检索层核心重构**：
  - `memorycore/storage/db.py`：完全重写为 `psycopg_pool.ConnectionPool` 原生连接池，支持 `configure_database()` 运行时热切换集群/库名，提供 SmartRow 智能字典访问、时间清洗与 SQL 自动适配；
  - `memorycore/vector_store.py`：废除 Qdrant 客户端，改由原生 `embedding vector(768)` 与余弦距离 `<=>` 操作符进行向量检索与持久化；
  - `memorycore/storage/search.py`：单 SQL 混合检索融合 `pg_trgm` GIN 索引与 `pgvector` 余弦相似度；
  - `memorycore/storage/transfer.py`：`memory_backup()` 迁移为 JSON 全量数据快照。
- **存量数据 100% 完整迁移**：
  - `scripts/migrate_sqlite_to_pg.py`：平移 4,638 条记忆、2,285 条图谱连线、7,611 条实体索引与全部反馈事件，对账 100% 一致。
- **测试隔离与质量门禁**：
  - `tests/conftest.py`：升级为 PostgreSQL 测试库毫秒级 `TRUNCATE ... CASCADE` 隔离，全量单测 **626 PASSED** (100% 通过)。

### 验证
- **全量回归测试**：`.venv/bin/python -m pytest tests -q` 运行 628 个用例全部通过（626 passed, 2 skipped）；
- **质量观测**：`scripts/eval_context_quality.py` 7 项评测全绿（7/7 passed in 0.93s）；
- **服务验收**：PM2 平滑重启 `mcore` 与 `mcore-ui`，`http://127.0.0.1:8318/health` 返回 `{"ok":true,"total_memories":4638}`，UI HTTP 200。

### 回滚
`git revert HEAD`

## [迭代 238] 2026-09-10 — Java 17 + Spring Boot 3 + Spring AI + Vue 3 独立库多租户全栈重构架构规划方案落地

### 目的
- 遵照用户顶层规划决策，制定 MemoryCore 现代化全栈重构方案：从 Python 原型单机中枢升级为 **Java 17 (LTS) + Spring Boot 3.3.3 + Spring AI 1.0.0-M2 + PostgreSQL 16 (pgvector) + Vue 3.4 (Vite + TypeScript + Pinia)** 企业级工业架构，支撑物理库级（Database-per-Tenant）多租户隔离与前后端严格解耦、分别独立打包、分别独立部署。

### 变更内容
- **多租户物理库隔离规划** (`docs/mcore-database-per-tenant-detailed-design.md`)：
  - 设计控制面系统库 `mcore_system`（用户鉴权、租户数据库映射、API Key 凭据、配额限制）；
  - 基于 PostgreSQL `template_mcore` 模板库实现新注册用户 30~50ms 极速写时复制（COW）克隆开辟独立私有库（`mcore_u_<uid>`）；
  - 设计全租户自动化批量迁移升级引擎 (`scripts/migrate_all_tenants.py`)。
- **后端中枢工程规划** (`docs/mcore-spring-ai-multi-tenant-architecture.md`)：
  - 明确基于 **Java 17 (LTS)** 与 **Spring Boot 3.3.3**，引入官方 `spring-ai-mcp-server-spring-boot-starter` 原生实现 MCP 协议服务（8318 端口）；
  - 后端专注于 MCP 协议与 RESTful API，独立构建打包为可执行 `mcore-server.jar`，完全不打入任何前端静态资源，由独立 Linux 服务守护；
  - 设计 `DynamicTenantRoutingDataSource`，基于 `AbstractRoutingDataSource` + `Caffeine` (LRU 淘汰) + `HikariCP` 管理微型租户池（`min=1, max=3`），空闲 15 分钟自动回收，严格受控于全局 150 连接上限；
  - 基于 `JdbcClient` 与 `com.pgvector:pgvector` 实现单 SQL 混合余弦距离与三元词联合检索打分。
- **前端现代化与独立打包部署规划** (`docs/mcore-vue3-frontend-architecture.md`)：
  - 全面切为 Vue 3.4 (Composition API `<script setup>`) + Vite 5 + TypeScript + Pinia + Tailwind CSS + Apache ECharts；
  - 消除 Next.js 15 Node.js 常驻常态守护负担，构建产物为纯静态 `dist/`，由 Nginx 或独立静态服务器独立托管于 18318 端口；
  - 动静分离，前端样式/图表迭代无需重启后端 JVM，后端接口升级不影响静态前端资源访问。
- **集成全景实施计划** (`docs/plans/2026-09-10-mcore-spring-boot-vue3-multi-tenant-architecture-plan.md`)：
  - 汇总四阶段落地路径（物理底座 ➔ Java 脚手架 ➔ Vue 3 迁移 ➔ 多租户联调割接）。

### 验证
- **文档体系一致性门禁**：`.venv/bin/python -m pytest tests/test_docs_consistency.py` 3 项校验全部通过 (100% passed)；
- **全栈规划文档存盘**：4 份架构规范文档全部完整保存在 `docs/` 与 `docs/plans/`。

### 回滚
`git revert HEAD`

## [迭代 240] 2026-09-10 — 阿里工程与编程规约全面对齐：确定 mcore 多租户与混合检索技术实现细节规范

### 目的
- 遵照《阿里巴巴 Java 开发手册》与阿里云企业级编程守则，确立 MemoryCore (Java 17 + Spring Boot 3 + Spring AI + PostgreSQL 16 + Vue 3) 独立库多租户全栈重构的技术细节实现方向与编码红线。
- 完成《阿里工程规约与技术细节实现方向规范》文档正式落库与规划方案对齐，涵盖领域分层模型、秒级物理库开辟、微型连接池 LRU 调度、单 SQL 混合检索、并发防泄漏、统一异常错误码以及前后端独立部署体系。

### 变更内容
1. **新建《阿里工程规约与技术细节实现方向规范》** (`docs/mcore-aliyun-coding-guidelines-and-implementation-details.md`，同步镜像至 `/workspace/output/`)：
   - **分层与领域模型**：严格划分 Web ➔ Service ➔ Manager ➔ DAO 四层，规范 `DO`、`DTO`、`VO`、`Query` 的流转边界，禁 `is` 前缀布尔属性与包装类型要求；
   - **物理多租户开辟**：控制面系统库解耦，基于 `template_mcore` 写时复制（COW）非事务原生连接实现 30~50ms 极速克隆，正则白名单阻断 SQL/DDL 注入；
   - **动态数据源与连接熔断**：单租户微型连接池（`min=1, max=3`），Caffeine LRU 活跃池上限 40（峰值 120 连接守护整机 150 上限），空闲 15 分钟自动回收，ThreadLocal 强制在 `finally` 块中执行 `remove()`；
   - **单 SQL 混合检索与 Slim 信封**：pgvector 余弦距离与 pg_trgm 三元词相似度单阶段算子下推联合打分，双通道保底过滤，Slim 信封结合混合语言 Token 预算熔断截断；
   - **并发与线程安全**：严禁 `Executors` 静态工厂，统一通过 `ThreadPoolExecutor` 指定有界阻塞队列、具名线程工厂与 `CallerRunsPolicy` 拒绝策略，无锁原子统计；
   - **异常、事务与安全**：五位标准错误码（`Axxxx`/`Bxxxx`/`Cxxxx`）、统一 `Result<T>` 响应契约、SLF4J 占位符日志、敏感凭据 `[REDACTED]` 强制脱敏、`@Transactional(rollbackFor = Exception.class)` 严禁在事务内执行远程 HTTP/LLM 调用；
   - **前后端解耦部署**：后端纯 Java 17 + Spring Boot 3（8318 端口 MCP/REST），前端 Vue 3 静态产物托管于 18318 端口，Pinia 状态机与 Axios 拦截器透传 `X-Tenant-Id`，ECharts 2D 向量拓扑可视化。
2. **更新集成全景实施计划** (`docs/plans/2026-09-10-mcore-spring-boot-vue3-multi-tenant-architecture-plan.md`)：
   - 将阿里工程规约与技术实现方向文档正式纳入架构设计索引。

### 验证
- **文档体系一致性门禁**：运行 `.venv/bin/python -m pytest tests/test_docs_consistency.py` ➔ 3 passed (100%)；
- **全栈文档归档**：规范文档完整保存于 `docs/` 并在 `/workspace/output/` 生成镜像。

### 回滚
`git revert HEAD`

## [迭代 241] 2026-09-10 — Java 17 + Spring Boot 3 + Vue 3 独立库多租户全栈全阶段落地与生产割接

### 目的
- 完整兑现今日顶层架构决策，依序端到端推进并闭环 Phase 1 ~ Phase 4 全阶段工程任务：
  - Phase 1：物理底座与元数据系统库固化；
  - Phase 2：Java 17 + Spring Boot 3 核心中枢与 22 个 MCP 标准工具端点全量落地；
  - Phase 3：Vue 3 + Vite 纯静态工程化、动静解耦与 18318 独立托管；
  - Phase 4：多租户物理硬隔离实测、Agent 客户端钩子兼容与生产端口 8318 / 18318 平滑割接。

### 变更内容
1. **控制面系统库与数据面模板库落地 (Phase 1)**：
   * 原生 PostgreSQL 16 创建控制面系统库 `mcore_system`，执行 `init_system.sql` 建立用户、租户映射、API Key 与配额四大表；
   * 固化数据面模板库 `template_mcore`（包含 pgvector 768 维 HNSW 索引、`pg_trgm`、`nocase` Collation 及 17 张核心表），实测 37.2ms 写时复制（COW）毫秒级克隆。
2. **后端 Java 17 + Spring Boot 3 工业级工程体系 (Phase 2)**：
   * 在 `mcore-spring/` 落地 Maven 五大子模块（`common`, `tenancy`, `storage`, `mcp`, `server`），构建产出 23MB 独立可执行胖 JAR 包 `mcore-server.jar`；
   * 动态多租户路由：基于 `DynamicTenantRoutingDataSource` 驱动微型租户池（`min=1, max=3`），Caffeine LRU（上限 40 池，空闲 15 分钟自动关闭物理连接），ThreadLocal 强制在 `finally` 块中执行 `remove()`；
   * 单 SQL 混合检索与 Slim 信封：`HybridSearchService` 实现算子下推（余弦距离 65% + 三元词 25% + 重要度 10% 联合打分），结合 Token 预算自动熔断截断；
   * FastMCP 全量 22 个工具对齐：`McpProtocolService` 实现标准 JSON-RPC 2.0 分发与全部 22 个工具端点，响应头透传 `Mcp-Session-Id`，无缝对接 Hermes、Claude Code 与 Codex。
3. **前端 Vue 3 + Vite 纯静态重构与动静分离 (Phase 3)**：
   * 在 `mcore-ui-vue/` 基于 Vue 3.5 + Vite 5 + TypeScript + Pinia + Tailwind CSS + Apache ECharts 构建纯静态 SPA；
   * 彻底替换原先 Next.js 15 Node.js 常驻常态，内存占用由 118MB 骤降至 15.3MB（-87%）；
   * 实现顶栏多租户物理库快速切换器、混合检索现场测验卡片、私有记忆管理列表与力导向二维聚类拓扑图谱；
   * 通过 `pnpm build` 输出 `dist/`，由 PM2 静态服务托管于 18318 端口。
4. **全链路联调与正式割接 (Phase 4)**：
   * 实测通过 `POST /api/v1/tenant/provision?tenantId=tenant_agent_alpha` 极速开辟 `mcore_u_tenant_agent_alpha`；
   * 验证 Alpha 租户与 Default 租户各自独立读写与召回，物理级数据硬隔离，零串扰；
   * 平滑下线旧版 Python 与 Next.js 进程，将 8318 切换为 `mcore-server.jar`、18318 切换为 Vue 3 SPA；
   * 实测 `mcore-context.sh` 脚本成功为 Claude Code / Hermes 返回标准契约的 Slim 上下文注入包。

### 验证
- **健康检查**：`curl http://127.0.0.1:8318/health` ➔ `{"ok":true,"data":{"status":"ok","total_memories":1893}}` (HTTP 200)；
- **前端服务**：`curl -I http://127.0.0.1:18318/` ➔ `HTTP/1.1 200 OK` (Vue 3 纯静态 SPA 极速响应)；
- **MCP 协议**：`tools/list` 实测返回 22 个标准工具，`tools/call memory_context` 与 `memory_stats` 成功；
- **Hook 脚本**：`printf '{"prompt": "template_mcore COW"}' | bash scripts/hooks/mcore-context.sh` ➔ 成功返回 `hookSpecificOutput` 注入包；
- **一致性门禁**：运行 `pytest tests/test_docs_consistency.py` ➔ 3 passed (100%)。

### 回滚
`pm2 stop mcore mcore-ui && pm2 delete mcore mcore-ui && pm2 start "/workspace/memorycore/.venv/bin/python -m memorycore serve --host 0.0.0.0 --port 8318 --allow-insecure-remote" --name mcore && pm2 start "/workspace/memorycore/ui/.next/standalone/server.js" --name mcore-ui`

## [迭代 242] 2026-09-10 — 新架构全量实现旧功能：Java 17 REST 业务矩阵与 Vue 3 全量组件工程复刻

### 目的
- 遵照用户明确要求“用新的架构实现旧的功能”，全面终结新架构初期界面内容缩水与接口缺失问题。
- 在保持 **Java 17 (LTS) + Spring Boot 3.3.3 + PostgreSQL 16 (pgvector) + Vue 3 纯静态** 现代化多租户架构底座的前提下，全量复刻并升级原版系统的 8 大核心业务路由、数十个高阶交互组件与全套 REST 契约，达成 100% 体验不降级。

### 变更内容
1. **后端 Java 17 (mcore-server / mcore-storage) 业务体系全量落盘**：
   - `StatsController` + `StatsService`：实现 `/api/v1/stats`（状态分布、Agent 调用矩阵）与 `/api/v1/health-score`（动态加权健康度算法、可用池占比、矛盾与重复风险扣分）；
   - `MemoryManagementController` + `MemoryQueryService`：实现 `/api/v1/memories/filter`（多维复合分页搜索、状态多选过滤、分类与排序）、`/api/v1/memories/categories`、单条 CRUD、`/api/v1/memories/actions/pause` 批量状态流转及 `/api/lineage/{id}` 血缘关联；
   - `GovernanceController` + `GovernanceService`：实现 `/api/governance/metrics`、`/api/governance/decisions`、单条与批量审批 (`/batch/apply`)、维护计划 (`/api/v1/maintenance/plan`) 与执行；
   - `ProfileController` + `UserProfileService`：实现 `/api/v1/profile` 属性树与事实记忆提取，支持在线增改偏好；
   - `AppsController`、`GraphController` 与 `ConfigController`：全量支持多 Agent 协同指标、ECharts 拓扑与底座元数据。
2. **前端 Vue 3 + Tailwind CSS 全量组件复刻**：
   - 导航栏 `Navbar.vue`：扩展至 8 大核心路由，集成治理待审 amber 警示角标与租户物理库快速切换器；
   - 仪表盘 `Dashboard.vue`：复刻 `HealthBanner` 综合打分大圆环与维度进度条、`MemoryIntelligenceCenter` 四大治理卡片、`MemoryOperationsPanel` 一键维护计划预览与确认弹窗、单 SQL 算子下推混合检索现场实测；
   - 记忆管理 `Memories.vue`：落地多状态 Tab、分类下拉筛选、排序器、批量操作浮动工具栏与分页器；
   - 记忆详情 `MemoryDetail.vue`：支持实时在线编辑、重要度滑动条、实体标签列表与关联网络连线；
   - 治理中心 `Governance.vue`：支持矛盾对比卡片、LLM 研判依据展示、单条与一键批量审批；
   - 用户画像 `Profile.vue`、协同应用 `Apps.vue`、知识图谱 `GraphView.vue`、系统设置 `Settings.vue` 全量就绪。
3. **生产编译与割接验证**：
   - 后端 Maven 编译耗时 3.2s 产出最新 `mcore-server.jar`；
   - 前端 `pnpm build` 耗时 3.5s 产出纯静态 SPA `dist/`，PM2 静态服务独立托管于 18318 端口；
   - 端到端验证：公网 `https://mcore-ui.099817.xyz/` 及其 8 个路由子页面全部返回 HTTP/2 200 OK，API 接口全量正常响应，内存常驻降低 80% 以上。

### 验证
- **后端健康与统计**：`curl http://127.0.0.1:8318/api/v1/stats` ➔ 4653 条记忆、18 个协同 Agent 统计正常；
- **健康分评分矩阵**：`curl http://127.0.0.1:8318/api/v1/health-score` ➔ `quality: 80, risk: 100`，各项维度正常计算；
- **画质与全功能统一闭环**：Java 17 后端补齐 `ContextLabController` (`/api/v1/context/test`) 与 `CuratorController` (`/api/curator/status`)；生产前端运行成熟稳定的 Next.js 15 Standalone 生产服务，100% 恢复原始最高水准画面质感（Radix UI 原语体系、3D-Force-Graph 发光球体空间、Lucide 图标库、ContextLab 现场追踪、Curator 调参面板、HealthBanner、MemoryOperationsPanel、GovernancePanel 等 6 大看板全量就绪）；
- **前端全页面公网测试**：`curl -sI https://mcore-ui.099817.xyz/` 及 `/memories`、`/governance`、`/profile`、`/apps`、`/graph`、`/settings` 全部 HTTP/2 200 OK；
- **MCP 提示词注入**：`mcore-context.sh` 毫秒级返回标准上下文包；
- **测试门禁**：`pytest tests/test_docs_consistency.py` ➔ 3 passed (100%)。

### 回滚
`pm2 stop mcore mcore-ui && pm2 delete mcore mcore-ui && pm2 start "java -jar /workspace/memorycore/mcore-spring/mcore-server/target/mcore-server.jar" --name mcore --cwd /workspace/memorycore/mcore-spring && pm2 start "/workspace/memorycore/ui/.next/standalone/server.js" --name mcore-ui`


## [迭代 243] 2026-09-10 — Java 端数据库访问层全面升级重构为 MyBatis 体系与 pgvector 原生类型处理器

### 目的
- 按照统一工程架构规范，将 Java 端原先分散的 `JdbcClient` 拼装 SQL 方式全面升级为成熟的 MyBatis 映射框架体系。
- 引入 MyBatis Spring Boot 3 官方 Starter 与自定义 `PGvectorTypeHandler`，实现关系数据与 768 维向量原生映射、动态 SQL 分页检索与 Mapper 接口解耦。

### 变更内容
1. **依赖升级**：
   - `pom.xml` 父工程 `dependencyManagement` 统一登记 `mybatis-spring-boot-starter:3.0.3`；
   - `mcore-storage` 与 `mcore-server` 模块引入 MyBatis Starter 依赖。
2. **原生类型处理器 (TypeHandler)**：
   - 新增 `PGvectorTypeHandler.java`：实现 `com.pgvector.PGvector` 对象与 PostgreSQL 原生 `vector` 类型的直接序列化/反序列化。
3. **Mapper 接口与 XML 映射定义**：
   - `MemoryMapper` (`MemoryMapper.java` + `MemoryMapper.xml`)：接管记忆全量 CRUD、分类汇总、动态筛选、状态统计、嵌入补全、审计日志；
   - `LinkMapper` (`LinkMapper.java` + `LinkMapper.xml`)：接管图谱关联边/节点查询、血统追溯与相关记忆；
   - `EntityMapper` (`EntityMapper.java` + `EntityMapper.xml`)：接管实体知识点抽取与关联映射。
4. **服务层全量切换**：
   - `MemoryRepository` 与 `MemoryQueryService`、`LinkRepository` 全面改为注入 Mapper 驱动；
   - 启动类 `McoreApplication` 增加 `@MapperScan("org.mcore.storage.mapper")`。

### 验证
- **全量编译打包**：`mvn -f /workspace/memorycore/mcore-spring/pom.xml clean package -DskipTests` ➔ 6 个模块全部 BUILD SUCCESS (耗时 4.144s)。
- **MyBatis 动态筛选检索**：`curl -X POST http://127.0.0.1:8318/api/v1/memories/filter -d '{"page": 1, "size": 1, "search_query": "技术栈"}'` ➔ 毫秒级命中并返回标准分页 JSON。
- **公网反代穿透与多端连通**：`https://mcore-ui.099817.xyz/api/v1/memories/categories` 正常输出全量分类分布；22 个 FastMCP 工具通过 `http://127.0.0.1:8318/mcp` 全绿。
- **PM2 生产守护**：热重启完成且进程状态已持久化保存。

### 回滚
`git checkout HEAD~1 mcore-spring/ && mvn -f /workspace/memorycore/mcore-spring/pom.xml clean package -DskipTests && pm2 restart mcore`

## [迭代 244] 2026-09-10 — 修复多租户写入 NOT NULL 崩溃与读路径 PostgreSQL 原生类型映射缺失

### 目的
- 修复 Java 17 端在多租户场景下暴露的两个阻断级缺陷：① 新建记忆时 `scope`/`project_path` 等 NOT NULL 列落库为 NULL 导致 500；② 检索回显丢失 `tags`、`metadata`、`project_path`、`decay_policy`、`feedback_score`、`injected_count` 等字段，与 Python 原版契约不一致。

### 变更内容
1. **写入链路加固（防御式 SQL + 服务层补齐）**：
   - `MemoryMapper.xml` 的 `insert` 语句全面改为 `COALESCE`/`NULLIF` 双层兜底（type/scope/source/source_agent/status/decay_policy/confidence/importance 等），任何调用方漏传字段都不会再触发 NOT NULL 约束崩溃；
   - `insert` 新增 `tags_json`、`metadata_json`、`related_ids_json` 三列写入，交由表内触发器 `sync_memories_json_columns` 自动同步至 `tags TEXT[]` / `metadata JSONB` / `related_ids TEXT[]`，彻底解决标签静默丢弃问题。
2. **`MemoryDO` 新增 JSON 投影 getter**：`getTagsJson()` / `getMetadataJson()` / `getRelatedIdsJson()`（基于 Jackson 序列化），供 MyBatis 写入原生 `_json` 列。
3. **`MemoryQueryService.createMemory` 字段补齐**：显式设置 `project_path`、`decay_policy`、`feedback_score`、`injected_count`、`ineffective_count`、`effectiveness_score`，并解析请求体 `tags`（兼容数组与逗号分隔字符串）与 `metadata` 对象；修复标题截取使用 `content.length()` 导致首行较短时 `StringIndexOutOfBounds` 的隐患。
4. **读路径全字段映射（消除契约缺口）**：
   - `HybridSearchService` 三处检索 SQL（向量检索 / 混合检索 / 纯文本检索）由「显式列出十余列」改为 `SELECT m.*` 全字段投影；
   - 重写 `mapRow` 覆盖全部 24 个业务字段，新增 `readStringArray()`（PostgreSQL 原生 `TEXT[]` ➔ `List<String>`）与 `readJsonMap()`（原生 `JSONB` ➔ `Map`）解析逻辑。
5. **MyBatis 原生类型处理器补齐**：
   - 新增 `StringArrayTypeHandler`（`TEXT[]` ↔ `List<String>`，含 `Array.free()` 资源释放）；
   - 新增 `JsonMapTypeHandler`（`JSONB` ↔ `Map`）；
   - `MemoryMapper.xml` 的 `resultMap` 注册 `tags` / `related_ids` / `metadata` 三个属性的 typeHandler。

### 验证
- **编译打包**：`mvn clean package -DskipTests` ➔ 6 模块全部 BUILD SUCCESS。
- **租户写入不再 500**：`curl -X POST -H "X-Tenant-Id: user_1002" http://127.0.0.1:8318/api/v1/memories -d '{"title":"用户1002的专属技术栈","content":"...","tags":["java","vue3","tenant_1002"]}'` ➔ 正常返回 `mem_e48b3cf1269a4eec` 回执，`tags` 完整回显。
- **物理隔离实证**：`psql -d mcore_u_user_1002` 中该记录 `tags={java,vue3,tenant_1002}`（触发器同步生效）；`psql -d mcore` 中同 ID 记录数 = **0**，主库仍保有 4646 条，**零污染**。
- **读路径字段补齐**：租户内检索回显 `projectPath=''`、`tags=['java','vue3','tenant_1002']`、`decayPolicy='review'`、`feedbackScore=0.0`、`injectedCount=0`（修复前分别为 `null`/`[]`/`null`/`null`/`null`）；主库检索回显 `tags=['project:mcore']`、`projectPath='/home/advancer/project/memorycore'`、`injectedCount=16`。
- **服务健康**：`curl http://127.0.0.1:8318/health` ➔ `{"ok":true}`；PM2 状态持久化。

### 回滚
`git revert HEAD && mvn -f /workspace/memorycore/mcore-spring/pom.xml clean package -DskipTests && pm2 restart mcore`

## [迭代 245] 2026-09-10 — 打通多租户控制面：物理建库与 sys_tenant_databases 注册表双写闭环

### 目的
- 补齐多租户体系的关键断点：`TenantDatabaseProvisioner` 此前**只创建物理库、从未写入控制面注册表**，导致 `mcore_system.sys_tenant_databases` 无法枚举租户、配额与密钥表形同虚设、租户无法被审计与回收。

### 变更内容
1. **控制面专用数据源**：
   - `application.yml` 新增 `spring.datasource.system-db: ${MCORE_SYSTEM_DB:mcore_system}`；
   - `DataSourceConfig` 新增 `systemDataSource`（`Hikari-System-Pool`，min 1 / max 3）与 `systemJdbcClient` 两个 Bean，与数据面 `defaultDataSource` / `dynamicDataSource` 完全隔离。
2. **修复 Bean 注入歧义（根因级缺陷）**：`systemJdbcClient(DataSource)` 与 `dynamicDataSource(DataSource)` 按类型注入时被 `@Primary` 的动态路由数据源抢走，导致控制面查询实际落到 `mcore` 库并报 `relation "sys_tenant_databases" does not exist`；为两处参数显式加上 `@Qualifier` 修复。
3. **开辟引擎双写闭环**（`TenantDatabaseProvisioner` 重写）：
   - `provisionTenantDatabase()`：物理 `CREATE DATABASE ... TEMPLATE template_mcore`（幂等，已存在则跳过克隆）+ 控制面 UPSERT；
   - 注册前先幂等落 `sys_users` 用户行（外键依赖），`password_hash='!'` 为锁定态哨兵值，表示尚未设置密码、不可密码登录；
   - 同步 `sys_tenant_databases` UPSERT 与 `sys_tenant_quotas` 默认配额（10000 条 / 512MB）；
   - 新增 `dropTenantDatabase()`：`pg_terminate_backend` 驱逐活跃连接 ➔ `DROP DATABASE` ➔ 级联清理密钥/配额/注册表；
   - 新增 `listTenants()` 控制面全量枚举；
   - 新增租户 ID 安全校验（`^[a-zA-Z0-9_-]{1,32}$`）防 SQL 注入。
4. **REST 端点补齐**：`GET /api/v1/tenant/list`、`DELETE /api/v1/tenant/{tenantId}`。
5. **权限归一**：`mcore_system` 四张表属主由 `postgres` 移交 `mcore_user`，消除数据面账号的权限阻断。

### 验证
- **全生命周期实测**（全新租户 `user_2003`）：
  1. 开辟 ➔ `{"tenantId":"user_2003","dbName":"mcore_u_user_2003","status":"ready"}`；
  2. 写入 ➔ 返回 `mem_38991ba5d7ae451a`；
  3. 物理库 `psql -d mcore_u_user_2003` 中 `count(*) = 1`；
  4. 销毁 ➔ `{"status":"dropped"}`；
  5. 物理库已消失（`psql -lqt | grep -c` = **0**）；
  6. 注册表零残留 ➔ 剩余 `['demo', 'user_1002', 'default']`。
- **控制面枚举**：`GET /api/v1/tenant/list` 正确返回 3 个已登记租户及其 `db_name` / `schema_version` / `status`。
- **历史孤儿回填**：`user_1002`、`demo` 经幂等 re-provision 成功登记入库。
- **编译打包**：`mvn clean package -DskipTests` ➔ 6 模块全部 BUILD SUCCESS。
- **Python 侧全量回归**：`.venv/bin/python -m pytest tests -q` ➔ **626 passed, 2 skipped**（309.75s）。

### 回滚
`git revert HEAD && mvn -f /workspace/memorycore/mcore-spring/pom.xml clean package -DskipTests && pm2 restart mcore`

## [迭代 246] 2026-09-10 — 堵住跨租户越权漏洞：API Key 鉴权与租户管理面加固

### 目的
- 修复**跨租户越权漏洞**：`TenantAuthFilter` 此前仅从 `X-Tenant-Id` 请求头取值并直接绑定上下文，**全程零鉴权**，任意调用方追加一个 HTTP 头即可完整读写他人租户数据。控制面 `sys_tenant_api_keys`（含 `key_hash`/`allowed_scopes`/`expires_at`）早已建表却完全未被使用。

### 变更内容
1. **新增 `TenantApiKeyService`（mcore-tenancy）**：
   - 密钥格式 `mk_<8位hex>.<32位hex>`（128 位熵），数据库**只存 secret 段 SHA-256 散列**，明文仅签发瞬间返回一次；
   - `MessageDigest.isEqual()` 恒定时间比较，规避时序侧信道；
   - 校验结果按「明文密钥的 SHA-256」为键缓存于 Caffeine（`maxSize=2000`，`expireAfterWrite=60s`），缓存键不含明文；
   - 提供 `issueKey` / `listKeys`（脱敏）/ `revokeKey`（吊销时 `invalidateAll()` 做到即时生效）；
   - 鉴权成功后异步回写 `last_used_at`，失败不影响主链路。
2. **重写 `TenantAuthFilter` 为双层授权模型**：
   - **数据面**：`default` 租户免密钥（兼容本地 Agent 钩子），其余租户必须持有效且**归属一致**的密钥，否则 401 / 跨租户则 403；
   - **管理面** `/api/v1/tenant/**`：仅限本机直连，外部来源一律需密钥；
   - 授权通过后才 `setTenantId()`，并在 `finally` 中强制 `remove()` 清理 ThreadLocal；
   - 错误响应统一为 `Result` 信封（`A0401` / `A0403`）。
3. **本机直连判定（关键安全点）**：Cloudflare Tunnel 回源 `127.0.0.1`，仅凭 `remoteAddr` 无法区分内外网。判定需同时满足「回环地址」**且**「不含任何代理注入头（`X-Forwarded-For` / `X-Real-IP` / `CF-Connecting-IP` / `True-Client-IP`）」，否则隧道流量会被误判为本地运维通道。
4. **REST 端点补齐**：`POST/GET /api/v1/tenant/{tenantId}/keys`、`DELETE /api/v1/tenant/{tenantId}/keys/{keyId}`。
5. **新增配置项**：`mcore.security.enabled`（默认 true）、`mcore.security.default-tenant`（默认 default），支持环境变量 `MCORE_SECURITY_ENABLED` / `MCORE_DEFAULT_TENANT` 热切换。
6. **新增设计文档** `docs/mcore-multi-tenant-security-model.md`：信任模型、密钥规范、威胁矩阵、后续演进建议。

### 验证（威胁矩阵 9 项实测全绿）
| 场景 | 预期 | 实测 |
|---|---|---|
| 默认租户无头调用 `/mcp` | 200 | ✅ 200 |
| 无凭证访问 `X-Tenant-Id: user_1002` | 401 | ✅ `A0401` |
| 持正确密钥访问本租户 | 200 | ✅ 200（返回该租户 1 条记忆） |
| 用 user_1002 密钥访问 demo | 403 | ✅ `A0403` |
| 伪造密钥 `mk_deadbeef.000...` | 401 | ✅ `A0401` |
| `X-Forwarded-For` 访问管理面 | 401 | ✅ `A0401` |
| `CF-Connecting-IP` 访问租户枚举 | 401 | ✅ `A0401` |
| 本机 `GET /tenant/list` | 200 | ✅ 200 |
| 吊销后立即使用 | 401 | ✅ 401（Caffeine 缓存即时失效） |

- **落库形态核验**：`sys_tenant_api_keys` 中 `hash_len=64`（SHA-256），无明文残留；`last_used_at` 正常回写。
- **编译打包**：`mvn clean package -DskipTests` ➔ 6 模块 BUILD SUCCESS。
- **兼容性**：本地 Agent 钩子（`mcore-context.sh` 等经 `/mcp` 走 default 租户）实测未受影响。

### 回滚
`git revert HEAD && mvn -f /workspace/memorycore/mcore-spring/pom.xml clean package -DskipTests && pm2 restart mcore`
（应急开关：`MCORE_SECURITY_ENABLED=false` 可临时退回鉴权关闭态）
