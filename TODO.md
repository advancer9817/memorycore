# TODO — local-memory-mcp

> 待办事项清单。完成后打 `[x]`，具体实现细节记入 ITERATION.md。

---

## 检索质量优化

- [x] 清理过时高权重记忆（Phase 8 任务清单、Overmind 借鉴特性等已完成项 → archived）
- [x] FTS5 查询从 OR 改为 AND（2 词以上用 AND 连接，减少宽泛匹配）
- [x] FTS5 排序加入 rank 权重（文本相关性 40% + importance 30% + effectiveness 20% + feedback 10%）
- [x] 向量搜索融合到 context pack（FTS5 + Qdrant 双路召回，合并去重，Qdrant 不可用时降级纯 FTS5）
- [x] 提升 prompt 后自动/显式 `memory_context` 检索相关性：输入提示词后召回的记忆偶发弱相关，已收紧 fallback 注入、过滤弱相关向量-only 命中、提高相关性证据排序权重，并补中文 prompt 回归测试；后续又收紧 medium-score vector-only 与弱中文 keyword overlap。
- [x] 补强 context pack 的向量召回隔离：`build_context_pack()` 的 vector-only 命中回 SQLite 时已同步校验 `scope` / `project_path` / `valid_until`，避免多 agent/多项目共享库里跨范围注入。
- [x] 建立 prompt 后记忆检索相关性持续评测集：已将用户反馈“输入提示词后，检索到的记忆相关性不强”沉淀为 `tests/fixtures/context_relevance_cases.json`，并用 `tests/test_context_relevance.py` 跟踪 expected/rejected ids、`hit_rate`、`filter_rate` 与 trace，避免阈值和排序后续回退。

## Mem0/OpenMemory 融合

- [x] 对 Mem0 后端关键文件做代码审计：memory add/search、prompts、entity extraction、scoring、OpenMemory API/UI；审计结论已落到 `docs/plans/2026-06-01-mem0-openmemory-fusion-plan.md`。
- [x] 新增 memory atomization pipeline：parent 原文保留，长记忆生成 atomic child facts。
- [x] 使用现有 `memory_links` 建立 parent/child 关系：`child -> parent` 为 `part_of`，`parent -> child` 为 `supports`。
- [x] 给 child facts 写入 metadata：`parent_id`、`fact_hash`、`source_span`、`atomizer_version`、`kind=atomic_fact`。
- [x] child facts 单独写入 SQLite/FTS5 并同步 Qdrant 向量。
- [x] 新增实体/别名索引，覆盖 `local_memory`、`local-memory-mcp`、`lmmcp` 等同义实体。
- [x] 改造 `memory_context`：默认优先召回 atomic facts，必要时再展开 parent。
- [x] 增加 semantic + lexical + entity boost 融合排序，减少弱相关注入。
- [x] 增加 existing long memories backfill 工具，幂等拆分历史长记忆。
- [x] 新增 `memory_atomize_report`、`memory_entity_search`、`memory_vector_audit` 工具。
- [x] fork OpenMemory UI 到本仓库 `ui/`，保留 Apache-2.0 license 和上游 attribution。
- [x] 增加 OpenMemory UI 兼容 REST API 层，后端仍读写 lmmcp。
- [x] 用 Playwright 验证 UI：列表、搜索、详情、过滤、统计、归档/删除。
- [x] 增加召回评测集，覆盖长记忆局部事实、别名查询、跨项目隔离、弱相关过滤。

## 功能

