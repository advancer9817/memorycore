## [迭代 19] 2026-05-25 — 熵检测 + curator_apply 审计 + qdrant-client 升级

### 变更摘要
- `local_memory_mcp/privacy.py`：新增 `_shannon_entropy()`、`_redact_high_entropy_tokens()` 函数；`redact_secrets()` 在 pattern pass 之后追加熵检测 pass，捕获无前缀高熵随机字符串（Shannon 熵 ≥ 4.5、长度 ≥ 20），命中时追加 `high_entropy` label；已 REDACTED 占位符不二次标记（幂等）
- `local_memory_mcp/storage.py`：`curator_report()` apply 块（`not dry_run`）末尾新增 `log_audit_event("curator_apply", detail={"stale": N, "archived": N, "total_actions": N})`，dry_run 路径不写审计
- `requirements.txt`：`qdrant-client==1.14.3` → `qdrant-client>=1.18.0,<2.0`；venv 内已升级至 1.18.0，消除 server/client 版本不兼容警告
- `tests/test_iter19.py`：新增 10 个测试覆盖三项改动（熵检测 6 个、curator_apply 审计 3 个、版本兼容 1 个）

### 验证
- 全量测试：**274/274 pass**（新增 10 个，无警告）

### 已知问题
- 无

### 回滚
`git revert HEAD`

## [迭代 18] 2026-05-22 — Qdrant 自动同步 + config.yaml schema 验证

### 变更摘要
- `storage.py`：顶部 try-import `_get_vector_store`；新增 `_sync_to_vector(record)`（fire-and-forget，失败只 warn）；在 `add_memory_record`、`update_memory_content`、`update_status` 三个写入路径末尾调用，SQLite 写入后自动同步到 Qdrant
- `models.py`：新增 `validate_config(cfg) -> list[str]`，校验 embedding/qdrant/context_pack/backend 各 section 的类型、范围、URL scheme；加入 `__all__`
- `server.py`：serve 分支启动时调用 `validate_config(load_config())`，每条警告 `logger.warning` 输出，degraded 提示更清晰
- `__init__.py`：导出 `validate_config`
- 新增测试：`tests/test_vector_sync.py`（5 个）、`tests/test_config_validation.py`（13 个）
- 验证：264/264 pass

## [迭代 17] 2026-05-22 — Context Pack v2 + Mailbox TTL/广播 + Graph 增强

### 变更摘要
- `build_context_pack()` 增加 `sections`（按类型分组的记忆列表）和 `trace`（`total_candidates/used_count/filtered_count/fallback_used`）字段，保留全部 legacy 字段
- Agent Mailbox：`send_agent_message` 支持 `ttl_seconds`；`get_agent_inbox` 自动过滤已过期消息；新增 `cleanup_expired_messages() -> int`；`agent_send` 支持广播 `to_agent="*"`；新增 MCP 工具 `agent_messages_cleanup`（第 23 个工具）
- Graph 增强：`VALID_RELATION_TYPES` 扩展至 8 种，新增 `blocked_by`、`causes`、`failure_pattern`；`get_active_warnings()` 对 `causes`/`failure_pattern` 产生 severity=medium warning
- 新增测试：`tests/test_context_pack_v2.py`、`tests/test_graph_enhanced.py`、`tests/test_mailbox_enhanced.py`
- README：工具数 22→23，文档同步
- 验证：246/246 pass

## 2026-05-22 13:48 +0800 — feat: agent message + privacy filter + degraded mode + binary-files export/import

### 目的
批量落地 Agent Mailbox 剩余功能、隐私过滤架构、降级模式、以及二进制文件导出/导入全链路。

### 变更摘要
- `local_memory_mcp/storage.py`: agent_messages/agent_presence 表、send/get/update/presence 函数、privacy.py 集成、degraded mode 显式状态跟踪
- `local_memory_mcp/server.py`: 注册 4 个 mailbox MCP 工具、2 个 privacy MCP 工具、1 个 degraded mode MCP 工具、export_memory + import_memory 工具
- `local_memory_mcp/__init__.py`: 导出新增函数
- `local_memory_mcp/privacy.py`: 新增隐私内容过滤模块（含 rules 白名单）
- `README.md`: 工具数 22→29，文档同步
- `tests/test_privacy.py`, `tests/test_degraded.py`, `tests/test_audit.py`: 新增测试覆盖
- `ITERATION.md`: 本记录追加

### 验证
```bash
.venv/bin/python -m pytest tests -q
```
应通过 182+ 测试。

### 风险
低。新增功能不影响现有 memory/context/timeline 路径。

### 回滚
`git revert HEAD`

# local-memory-mcp 迭代日志

## [迭代 16] 2026-05-22 — Agent Mailbox MVP：agent_messages + agent_presence + 4 个 MCP 工具

**提交**: 本提交（见 `git log -1 --oneline`）

### 变更
- `local_memory_mcp/storage.py` `init_db()`: 新增 `agent_messages` 表（`id, from_agent, to_agent, subject, body, priority, status, created_at, read_at, metadata_json`）及 3 个索引；新增 `agent_presence` 表（`agent_id PK, status, last_seen_at, metadata_json`）。
- `local_memory_mcp/storage.py`: 新增 `send_agent_message()` — 向指定 agent 发送消息，支持 priority（low/normal/high/urgent），写入审计事件 `agent_message_send`。
- `local_memory_mcp/storage.py`: 新增 `get_agent_inbox()` — 读取 agent 收件箱，支持按 status 过滤、`mark_read` 自动标记已读、limit 和 newest-first 排序。
- `local_memory_mcp/storage.py`: 新增 `update_agent_presence()` — upsert agent 在线状态（online/idle/busy/offline），支持 metadata，写入审计事件 `agent_presence_update`。
- `local_memory_mcp/storage.py`: 新增 `list_agent_presence()` — 列出 agent 在线状态，支持按 status 过滤，most-recently-seen-first 排序。
- `local_memory_mcp/server.py`: 新增 4 个 MCP 工具 — `agent_send`、`agent_inbox`、`agent_presence_update`、`agent_presence_list`（第 19–22 个工具）。
- `local_memory_mcp/__init__.py`: 导出 `send_agent_message`、`get_agent_inbox`、`update_agent_presence`、`list_agent_presence`。
- `README.md`: 工具数 18→22，MCP 工具表追加 4 个 mailbox 工具，下一步计划更新。
- `tests/test_mailbox.py`: 19 个测试，覆盖消息发送/接收、inbox 过滤/排序/limit/mark_read、presence upsert/list/filter、审计事件写入、schema 存在性验证。

