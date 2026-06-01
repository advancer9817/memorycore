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

- [x] 修复前端测试卡死：`tests/test_frontend.py` 单独运行会卡在第一个 `TestClient` 用例；当前在重启真实 `lmmcp.service` 并清理遗留 pytest/脚本进程后已恢复，`tests/test_frontend.py` 8/8 pass，保留为运行态验证记录。
- [x] 修复 hooks 初始化脚本未同步 Hermes SQLite session 存储变化：`scripts/setup-hooks.sh` 现在安装带 `--background` 的 Hermes on_session_end hook，`scripts/hooks/lmmcp-ingest.py` 只从 `~/.hermes/state.db` 读取 transcript，并在后台模式保留 stdin payload。
- [x] Embedding 外接 API / Ollama API / hashing 降级：`embed_text()` 默认 `auto`，优先配置的 OpenAI-compatible embedding API，未配置时尝试 Ollama `/api/embed`，失败后使用 hashing；不再默认安装或调用 sentence-transformers/PyTorch/CUDA 依赖链。
- [x] 修复 rollup 测试隔离问题：`test_rollup_processes_manual_source_episodic` 和 extraction source 对应用例已传入 stub summarizer，避免 dry-run/force 扫描测试依赖真实 extraction LLM。
- [x] 默认启用 Claude 对话前自动检索注入：`setup-hooks.sh` 和 `connect_agents.py --register-hooks` 已默认给 Claude 注册 `UserPromptSubmit -> lmmcp-context.sh`，并保留显式 `memory_context` 作为自动注入缺失时的兜底。
- [x] 停用 Codex 对话前自动检索注入：Codex 不再注册 `UserPromptSubmit -> lmmcp-context.sh`，本机 `~/.codex/hooks.json` 已移除该读前 hook；Codex 读记忆改为按 `AGENTS.md` 规则显式调用 MCP `memory_context`，只保留 `SessionStart` presence/capability 与 `Stop` 写回 hook，避免可见 hook 输出和弱相关记忆污染对话。
- [x] 补齐 opencode 对话前自动检索注入：新增 `scripts/hooks/opencode-lmmcp-plugin.js`，通过 opencode `experimental.chat.system.transform` 在 LLM 调用前读取最新用户消息并调用 `memory_context` 注入 system context；`connect_agents.py --register-hooks` 会把该 plugin 写入 opencode `plugin` 配置。
- [x] 补齐 Hermes 对话前自动检索注入：`setup-hooks.sh` 与 `connect_agents.py --register-hooks` 会注册 Hermes `pre_llm_call -> lmmcp-context.sh`，脚本返回 Hermes `{"context": ...}` 格式并通过短 timeout 调用 `memory_context`。
- [x] 补齐 Gemini 对话前自动检索注入支持矩阵：`setup-hooks.sh` 与 `connect_agents.py --register-hooks` 会注册 Gemini `BeforeAgent -> lmmcp-context.sh`，脚本返回 `additionalContext` 并通过短 timeout 调用 `memory_context`。
- [x] 扩展 opencode 回答后自动总结写回覆盖面：`lmmcp-ingest.py` 已支持从 `~/.local/share/opencode/opencode.db` 抽取 user/assistant text parts，`connect_agents.py --register-hooks` 会注册 opencode `session_end -> lmmcp-ingest.py --agent opencode --background`。
- [x] 补齐 Gemini 回答后自动总结写回自动 hook：`setup-hooks.sh` 与 `connect_agents.py --register-hooks` 会注册 Gemini `AfterAgent` + `SessionEnd -> lmmcp-ingest.py --agent gemini --background`，并支持 hook stdin 的 `transcript_path` 以及 `GEMINI_SESSION_FILE` JSON/JSONL transcript；`AfterAgent` 用于真实 headless prompt 后写回，`SessionEnd` 保留为退出兜底；真实 Gemini CLI JSONL 的 `type: "gemini"` assistant 消息与 `displayContent` 用户文本已纳入解析。
- [x] Gemini 真实 CLI 端到端现场验证：本机已有 `gemini` 命令，`gemini mcp list` 显示 `local_memory` connected；2026-06-01 11:14 CST 真实 `gemini -p ... --extensions '' --output-format json` 成功返回，transcript 中出现 `<hook_context># memory_context for gemini`，证明 `BeforeAgent` 注入生效；2026-06-01 11:20 CST 补 `AfterAgent` 写回与真实 JSONL 解析后，`gemini -p ...` 触发 `lmmcp-ingest.py --agent gemini --background`，日志显示 `messages=2`、`updated=1`，SQLite 中出现 `source_agent=gemini` 的 `LMMCP-GEMINI-WRITEBACK-20260601-1120` marker。
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
