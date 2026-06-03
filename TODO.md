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

- [ ] `WAL checkpoint` 策略优化：当前 `wal_autocheckpoint=500` 在高频写场景下偶发短暂停顿，可改为 `PASSIVE` 模式并在低峰后台触发
- [ ] `build_context_pack` 中 extra_records 补充查询仍用 `managed_conn`，改为 `read_conn`
- [ ] LLM Curator job registry 无 TTL 清理：`_llm_curator_jobs` dict 会无限增长，应在 succeeded/error 后 30 分钟自动清除
- [ ] `_write_injected_counts` / `_write_last_accessed` daemon thread 在进程退出时可能丢失最后几条写回，考虑改为共享队列 + 单写线程
- [ ] `atomize_record` 在批量写入时产生过多独立事务（每个 child 一次），应传入 `conn` 复用事务

## LLM Curator 改进（迭代 96 后续）

- [ ] 语义去重：当前只做"是否重复"二分判断，应返回"保留哪个 + 合并补充信息"，对高 importance 记忆不直接归档而是合并内容
- [ ] 拆分执行：目前 split 时子记忆 `importance` 直接继承 parent 均值，应让 LLM 对每条子记忆单独评分
- [ ] LLM Curator 应每次随机打乱候选顺序（已实现），但还缺少"已审查记忆跳过冷却期"机制，避免同一批记忆被重复评估
- [ ] `_find_semantic_duplicate_candidates` 对大库（>1000 条）每条都做向量搜索，O(N) Qdrant 请求；改为批量 clustering 或限制候选池
- [ ] LLM Curator 结果面板应支持"接受/拒绝"单条 finding，而不只是全量 apply

## Graph 图谱改进（迭代 96 后续）

- [ ] Graph 节点标签：当前只在 hover 时显示，高 importance 节点应常驻显示 title（Three.js Sprite/CSS2DRenderer）
- [ ] Graph 节点缺少 status 过滤（candidate/stale 节点也在图中），应加 status 筛选按钮
- [ ] Graph 导出功能：截图保存或导出 JSON 供外部分析
- [ ] Graph 侧边栏详情：目前只读，应支持直接编辑 importance/status
- [ ] 图谱初始化时节点聚集在中心（3D force 模拟未收敛），应在后端预计算初始坐标或在前端增加"稳定后显示"状态

## UI/UX 改进（迭代 96 后续）

- [ ] 记忆列表 Created On 列支持点击排序切换 asc/desc（目前只能通过 URL 参数控制）
- [ ] LLM Curator 面板 findings 超过 20 条时应分页或收折，避免长列表导致滚动体验差
- [ ] Dashboard Curator Operations 卡片：Manual run 展示最多 3 条 actions，应加"查看全部"展开
- [ ] 记忆列表 page size 选择器（当前 20，可选 50/100/全部）
- [ ] 页面刷新后 LLM Curator job 轮询能自动恢复（已实现），但 UI 缺少"正在恢复中..."的 loading 状态提示

## 测试覆盖

- [ ] `test_search.py`：补充 `last_accessed_at` 异步写回的并发一致性测试
- [ ] 补 LLM Curator job 轮询逻辑的单元测试（mock job registry）
- [ ] Graph API `/api/graph` 补集成测试（节点数量、edge 过滤、importance 字段）
- [ ] `extraction.py` URL 路径拼接逻辑补参数化测试（带/不带 `/v1` 前缀）