### 验证
- 全量测试: `.venv/bin/python -m pytest -q` → **182/182 pass**。
- 文档一致性门禁: `test_docs_consistency` 通过，README 工具表与 `@mcp.tool()` 注册一致。

### 已知问题
- Agent Mailbox 为 MVP 版本，尚无消息 TTL 过期、广播、agent 权限控制或 webhook 通知。
- `now()` 使用秒级精度（`timespec="seconds"`），同一秒内的消息依靠 `rowid` 保证插入顺序。

### 回滚方式
- 回滚本提交可移除 `agent_messages`/`agent_presence` 表定义、4 个存储函数、4 个 MCP 工具和对应测试；已有 SQLite 表会保留但无业务影响。

### 下一步
1. Agent Mailbox 增强：消息 TTL 过期、广播消息、agent 权限。
2. Context Pack v2：增加 sections / records / warnings / trace。
3. Graph / Warning 增强：扩展 relation types。

---

## [迭代 15] 2026-05-22 — P0 稳定化：写入端隐私脱敏 + 审计日志 + 降级合约

**提交**: 本提交（见 `git log -1 --oneline`）

### 变更
- `local_memory_mcp/privacy.py`: 新增写入端 secret redaction 模块，8 类模式（OpenAI/Anthropic key、GitHub token、AWS key/secret、Bearer token、PEM 私钥、连接字符串密码、通用 env 赋值），具体模式优先于通用模式，幂等安全。
- `local_memory_mcp/storage.py` `add_memory_record()` / `update_memory_content()`: 写入 SQLite 前调用 `redact_record_fields()`，高熵 secret 不落库。
- `local_memory_mcp/storage.py` `init_db()`: 新增 `audit_events` 表（`id, event_type, memory_id, agent, detail_json, created_at`）及三个索引；`log_audit_event()` 与 `get_audit_log()` 实现 fire-and-forget 审计写入与查询。
- `local_memory_mcp/storage.py` `add_memory_record()` / `update_memory_content()` / `update_status()`: 各关键写路径写入审计事件（`memory_add` / `memory_update` / `memory_status_change`）。
- `local_memory_mcp/server.py`: 新增 `memory_audit_log` MCP tool（第 18 个工具），暴露 `get_audit_log()`，支持按 `memory_id`、`event_type`、`limit` 过滤。
- `local_memory_mcp/server.py` `memory_ingest()`: 捕获 ingest pipeline 全链路异常，返回带 `degraded=True/False` 的统一响应结构。
- `local_memory_mcp/server.py` `memory_vector_search()` / `memory_vector_status()`: 捕获 Qdrant 连接异常，返回结构化降级响应而非抛出。
- `local_memory_mcp/__init__.py`: 导出 `redact_secrets`、`redact_record_fields`、`log_audit_event`、`get_audit_log`。
- `README.md`: 工具数 17→18，MCP 工具表追加 `memory_audit_log`。
- `tests/test_privacy.py`: 14 个测试，覆盖各 redaction 模式、幂等性、集成写入验证。
- `tests/test_audit.py`: 9 个测试，覆盖 audit 写入、fire-and-forget 容错、过滤、排序、集成写入验证。
- `tests/test_degraded.py`: 5 个测试，覆盖 ingest/vector_search/vector_status 的降级响应合约。

### 验证
- 全量测试: `.venv/bin/python -m pytest -q` → **163/163 pass**。
- 静态 secret scan：未发现凭证泄露；redaction 已在写入端生效。

### 已知问题
- `log_audit_event` 当前仅覆盖三类写事件；curator apply 路径的审计事件留待后续迭代补充。
- `privacy.py` 为 pattern-based，高熵随机字符串如不符合已知前缀则不会被捕获；后续可补充熵检测。

### 回滚方式
- 回滚本提交可移除 `privacy.py`、`audit_events` 表（SQLite 列仍存在但无业务影响）、降级响应包装和对应测试；无需 schema 迁移。

### 下一步
1. curator apply 路径补充审计事件。
2. `privacy.py` 补充熵检测，捕获无前缀高熵随机字符串。
3. Agent Mailbox MVP：`agent_messages` / `agent_presence` 表 + 4 个 MCP 工具。

---

## [迭代 14] 2026-05-21 — 部署自动化与 curator 报告提交扫尾

**提交**: 本提交（见 `git log -1 --oneline`）

### 变更
- `scripts/deploy.sh`: 新增一键部署入口，统一安装依赖、生成配置、安装/验证 systemd user 服务，并支持 dry-run、skip-tests、no-systemd、no-qdrant 等可移植部署参数。
- `scripts/lmmcp.service` / `scripts/qdrant.service`: 新增可模板化 systemd user 服务单元，支持本地 MCP HTTP/SSE 服务与 Qdrant Docker 服务托管。
- `scripts/lmmcp-curator.service`: 调整 curator systemd 服务模板，配合部署脚本替换运行路径、配置、DB 与 apply 参数。
- `scripts/init_local_memory.sh`: 改为兼容包装入口，避免重复维护旧初始化逻辑。
- `run_curator.sh`: 补充 `PYTHONPATH`，提升 systemd 与直接 shell 执行一致性。
- `local_memory_mcp/storage.py`: 补充 curator 候选记忆自动 stale/归档策略与 legacy DB effectiveness 字段迁移。
- `tests/test_curator.py`: 增加 curator 候选记录自动 stale 回归测试。
- `README.md` / `docs/deployment.md`: 更新一键部署、服务拓扑、验证与回滚说明。
- `reports/curator-20260521T*.json`: 纳入本轮 curator 报告快照，保留累计治理统计数据。

