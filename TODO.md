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

## 画像召回融合（2026-08-24 unified plan F 组）

> 画像层基础（user_profile_attrs 表 + profile.py + 快照注入 + Profile Tab）已落地于前迭代；本批为画像参与检索的 F 组增强。

- [x] **[F1]** 画像参与召回排序：纯本地 rerank（零 LLM）——`profile_feature_words()` 从高置信画像属性提取特征词；`profile_overlap_ratio()` 计算记录与画像特征词重叠度（3 词封顶 1.0）；`_rank_score` 加 `overlap × profile_boost_weight`（config `context_pack.profile_boost_weight`，默认 0.15 可调可关）；user_profile 型记忆与画像矛盾时 `× profile_conflict_penalty`（默认 0.6）
- [x] **[F2]** 画像驱动查询扩展：`profile_query_expansion()` 从任务与画像属性值词重叠推导 ≤3 个扩展短语（属性名命中或值 token 重叠 ≥ min_overlap）；FTS 按扩展短语**独立检索**再合并去重（不收紧 AND 查询），记录标 `profile_expand` 源
- [x] **[F4]** 画像冲突过滤：`profile_conflict_for_record()` 启发式检测（属性名出现但画像值 token 全缺席 → 矛盾候补）；`build_context_pack` 对矛盾 user_profile 记忆不注入正文、转入 `type=profile_conflict` warnings（带属性名与当前画像值）；默认只查高置信属性，`only_immutable` 可收紧
- [x] F1/F2/F4 trace 诊断字段：`profile_boost_weight` / `profile_query_expansions` / `profile_conflict_filtered`

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
- [x] Graph 全状态性能优化：页面可控制节点加载上限；后端按高价值节点排序并只返回当前节点集合内的边；大图渲染缓存 glow 纹理/材质、减少 shader 动画与边粒子开销

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

## UI i18n 全局中英文切换

> 背景：用户要求给 mcore 添加 i18n 功能，支持全局语言切换中英文。已通过 CCG 咨询 Codex/Gemini，采纳“无路由 locale、无新增依赖、typed dictionary + React Context + localStorage 持久化”的轻量方案。当前已接入应用并完成基础页面覆盖。

- [x] 新增 `ui/lib/i18n/dictionaries/zh.ts`：与 `en.ts` 结构一致，用 `satisfies Messages` 保证中英文 key 完整一致。
- [x] 新增 `ui/lib/i18n/I18nProvider.tsx`：负责 locale state、`localStorage(memorycore.locale)` 持久化、`navigator.language` 初始推断、更新 `document.documentElement.lang`。
- [x] 新增 `ui/hooks/useI18n.ts`：导出类型安全的 `useI18n()` hook，缺少 provider 时 fail fast。
- [x] 接入 `ui/app/providers.tsx`：在 Redux `Provider` 内包裹 `I18nProvider`，避免在 store 初始化阶段读取 `window`。
- [x] 扩展 `ui/store/uiSlice.ts`：增加只用于观测的 `language.locale` 与 `setLocale` action；持久化仍由 i18n provider 负责。
- [x] 新增 `ui/components/LanguageSwitcher.tsx`：使用现有 Radix/shadcn `Select`，放到 Navbar refresh/create 操作区附近，具备 `aria-label` 和 EN/中文选项。
- [x] 迁移 `ui/components/Navbar.tsx`：导航项、Refresh/Refreshing、刷新成功 toast 使用 `useI18n()`；App 名称 MemoryCore 不翻译。
- [x] 迁移 `ui/app/memories/components/CreateMemoryDialog.tsx`：按钮、标题、说明、label、placeholder、toast、保存/取消文案使用字典；用户输入内容不翻译。
- [x] 迁移 Memories 主要列表页：`MemoryFilters`、`MemoryTable`、`MemoriesSection`、`PageSizeSelector`、`MemoryPagination` 的搜索 placeholder、表头、分页、empty state、批量操作、状态 tooltip 等静态文案。
- [x] 迁移 Apps 页 app chrome：`ui/app/apps/page.tsx` 标题/描述；App 名称、ID、后端枚举原值不翻译，只翻译展示 label。
- [x] 迁移 Settings 页：标题/描述、Reset/Save、AlertDialog、toast、API Connection、Form/JSON tab 等静态文案。
- [x] 迁移 Dashboard 高频文案：`Stats.tsx`、`Install.tsx`、`MemoryIntelligenceCenter.tsx` 中标题、按钮、状态说明；curator/LLM 返回的 reason/title/raw 内容保持原样。
- [x] 改造相对时间：`formatDate` 支持 `locale === "zh" ? "zh-CN" : "en-US"`，避免主要列表固定英文。
- [x] 增加 Playwright i18n 覆盖：默认 `html[lang="en"]`；切到中文后 Navbar 可见中文且 `html[lang="zh-CN"]`；刷新后 localStorage 保持中文；切回英文不破坏现有 smoke selectors。
- [x] 验证：`ui/` 下 `pnpm exec tsc --noEmit` 与 `pnpm build` 均通过；后端目标测试通过。
- [x] 完成后在 `ITERATION.md` 追加实际完成记录；TODO 只保留未完成项或打勾。