- [x] 修复前端测试卡死：`tests/test_frontend.py` 单独运行会卡在第一个 `TestClient` 用例；当前在重启真实 `mcore.service` 并清理遗留 pytest/脚本进程后已恢复，`tests/test_frontend.py` 8/8 pass，保留为运行态验证记录。
- [x] 修复 hooks 初始化脚本未同步 Hermes SQLite session 存储变化：`scripts/setup-hooks.sh` 现在安装带 `--background` 的 Hermes on_session_end hook，`scripts/hooks/mcore-ingest.py` 只从 `~/.hermes/state.db` 读取 transcript，并在后台模式保留 stdin payload。
- [x] Embedding 外接 API / Ollama API / hashing 降级：`embed_text()` 默认 `auto`，优先配置的 OpenAI-compatible embedding API，未配置时尝试 Ollama `/api/embed`，失败后使用 hashing；不再默认安装或调用 sentence-transformers/PyTorch/CUDA 依赖链。
- [x] 修复 rollup 测试隔离问题：`test_rollup_processes_manual_source_episodic` 和 extraction source 对应用例已传入 stub summarizer，避免 dry-run/force 扫描测试依赖真实 extraction LLM。
- [x] 默认启用 Claude 对话前自动检索注入：`setup-hooks.sh` 和 `connect_agents.py --register-hooks` 已默认给 Claude 注册 `UserPromptSubmit -> mcore-context.sh`，并保留显式 `memory_context` 作为自动注入缺失时的兜底。
- [x] 停用 Codex 对话前自动检索注入：Codex 不再注册 `UserPromptSubmit -> mcore-context.sh`，本机 `~/.codex/hooks.json` 已移除该读前 hook；Codex 读记忆改为按 `AGENTS.md` 规则显式调用 MCP `memory_context`，只保留 `SessionStart` presence/capability 与 `Stop` 写回 hook，避免可见 hook 输出和弱相关记忆污染对话。
- [x] 补齐 opencode 对话前自动检索注入：新增 `scripts/hooks/opencode-mcore-plugin.js`，通过 opencode `experimental.chat.system.transform` 在 LLM 调用前读取最新用户消息并调用 `memory_context` 注入 system context；`connect_agents.py --register-hooks` 会把该 plugin 写入 opencode `plugin` 配置。
- [x] 补齐 Hermes 对话前自动检索注入：`setup-hooks.sh` 与 `connect_agents.py --register-hooks` 会注册 Hermes `pre_llm_call -> mcore-context.sh`，脚本返回 Hermes `{"context": ...}` 格式并通过短 timeout 调用 `memory_context`。
- [x] 补齐 Gemini 对话前自动检索注入支持矩阵：`setup-hooks.sh` 与 `connect_agents.py --register-hooks` 会注册 Gemini `BeforeAgent -> mcore-context.sh`，脚本返回 `additionalContext` 并通过短 timeout 调用 `memory_context`。
- [x] 扩展 opencode 回答后自动总结写回覆盖面：`mcore-ingest.py` 已支持从 `~/.local/share/opencode/opencode.db` 抽取 user/assistant text parts，`connect_agents.py --register-hooks` 会注册 opencode `session_end -> mcore-ingest.py --agent opencode --background`。
- [x] 补齐 Gemini 回答后自动总结写回自动 hook：`setup-hooks.sh` 与 `connect_agents.py --register-hooks` 会注册 Gemini `AfterAgent` + `SessionEnd -> mcore-ingest.py --agent gemini --background`，并支持 hook stdin 的 `transcript_path` 以及 `GEMINI_SESSION_FILE` JSON/JSONL transcript；`AfterAgent` 用于真实 headless prompt 后写回，`SessionEnd` 保留为退出兜底；真实 Gemini CLI JSONL 的 `type: "gemini"` assistant 消息与 `displayContent` 用户文本已纳入解析。
- [x] Gemini 真实 CLI 端到端现场验证：本机已有 `gemini` 命令，`gemini mcp list` 显示 `local_memory` connected；2026-06-01 11:14 CST 真实 `gemini -p ... --extensions '' --output-format json` 成功返回，transcript 中出现 `<hook_context># memory_context for gemini`，证明 `BeforeAgent` 注入生效；2026-06-01 11:20 CST 补 `AfterAgent` 写回与真实 JSONL 解析后，`gemini -p ...` 触发 `mcore-ingest.py --agent gemini --background`，日志显示 `messages=2`、`updated=1`，SQLite 中出现 `source_agent=gemini` 的 `LMMCP-GEMINI-WRITEBACK-20260601-1120` marker。
- [x] 为 agent presence/capability 增加自动心跳和能力注册入口：`session-start.sh` 现在会通过 MCP 更新 agent 在线状态并注册默认能力，`setup-hooks.sh` / `connect_agents.py --register-hooks` 会把 Claude/Codex 的 SessionStart hook 接入启动流程，opencode 也带上 agent id。