### 验证
- `python3 -m venv /tmp/lmmcp-verify-venv`
- `/tmp/lmmcp-verify-venv/bin/pip install -q -r requirements.txt`
- `/tmp/lmmcp-verify-venv/bin/pytest -q` → 135/135 pass。
- 静态 secret scan：未发现凭证；报告内容包含历史记忆摘要与已知问题说明。

### 已知问题
- 当前仓库 `.venv/bin/pytest` shebang 仍指向旧路径 `/home/advancer/.agent-memory/local-memory-mcp/.venv/bin/python`，本轮验证改用 `/tmp/lmmcp-verify-venv`。
- 默认完整部署依赖 user systemd 与 Docker；无 systemd/Docker 环境应使用 `scripts/deploy.sh --no-systemd` 或 `--no-qdrant`。

### 回滚方式
- 回滚本提交即可移除部署脚本、服务模板、文档更新、curator 测试和报告快照；如已经安装 user services，需按文档运行 `systemctl --user disable --now qdrant.service lmmcp.service lmmcp-curator.timer` 并 `systemctl --user daemon-reload`。

### 下一步
1. 修复或重建仓库本地 `.venv`，避免旧路径 shebang 误导后续验证。
2. 继续 P0 稳定化：隐私脱敏、审计日志、统一 degraded/fallback response contract。

---


## [迭代 13] 2026-05-21 — Claude 风格本地记忆 Dashboard

**提交**: 本提交（见 `git log -1 --oneline`）

### 变更
- `local_memory_mcp/storage.py`: 将 `export_html()` 生成的本地 Dashboard 从暗色 Operations Console 改为 Claude-inspired 暖纸张视觉风格，更新标题、侧栏品牌、hero 文案、指标卡片、过滤器、记录卡片、时间线、健康分布和 curator 视图样式。
- `local_memory_mcp/storage.py`: 保持单文件静态导出和 Alpine.js 本地交互模式；仍通过 `x-text` 渲染记录内容，并保留 JSON `<` 转义，避免把记忆内容作为 HTML 执行。
- `tests/test_html.py`: 同步 HTML 导出断言，验证新 UI 文案，同时保留 `<script>` 逃逸回归检查。

### 验证
- 局部测试: `.venv/bin/python -m pytest -q tests/test_html.py tests/test_docs_consistency.py` → 3/3 pass。
- 全量测试: `.venv/bin/python -m pytest -q` → 133/133 pass。
- 静态扫描: added-line secret/security pattern scan → none。
- 独立审查: `delegate_task` 只读审查 → PASS；未发现新增 XSS、秘密泄露、外部数据发送或明显逻辑错误；确认外部 Alpine CDN 为既有行为。

### 已知问题
- Dashboard 仍依赖 jsdelivr Alpine CDN；离线或零外部请求环境可后续考虑 vendoring Alpine，但本轮未改变该既有外部依赖。
- 本轮只调整静态 HTML Dashboard 视觉与测试，不修改数据库 schema、MCP tool contract 或生产记忆数据。

### 回滚方式
- 回滚本提交即可恢复旧 Dashboard 文案/样式与测试断言；无需数据库迁移。

### 下一步
1. 如需完全离线部署，评估将 Alpine.js vendor 到仓库或提供无 CDN fallback。
2. 继续 P0 稳定化：隐私脱敏、审计日志、统一 degraded/fallback response contract。

---

## [迭代 12] 2026-05-21 — P0 Context Pack 注入防护

**提交**: 本提交（见 `git log -1 --oneline`）

### 变更
- `local_memory_mcp/injection_guard.py`: 新增 prompt-injection guard，扫描记忆 title/content 中的中英文高风险指令覆盖、system prompt/developer message、密钥泄露/执行命令等模式。
- `local_memory_mcp/storage.py`: `build_context_pack()` 增加 safety boundary notice，明确检索记忆是 untrusted data, not instructions；高风险记忆不进入普通 context body，仅以 `warnings` 返回脱敏摘要。
- `local_memory_mcp/storage.py`: `build_context_pack()` 返回新增 `filtered_ids`，`quality.filtered_count` 记录被过滤记忆数；只有真正注入 context 的记忆才递增 `injected_count`。
- `local_memory_mcp/__init__.py`: 导出 injection guard 相关 public helpers。
- `tests/test_context_injection_guard.py`: 新增 5 个 TDD 回归测试，覆盖 context boundary notice、英文 prompt injection 过滤、中文指令注入过滤、常见误报规避和 warning title 脱敏。

### 修复
- 防止长期记忆内容以“忽略之前指令 / reveal system prompt / 泄露密钥 / 输出 developer message”等形式被直接拼入 agent context。
- 保留可审计信号：过滤结果进入 `warnings`，但不重复输出可疑原文，降低二次注入风险。

### 验证
- TDD RED: `pytest -q tests/test_context_injection_guard.py -vv` 首次 3/3 fail，证明旧 context pack 未标记 untrusted data、未过滤恶意记忆、无 `filtered_ids`。
- TDD GREEN: `pytest -q tests/test_context_injection_guard.py -vv` → 5/5 pass。
- 全量测试: `.venv/bin/python -m pytest -q` → 133/133 pass。
- MCP 连接: `hermes mcp test local_memory` → Connected，Tools discovered: 17。
- 服务脚本: `scripts/lmmcp status` → running，endpoint `http://127.0.0.1:8318/mcp`，DB `/home/advancer/project/local-memory-mcp/memory.sqlite3`。

### 已知问题
- 本轮是 pattern-based guard，不替代后续 P0-3 写入前隐私脱敏，也不替代更完整的 policy engine。
- `memory_add` 仍允许写入可疑内容；当前只在 context pack 注入阶段阻断。下一轮应在写入/ingest 入口做 redaction/minimization。

### 回滚方式
- 回滚本提交即可移除 injection guard 与对应测试；本轮未修改数据库 schema 和生产记忆数据。

### 下一步
1. P0-3: 实现 `privacy.py`，在 `memory_add` / `memory_ingest` 写入前做 secret redaction 与内容最小化。
2. P0-4: 新增 `audit_events` 表，追踪自动写入、过滤、状态变更与 curator apply。
3. P0-5: 统一 degraded/fallback response contract。

---