## 已发现待修复问题

- [x] 修复 UI TypeScript 全量 typecheck 的 `react-icons` JSX 兼容问题：新增 `ui/components/shared/react-icons.tsx` typed wrapper，统一适配 React 19 / react-icons `ReactNode` 返回类型；`pnpm exec tsc --noEmit` 已通过。
- [x] Dashboard 首次打开 loading 卡死：首屏加载增加 dashboard refresh token、AbortController + timeout、Install/useStats loading 收尾，避免 skeleton 一直卡住。
- [x] Dashboard 后续成熟化：增加健康分趋势/分解、duplicates/contradictions/never accessed/LLM curator duration 视图、可点击 drill-down、导出治理报告、按风险排序的 review queue。
- [x] 数据质量后续治理：LLM split 子记忆补 parent/child links，LLM duplicate archive 写 merge audit，LLM finding 支持批量接受/拒绝，并自动归档同 parent+fact_hash 的历史重复 atomic facts。

## Temporal Governance Engine — Phase 1 Foundation

> 背景：记忆系统需要从“被动检索库 + 人工审查工具”升级为“时间线事实系统 + 可审计治理”。Phase 1 只做低风险基础能力，不引入 LLM 自动改库：明确 superseded 状态、事实 lineage、recency 软排序、curator supersession 候选、审计与测试。

- [x] 增加 `superseded` 状态：扩展模型状态校验、非 active 向量同步删除、搜索默认排除，作为“已被新事实替代”的明确生命周期状态。
- [x] 增加 `superseded_by` 与 `fact_lineage_root` 字段：初始化新库与老库迁移都补齐字段，支持记录旧事实被哪条新事实替代以及事实链根节点。
- [x] 增加事实 lineage / supersede 基础操作：提供内部函数查询某条记忆的前驱/后继链，并提供可审计的 supersede 操作，避免直接删除旧记忆。
- [x] Context Pack 排序加入 `recency_score`：新记忆获得小权重加成，但不能压倒文本相关性、importance、effectiveness 和 feedback。
- [x] Curator 增加 supersession candidate：对同 scope/project/type/title-key 的 active 新旧记忆生成可解释候选，不自动处理高价值类型。
- [x] MCP/API 暴露最小必要能力：优先复用 `memory_timeline` / `memory_update` / `memory_curator_report`，仅在确有必要时新增 lineage 查询工具，避免继续膨胀工具面。
- [x] 补测试与文档记录：覆盖状态校验、schema 迁移、supersede audit、context recency 排序、curator candidate；完成后追加 `ITERATION.md`。

## Temporal Governance Engine — Phase 2 LLM Governance Decision

> 背景：Phase 1 已具备 lineage / supersede / recency / supersession candidate。Phase 2 目标是让 LLM 只做结构化语义判断，由 deterministic policy gate 决定 auto-approve / human-review / reject，并且所有治理动作可审计、可回滚；LLM 不直接写 SQL、不直接改库。

- [x] 新增治理决策模型：设计 `governance_decisions` 持久化结构或等价存储，记录 source ids、decision type、recommended action、LLM confidence、risk level、review status、policy reason、LLM trace、before/after state、rollback snapshot、applied/rolled_back 时间。
- [x] 抽出 deterministic policy gate：根据 action type、confidence、risk、memory type、importance、feedback、scope/project 判断 `auto_approved` / `needs_review` / `rejected`。
- [x] 将 LLM curator finding 转换为 governance decision：保留原始 finding、LLM rationale、raw response 指针，禁止 LLM 直接执行数据库写入。
- [x] 增加治理 apply / reject / rollback 基础接口：复用现有 LLM curator apply-single / batch 能力，写入 audit event，并支持低风险 auto-apply。
- [x] 为 high-value / precious memory 加强人工审查保护：`user_profile`、`decision`、`project_memory`、高 importance 记忆、merge/delete 类动作必须进入 review queue。
- [x] 补 Phase 2 测试：policy gate 分支、decision 持久化、auto-approved apply、needs-review 不改库、reject/rollback 审计。

## Temporal Governance Engine — Phase 3 Auto-Supersession