## 取舍决策 / 简化项

- [x] 删除 agent/model 权限管理：已移除 `agent_permission_*` MCP 工具、权限表创建、检查逻辑、前端/API 入口和相关测试；lmmcp 作为个人本地记忆总线，不再维护半成品 RBAC。
- [x] 修复前端 `/api/vector/search` 的 `score_threshold` 参数传递：已改为关键字参数并补前端 API 回归测试，避免第三个位置参数误传为 `filters`。
- [x] 自动生成 MCP 工具文档：新增 `scripts/generate_tools_doc.py` 从 `server.py` 的 `@mcp.tool()` 函数签名/docstring 生成 `docs/tools.md`，并通过 `tests/test_docs_consistency.py` 的 `--check` 测试确保文档与实际工具列表一致。
- [x] 将 `semantic-*` CLI 改为真实 Qdrant 功能：`semantic-status` 调 `VectorStore.status()`，`semantic-search` 调 Qdrant search，`semantic-index` 调 `memory_rebuild_vectors()`，不再只返回 sqlite-vec 移除提示。
- [x] 不新增 LLM 全自动记忆治理管线：继续强化现有规则型 `curator` / `rollup`，优先做可解释、可回滚的状态迭代、归档、重复检测、重要性调整和总结沉淀；本轮已通过 prompt 评测集、rollup 测试隔离、curator/tool 面收敛延续该方向。
- [x] `start.sh` 默认安装运行依赖 `.[all]`：一键启动已包含 Qdrant vector 与 extraction 能力，避免新设备只装 `.[extraction]` 导致语义检索降级；`sentence-transformers` 大依赖改为显式 `.[embedding]` / `.[full]`。
- [x] 明确 audit 导入策略：`memory_export(include_audit=True)` 可导出 `audit_events`，但 `memory_import()` 不导入本机审计日志，并在返回结果与导入审计事件中报告 `ignored_tables=["audit_events"]`，避免静默丢弃。
- [x] `start.sh` 增加 venv 路径漂移检测：若 `.venv/bin/pytest` / `.venv/bin/pip` shebang 指向旧 checkout 路径，或 `.venv/bin/python` 不可运行，则自动重建 `.venv`，避免 bad interpreter。
- [x] 收敛 MCP 工具面但不引入 admin profile：已删除 `agent_permission_*`、`memory_update_status`、`memory_consolidate`，将状态更新并入 `memory_update`，将去重/低反馈报告并入 `memory_curator_report`，避免新增角色/权限复杂度。

## 发布与部署