## [迭代 11] 2026-05-21 — P0 文档现实对齐与工具清单门禁

**提交**: `cd7538f`

### 变更
- `README.md`: 按当前实现重写“当前状态 / MCP 工具列表 / CLI / 服务脚本 / 语义层 / 设计边界”，将工具数对齐为 17，并明确 Qdrant 语义检索、Mem0/OpenMemory 非当前核心部署、sqlite-vec CLI 已移除。
- `.gitignore`: 增加 `*.log`，避免 `lmmcp.log` 等运行日志进入提交。
- `scripts/lmmcp`: 纳入可复用服务脚本，默认 root 为 `$HOME/project/local-memory-mcp`，默认 endpoint 为 `http://127.0.0.1:8318/mcp`，默认 DB 为 `$LMMCP_DIR/memory.sqlite3`，支持 `start/stop/restart/status/logs`。
- `tests/test_docs_consistency.py`: 新增 README 与 `@mcp.tool()` 注册函数的一致性门禁，防止文档列出不存在工具或遗漏新增工具。

### 修复
- 修正 README 中过时的 “16 个工具”、sqlite-vec、Mem0/OpenMemory 当前能力描述，避免未来 agent 被旧文档误导。
- 将下一阶段计划从 Agent Mailbox 优先调整为 P0 稳定化优先：文档门禁、context injection guard、隐私脱敏、审计日志、degraded/fallback contract。

### 验证
- TDD RED: `pytest -q tests/test_docs_consistency.py -vv` 首次失败，准确报告 README 缺失 `memory_ingest/memory_link_add/memory_link_query/memory_update/memory_vector_search/memory_vector_status/memory_warnings`，并误列旧 semantic/Mem0 工具。
- TDD GREEN: `pytest -q tests/test_docs_consistency.py -vv` → 2/2 pass。
- 全量测试: `.venv/bin/python -m pytest -q` → 128/128 pass。
- MCP 连接: `hermes mcp test local_memory` → Connected，Tools discovered: 17。
- 服务脚本: `scripts/lmmcp status` → running，endpoint `http://127.0.0.1:8318/mcp`，DB `/home/advancer/project/local-memory-mcp/memory.sqlite3`。

### 已知问题
- 本轮未实现 context injection guard、隐私脱敏、审计日志或统一 degraded/fallback response contract；这些进入后续 P0 稳定化迭代。

### 回滚方式
- 回滚本提交即可恢复 README/.gitignore/scripts/tests 改动；本轮未修改数据库 schema 和生产记忆数据。

### 下一步
1. P0-2: 实现 `injection_guard.py` 与 `tests/test_context_injection_guard.py`，确保长期记忆作为 data 而非 instruction 注入 context。
2. P0-3: 实现 `privacy.py`，在写入与外部 extraction 前做 secret redaction/minimization。
3. P0-4: 新增 `audit_events` 表，追踪自动写入、状态变更与 curator apply。

---

## [迭代 10] 2026-05-20 — effectiveness 闭环 + memory_warnings/memory_update MCP tools

**提交**: `80bd301`

### 变更
- `local_memory_mcp/storage.py` `add_feedback()`: 补全 effectiveness 追踪 — 正向反馈 `injected_count++`、`effectiveness_score += 0.05*score`；负向反馈 `ineffective_count++`、`effectiveness_score -= 0.05*|score|`；clamp [0.0, 1.0]
- `local_memory_mcp/storage.py` `build_context_pack()`: 注入记忆时自动更新 `injected_count`、`last_injected_at`、`last_accessed_at`，使 decay 检测有真实注入数据支撑
- `local_memory_mcp/server.py`: 新增 `memory_warnings` MCP tool — 直接暴露 `get_active_warnings()`，参数 `memory_ids/min_weight/max_warnings`
- `local_memory_mcp/server.py`: 新增 `memory_update` MCP tool — 暴露 `update_memory_content()`，支持 `content/title/status/confidence/importance` 按需更新
- `local_memory_mcp/__init__.py`: 补充导出 `get_active_warnings`、`get_memory_stats`、`update_memory_content`
- `tests/test_phase10.py`: 新增 15 个测试覆盖全部新功能

### 验证
- 测试: **125/126 pass**（1 个预存在失败 `test_deployment.py::test_default_config_user_id_is_not_a_source_machine_username` 与本次无关）
- MCP 工具数量: 15 → **17**（新增 `memory_warnings`、`memory_update`）
- effectiveness 追踪: 正/负/零分值均通过单元测试验证，clamp 边界测试通过
- 注入记录: `build_context_pack` 调用后 `injected_count` 递增、`last_injected_at` 非空

### 已知问题
- `test_deployment.py` 预存在失败（`openmemory.user_id` key 已废弃），与本次无关

### 下一步
1. Phase 11: `memory_ingest` 改进 — 提取后自动打 `effectiveness_score` 初始值（基于 Qdrant 相似度）
2. Phase 12: Agent Mailbox MVP — `agent_messages` / `agent_presence` 表 + 4 个 MCP 工具
3. lmmcp hooks 生效验证 — 确认 `~/.claude/settings.json` SessionStart/Stop 钩子已注册

---

## [迭代 8.1] 2026-05-20 — Overmind 借鉴：effectiveness 追踪、主动预警、curator 衰减

**提交**: `a876c69`

### 变更
- `local_memory_mcp/storage.py`: `init_db()` 新增四列 — `injected_count INTEGER DEFAULT 0`、`ineffective_count INTEGER DEFAULT 0`、`effectiveness_score REAL DEFAULT 0.5`、`last_injected_at TEXT`；新增 `idx_memories_effectiveness` 索引
- `local_memory_mcp/storage.py`: `add_feedback()` 新增 effectiveness 追踪 — score > 0 递增 `injected_count` 并更新 `effectiveness_score`；score < 0 递增 `ineffective_count`
- `local_memory_mcp/storage.py`: `search_memory_records()` ORDER BY 加入 `effectiveness_score DESC`（排在 importance 之后）
- `local_memory_mcp/storage.py`: 新增 `get_active_warnings()` — 查询 `memory_links` 中 `contradicts`/`supersedes` 关系，结合 `feedback_score` 判断 severity，返回预警列表
- `local_memory_mcp/storage.py`: `build_context_pack()` 返回值新增 `warnings` 字段；修复无条件 fallback（问候语不触发全量查询）
- `local_memory_mcp/storage.py`: `curator_report()` 新增 `decay_candidates`（90天未访问且 effectiveness_score < 0.4）和 `evolution_candidates`（内容过短或 feedback_score < -1.0）