> 背景：Phase 1 只报告 supersession candidate，Phase 3 允许在高置信、低风险场景中自动 supersede 旧事实；中等置信冲突继续进入治理队列，避免误伤高价值记忆。

- [x] 配置化 auto-supersession 阈值：新增 `temporal.auto_supersede_threshold`、`temporal.review_similarity_threshold`、`temporal.auto_supersede_enabled`，默认保守关闭或仅低风险开启。
- [x] 写入路径接入候选检测：在 `memory_add` / `memory_ingest` 后对同 type/scope/project 的 active 记忆做语义/词法候选查找。
- [x] 高置信自动 supersede：相似度达到阈值且非 precious / 非高 importance 时调用 `supersede_memory_record()`，并写入 governance/audit 记录。
- [x] 中等置信进入 review：相似度在 review 区间时创建 contradiction / supersession governance decision，不自动改状态。
- [x] 保障向量索引一致性：被 superseded 的旧记录从 Qdrant 删除，新 head 保留 active 向量，rollback 后能重建索引。
- [x] 补 Phase 3 测试：阈值命中、阈值未命中、precious 跳过、review decision 创建、Qdrant 不可用降级、lineage 链连续性。

## Temporal Governance Engine — Phase 4 Auto-Governance Cockpit UI

> 背景：Phase 2/3 后端具备治理决策与自动处理能力，Phase 4 将 Dashboard 从 manual-review-first 改为 Auto-Governance Cockpit：系统默认自动处理低风险项，只让用户审查少量高风险项，并提供完整 audit / undo / lineage 解释。

- [x] 新增 `/governance` Auto-Governance Cockpit MVP：治理指标、决策队列、决策详情、before/after、LLM trace、lineage、audit、Apply/Reject/Rollback 操作入口。
- [x] 拆分 `MemoryIntelligenceCenter.tsx`：抽出 `HealthMetricsPanel`、`ReviewFlowPanel`、`CurationActivityPanel`、`SourceBreakdownPanel`、`AutoAppliedStrip`、`Primitives` 等小组件到 `intelligence/` 目录，主文件从 994 行降至 292 行。
- [x] 增加 Auto-Applied 区：新增 `AutoAppliedStrip` 组件，展示最近自动执行的 stale/archive/supersede/reweight/split/promote 动作，每条显示操作类型 badge、摘要、时间戳和 Undo 按钮，底部链接到 `/governance`。
- [x] 增加 Needs Human Review 队列：治理页已具备 `actionable` 筛选、批量 Apply/Reject、一键应用全部、优先级排序，Dashboard ReviewFlowPanel 链接到 `/governance`。
- [x] 增加 lineage 展示：记忆详情页新增 `MemoryLineage` 组件，以垂直时间线展示 supersession 链，标注 Root/Head 节点；治理 Sheet History tab 增强 lineage 链展示。
- [x] 增加 Undo / rollback UI：`AutoAppliedStrip` 每条 auto-applied action 显示 Undo 按钮（`canRollbackDecision()` 判断），调用 `POST /api/governance/{id}/rollback`，成功后移除条目。
- [x] 保持 Claude 设计语言与 i18n：新增文案进入 typed dictionary，确保中英文 key 完整一致。
- [x] 补 Phase 4 验证：`pnpm exec tsc --noEmit` 零错误，`pnpm build` 9/9 路由通过，后端 `test_governance` / `test_governance_foundation` / `test_frontend` / `test_docs_consistency` 42 passed。

## 向量相似度召回增强 — Context Pack Hybrid Retrieval V2

> 背景：`build_context_pack` 已有三路并发召回（FTS5 + Qdrant vector + entity），但向量分数在排序阶段被弱化——FTS 命中的记录直接用 lexical score 替代了向量分数，向量只对 vector-only 记录生效。需要让向量相似度作为独立且贯穿的召回信号，提升语义近似但词法不匹配的记忆召回率。

### Step 1：向量分数贯穿排序（核心改动）

- [x] **`_rank_score` 融合向量分数为独立信号**：当前第 688 行 `vscore = lexical if text_matched else vector_hits.get(...)` 把 FTS 命中记录的向量分数完全丢弃了。改为：所有记录都取 `vector_score = vector_hits.get(r["id"], 0.0)`，与 `lexical` 分开参与加权。新公式：`vector_score * W_vec + lexical * W_lex + entity_boost + source_bonus + ...`，其中 `W_vec` 和 `W_lex` 需要调参（建议初始 `W_vec=0.30, W_lex=0.35`，留 `0.35` 给其余信号）。
  - 文件：`memorycore/storage/search.py` `_rank_score()` 函数
  - 影响：排序逻辑变更，需回归测试 `tests/test_context_relevance.py`