- [x] PyPI 首次发布（打 tag 触发 publish workflow，验证安装可用）：v0.25.0 已通过 GitHub Actions `Publish to PyPI` run `26746195311` 发布成功；`pip index versions local-memory-mcp` 显示 `0.25.0`，临时 Python 3.11 venv 执行 `pip install "local-memory-mcp[all]==0.25.0"` 成功，import 路径为 venv `site-packages/local_memory_mcp/__init__.py`。Trusted Publishing 路线仍可后续补配；当前发布使用 GitHub Secret `PYPI_API_TOKEN`，不得将明文 token 写入仓库。
- [x] 修复 CI 并发写入偶发锁库失败：GitHub Actions main/tag CI 中 `test_concurrent_writes_no_corruption` 偶发 `sqlite3.OperationalError: database is locked`；已提高 SQLite busy timeout，并用进程内 reentrant lock 串行化 `managed_conn()` 写事务，保留 commit retry。
- [x] 修复 GitHub Actions CI 依赖安装缺口：tag/main CI 只安装 `requirements.txt`，缺少项目依赖导致 `ModuleNotFoundError: No module named 'yaml'`；已改为安装 `.[dev,all]`，让 CI 与当前 package metadata 对齐。
- [x] 修复 PyPI publish workflow checkout 权限缺口：publish job 只声明 `id-token: write` 会覆盖默认权限，tag workflow 中 `actions/checkout` 无法读取私有仓库并报 repository not found；已补 `contents: read`。
- [x] Docker Compose 完善：`docker-compose.yml` 默认启动 lmmcp + Qdrant，Dockerfile 安装 `.[all]`，Compose 环境设置 Qdrant endpoint 与持久化 volume。
- [x] Docker Compose 容器端到端验证：2026-06-01 已修复 Docker daemon 过期代理 IP、Compose 远程绑定 auth token 缺口、容器内 `QDRANT_URL` 未被配置层读取的问题，并给 Dockerfile pip 下载补充 timeout/retries。临时 Compose E2E 使用 18318/16333/16334 端口验证通过：`/health` 返回 ok，MCP `initialize` 成功，`memory_vector_status` 返回 `available=true`、`url=http://qdrant:6333`、`collection=agent_memory`，`memory_add` 后 `memory_vector_search` 可查回 `LMMCP-DOCKER-E2E-QDRANT-20260601-1311`。
- [x] README 补充 PyPI 安装说明；Docker Compose 快速启动文档已补，README 已补发布后可用的 `pip install "local-memory-mcp[all]"` / `"[full]"` 安装命令。
- [x] `deploy.sh` 安装默认 Python extras：部署脚本现在在 `requirements.txt` 后继续执行 `pip install -e ".[all]"`，确保 Qdrant 与 extraction 随一键部署补齐；`sentence-transformers` fallback 作为显式重依赖 extra 安装。
- [x] `deploy.sh` 默认自动补齐运行时依赖：一键部署默认开启 host 依赖 bootstrap、Docker/Qdrant service、Ollama 安装/启动与 embedding 模型拉取，并提供 `--no-bootstrap-deps`、`--no-ollama`、`--no-qdrant`、`--no-pull-*` 作为显式降级开关。
- [x] 修复 `.[all]` 安装过重/卡住问题：`sentence-transformers` 作为默认 all extra 会触发大包下载，在当前环境长时间无进展；现已将 `.[all]` 收敛为 vector + extraction，新增 `.[full]` 并保留 `.[embedding]` 作为显式本地 fallback 安装路径。

## UI 风格重构 — Claude 设计语言

> 背景：当前 UI 沿用 OpenMemory fork 的紫色主题（`--primary: 260 94% 59%` 即亮紫），整体是 zinc-900/950 暗底 + 紫色高亮。需要改为 Claude 风格：暖米色/沙色为主调，橙棕色作为 accent，圆润卡片，柔和排版，去掉硬科技感。
> Claude 设计语言参考：背景 `#F5F0E8`（暖纸色），卡片 `#FFFFFF`，accent `#DA7756`（Claude 橙），文字 `#2D2B28`（暖黑），辅助文字 `#8B8680`，border `#E8E0D4`，圆角 `12-16px`，字体 Söhne/Inter。

- [x] 替换 CSS 变量色板：`globals.css` 中 `--primary` 从紫色改为 Claude 橙 `#DA7756`，`--background` 改为暖米色，`--card` 改为白色，`--border`/`--muted` 改为暖灰
- [x] Navbar 重构：去掉 zinc-950 暗底，改为白底 + 底部细线分隔；logo 改用暖色调；导航按钮改为文字链接 + hover 下划线
- [x] Dashboard 页（`app/page.tsx` + `Install.tsx`）：Memory Operations 卡片改为白底圆角卡，统计数字用 Claude 橙色高亮；Curator 区域简化
- [x] Memories 列表页（`app/memories/`）：表格改为卡片式列表，搜索栏用圆角输入框 + 暖灰边框；分类 badge 改为柔和色调的 pill
- [x] Apps 页（`app/apps/`）：Agent Activity 表格改为白底卡片列表；status badge 保留语义色但柔化
- [x] Memory 详情页（`app/memory/[id]/`）：内容区域用左竖线引用样式，metadata 区域收起折叠；RelatedMemories 改为卡片网格
- [x] Settings 页：表单控件对齐 Claude 风格——圆角输入框、暖色 toggle/switch
- [x] 全局字体：优先 Inter，回退 system-ui；去掉 monospace 硬编码

## 记忆图谱可视化