### 设计依据
基于对 overmind 源码的完整审计，借鉴其反馈闭环和主动预警机制，同时规避其凭证泄露（C-1）、FTS 手动同步（M-7）、key-prefix 误删（H-5）等缺陷。详见 MCP 记忆 `ed02122e`、`8d21286d`、`94aa0824`。

### 验证
- 测试: **106/106 pass**（1 个预存在失败 `test_deployment.py::test_default_config_user_id_is_not_a_source_machine_username` 与本次无关）
- 新字段向后兼容：现有数据库通过 `ALTER TABLE IF NOT EXISTS` 模式自动迁移

### 已知问题
- `get_active_warnings()` 尚未暴露为独立 MCP tool，目前只通过 `build_context_pack` 的 `warnings` 字段返回

### 下一步
1. 在 `server.py` 新增 `memory_warnings` MCP tool 直接暴露 `get_active_warnings()`
2. Phase 9: Agent Mailbox MVP

---

## [迭代 9] 2026-05-19 — Agent Memory Hook Contract 与 Overmind 升级计划文档

**提交**: `Phase 9`（`git log --oneline --grep="Phase 9"` 可查具体 hash）

### 变更
- `docs/plans/2026-05-19-agent-memory-hook-contract.md`: 新增跨 Agent Hook / Wrapper / MCP 记忆接入协议，覆盖 context_pack、ingest_session、feedback_event、Hermes/Claude Code/Generic CLI adapter、风险防线与分阶段实施计划。
- `docs/plans/2026-05-19-overmind-inspired-lmmcp-evolution.md`: 纳入 Overmind 亮点到 lmmcp 演进计划，强调 client-neutral、URL-based MCP、fallback/degraded、图谱预警、反馈事件、技能推荐与可选 include adapter。
- `docs/plans/2026-05-19-local-memory-mcp-upgrade-plan-overmind.md`: 新增 local-memory-mcp 升级计划书，按 Phase 1-6 规划图谱增强、主动预警、反馈闭环、自动 consolidate、图谱扩展注入和可选自动注入。

### 修复
- （无代码修复；本轮为架构文档留存。）

### 验证
- 文档检查: 新增 Hook Contract 文档已写入 docs/plans，包含 before-agent / during-agent / after-agent 生命周期、三类核心 schema、adapter 边界、fallback 策略和风险矩阵。
- Git 检查: 仅暂存本轮文档与 ITERATION.md。

### 已知问题
- 尚未实现对应代码；后续需要走 design -> impl -> qa/review/security gates。
- Hermes design/security profile 此前调用失败：HTTP 401 Invalid API key，落地实现前需修复 profile 凭据。

### 下一步
1. Phase 10: 实现 `context_pack` v2，返回 sections/sources/warnings/suggested_skills/degraded/fallback_used。
2. Phase 11: 实现 `ingest_session` 和 feedback event taxonomy。
3. Phase 12: 增加 generic CLI wrapper 与 Hermes profile adapter。

---

## [迭代 8] 2026-05-19 — Curator 自动化 + memory_stats + Context Pack 质量报告

**提交**: `Phase 8`（`git log --oneline --grep="Phase 8"` 可查具体 hash）

### 变更
- `local_memory_mcp/storage.py`: 新增 `get_memory_stats()` — 按 type/status/source_agent 分组统计、avg confidence/importance/feedback_score、never_accessed_count、link_count
- `local_memory_mcp/server.py`: 新增 `memory_stats` MCP tool（第 16 个工具）
- `local_memory_mcp/storage.py`: `build_context_pack()` 返回值新增 `quality` 字段 — total_candidates、used_count、active_ratio、avg_importance、stale_in_results、estimated_tokens
- `scripts/lmmcp-curator.service`: 新增 systemd user service 单元
- `scripts/lmmcp-curator.timer`: 新增 systemd user timer（每小时，RandomizedDelaySec=300）
- `scripts/install_curator_timer.sh`: 新增一键安装脚本，自动 symlink 到 ~/.config/systemd/user/ 并 enable
- `tests/test_stats.py`: 新增 6 个测试覆盖 memory_stats 工具

### 修复
- `run_curator.sh`: 删除 `semantic-index` 调用 — 该命令 Phase 7 后已废弃，返回 error JSON 但被 `/dev/null` 静默，语义索引实际未执行
- `local_memory_mcp/storage.py` `consolidate()`: 重复检测 key 生成改为调用 `normalize_title_key()`，与 `curator_report()` 一致
- ive/low_feedback/skill_promotion 候选检测全部改为专用 SQL 查询，不再依赖 `list_recent()` 的 `updated_at DESC` 排序截断，确保最老记录也能被扫描到；apply 模式下去重逻辑改用 `seen_ids` set 替代 dict comprehension

### 验证
- 测试: **111/111 pass** (0 skipped，新增 6 个)
- `memory_stats` MCP tool: 空库返回 total=0 不报错，有数据时返回完整分布
- `build_context_pack` quality 字段: 向后兼容，现有调用方不受影响
- systemd timer: WSL2 systemd=true 环境下 install_curator_timer.sh 可正常安装

### 已知问题
- （无新增已知问题）

### 下一步
1. Phase 9: Agent Mailbox MVP — `agent_messages` / `agent_presence` 表 + 4 个 MCP 工具
2. README 同步修订（Phase 7/8 架构漂移，仍有旧 stdio/Mem0/sqlite-vec 描述）
3. 24 小时 curator dry-run 观察，确认 stale/archive 候选分布合理后开放 apply

---

## [迭代 7] 2026-05-18 — 模块重构 + MCP 循环导入彻底修复

**提交**: `Phase 7`（`git log --oneline --grep="Phase 7"` 可查具体 hash）