- [x] **交叉验证加成（cross-retrieval boost）**：同时被 FTS 和 vector 两路命中的记录，说明词法和语义都匹配，应获得额外加成。当前 `source_bonus` 只按来源类型给固定 0.08/0.06，改为：`multi_source_bonus = 0.12 if ("fts" in sources and "vector" in sources) else 0.0`，叠加在现有 source_bonus 上。
  - 文件：`memorycore/storage/search.py` `_rank_score()` 函数

- [x] **向量召回阈值跟随 retrieval_mode 变化**：当前 `_VECTOR_SEARCH_THRESHOLD = 0.35` 是硬编码常量，`_fetch_vector` 调用时不区分 mode。改为：`mode_settings` 中增加 `vector_search_threshold` 字段（strict=0.40, balanced=0.35, recall=0.25），传入 `_vector_search_ids(task, top_k=..., score_threshold=mode_settings["vector_search_threshold"])`。
  - 文件：`memorycore/storage/search.py` `build_context_pack()` 的 mode_settings 和 `_fetch_vector` lambda

### Step 2：向量分数透出与可观测性

- [x] **trace 中增加向量召回质量指标**：在返回的 `trace` dict 中新增 `vector_avg_score`（向量命中的平均分）、`vector_max_score`（最高分）、`cross_retrieval_count`（FTS+vector 交叉命中数）、`vector_only_count`（仅向量命中数）、`fts_only_count`（仅 FTS 命中数）。
  - 文件：`memorycore/storage/search.py` `build_context_pack()` 返回值 trace 部分

- [x] **slim_records 中保留 `_retrieval_sources` 和 `_vector_score`**：让调用方（hook、前端）能看到每条记忆是从哪条通道召回的、向量分数是多少。
  - 文件：`memorycore/storage/search.py` slim_records 构造部分

- [x] **context_quality_events 表增加向量维度字段**：`_record_context_quality_event` 新增 `vector_avg_score`、`cross_retrieval_rate`，写入 `context_quality_events` 表。需要 schema migration。
  - 文件：`memorycore/storage/search.py`、`memorycore/storage/db.py`（schema migration）

### Step 3：向量相似度聚合（去重展示）

- [x] **高相似度记忆聚类展示**：在 context pack 输出阶段，对同 group 内向量相似度 > 0.85 的记忆做聚合：只展示分数最高的一条，其余折叠为 `[+N related]` 计数。节省 token budget，避免重复信息占满上下文窗口。
  - 实现方式：在 `build_context_pack` 的分组输出循环（第 776-803 行）前，增加一个 `_cluster_similar_records(records, vector_hits, threshold=0.85)` 步骤，返回 `[(primary_record, [clustered_ids])]`。
  - 聚类算法：简单贪心——按分数降序遍历，每条记录查 `vector_hits` 中与已选 primary 的余弦相似度，超过阈值则归入该 cluster。不需要完整 N×N 矩阵（太贵），只需对 vector_hits 中的 ID 对做 Qdrant point-to-point 查询或用嵌入缓存比较。
  - 文件：`memorycore/storage/search.py` 新增 `_cluster_similar_records()` 函数

- [x] **聚合阈值可配置**：在 `config.yaml` 的 `context_pack` 部分新增 `cluster_similarity_threshold`（默认 0.85）和 `cluster_enabled`（默认 true）。
  - 文件：`memorycore/models.py`（config 校验）、`memorycore/storage/search.py`（读取配置）

- [x] **聚合结果透出到 trace**：trace 新增 `clustered_count`（被折叠的记忆数）、`cluster_groups`（聚类组数）。
  - 文件：`memorycore/storage/search.py` trace 部分

### Step 4：向量召回扩展能力

- [x] **支持 embedding 缓存避免重复嵌入**：`_vector_search_ids` 每次调用都对 task 做一次嵌入。增加 LRU 缓存（`functools.lru_cache` 或手动 dict，maxsize=128，TTL=300s），对相同或高度相似的 task 文本复用嵌入向量。
  - 文件：`memorycore/vector_store.py` 或 `memorycore/storage/search.py`

- [x] **向量召回 fallback 策略优化**：当 Qdrant 不可用时，当前直接返回空列表。增加降级日志 + trace 标记 `vector_fallback: true`，让调用方知道本次召回缺少语义通道。
  - 文件：`memorycore/storage/search.py` `_vector_search_ids()` 和 trace