> 背景：后端有 `memory_links`（14 条：related_to/supports/contradicts）和 `memory_entities`（78 条），但 UI 没有图形化展示。需要一个力导向图页面，展示记忆之间的关系网络和实体聚类。

- [x] 新增 `/graph` 页面，Navbar 加入入口
- [x] 后端新增 `/api/graph` 端点：返回 `{nodes: [{id, title, type, status}], edges: [{source, target, relation_type, weight}]}` 格式，合并 memories + links 数据
- [x] 前端用 force-directed graph 库（d3-force 或 react-force-graph）渲染节点和连线
- [x] 节点按 memory type 着色，边按 relation_type 区分样式（实线/虚线/颜色）
- [x] 支持点击节点跳转到 `/memory/{id}` 详情页
- [x] 支持缩放、拖拽、搜索高亮

## Atomization Backfill — 数据质量

> 背景：atomization 代码已完成（`storage/atomization.py`，252 行），`memory_atomize_report` MCP 工具已注册，但从未对历史数据运行过。当前 1044 条记忆中 0 条 atomic facts，14 条 links，78 个 entities。长记忆中的局部事实被整段 embedding 稀释，召回质量受限。

- [x] 对 active 记忆执行 dry-run atomization：`memory_atomize_report(dry_run=true, limit=500)`，评估可拆分的 parent 数量和预期 child facts 数量
- [x] 检查 atomization 质量：抽样 5-10 条长记忆的拆分结果，确认 child facts 自包含、无信息丢失、hash 去重有效
- [x] 执行 apply：`memory_atomize_report(dry_run=false, limit=500)` 对历史长记忆实际拆分，生成 atomic facts + parent/child links
- [x] 验证 child facts 写入 Qdrant 向量索引：`memory_vector_audit(dry_run=true)` 检查 SQLite/Qdrant 一致性
- [x] 修复 `memory_entities` 表在生产库缺失问题：当前只有旧路径 `~/.agent-memory/local-memory-mcp/memory.sqlite3` 有该表的空壳，生产库 `project/memorycore/memory.sqlite3` 虽有表但仅 78 条，需检查 entity 提取是否在写入路径中正常触发
- [x] 对 active 记忆重新运行 entity 提取，填充 entity/alias 索引
- [x] 运行 `memory_context` 对比测试：atomization 前后，查询 `local_memory`/`lmmcp`/端口/路径 等关键词的召回命中率变化

## 性能与并发（迭代 96 后续）

- [x] `WAL checkpoint` 策略优化：`wal_autocheckpoint=0` + 后台 PASSIVE checkpoint 线程每 60 秒触发
- [x] `build_context_pack` 中 extra_records 补充查询改用 `read_conn`
- [x] LLM Curator job registry TTL 清理：`_cleanup_stale_llm_jobs()` 在 30 分钟后清除 succeeded/error 的 job
- [x] `_write_injected_counts` / `_write_last_accessed` 改为共享 `queue.Queue(maxsize=2000)` + 单消费者线程，atexit 保证退出时 drain
- [x] `atomize_record` 批量写入时传入共享 `conn` 复用事务，`_existing_fact_hashes` 改用 `read_conn`

## LLM Curator 改进（迭代 96 后续）

- [x] 语义去重：返回 `merge_info` 字段（被丢弃记忆的补充信息），action 升级为 `archive_and_merge_duplicate`
- [x] 拆分执行：LLM 对每条子记忆单独评分 `importance`，不再继承 parent 均值
- [x] 已审查记忆冷却期机制：`_reviewed_memory_ids` dict + `_REVIEW_COOLDOWN_SECONDS=7200`，避免同批重复评估
- [x] `_find_semantic_duplicate_candidates` 大库（>500 条）采样 200 条限制候选池，同样适用于 contradiction 检测
- [x] LLM Curator 结果面板支持"✓ 接受"/"✗ 拒绝"单条 finding；后端新增 `/api/curator/llm/apply-single` 端点

## Graph 图谱改进（迭代 96 后续）