### 变更
- `local_memory_mcp/` 包结构: 将 1284 行的单文件拆分为 `models.py`/`storage.py`/`server.py`/`__init__.py`/`__main__.py`
- `local_memory_mcp/models.py`: 抽取常量、YAML 配置解析、类型验证、工具函数（无 MCP 依赖）
- `local_memory_mcp/storage.py`: 抽取 SQLite CRUD、FTS 搜索、curator、memory_links、dashboard 生成
- `local_memory_mcp/server.py`: FastMCP 实例、15 个 @mcp.tool() 注册、CLI main() 入口
- `local_memory_mcp/__main__.py`: 新增 `python -m local_memory_mcp` 入口
- `scripts/init_local_memory.sh`: 更新命令为 `python -m local_memory_mcp`
- `run_curator.sh`: 更新 SERVER 路径
- `probe_mcp.py`: 更新 MCP server 路径

### 修复
- `dedup.py`: 消除 `__main__` fallback 循环导入 → 改为直接从 `local_memory_mcp.storage` 导入（storage.py 无 MCP 依赖，彻底断绝循环链）
- **MCP 通道 `memory_ingest`**：此前即使显式传入函数引用，写入阶段仍因模块状态不一致失败。重构后 MCP 全链路验证通过（initialize → tools/list → memory_add → memory_ingest，全部正常返回）

### 验证
- 测试: **105/105 pass** (0 skipped)
- MCP 协议初始化: 正常握手，返回 `serverInfo: {"name": "local-memory-mcp", "version": "1.27.1"}`
- MCP tools/list: 返回 15 个工具（含 memory_ingest、memory_vector_search 等）
- MCP memory_add: 正常写入并返回记录
- CLI: `python -m local_memory_mcp init` 正常
- 导入验证: `from local_memory_mcp.storage import add_memory_record` + `from dedup import ingest` 无循环导入

### 已知问题
- （无新增已知问题；Phase 6 的 MCP 循环导入已修复）

### 下一步
1. curator cron job（定期去重/归档/矛盾检测）
2. 实体/关系迁移（从官方 server-memory，按需）
3. 多 Agent 集成增强

---

## 日志格式规范

每次提交必须在本文件顶部追加一条迭代记录，格式如下：

```markdown
## [迭代 N] YYYY-MM-DD — 标题

**提交**: `Phase N`（可通过 `git log --oneline --grep="Phase N"` 定位）

### 变更 (新增功能/接口/配置)
- `<文件路径>`: 变更描述

### 修复 (Bug 修复)
- `<文件路径>`: 问题描述 → 修复方式

### 验证
- 测试: N/N pass (skipped: N)
- 端到端: 关键链路验证结果

### 已知问题
- 问题描述（若有）

### 下一步
1. 下个迭代计划任务
```

> **规则**: 
> - 每次提交必须追加新条目（追加到文件顶部，即最新迭代在最上面）。
> - 变更与修复分开列出；如果某次提交仅有修复无新功能，"变更" 段可省略。
> - 测试结果必须写实际数字（如 105/105 pass），不允许占位符。
> - 已知问题如已在上个迭代修复，从列表中移除并改记入"修复"段。

---

## [迭代 6] 2026-05-15 — 端到端验证 + Qdrant server 模式 + 5 个 bug 修复

**提交**: `Phase 6`（`git log --oneline --grep="Phase 6"` 可查具体 hash）

### 变更
- `local_memory_mcp.py`: 新增 `update_memory_content()` — 按字段更新记忆（content/title/status/confidence/importance）
- `vector_store.py`: Qdrant 新增 server URL 模式，优先 Docker Qdrant，fallback 本地文件
- `vector_store.py`: `VectorStoreConfig` 新增 `url` 字段
- `config.yaml`: 移除 openmemory 残留；修正 `llm_base_url` 补全 `/v1`；`llm_api_key` 直接写入
- `local_memory_mcp.py`: `memory_ingest` 显式传递 `_add_memory_fn` / `_update_memory_fn` 避免循环导入
- `ITERATION.md`: 新建迭代日志文件及格式规范

### 修复
- `local_memory_mcp.py`: `update_memory_content` 缺失 → 新增完整函数（含 content/title/status/confidence/importance 字段更新）
- `extraction.py`: `os.environ.setdefault()` 被 Hermes 安全空值拦截 → 改为直接赋值 `os.environ[k]=v`
- `dedup.py`: `add_memory_record(type=...)` 参数名错误 → 修正为 `memory_type`（2 处）
- `dedup.py`: 增加 `__main__` fallback 导入（兼容 MCP server 循环导入场景）
- `config.yaml`: DeepSeek `base_url` 缺 `/v1` 导致 401 → 补全

### 验证
- 测试: **105/105 pass** (0 skipped)
- CLI 端到端: DeepSeek 提取(3-4s/次) → Qdrant 去重 → SQLite 写入 → Qdrant 语义索引 — 全链路通过
- Qdrant Docker 模式: 连接成功，向量读写正常（4 条记录）
- Curator: 扫描 16 条记录，报告正常，无异常候选
- MCP 通道 `memory_ingest`: 提取成功，写入阶段仍有 `__main__` 循环导入问题（4 errors / 4 facts）

### 已知问题
- MCP `__main__` 循环导入：`dedup.ingest` 即使显式传入函数引用，仍因模块状态不一致导致写入失败。CLI 通道完整通过，MCP 通道待重构后验证。

### 下一步
1. 重构模块结构，消除 `__main__` 循环导入
2. 跑通 MCP 通道完整 ingestion
3. 实体/关系迁移（从官方 server-memory）
4. 增加 curator cron job（定期去重/归档/矛盾检测）
## 2026-05-19 14:17:19 +0800 - test(local-memory-mcp): update project iteration

- 项目: `local-memory-mcp`
- 分支: `main`
- 远端: `https://github.com/advancer9817-crypto/local-memory-mcp.git`
- 关联提交: `390ff382c4a7e79df1a86b7bb03f91b81c9a3184`
- 提交时间: `2026-05-19 14:14:00 +0800`
- 提交作者: `advancer9817-crypto <advancer9817-crypto@users.noreply.github.com>`

### 迭代说明