- [x] **支持 task 拆分多轮向量查询**：对长 task 文本（>200 字符），拆分为 2-3 个语义片段分别做向量查询，合并去重。提升长 prompt 的召回覆盖面。
  - 文件：`memorycore/storage/search.py` `_vector_search_ids()` 或新增 `_multi_segment_vector_search()`

### Step 5：测试与验证

- [x] **更新 `tests/test_context_relevance.py` 回归用例**：覆盖新权重公式、交叉验证加成、mode 阈值变化
- [x] **新增 `tests/test_vector_context_integration.py`**：专项测试向量召回在 context pack 中的端到端行为，包括：
  - 向量-only 记忆能通过新阈值被召回
  - FTS+vector 交叉命中获得更高排名
  - 高相似度记忆被正确聚合
  - Qdrant 不可用时降级不报错
  - retrieval_mode 切换影响向量阈值
- [x] **新增 `tests/test_vector_clustering.py`**：测试 `_cluster_similar_records` 的聚类正确性、边界条件（空记录、单条记录、全部相似、全部不同）
- [x] **真实 prompt 对比测试**：用现有评测集 `tests/fixtures/context_relevance_cases.json` 在改动前后运行，对比 `hit_rate`、`vector_avg_score`、`cross_retrieval_count` 变化

### 优先级与依赖关系

```
Step 1（核心排序改动）→ Step 2（可观测性）→ Step 5（测试）
                                              ↑
Step 3（聚合展示）────────────────────────────┘
Step 4（扩展能力）— 独立，可与 Step 1-3 并行
```

建议执行顺序：**Step 1 → Step 2 → Step 5（前三步的测试）→ Step 3 → Step 5（聚合测试）→ Step 4**

## 全链路时间感知增强

> 背景：LLM curator 的去重/矛盾/重要性/拆分四个能力虽然 prompt 提到 recency 和 temporal supersession，但实际不传 `created_at`/`updated_at` 给 LLM，时间维度名存实亡。Context pack recency 权重仅 0.05（上限 0.10），时间几乎只是 tiebreaker。前端不暴露 `valid_from`/`valid_until` 编辑能力。本方案通过 `temporal.enabled` 总开关，分阶段将时间意识注入系统的每一个决策点。

### Phase 1: 激活时间配置（前置条件）

- [x] 扩展 `models.py` `DEFAULT_CONFIG["temporal"]`：新增 `recency_half_life_days`(90)、`llm_temporal_prompts`(true)、`dedup_temporal_guard`(true)、`governance_age_risk_days`(7) 配置项
- [x] `config.yaml` 启用 `temporal.enabled: true`

### Phase 2: LLM Curator 时间注入（最高优先级）

- [x] `curator_llm.py` 新增 `_temporal_tag()` 共享时间标签格式化器，输出格式 `[时间: 创建=YYYY-MM-DD, 更新=YYYY-MM-DD, 距今=N天]`，由 `temporal.enabled` 开关控制
- [x] `_fetch_active_memories()` 和 `_fetch_memories_by_ids()` SELECT 追加 `created_at, valid_from, valid_until, last_accessed_at, last_injected_at`
- [x] `_llm_judge_duplicates` 注入 `_temporal_tag` + 中文时间推理 prompt（优先保留更新日期更近的记忆）
- [x] `_llm_judge_contradictions` 注入 `_temporal_tag` + 时间推理 prompt（更新日期更近的记忆更可能正确）
- [x] `_llm_reassess_importance` 注入 `_temporal_tag` + 时间推理 prompt（距今>180天未访问应降级，近30天不应轻易降级）
- [x] `_llm_detect_splittable` 注入 `_temporal_tag`（仅数据可见性，不加额外 prompt）
- [x] 去重 fallback 逻辑：LLM 未指定 `keep_id` 时，temporal 启用下按 `updated_at` 选保留而非 importance

### Phase 3: Rollup 时间推理指令

- [x] `rollup.py` `_call_rollup_llm()` 构建 system_prompt 后追加中文时间推理规则：多版本以 `created_at` 最晚为准，保留变化历程（"从X改为Y"），删除已被取代的过时信息

### Phase 4: Context Pack 检索时间权重提升

- [x] `search.py` `_context_recency_weight()` temporal 启用时默认 0.15（上限 0.30），保留非 temporal 模式原有 0.05/0.10
- [x] `search.py` `_recency_score()` temporal 启用时改为指数衰减（半衰期可配 `temporal.recency_half_life_days`，默认 90 天），非 temporal 保留线性衰减

### Phase 5: Dedup 时间守卫

- [x] `dedup.py` `ingest()` update 分支：temporal 启用时检查已有记录 `updated_at`，若 1 小时内刚更新则降级为 "add with link" 而非覆盖

### Phase 6: 治理时间信号

