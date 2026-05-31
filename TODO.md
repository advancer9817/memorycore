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
- [ ] 建立 prompt 后记忆检索相关性持续评测集：已将用户反馈“输入提示词后，检索到的记忆相关性不强”列为专项问题；把真实弱相关提示词沉淀为评测样例，跟踪 `hit_rate` / `filtered_count` / `ineffective_rate`，避免阈值和排序后续回退。

## 功能

- [x] 修复 hooks 初始化脚本未同步 Hermes SQLite session 存储变化：`scripts/setup-hooks.sh` 现在安装带 `--background` 的 Hermes on_session_end hook，`scripts/hooks/lmmcp-ingest.py` 只从 `~/.hermes/state.db` 读取 transcript，并在后台模式保留 stdin payload。
- [x] Embedding sentence-transformers 降级（Ollama 不可用时自动切换）：`embed_text()` 现在按 Ollama -> sentence-transformers -> hashing 顺序降级，支持环境变量覆盖 fallback provider/model。
- [ ] 修复 rollup 测试隔离问题：`test_rollup_processes_manual_source_episodic` 在本机全量测试中会因真实 extraction 配置触发外部 LLM 调用并超时；应让 dry-run/force 测试使用 stub summarizer 或隔离测试配置，避免依赖外部服务。
- [x] 默认启用 Claude/Codex 对话前自动检索注入：`setup-hooks.sh` 和 `connect_agents.py --register-hooks` 已默认给 Claude/Codex 注册 `UserPromptSubmit -> lmmcp-context.sh`，并保留显式 `memory_context` 作为自动注入缺失时的兜底。
- [x] 补齐 opencode 对话前自动检索注入：新增 `scripts/hooks/opencode-lmmcp-plugin.js`，通过 opencode `experimental.chat.system.transform` 在 LLM 调用前读取最新用户消息并调用 `memory_context` 注入 system context；`connect_agents.py --register-hooks` 会把该 plugin 写入 opencode `plugin` 配置。
- [x] 补齐 Hermes 对话前自动检索注入：`setup-hooks.sh` 与 `connect_agents.py --register-hooks` 会注册 Hermes `pre_llm_call -> lmmcp-context.sh`，脚本返回 Hermes `{"context": ...}` 格式并通过短 timeout 调用 `memory_context`。
- [x] 补齐 Gemini 对话前自动检索注入支持矩阵：`setup-hooks.sh` 与 `connect_agents.py --register-hooks` 会注册 Gemini `BeforeAgent -> lmmcp-context.sh`，脚本返回 `additionalContext` 并通过短 timeout 调用 `memory_context`。
- [x] 扩展 opencode 回答后自动总结写回覆盖面：`lmmcp-ingest.py` 已支持从 `~/.local/share/opencode/opencode.db` 抽取 user/assistant text parts，`connect_agents.py --register-hooks` 会注册 opencode `session_end -> lmmcp-ingest.py --agent opencode --background`。
- [x] 补齐 Gemini 回答后自动总结写回自动 hook：`setup-hooks.sh` 与 `connect_agents.py --register-hooks` 会注册 Gemini `SessionEnd -> lmmcp-ingest.py --agent gemini --background`，并支持 hook stdin 的 `transcript_path` 以及 `GEMINI_SESSION_FILE` JSON/JSONL transcript。
- [ ] Gemini 真实 CLI 端到端现场验证：本机当前无 `gemini` 命令，已按官方 hooks 合约和 dry-run/fixture 回归验证；安装 Gemini CLI 后需执行一次真实 BeforeAgent/SessionEnd 验证。
- [x] 为 agent presence/capability 增加自动心跳和能力注册入口：`session-start.sh` 现在会通过 MCP 更新 agent 在线状态并注册默认能力，`setup-hooks.sh` / `connect_agents.py --register-hooks` 会把 Claude/Codex 的 SessionStart hook 接入启动流程，opencode 也带上 agent id。

## 取舍决策 / 简化项

- [ ] 删除 agent/model 权限管理：移除 `agent_permission_*` MCP 工具、权限表/检查逻辑和相关前端/API 入口；lmmcp 作为个人本地记忆总线，不再维护半成品 RBAC。
- [x] 修复前端 `/api/vector/search` 的 `score_threshold` 参数传递：已改为关键字参数并补前端 API 回归测试，避免第三个位置参数误传为 `filters`。
- [ ] 自动生成 MCP 工具文档：用脚本从 `server.py` 的 `@mcp.tool()` 函数签名/docstring 生成 `docs/tools.md`，并加测试确保文档与实际工具列表一致。
- [x] 将 `semantic-*` CLI 改为真实 Qdrant 功能：`semantic-status` 调 `VectorStore.status()`，`semantic-search` 调 Qdrant search，`semantic-index` 调 `memory_rebuild_vectors()`，不再只返回 sqlite-vec 移除提示。
- [ ] 不新增 LLM 全自动记忆治理管线；继续强化现有规则型 `curator` / `rollup`，优先做可解释、可回滚的状态迭代、归档、重复检测、重要性调整和总结沉淀。
- [x] `start.sh` 默认安装完整依赖 `.[all]`：一键启动已包含 Qdrant vector 与 extraction 能力，避免新设备只装 `.[extraction]` 导致语义检索降级。
- [x] 明确 audit 导入策略：`memory_export(include_audit=True)` 可导出 `audit_events`，但 `memory_import()` 不导入本机审计日志，并在返回结果与导入审计事件中报告 `ignored_tables=["audit_events"]`，避免静默丢弃。
- [x] `start.sh` 增加 venv 路径漂移检测：若 `.venv/bin/pytest` / `.venv/bin/pip` shebang 指向旧 checkout 路径，或 `.venv/bin/python` 不可运行，则自动重建 `.venv`，避免 bad interpreter。
- [ ] 收敛 MCP 工具面但不引入 admin profile：直接删除/合并低价值工具，优先删除 `agent_permission_*`，将 `memory_update_status` 并入 `memory_update`，将 `memory_consolidate` 并入 `memory_curator_report`，避免新增角色/权限复杂度。

## 发布与部署

- [ ] PyPI 首次发布（打 tag 触发 publish workflow，验证安装可用）
- [x] Docker Compose 完善：`docker-compose.yml` 默认启动 lmmcp + Qdrant，Dockerfile 安装 `.[all]`，Compose 环境设置 Qdrant endpoint 与持久化 volume。
- [ ] Docker Compose 容器端到端验证：已通过 `docker compose config` 静态解析，仍需在允许拉取/构建镜像的窗口执行 `docker compose up --build` 并验证 `/health`、`/mcp`、`memory_vector_status`。
- [ ] README 补充 PyPI 安装说明；Docker Compose 快速启动文档已补，PyPI 首发后再补正式安装命令
- [x] `deploy.sh` 安装完整 Python extras：部署脚本现在在 `requirements.txt` 后继续执行 `pip install -e ".[all]"`，确保 Qdrant、extraction 与 sentence-transformers fallback 依赖随一键部署补齐。
- [x] `deploy.sh` 默认自动补齐运行时依赖：一键部署默认开启 host 依赖 bootstrap、Docker/Qdrant service、Ollama 安装/启动与 embedding 模型拉取，并提供 `--no-bootstrap-deps`、`--no-ollama`、`--no-qdrant`、`--no-pull-*` 作为显式降级开关。