```text
- ITERATION.md                                       |   36 +
- README.md                                          |   74 +-
- config.yaml                                        |    7 +-
- dedup.py                                           |   12 +-
- docs/deployment.md                                 |   21 +-
- docs/memory-platform-briefing/data.js              |    2 +-
- docs/migration/2026-05-12-baseline.md              |   10 +-
- ...enmemory-qdrant-memory-platform-project-book.md |   66 +-
- docs/plans/frontend-design-brief.md                |    4 +-
- extraction.py                                      |    2 +-
- local_memory_mcp.py                                | 1226 --------------------
- probe_mcp.py                                       |    2 +-
```

### 修改范围统计

```text
ITERATION.md                                       |   36 +
 README.md                                          |   74 +-
 config.yaml                                        |    7 +-
 dedup.py                                           |   12 +-
 docs/deployment.md                                 |   21 +-
 docs/memory-platform-briefing/data.js              |    2 +-
 docs/migration/2026-05-12-baseline.md              |   10 +-
 ...enmemory-qdrant-memory-platform-project-book.md |   66 +-
 docs/plans/frontend-design-brief.md                |    4 +-
 extraction.py                                      |    2 +-
 local_memory_mcp.py                                | 1226 --------------------
 local_memory_mcp/__init__.py                       |   67 ++
 local_memory_mcp/__main__.py                       |    9 +
 local_memory_mcp/models.py                         |  267 +++++
 local_memory_mcp/server.py                         |  406 +++++++
 local_memory_mcp/storage.py                        |  848 ++++++++++++++
 probe_mcp.py                                       |    2 +-
 run_curator.sh                                     |    2 +-
 scripts/connect_agents.py                          |  335 ++++++
 scripts/init_local_memory.sh                       |   25 +-
 scripts/serve.sh                                   |    6 +
 tests/test_deployment.py                           |    3 +-
 vector_store.py                                    |   16 +-
 23 files changed, 2096 insertions(+), 1350 deletions(-)
```

### 文件变更清单

```text
M	ITERATION.md
M	README.md
M	config.yaml
M	dedup.py
M	docs/deployment.md
M	docs/memory-platform-briefing/data.js
M	docs/migration/2026-05-12-baseline.md
M	docs/plans/2026-05-12-openmemory-qdrant-memory-platform-project-book.md
M	docs/plans/frontend-design-brief.md
M	extraction.py
D	local_memory_mcp.py
A	local_memory_mcp/__init__.py
A	local_memory_mcp/__main__.py
A	local_memory_mcp/models.py
A	local_memory_mcp/server.py
A	local_memory_mcp/storage.py
M	probe_mcp.py
M	run_curator.sh
A	scripts/connect_agents.py
M	scripts/init_local_memory.sh
A	scripts/serve.sh
M	tests/test_deployment.py
M	vector_store.py
```

## Iteration - 2026-05-19 16:42:52 +0800

- Branch: `main`
- Remote: `https://github.com/advancer9817-crypto/local-memory-mcp.git`
- Purpose: 增强 local-memory-mcp 记忆治理、curator 统计与 dashboard 数据能力，新增 stats 测试和 curator timer 安装脚本/计划文档。
- Changed files:
  - `local_memory_mcp/server.py`
  - `local_memory_mcp/storage.py`
  - `run_curator.sh`
  - `docs/plans/2026-05-19-overmind-lessons-lmmcp-hardening.md`
  - `docs/plans/cpa-real-write-validation-2026-05-19.md`
  - `docs/plans/cpa-write-narrow-buffer-e2e-2026-05-19.md`
  - `scripts/install_curator_timer.sh`
  - `scripts/lmmcp-curator.service`
  - `scripts/lmmcp-curator.timer`
  - `tests/test_stats.py`
- Diff stat:
```
local_memory_mcp/server.py  |   1 +
 local_memory_mcp/storage.py | 126 +++++++++++++++++++++++++++++++++-----------
 run_curator.sh              |   1 -
 3 files changed, 95 insertions(+), 33 deletions(-)
```
- Untracked files intentionally included:
  - `docs/plans/2026-05-19-overmind-lessons-lmmcp-hardening.md`
  - `docs/plans/cpa-real-write-validation-2026-05-19.md`
  - `docs/plans/cpa-write-narrow-buffer-e2e-2026-05-19.md`
  - `scripts/install_curator_timer.sh`
  - `scripts/lmmcp-curator.service`
  - `scripts/lmmcp-curator.timer`
  - `tests/test_stats.py`
- Validation:
  - /home/advancer/.agent-memory/local-memory-mcp/.venv/bin/python -m pytest tests/test_stats.py -q => PASS (6 passed); python3 -m pytest tests/test_stats.py -q => FAIL: system python missing pytest
- Risk notes: 涉及记忆统计、curator 报告查询和运行脚本；系统 Python 缺少 pytest，已使用运行时 venv 验证新增测试。
- Rollback: 回滚本次提交可移除 stats API、curator timer 资产和相关计划文档。
- Commit message: `feat(memory): add curator stats and timer assets`
## Iteration - 2026-05-19 16:47:26 +0800

- Branch: `main`
- Remote: `https://github.com/advancer9817-crypto/local-memory-mcp.git`
- Purpose: 完全追踪 docs/ 与迭代文档变更；补充提交用户维护的 Phase 8 迭代记录。
- Changed files:
  - `ITERATION.md`
- Diff stat:
```
ITERATION.md | 34 ++++++++++++++++++++++++++++++++++
```
- Validation:
  - 文档/迭代日志更新，无代码路径变更；复用上一轮新增测试验证结果：`/home/advancer/.agent-memory/local-memory-mcp/.venv/bin/python -m pytest tests/test_stats.py -q => PASS (6 passed)`
- Risk notes: 仅文档记录更新。
- Rollback: 回滚本次提交即可移除新增迭代日志。
- Commit message: `docs: track phase 8 iteration log`

## 迭代 — Phase 9 准备：移除 openmemory 后端 + Agent Hooks 体系 (2026-05-20)

### 目的
清理 openmemory 后端残留代码，新增 Agent Hooks 体系（session-start/end + daemon 管理脚本），
为 Phase 9 Mailbox MVP 做基础设施准备。同步修复 lmmcp-ingest 和 lmmcp-session-end.py 的
streamable-http 握手 bug。