- [x] `governance.py` `policy_gate()` temporal 启用时：目标记忆创建/更新不足 `governance_age_risk_days`（默认 7 天）且操作为破坏性，追加 `recently_created_memory` reason 强制人工审核

### Phase 7: 前端时间增强

- [x] 后端 `frontend.py` `GET /memories` 追加 `date_from`/`date_to` 参数，映射到 SQL `WHERE created_at >= ? AND created_at <= ?`
- [x] 前端记忆列表 `FilterComponent` 增加日期范围选择器
- [x] 后端 `crud.py` `update_memory_content()` 追加 `valid_from`/`valid_until` 可选参数；`frontend.py` PATCH handler 传递
- [x] 前端记忆详情面板追加 `valid_from`/`valid_until` 日期输入框
- [x] i18n 字典补充时间相关国际化键

### 验证

- [x] Phase 2 验证：`run_llm_curator(apply=False)` dry run，检查 `llm_prompt` 包含 `[时间:]` 标签，`keep_id` 指向更新的记忆
- [x] Phase 4 验证：`memory_context` 对比前后排序，近期更新的记忆应明显靠前
- [x] 全链路回归：`python -m pytest tests/` 确保无回归

## LLM Curator 全面优化 — 2026-06-23

> 背景：深度审计发现 6 个系统性问题、18 个具体缺陷。71% 记忆零图谱链接，keep_id/newer_id 因 ID 截断完全无效，cooldown 只覆盖有发现的记忆导致反复扫描烧 token，去重和矛盾检测两轮独立向量扫描。详细方案见 `docs/plans/2026-06-23-llm-curator-full-overhaul.md`，逐步实施见 `docs/plans/2026-06-23-llm-curator-implementation-steps.md`。

### Phase A: 修复数据损坏风险（P0）

- [x] **[A1]** 修改 `_PROMPT_STYLES` 全部三套 duplicate prompt：`keep_id` → `keep ("A"/"B")`
- [x] **[A1]** 修改 `_PROMPT_STYLES` 全部三套 contradiction prompt：`newer_id` → `newer ("A"/"B")`
- [x] **[A2]** 填充 `_PROMPT_STYLES["aggressive"]`：把四个函数的硬编码 fallback prompt 移入，消除 `if not system:` 分支
- [x] **[A3]** `_llm_judge_duplicates` items_text：移除 `id=xxx[:8]` 截断，改为 `A:` / `B:` 标签
- [x] **[A3]** `_llm_judge_duplicates` 结果解析：`keep_id` → `keep` label 映射（"A"→a["id"], "B"→b["id"]），保留时间/importance fallback
- [x] **[A4]** `_llm_judge_contradictions` items_text：同理移除 ID 截断
- [x] **[A4]** `_llm_judge_contradictions` 结果解析：`newer_id` → `newer` label 映射，无法识别时用 `updated_at` fallback
- [x] **[A5]** 全部四个 `_llm_judge_*` 函数：batch 循环内 JSON 解析从 raise 改为 warning + continue

### Phase B: 消除性能浪费（P0）

- [x] **[B1]** 新增 `_find_candidate_pairs(vs, memories, sim_threshold)` 合并函数，一次向量扫描，按分数区间分流去重/矛盾候选
- [x] **[B1]** 删除旧的 `_find_semantic_duplicate_candidates` 和 `_find_contradiction_candidates`
- [x] **[B1]** 移除矛盾检测 `max(0.60, sim_threshold - 0.12)` 硬编码下限
- [x] **[B2]** `llm_curator_report` 主流程改用合并扫描，增加 `timing` 字典跟踪各阶段耗时
- [x] **[B3]** 全部四个 `_llm_judge_*` 函数增加 `config` 参数，返回 `(results, evaluated_ids)` 元组
- [x] **[B3]** 移除函数内部所有 `from memorycore.models import load_config` 重复调用，统一用传入的 `config`
- [x] **[B4]** 全量冷却：所有经 LLM 评判的记忆（含无发现的）都写入 `curator_review_log`

### Phase C: Prompt 质量提升（P1）

- [x] **[C1]** conservative 和 balanced 的 importance prompt 追加 feedback 保护规则（feedback_score > 0 不应 archive/downgrade）
- [x] **[C2]** `_llm_judge_contradictions` 和 `_llm_reassess_importance` 追加 `_language_instruction()` 后缀（当前只有 duplicate 和 split 有）
- [x] **[C3]** `_temporal_tag()` 支持双语：根据 `output_language` 生成中文或英文标签

### Phase D: 新增图谱建链能力（P1）