- [x] Graph 高 importance 节点常驻 Sprite 标签（Three.js CanvasTexture，gold 文字，悬浮于节点上方）
- [x] Graph status 筛选按钮（All / active / candidate / stale）
- [x] Graph 导出 JSON（filteredNodes + filteredEdges 下载为 memory-graph.json）
- [x] Graph 侧边栏支持内联编辑 importance（滑块）和 status（下拉），PATCH `/api/v1/memories/{id}`
- [x] 图谱初始化预稳定：`cooldownTicks(300)` + `onEngineStop` 触发 `onReady`，显示"布局计算中…"覆盖层

## UI/UX 改进（迭代 96 后续）

- [x] 记忆列表 Created On 列点击切换 asc/desc 排序，显示方向箭头
- [x] LLM Curator 面板 findings 超过 20 条时收折，"显示全部 (N 条)"展开
- [x] Dashboard Curator Operations 卡片：Manual run 默认展示 3 条 actions，"查看全部 (N 项)"展开
- [x] 记忆列表 page size 选择器已完整（PageSizeSelector.tsx 已实现并接入 MemoriesSection）
- [x] LLM Curator job 恢复时显示"正在恢复任务状态..."loading 提示（animate-pulse）

## 测试覆盖

- [x] `test_search.py`：`test_last_accessed_at_concurrent_write_consistency`（10 线程并发写回，无异常）
- [x] `tests/test_curator_llm_jobs.py`：冷却期注册/检测/过期逻辑单元测试，大库采样 warning 测试（3 passed, 1 skipped by design）
- [x] `test_graph_enhanced.py`：`TestGraphAPI` 集成测试（节点返回、importance 字段、edges 列表）
- [x] `test_extraction.py`：6 个参数化 URL 拼接测试（带/不带 `/v1`、trailing slash、port）


---

## Bug 审计剩余项 — 2026-06-05

### 🟠 High — 后端并发/性能（大改）

- [x] **[backend] search.py** — `build_context_pack` 内用同步 `ThreadPoolExecutor + .result()` 阻塞事件循环；已通过 `_dispatch_api_sync` + `asyncio.to_thread` 整体迁移到线程池，事件循环不再阻塞
- [x] **[backend] frontend.py** — 所有 API handler 在 `async def frontend_api` 中直接调同步 SQLite 函数，阻塞事件循环；`_dispatch_api` 改为 async 包装层，所有同步工作在 `asyncio.to_thread` 中运行
- [x] **[backend] atomization.py:147** — `atomize_record` 加模块级 `_atomize_lock`，函数串行化消除 TOCTOU 窗口

### 🟡 Medium — 性能

- [x] **[perf-backend] vector_store.py:382** — Qdrant 连接加 30 秒冷却期，失败后静默跳过，消除高频 ERROR 日志
- [x] **[perf-backend] vector_store.py:434** — 新增 `upsert_batch` 方法，批量写场景单次 HTTP 请求
- [x] **[perf-frontend] Graph3D.tsx:288** — 搜索输入拆分为即时 `searchInput` + 300ms debounced `search`，keystroke 不再触发 3D 图重建
- [x] **[perf-frontend] page.tsx:386** — 左侧节点列表接入 `@tanstack/react-virtual`，虚拟滚动仅渲染可见条目

### 🔵 Low — 其他

- [x] **[backend] db.py:83** — `_LOCK_RETRY_ATTEMPTS` 从 10 改为 3，最长持锁从 4.5s 降至 0.6s
- [x] **[ui-ux] page.tsx** — Graph 移动端：虚拟滚动 + 面板约束降低小屏溢出影响（完整三栏响应式留后续）
- [x] **[test] dedup.py** — 新增 `TestIngestIdConsistency`：验证 update/add 分支 Qdrant id 与 SQLite memory_id 一致
- [x] **[test] curator_llm.py** — 新建 `tests/test_curator_apply.py`：smoke test `apply_llm_curator(dry_run=False)` split 分支
- [x] **[test] transfer.py** — `tests/test_sync.py` 追加 `null confidence` 和 `invalid_status` malformed import 边界测试
- [x] **[mcore] branding** — MCP server 命名空间归一，工具前缀变更为 `mcp__mcore__`，清理旧版 local-memory-mcp 垃圾和配置文件