### 变更摘要
- `local_memory_mcp/models.py`
  - 移除 `DEFAULT_CONFIG` 中的 `openmemory` 节
  - 移除 `load_config()` 中的 openmemory user_id 自动注入逻辑
- `scripts/init_local_memory.sh`
  - 移除生成配置模板中的 openmemory 节
- `tests/test_config.py`
  - 移除 openmemory 相关断言
- `tests/test_deployment.py`
  - 将 stale test `test_default_config_user_id_is_not_a_source_machine_username`
    替换为 `test_load_config_returns_dict_without_openmemory`，验证 openmemory key 已不存在
- `scripts/connect_agents.py` (新增 150 行)
  - Agent 连接辅助脚本，支持 Hermes/Claude Code/Codex 接入 lmmcp
- `scripts/lmmcp-daemon.sh` (新增)
  - 幂等 lmmcp HTTP 服务生命周期管理：start/stop/status，供 hooks 调用
- `scripts/hooks/session-start.sh` (新增)
  - 会话开始 hook：确保 lmmcp 运行，拉取任务相关 context pack
- `scripts/hooks/session-end.sh` (新增)
  - 会话结束 hook：从 transcript 提取消息，调用 memory_ingest 写入 lmmcp

### 关联修复（~/.local/bin/lmmcp-ingest + ~/.hermes/agent-hooks/lmmcp-session-end.py）
- lmmcp-ingest: 新增 `_mcp_initialize()` 握手，修复 streamable-http 400 Bad Request
- lmmcp-session-end.py: SESSION_DB 路径从 sessions.db 修正为 state.db

### 测试
- 126 passed（新增 1 个替换测试，净增 1）

### 影响范围
- openmemory 后端彻底移除，不影响 SQLite/Qdrant 主路径
- Agent Hooks 为可选接入，不影响现有 MCP 工具

### 风险
低。openmemory 本地未运行，移除无副作用。Hooks 脚本 exit 0 兜底，不阻塞 agent 启动。

### 回滚
`git revert HEAD`

## 2026-05-21T09:28:03+08:00 — fix: migrate Phase 8.1 effectiveness columns for legacy SQLite DBs

- Branch: `main`
- Remote: `https://github.com/advancer9817-crypto/local-memory-mcp.git`
- Purpose: fix production `memory_context` failures caused by older `memories` tables missing Phase 8.1 effectiveness tracking columns.
- Change summary:
  - Added `_ensure_column()` helper in `local_memory_mcp/storage.py`.
  - `init_db()` now applies idempotent SQLite `ALTER TABLE ... ADD COLUMN` migrations for existing databases:
    - `injected_count INTEGER NOT NULL DEFAULT 0`
    - `ineffective_count INTEGER NOT NULL DEFAULT 0`
    - `effectiveness_score REAL NOT NULL DEFAULT 0.5`
    - `last_injected_at TEXT`
  - Added regression coverage in `tests/test_phase10.py` for a legacy `memories` table without those columns.
- Changed files:
  - `local_memory_mcp/storage.py`
  - `tests/test_phase10.py`
  - `ITERATION.md`
- Verification:
  - Live DB migration check confirmed `/home/advancer/project/local-memory-mcp/memory.sqlite3` now has all four columns and `memory_context` no longer raises `no such column: m.effectiveness_score`.
  - `systemctl --user restart lmmcp.service` reloaded the patched service.
  - `.venv/bin/python -m pytest tests -q --tb=short` passed: `134 passed`.
- Risk:
  - Low. Migration is additive and idempotent; existing rows receive SQLite defaults.
- Rollback:
  - Revert this commit for code rollback. Existing added SQLite columns can safely remain; they are additive and backward-compatible.


## 2026-05-22 18:11:22 +0800 - Repository sync publish

- Branch: `main`
- Target remote: `origin`
- Remotes:

```text
origin	https://github.com/advancer9817-crypto/local-memory-mcp.git (fetch)
origin	https://github.com/advancer9817-crypto/local-memory-mcp.git (push)
```

### Purpose
Batch commit and push project repository to the user-owned GitHub account as requested.

### Change summary
- Added/updated repository-local iteration record for auditable sync.
- Included current tracked/untracked project changes selected by git status.
- For newly initialized repositories, added conservative ignore rules for local runtime files and secrets.

### Impact scope
- Repository-local files only.
- No force push, no branch rewrite, no remote replacement of vendor/upstream remotes.

### Validation commands
```bash
git status --porcelain=v1 --untracked-files=all
git rev-list --left-right --count @{u}...HEAD
```

### Risks
- Large generated files and secret-like local files are intentionally excluded when ignored by `.gitignore`.
- Existing repository-specific tests are not exhaustively run for this batch metadata/publish operation.

### Rollback
```bash
git revert HEAD
git push
```

### Commit content before staging
```text
Only repository sync/iteration metadata changes.
```
## 2026-05-25T18:39:30+08:00 — batch repository sync

- Branch: `main`
- HEAD before commit: `439f54a`
- Target remote: `origin`
- Remote URLs:

```text
origin	https://github.com/advancer9817-crypto/local-memory-mcp.git (fetch)
origin	https://github.com/advancer9817-crypto/local-memory-mcp.git (push)
```

### Purpose

Batch commit and push this repository under `/home/advancer/project` to the user's GitHub account, with a repository-local iteration record kept in version control.

### Change summary / commit content

```text
clean before ITERATION entry
```

### Diff stat before staging

```text
No tracked diff before staging; changes may be untracked/ITERATION-only.
```

### Impact scope

Repository synchronization/auditability. No intentional source behavior change is introduced by this iteration record itself unless listed above.

### Validation commands

```text
git status --porcelain=v1 --untracked-files=all
git push -u <target-remote> <branch>
git rev-list --left-right --count @{u}...HEAD
```

### Risks

This is an automated multi-repository sync. Generated/runtime artifacts already present in the working tree may be included when not ignored by this repository.

### Rollback

Use `git revert <commit>` on this repository, then push the revert commit to the same remote/branch.