- [x] **[D1]** 新增 `_find_link_candidates(vs, memories, sim_threshold, link_upper=0.75, max_pairs=100)`：取 [sim_threshold, link_upper] 区间的对，排除已有链接，优先孤立记忆
- [x] **[D2]** 新增 `_LINK_DISCOVERY_PROMPTS`（三套 prompt_style）和 `_llm_discover_links()` 函数：LLM 判断 related_to/supports/part_of/supersedes/none
- [x] **[D3]** 新增 `_append_link_discovery_requests()`：复用 `memory_link_insert` MutationRequest 建链
- [x] **[D4]** `llm_curator_report()` 主流程集成 link discovery 阶段（去重矛盾之后、split 之前）
- [x] **[D4]** `apply_llm_curator()` 新增 `_append_link_discovery_requests` 调用，`applied` 追加 `link_discoveries_created`
- [x] **[D5]** `CuratorTuningPanel.tsx` 知识图谱预设参数修正：sim_threshold 0.45→0.55, importance_limit 1500→100, temperature 0.5→0.6, prompt_style balanced→aggressive 等

### Phase E: 调度协调（P2）

- [x] **[E1]** `server.py` `_start_auto_curator()` 后台线程移除 `curator_report(dry_run=False)` 调用，rule curator 执行统一由 systemd timer 负责

### Phase F: 收尾优化（P2）

- [x] **[F1]** `_request_from_result()` 从全表遍历 `query_ledger(limit=500)` 改为 `WHERE id = ?` 单条查询
- [x] **[F2]** 硬编码上限配置化：`max_dedup_pairs`(200)、`max_contradiction_pairs`(200)、`max_split_candidates`(100)、`max_link_pairs`(100) 提取到 `llm_curator` 配置段
- [x] **[F3]** `llm_curator_report` diagnostics 追加 `timing`（各阶段耗时 ms）、`cooldown_registered`、`json_parse_failures`

### 验证

- [x] Phase A 验证：`_PROMPT_STYLES` 三套 style 无 `keep_id`/`newer_id`，aggressive 非空字典
- [x] Phase B 验证：`_find_candidate_pairs` 存在，旧函数已删除，`_llm_judge_*` 签名含 `config` 参数
- [x] Phase D 验证：LLM curator 运行后 `link_discoveries > 0`，孤立记忆比例从 71% 下降
- [x] 全量回归：`.venv/bin/python -m pytest tests/ -x -q` + `cd ui && npx tsc --noEmit`

---

## 深度审计续作 — 2026-07-10

> 执行依据：`docs/plans/2026-07-09-deep-audit-iteration-plan.md` 第八节。按 R1 → R7 顺序推进，完成后在 `ITERATION.md` 记录实绩。

### R1 治理止血（P0/P1）

- [x] 从 LLM Curator stages 中关闭 `split`，并增加配置级开关与回归测试
- [x] 将剩余符合规则的未召回 governance_split 记忆降级为 stale，并记录可回滚清单
- [x] 在 ingest 写入前增加 active `title + type` 精确去重保护
- [x] 清理当前 active 重复标题，并验证重复组为 0
- [x] 补齐 `curator_llm/report.py` 两处静默异常日志（复核确认已有 `exc_info` 日志）

### R2 测试可信度（P0）

- [x] 在测试 fixture 中重置 Qdrant/vector store 单例状态
- [x] 移除 6 个“singleton state leaks”临时 xfail
- [x] 修复或重建项目 `.venv` 测试依赖
- [x] 后端全量测试达到 0 failed、0 unexpected xpass

### R3 召回闭环（P1/P2）

- [x] `ExtractedFact` 增加 `title` 并兼容旧 LLM JSON schema
- [x] dedup 优先使用提取标题，缺失时安全回退
- [x] 新记忆写入后生成可解释的种子反馈并写审计
- [x] FTS 与向量双命中候选增加融合权重
- [x] 为提取、种子反馈和融合排序补回归测试

### R4 后端拆分（P2）

- [x] 拆分 `frontend.py`，保留 API app 与路由兼容入口
- [x] 拆分 `governance.py`，保留 storage re-export 入口
- [x] 拆分 `search.py`，保留 context pack 公开入口
- [x] 拆分 `server.py`，分离 MCP 工具注册与启动逻辑
- [x] 四个核心文件均压缩至 700 行以内并通过全量测试

### R5 前端整治（P2）

- [x] 提取 Graph theme 常量并将静态 inline style 降至 5 处以内
- [x] 清理 TypeScript `any` 至 20 处以内
- [x] 拆分 `form-view.tsx`、`MemoryOperationsPanel.tsx`、`FilterComponent.tsx`
- [x] 所有目标组件控制在 300 行以内
- [x] `pnpm build` 与 `tsc --noEmit` 通过

### R6 数据维护（P3）

- [x] 使用 SQLite backup API 创建瘦身前备份
- [x] 实现 30 天前 audit/governance 日志归档命令，默认 dry-run
- [x] 执行本机归档与 VACUUM，将数据库压缩至 200 MiB 以下
- [x] 增加每周维护脚本/定时器与归档统计

### R7 收尾验证（P0-P3）

- [ ] 连续跟踪 hit_rate、used_count 与 cross_retrieval_rate
- [x] 验证 governance_split 未召回目标和 active 重复标题均为 0
- [x] 更新计划状态、TODO 勾选与 `ITERATION.md` 完成记录
- [x] 最终执行后端全量测试、前端 build/tsc 和数据库完整性检查

---

## 未完成迭代项汇总 — 2026-09-02（按重要程度排序）

> 来源：2026-09-02 全量盘点（ITERATION.md 209 条 + TODO 全量核对）。按 P0→P3 排序，完成一项打勾一项，实现细节记入 ITERATION.md。

### P0 — 记忆主体上下文治理（方案已定稿，待实施）

> 单条记忆缺「主体」锚点：脱离 UI 无法判断归属项目。盘点基线：标题含「迭代」的记忆 58% 无头、95% 无 project_path、99% scope=global。缺口在写入侧（dedup.ingest 不传 project_path、hook 不发送、提取 prompt 无主体上下文）。方案细节：`docs/plans/2026-08-26-memory-subject-context.md`。

- [x] **阶段 1（P0）提取期注入主体**：`extraction.py` 注入 Active Context（project_name/path/scope），`ExtractedFact` 增加 `subject`/`entities` 字段，强化 title 自包含规则（带项目名前缀），输出 schema 同步
- [x] **阶段 2（P0）ingest 落库 metadata**：`dedup.ingest()` / `memory_ingest()` 增加 `project_path`/`scope` 参数并落库，tags 加 `project:*`；`scripts/hooks/mcore-ingest.py` 增加 `_detect_project()` 自动探测（git root / 环境变量 / claude slug）
- [x] **阶段 3（P0）实体索引兜底**：`entities.py` 增加 `resolve_project_entity()`，带 project_path 的记录强制注入项目实体行，保证 `entity_search("<项目名>")` 确定性命中
- [ ] **阶段 4（P1）检索端主体扩展**：查询期项目名低权重扩展 + 调用方自动探测 project_path（当前 Hermes 传 `(none)`）
- [x] **阶段 5（P2 可选）存量回填**：`scripts/backfill_subject.py` 高置信自动标主体 / 低置信进 review，dry-run + 备份 + 幂等
- [x] 新配置段 `subject_context`（enabled / default_scope / projects 白名单 name+paths+aliases+scope）与 config.yaml schema 校验

### P1 — 检索质量连续观测机制

> 评测集当天实测 7/7 pass 无回退，但缺乏周期观测，「待观察」项无法收敛。

- [ ] 建立周期性检索质量观测：定期跑 `tests/test_context_relevance.py` 评测集并记录 hit_rate / filter_rate / cross_retrieval_rate 趋势（可挂 cron 或每周手动）
- [ ] hit_rate 冲刺 >0.90（07-07 微调阈值后实测 0.889，需连续观测确认是否达标）
- [ ] cross_retrieval_rate 达标 ≥0.15（07-10 基线检查时未达标，持续偏低）
- [ ] context hit rate 基线 79.7% 回归观察（08-24 C2 数据收敛后遗留的观察项）

### P2 — LLM 治理成本观察（对象已切换）

- [ ] GLM 订阅端点用量/成本观察：确认切换后治理调用量与订阅额度匹配（原「deepseek 账单降至 1/5」一周核对项因 09-01 切换 GLM 已过时，并入本项关闭）

### P3 — 低优先级遗留 idea（可评估后放弃）

- [ ] 写入时按标点纯规则拆分长事实（>400 字符按句号/分号拆分，无 LLM）：框架重设计 Phase 4 遗留、从未实施；R3 深度审计续作（提取 title 分离 + 种子反馈 + 双命中融合）已部分覆盖其目标，动工前先评估剩余价值
- [ ] E1 Phase 4 统一设计打磨：无验收标准、未排期；8→4 页精简已由用户决策排除，仅剩视觉/交互统一打磨

### 运维观察（非迭代欠账）

- [ ] 矛盾/待清理回升收敛确认：09-01 收官后矛盾 7→16、待清理 36→62 属新数据正常增长；确认下次维护计划（或手动一键维护）后回落至低位
