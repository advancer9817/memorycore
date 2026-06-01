# ITERATION.md — local-memory-mcp 迭代日志

> 按时间升序排列，新条目追加到文件底部。

---

## [迭代 6] 2026-05-15 — 端到端验证 + Qdrant server 模式 + 5 个 bug 修复

### 变更

- `local_memory_mcp.py`: 新增 `update_memory_content()` — 按字段更新记忆（content/title/status/confidence/importance）
- `vector_store.py`: Qdrant 新增 server URL 模式，优先 Docker Qdrant，fallback 本地文件；`VectorStoreConfig` 新增 `url` 字段
- `config.yaml`: 移除 openmemory 残留；修正 `llm_base_url` 补全 `/v1`；`llm_api_key` 直接写入
- `local_memory_mcp.py`: `memory_ingest` 显式传递 `_add_memory_fn` / `_update_memory_fn` 避免循环导入
- `ITERATION.md`: 新建迭代日志文件及格式规范

### 修复

- `local_memory_mcp.py`: `update_memory_content` 缺失 → 新增完整函数
- `extraction.py`: `os.environ.setdefault()` 被 Hermes 安全空值拦截 → 改为直接赋值
- `dedup.py`: `add_memory_record(type=...)` 参数名错误 → 修正为 `memory_type`（2 处）
- `dedup.py`: 增加 `__main__` fallback 导入（兼容 MCP server 循环导入场景）
- `config.yaml`: DeepSeek `base_url` 缺 `/v1` 导致 401 → 补全

### 验证

- 测试: 105/105 pass
- CLI 端到端: DeepSeek 提取 → Qdrant 去重 → SQLite 写入 → Qdrant 语义索引 — 全链路通过
- MCP 通道 `memory_ingest`: 提取成功，写入阶段仍有 `__main__` 循环导入问题（4 errors / 4 facts）

### 已知问题

- MCP `__main__` 循环导入：`dedup.ingest` 即使显式传入函数引用，仍因模块状态不一致导致写入失败。CLI 通道完整通过，MCP 通道待重构后验证。

---

## [迭代 7] 2026-05-18 — 模块重构 + MCP 循环导入彻底修复

### 变更

- `local_memory_mcp/` 包结构: 将 1284 行的单文件拆分为 `models.py`/`storage.py`/`server.py`/`__init__.py`/`__main__.py`
- `models.py`: 抽取常量、YAML 配置解析、类型验证、工具函数（无 MCP 依赖）
- `storage.py`: 抽取 SQLite CRUD、FTS 搜索、curator、memory_links、dashboard 生成
- `server.py`: FastMCP 实例、15 个 @mcp.tool() 注册、CLI main() 入口
- `__main__.py`: 新增 `python -m local_memory_mcp` 入口

### 修复

- `dedup.py`: 消除 `__main__` fallback 循环导入 → 改为直接从 `local_memory_mcp.storage` 导入
- MCP 通道 `memory_ingest` 全链路验证通过

### 验证

- 测试: 105/105 pass
- MCP 协议初始化、tools/list、memory_add、CLI 全部正常

---

## [迭代 8] 2026-05-19 — Curator 自动化 + memory_stats + Context Pack 质量报告

### 变更

- `storage.py`: 新增 `get_memory_stats()` — 按 type/status/source_agent 分组统计、avg confidence/importance/feedback_score、never_accessed_count、link_count
- `server.py`: 新增 `memory_stats` MCP tool（第 16 个工具）
- `storage.py`: `build_context_pack()` 返回值新增 `quality` 字段 — total_candidates、used_count、active_ratio、avg_importance、stale_in_results、estimated_tokens
- 新增 systemd user service/timer（`scripts/lmmcp-curator.service`、`scripts/lmmcp-curator.timer`、`scripts/install_curator_timer.sh`）

### 修复

- `run_curator.sh`: 删除 `semantic-index` 调用（Phase 7 后已废弃）
- `storage.py` `consolidate()`: 重复检测 key 生成改为调用 `normalize_title_key()`
- curator 候选检测改为专用 SQL 查询，不再依赖 `list_recent()` 截断

### 验证

- 测试: 111/111 pass

---

## [迭代 8.1] 2026-05-20 — Overmind 借鉴：effectiveness 追踪、主动预警、curator 衰减

### 变更

- `storage.py`: `init_db()` 新增四列 — `injected_count`、`ineffective_count`、`effectiveness_score`、`last_injected_at`
- `storage.py`: `add_feedback()` 新增 effectiveness 追踪 — score > 0 递增 `injected_count` 并更新 `effectiveness_score`；score < 0 递增 `ineffective_count`
- `storage.py`: `search_memory_records()` ORDER BY 加入 `effectiveness_score DESC`
- `storage.py`: 新增 `get_active_warnings()` — 查询 contradicts/supersedes 关系，结合 feedback_score 判断 severity
- `storage.py`: `build_context_pack()` 返回值新增 `warnings` 字段；修复无条件 fallback（问候语不触发全量查询）
- `storage.py`: `curator_report()` 新增 `decay_candidates` 和 `evolution_candidates`

### 修复

- `storage.py`: `_ensure_column()` 向后兼容旧库迁移 effectiveness 四列

### 验证

- 测试: 106/106 pass（含 legacy DB migration 回归）

---

## [迭代 9] 2026-05-19~20 — Agent Memory Hook Contract + openmemory 清理

### 变更

- `docs/plans/`: 新增 Agent Hook Contract、Overmind 借鉴演进计划、升级计划书（Phase 1-6）
- `models.py`: 移除 `DEFAULT_CONFIG` 中的 `openmemory` 节及 `load_config()` 中 openmemory user_id 自动注入逻辑
- `scripts/connect_agents.py` (新增): Agent 连接辅助脚本，支持 Hermes/Claude Code/Codex 接入 lmmcp
- `scripts/lmmcp-daemon.sh` (新增): 幂等 lmmcp HTTP 服务生命周期管理
- `scripts/hooks/session-start.sh` (新增): 会话开始 hook
- `scripts/hooks/session-end.sh` (新增): 会话结束 hook

### 修复

- `lmmcp-ingest`: 新增 `_mcp_initialize()` 握手，修复 streamable-http 400 Bad Request
- `lmmcp-session-end.py`: SESSION_DB 路径从 sessions.db 修正为 state.db

### 验证

- 测试: 126 passed

---

## [迭代 10] 2026-05-20 — effectiveness 闭环 + memory_warnings/memory_update MCP tools

### 变更

- `storage.py` `add_feedback()`: 补全 effectiveness 追踪 — 正向/负向反馈更新 `injected_count`/`ineffective_count`/`effectiveness_score`，clamp [0.0, 1.0]
- `storage.py` `build_context_pack()`: 注入记忆时自动更新 `injected_count`、`last_injected_at`、`last_accessed_at`
- `server.py`: 新增 `memory_warnings` MCP tool — 暴露 `get_active_warnings()`
- `server.py`: 新增 `memory_update` MCP tool — 暴露 `update_memory_content()`
- MCP 工具数量: 15 → 17

### 验证

- 测试: 125/126 pass（1 个预存在失败与本次无关）

---

## [迭代 11] 2026-05-21 — P0 文档现实对齐与工具清单门禁

### 变更

- `README.md`: 按当前实现重写，工具数对齐为 17，明确 Qdrant 语义检索、Mem0/OpenMemory 非当前核心
- `.gitignore`: 增加 `*.log`
- `scripts/lmmcp`: 纳入可复用服务脚本（start/stop/restart/status/logs）
- `tests/test_docs_consistency.py`: 新增 README 与 `@mcp.tool()` 注册函数一致性门禁

### 验证

- 测试: 128/128 pass
- MCP 连接: Tools discovered: 17

---

## [迭代 12] 2026-05-21 — P0 Context Pack 注入防护

### 变更

- `injection_guard.py` (新增): prompt-injection guard，扫描记忆 title/content 中的高风险指令覆盖模式
- `storage.py`: `build_context_pack()` 增加 safety boundary notice，高风险记忆不进入 context body，仅以 `warnings` 返回脱敏摘要
- `storage.py`: `build_context_pack()` 返回新增 `filtered_ids`，`quality.filtered_count`

### 验证

- TDD RED → GREEN: 5/5 pass
- 全量测试: 133/133 pass

---

## [迭代 13] 2026-05-21 — Claude 风格本地记忆 Dashboard

### 变更

- `storage.py`: `export_html()` 改为 Claude-inspired 暖纸张视觉风格
- 保持单文件静态导出和 Alpine.js 本地交互模式

### 验证

- 全量测试: 133/133 pass

### 已知问题

- Dashboard 仍依赖 jsdelivr Alpine CDN

---

## [迭代 14] 2026-05-21 — 部署自动化与 curator 报告扫尾

### 变更

- `scripts/deploy.sh`: 新增一键部署入口，支持 dry-run、skip-tests、no-systemd、no-qdrant
- `scripts/lmmcp.service` / `scripts/qdrant.service`: 新增 systemd user 服务单元
- `storage.py`: 补充 curator 候选记忆自动 stale/归档策略与 legacy DB effectiveness 字段迁移
- `README.md` / `docs/deployment.md`: 更新部署文档

### 验证

- 测试: 135/135 pass

---

## [迭代 15] 2026-05-22 — P0 稳定化：写入端隐私脱敏 + 审计日志 + 降级合约

### 变更

- `privacy.py` (新增): 写入端 secret redaction 模块，8 类模式
- `storage.py`: 写入 SQLite 前调用 `redact_record_fields()`
- `storage.py`: 新增 `audit_events` 表，`log_audit_event()` 与 `get_audit_log()`
- `server.py`: 新增 `memory_audit_log` MCP tool（第 18 个工具）
- `server.py`: ingest/vector_search/vector_status 捕获异常，返回带 `degraded` 的统一响应结构

### 验证

- 全量测试: 163/163 pass

---

## [迭代 16] 2026-05-22 — Agent Mailbox MVP：agent_messages + agent_presence + 4 个 MCP 工具

### 变更

- `storage.py`: 新增 `agent_messages`/`agent_presence` 表及 CRUD 函数
- `server.py`: 新增 `agent_send`、`agent_inbox`、`agent_presence_update`、`agent_presence_list`（第 19–22 个工具）
- MCP 工具数量: 18 → 22

### 验证

- 全量测试: 182/182 pass

### 已知问题

- Agent Mailbox 为 MVP 版本，尚无消息 TTL 过期、广播、agent 权限控制

---

## [迭代 17] 2026-05-22 — Context Pack v2 + Mailbox TTL/广播 + Graph 增强

### 变更

- `build_context_pack()` 增加 `sections`（按类型分组）和 `trace`（total_candidates/used_count/filtered_count/fallback_used）字段
- Agent Mailbox: `send_agent_message` 支持 `ttl_seconds`；`get_agent_inbox` 自动过滤已过期消息；新增 `cleanup_expired_messages()`；广播 `to_agent="*"`；新增 MCP 工具 `agent_messages_cleanup`（第 23 个工具）
- Graph: `VALID_RELATION_TYPES` 扩展至 8 种，新增 `blocked_by`、`causes`、`failure_pattern`

### 验证

- 全量测试: 246/246 pass

---

## [迭代 18] 2026-05-22 — Qdrant 自动同步 + config.yaml schema 验证

### 变更

- `storage.py`: 新增 `_sync_to_vector(record)` — SQLite 写入后自动同步到 Qdrant（fire-and-forget）
- `models.py`: 新增 `validate_config(cfg) -> list[str]`，校验各 section 类型、范围、URL scheme
- `server.py`: 启动时调用 `validate_config()`，每条警告 `logger.warning` 输出

### 验证

- 全量测试: 264/264 pass

---

## [迭代 19] 2026-05-25 — 熵检测 + curator_apply 审计 + qdrant-client 升级

### 变更

- `privacy.py`: 新增 `_shannon_entropy()`、`_redact_high_entropy_tokens()`，`redact_secrets()` 追加熵检测 pass（Shannon 熵 ≥ 4.5、长度 ≥ 20）
- `storage.py`: `curator_report()` apply 块末尾新增 `log_audit_event("curator_apply", ...)`
- `requirements.txt`: `qdrant-client==1.14.3` → `qdrant-client>=1.18.0,<2.0`

### 验证

- 全量测试: 274/274 pass

---

## [迭代 20] 2026-05-26 — Agent 权限模型 + 拒绝审计

### 变更

- `storage/permissions.py` (新增): agent 权限策略模块，支持 grant/get/check + 拒绝审计
- `storage/db.py`: 新增 `agent_permissions` 表
- `storage/crud.py`: 写入前检查 agent 对 scope/type/tag 的写权限
- `storage/agents.py`: 广播消息前检查 `can_broadcast`；按 namespace 隔离广播
- `server.py`: 新增 MCP 工具 `agent_permission_grant`、`agent_permission_get`
- MCP 工具数量: 23 → 25

### 验证

- 全量测试: 285/285 pass

---

## [迭代 21] 2026-05-26 — export/import/backup/restore 稳定化

### 变更

- `storage/transfer.py` (新增): schema-versioned JSON 导出/导入、SQLite backup、Qdrant 向量重建
- `memory_export()`: 导出 memories、feedback_events、memory_links、agent_messages、agent_presence、agent_permissions，可选 audit_events
- `memory_import()`: 支持 dry_run、冲突报告、schema version 检查、skip/replace 冲突策略
- `memory_backup()`: SQLite backup API 一致性备份
- `memory_rebuild_vectors()`: 支持 dry-run 预估与从 SQLite 重建 Qdrant 向量索引
- `server.py`: 新增 4 个 MCP 工具
- MCP 工具数量: 25 → 29

### 验证

- 全量测试: 290/290 pass

---

## [迭代 22] 2026-05-26 — Curator apply plan + rollback metadata

### 变更

- `storage/curator.py`: `curator_report()` 新增 `allow_actions` / `deny_actions` 参数和 `action_plan` 字段
- apply 路径改为先生成 action plan，再执行状态变更；`curator_apply` 审计 detail 新增完整 action plan 与 rollback metadata

### 验证

- 全量测试: 294/294 pass

---

## [迭代 23] 2026-05-26 — Context Pack 质量指标与权重调优

### 变更

- `storage/db.py`: 新增 `context_quality_events` 表
- `storage/search.py`: 新增 task type 轻量分类与类型权重；`build_context_pack()` 根据 task type 对 memory type 做二次排序
- `build_context_pack()` 的 `quality` 新增 `hit_rate`、`filter_rate`、`ineffective_rate`；`trace` 新增 `task_type`、`type_weights`
- 新增 `get_context_quality_stats()` 及 MCP 工具 `memory_context_stats`
- MCP 工具数量: 29 → 30

### 验证

- 全量测试: 297/297 pass

---

## [迭代 24] 2026-05-26 — Agent handoff workflow schema

### 变更

- `storage/db.py`: 新增 `agent_capabilities` 表
- `storage/handoff.py` (新增): 结构化 handoff 工作流与能力注册模块
- `agent_handoff_create()`: 创建带 workflow/handoff_status/correlation_id/payload 的消息
- `agent_handoff_update()`: 支持 ack/done/failed 状态
- `agent_capability_register()` / `agent_capability_search()`: agent capability registry
- `server.py`: 新增 4 个 MCP 工具
- MCP 工具数量: 30 → 34

### 验证

- 全量测试: 301/301 pass

---

## [迭代 25] 2026-05-26 — Dashboard 运维台增强

### 变更

- `storage/dashboard.py`: Dashboard payload 新增 `links`、`mailbox`、`presence`、`context_quality`
- Dashboard 导航新增 Graph / Mailbox / Presence 视图
- Health 视图新增 Feedback drilldown，展示 context pack 质量趋势
- Curator 视图新增 Action plan 区块
- `storage/db.py`: SQLite lock 重试次数 3→10

### 验证

- 全量测试: 303/303 pass

---

## [迭代 26] 2026-05-26 — 同端口前端控制服务

### 变更

- `frontend.py` (新增): 同端口前端控制服务路由（`/` 控制台、`/api/*` REST API、`/health`、`/metrics`）
- `server.py`: 通过 FastMCP `custom_route` 将前端与 REST API 挂载到现有 HTTP 服务；`/mcp` 保持不变
- `serve` 默认端口改为 `8318`，新增 `--auth-token`、`--allow-insecure-remote`、`--mcp-only`
- 前端控制台使用无构建 vanilla JS

### 验证

- 全量测试: 310/310 pass

### 已知问题

- `/api/*` token 是单 token 模式，尚未实现 RBAC 或 agent identity 绑定

---

## [迭代 27] 2026-05-27 — Temporal Memory Layer + Auto-decay + Memory Stats

### 变更

- `memory_add` 新增 `valid_from` / `valid_until` 参数（ISO-8601 时间边界）
- `search_memory_records` 自动过滤 `valid_until < now()` 的过期记忆
- `curator.py`: 新增 auto-decay（30+ 天未访问且 decay_policy='review' 的 active 记忆 confidence -0.05/轮，floor 0.10）
- `curator_report` 新增 `contradiction_candidates` 列表
- `server.py`: 新增 `memory_stats` MCP tool（重构版，按 type/status/agent 分组统计）
- `pyproject.toml` version: 0.20.0 → 0.21.0

### 验证

- 全量测试: 317 → 327 passed（含迭代 28 修复后）

---

## [迭代 28] 2026-05-27 — 全项目缺陷审计与快速优化

### 修复

- **[CRITICAL] `managed_conn` retry 逻辑完全失效** — `@contextmanager` 内 retry 是死代码。修复：`yield` 拆出循环，retry 移到 `_commit_with_retry()`（`storage/db.py`）
- **[HIGH] `config.yaml` 中 `api_key: "sk"` 屏蔽 env var 回退** — 清空为 `""`（`config.yaml`）
- **[HIGH] N+1 查询** — `agents.py` broadcast 改为 `executemany`；`curator.py` auto_decay 改为 `executemany`
- **[MEDIUM] `"继续"` 在 `_GREETINGS` 中** — 误跳过 FTS 搜索，已从集合中删除（`storage/search.py`）
- **[MEDIUM] `context_quality_events` 和 `audit_events` 无清理机制** — curator apply 中加 90/180 天 DELETE（`storage/curator.py`）
- **[MEDIUM] `valid_from`/`valid_until` 无格式校验** — 新增 `_validate_iso()`（`storage/crud.py`）
- **[LOW] WAL 无检查点** — curator apply 后加 `PRAGMA wal_checkpoint(TRUNCATE)`
- **[LOW] `ops_db` 死配置** — 从 `models.py` 和 `config.yaml` 删除
- **[LOW] `mem0` compat 代码** — 从 `extraction.py` 和 `config.yaml` 清除
- **[LOW] `DEFAULT_DB` import 时冻结** — `db_path()` 直接读 `DEFAULT_ROOT`，不再依赖 `DEFAULT_DB`

### 验证

- 全量测试: 327 passed

---

## [迭代 29] 2026-05-27 — 多设备记忆同步（export/import/sync）

### 变更

- `storage/transfer.py`: `memory_export` 新增 `memories_only` 参数；`memory_import` 新增 `conflict_policy="newer"` 策略
- `server.py`: CLI 新增 `export` / `import` 子命令
- `scripts/sync-memory.sh` (新增): 独立同步脚本，支持 push/pull/sync/status
- `scripts/lmmcp`: `start` 前自动 pull+import，`stop` 后自动 export+push；新增 `sync` 子命令
- 环境变量: `LMMCP_AUTO_SYNC`（默认 1）

### 验证

- 全量测试: 338 passed

---

## [迭代 30] 2026-05-27 — 一键启动脚本 start.sh

### 变更

- `start.sh` (新增): 自动查找 Python 3.11+、创建 venv、安装依赖、初始化 DB、导入记忆、启动服务
- 参数: `--daemon`、`--no-import`、`--host`、`--port`、`--python`
- 环境变量: `LMMCP_HOST` / `LMMCP_PORT` / `LMMCP_PYTHON` / `LMMCP_PID_FILE` / `LMMCP_AUTO_SYNC`

### 验证

```bash
bash start.sh --no-import --daemon && sleep 1 && curl -s http://127.0.0.1:8318/health
```

---

## [迭代 31] 2026-05-27 — episodic memory 自动汇总 rollup

### 变更

- `storage/rollup.py` (新增): `rollup_report()` 扫描 episodic_memory，触发条件达标后通过 LLM 提炼为 durable memories
- `server.py`: 新增 MCP tool `memory_rollup_report`；CLI 新增 `rollup` 子命令
- 自动 curator 线程每轮先执行 rollup，再执行 curator

### 验证

- 全量测试: 通过（含 test_rollup.py 新增测试）

---

## [迭代 32] 2026-05-28 — 三端 hook 部署与写回脚本统一化

### 变更

- `scripts/hooks/lmmcp-ingest.py` (新增): 统一 Claude/Codex/Hermes 的 session-end 写回脚本
- `scripts/setup-hooks.sh` (新增/更新): 统一部署入口，写入 Claude/Codex/Hermes 配置
- `scripts/connect_agents.py`: 注册路径与 setup-hooks.sh 对齐
- 清理旧的 `session-end.sh`、`codex-session-end.sh`、`lmmcp-session-end.py`

### 验证

- 全量测试: 342 passed

---

## [迭代 33] 2026-05-28 — 记忆状态流转完善（v3 状态机）

### 变更

- `models.py`: 从 `STATUSES` 中移除 `promoted`（等价于 active）
- `storage/curator.py`（完整重写）:
  - candidate 超时分档（episodic 7天、precious 30天、default 7天）替代原 48h 一刀切
  - 新增 stale 复活通道（近期注入 + 有效 + 无负反馈 → active）
  - precious 类型保护加强（user_profile/environment_fact/decision/project_memory/skill_candidate）
  - contradicted 自动归档（90天无访问 → archive）
  - decay_policy 真正生效（freeze 完全跳过、stable 提高 stale 阈值）
  - decay 条件修正（未注入过的记忆不衰减）
  - promotion 扩展（injected_count ≥ 3 → active）
- `storage/rollup.py`: 去掉 `source = 'extraction'` 限制

### 验证

- 全量测试: 362 passed（含 test_curator_v3.py 20 个新测试）

---

## [迭代 34] 2026-05-28 — 文档缺口全修复（8 个遗留问题）

### 变更

- **D-2** `valid_until` 时区强制校验 — `_validate_iso()` 新增 `tzinfo is not None` 检查（`storage/crud.py`）
- **11-B** WAL autocheckpoint=500 — `_get_thread_conn()` 注册 `PRAGMA wal_autocheckpoint=500`（`storage/db.py`）
- **11-C** context_quality_events 写入节流 — `used_count == 0` 提前返回（`storage/search.py`）
- **12-A** 语义去重阈值按 type 差异化 — `TYPE_THRESHOLDS` 字典，`decide()` 新增 `memory_type` 参数（`dedup.py`）
- **12-B** 中文双语 extraction prompt — 中文字符 >15% 时追加中文指令段（`extraction.py`）
- **S-2** curator apply 单事务 — `update_status_batch(conn, updates)` + `managed_conn` 单一事务包裹（`storage/crud.py` + `storage/curator.py`）
- **13-A** handoff 超时清理 — 默认 `ttl_seconds=3600`，`cleanup_expired_handoffs()`，auto-curator 线程每轮调用（`storage/handoff.py` + `server.py`）
- **13-C** agent_handoff_create auto_route — 查询 online/idle agent presence，capability 关键字匹配打分选最高分者（`storage/handoff.py` + `server.py`）

### 验证

- 全量测试: 362 passed

### 影响范围

- `agent_handoff_create` 新增 `auto_route` 参数（默认 False，向后兼容）
- `ttl_seconds` 默认值从 None 改为 3600（破坏性变更）
- `valid_until` 无时区写入现在会报错

---

## [迭代 35] 2026-05-28 — lmmcp 本地时间与 Codex hook 信任修复

### 变更

**CST 本地时间统一**

- `models.py` 新增 `LOCAL_TZ` 与 `local_now()`；`now()` 改为返回 `+08:00` 偏移的 ISO 时间戳
- `extraction.py` observation date 改用本地日期
- `storage/agents.py`、`storage/curator.py`、`storage/rollup.py` 统一改用 `local_now()`
- `storage/transfer.py` 备份文件名将 `+` 替换为 `p`

**Codex ingest 可观测性**

- `scripts/hooks/lmmcp-ingest.py` 新增 `/tmp/lmmcp-ingest.log`（可用 `LMMCP_INGEST_LOG` 覆盖）

**Codex hook trust 自动写入**

- `scripts/connect_agents.py --register-hooks` 通过 `codex app-server` 获取 `currentHash`，自动写入 `~/.codex/config.toml`
- `scripts/setup-hooks.sh` 同步实现

**Codex 读取路径调整**

- `scripts/connect_agents.py`: 移除 Codex `UserPromptSubmit` 中的 `lmmcp-context.sh`，读取改由 `AGENTS.md` MCP 规则驱动
- `scripts/setup-hooks.sh`: 同步清理 Codex UserPromptSubmit 条目，仅保留 Stop hook

### 验证

```text
2026-05-28T13:54:42+08:00 ingest_start agent=codex messages=16
2026-05-28T13:54:52+08:00 ingest_done agent=codex messages=16 response=... "added": 2 ... "errors": 0 ...
```

---

## [迭代 36] 2026-05-29 — 检索质量优化：FTS5 + Qdrant 双路召回

### 变更

- `storage/search.py`: FTS5 多词查询从 OR 改为 AND，减少宽泛误匹配
- `storage/search.py`: FTS5 有查询时排序改为混合权重（`-rank*0.4 + importance*0.3 + effectiveness*0.2 + feedback*0.1`），文本相关性参与排名
- `storage/search.py`: 新增 `_vector_search_ids()`，向 Qdrant 发起语义召回（score_threshold=0.25），Qdrant/Ollama 不可用时静默降级
- `storage/search.py`: `build_context_pack()` 改为 FTS5 + Qdrant 双路召回，合并去重后用 `_rank_score()` 统一重排序（vector_score*0.45 + importance*0.30 + effectiveness*0.15 + feedback*0.10）
- `storage/search.py`: `trace` 新增 `vector_hits` 字段，记录 Qdrant 命中数

### 变更（记忆库）

- 归档 4 条高权重过时记忆：Phase 8 任务清单、Overmind 借鉴特性、Phase 历史全貌、旧未来规划

### 验证

- 测试: 361/362 pass（1 个并发测试偶发失败，单独运行通过，与本次改动无关）

### 回滚

`git revert HEAD`

---

## [迭代 37] 2026-05-29 — 修复向量搜索单例未携带 config 的问题

### 修复

- `server.py`: `serve` 启动时用 `load_config()` 预热 `get_vector_store(cfg)` 单例，确保 Ollama URL / Qdrant path 配置生效
- `storage/search.py` `_vector_search_ids()`: 检测 `_store is None` 时自动调用 `load_config()` 初始化单例，无需依赖 server 预热，独立调用也能拿到正确配置

### 验证

- 测试: 362/362 pass
- 直接调用 `build_context_pack()` 无需 server 启动，向量搜索自动连接 Qdrant server at `http://127.0.0.1:6333`

### 回滚

`git revert HEAD`

---

## [迭代 38] 2026-05-29 — 修复 Qdrant 向量状态失同步导致命中但注入为 0 的问题

### 修复

- `storage/crud.py` `_sync_to_vector()`: 非 active 状态（stale/archived/contradicted 等）改为调用 `vs.delete()` 删除向量，而非 upsert 旧 payload。确保向量索引只保留 active 记录
- `storage/crud.py` `update_status_batch()`: 批量状态变更后逐条同步向量（原来完全没有同步，curator 批量 stale/archive 后向量库不更新）
- `storage/search.py` `_vector_search_ids()`: 移除 `filters={"status": "active"}` Qdrant payload 过滤，改为依赖向量库本身只存 active 记录的不变量，避免因 payload 过时导致误过滤
- `tests/test_vector_sync.py`: 拆分原 `test_update_status_triggers_upsert` 为两个测试，分别验证 active→upsert 和 non-active→delete 行为

### 根因

Qdrant payload 里的 status 字段在 curator 批量操作时没有随 SQLite 同步更新，导致已变为 stale 的记录仍被向量搜索命中，最终被 DB 查询的 `status='active'` 条件过滤掉，出现"向量命中 20 条但注入 0 条"的现象。

### 验证

- 测试: 363/363 pass

### 回滚

`git revert HEAD`

---

## [迭代 39] 2026-05-29 — memory_context 返回体瘦身（records 精简 + fallback 收窄）

### 变更

- `storage/search.py`: `build_context_pack()` 返回的 `records` 字段从全量 candidates（含 content）改为仅注入记录的精简视图（id/type/title/importance/scope/tags），去掉未注入的候选和 content 字段
- `storage/search.py`: `sections` 内 records 同步精简为 `{id, title, importance}`
- `storage/search.py`: fallback 候选数从 20 条降为 8 条，避免无相关记忆时拉出过多兜底数据

### 效果

- 返回体体积：58,201 → 7,790 字符，缩小 87%
- context 文本本身不变（注入内容不受影响）

### 验证

- 测试: 363/363 pass

### 回滚

`git revert HEAD`

---

## [迭代 40] 2026-05-29 — TODO 取舍记录与 lmmcp 流程约定

### 变更

- `TODO.md`: 记录已确认的简化/修复取舍，包括删除 agent/model 权限管理、修复前端 vector search 参数、自动生成 MCP 工具文档、恢复真实 `semantic-*` CLI、强化规则型 curator/rollup、默认安装 `.[all]`、audit import 忽略策略、venv 路径漂移检测、直接合并/删除低价值 MCP 工具
- 项目流程约定：后续所有对 lmmcp 的改动必须同步写入 `ITERATION.md`；分析发现且决定要修复的问题必须自动写入 `TODO.md`

### 验证

- 未运行测试（仅 TODO/流程记录变更）

### 回滚

`git revert HEAD`

---

## [迭代 41] 2026-05-29 — 记忆生命周期与 ingest 噪音治理

### 变更

- `storage/curator.py`: decay 从 90 天 / 0.02 调整为 30 天 / 0.05，加快曾被使用但后来遗忘的记忆 confidence 衰减
- `storage/curator.py`: 新增 14 天 never-accessed candidate 归档规则；非 precious candidate 若 `last_accessed_at IS NULL` 且 `injected_count = 0`，超过窗口后进入 archive 计划
- `extraction.py`: LLM extraction prompt 增加 `importance` 字段要求，只保留 `importance >= 0.3` 的事实
- `extraction.py`: `ExtractedFact` 增加 `importance` 字段，解析 LLM 返回时做 0.0-1.0 裁剪并过滤低价值事实
- `dedup.py`: ingest 写入 candidate 时使用 `ExtractedFact.importance`，不再固定写入 `importance=0.5`

### 验证

- Stop hook 配置核对：Codex 和 Claude Code 的 Stop hook 均指向 `scripts/hooks/lmmcp-ingest.py --background`
- 测试: 362/363 pass，1 failed

### 已知问题

- `tests/test_curator_v3.py::test_rollup_processes_manual_source_episodic` 在本机全量测试中触发真实 rollup LLM 调用并被 pytest-timeout 截断；已写入 `TODO.md`，需要隔离测试配置或改用 stub summarizer
- 测试过程中 Qdrant 对非 UUID 测试 id `hermes-ep-manual` 的 delete 返回 400，但该异常被 vector sync 捕获为日志；需在后续判断是否要统一测试 id 或跳过非 UUID vector sync

### 回滚

`git revert HEAD`

---

## [迭代 42] 2026-05-30 — 更新至最新版本 + 重新执行初始化脚本

### 变更

- `git pull --rebase origin main`：从 `89f07af` 更新到 `163c302`（5 个新提交，含 v3 记忆状态机 tiered TTL / revival / freeze/stable / contradicted archive）
- `memory-sync/memories.json`：冲突时以远程版本为准，重新导入 537 条记忆（149 条以 newer wins 策略更新）
- `scripts/setup-hooks.sh`：重新运行，更新 Claude `~/.claude/settings.json` Stop hook、`CLAUDE.md` 记忆规则段、`AGENTS.md` 规则段、Codex hooks.json
- `scripts/install_curator_timer.sh`：修复 service 文件占位符未替换问题（`__ROOT__`/`__LMMCP_SERVICE__` 等），手动生成正确的 `lmmcp-curator.service`，timer 已启用（首次触发：22:02 CST）
- `scripts/init_local_memory.sh --skip-install --skip-tests`：重新初始化 SQLite + dashboard，config.yaml 保留不覆盖，Qdrant 不可用（无 Docker）走 hashing fallback

### 验证

- `lmmcp status`：running (pid 6398, endpoint http://127.0.0.1:8318/mcp)
- `cpa status`：running (pid 5968, port :8317)
- `systemctl --user list-timers lmmcp-curator.timer`：1 timer listed，35min 后首次触发
- setup-hooks.sh 输出：`lmmcp hooks configured`
- init_local_memory.sh 输出：`[done] local-memory-mcp deployed`

---

## [迭代 43] 2026-05-30 — WSL 安装 Docker + Qdrant 向量存储上线

### 变更

- WSL Ubuntu 24.04 安装 Docker Engine 29.5.2（阿里云镜像源）
- 配置 dockerd 代理 `http://127.0.0.1:7890`（继承 WSL Clash 代理），解决 Docker Hub 拉取超时
- 启动 Qdrant 容器（`docker.io/qdrant/qdrant:latest`，端口 6333/6334，存储 `~/.agent-memory/qdrant_storage`，`restart: unless-stopped`）
- 重新执行 `init_local_memory.sh --skip-install --skip-tests`，Qdrant 连接成功，集合 `agent_memory` (dim=768) 已创建
- 向量 embedding 仍走 hashing fallback（Ollama 未安装），语义搜索功能待后续安装 Ollama 后启用

### 验证

- `docker ps`：qdrant Up，healthz check passed
- `init_local_memory.sh` 输出：`available: True, collection: agent_memory, dim: 768`
- `lmmcp status`：running (pid 6398, endpoint http://127.0.0.1:8318/mcp)

**后续补充（同日）：Ollama + 向量语义搜索上线**

- 安装 Ollama 0.23.2，拉取 `nomic-embed-text` 模型
- `memory_rebuild_vectors` 重建 509 条记忆向量，写入 Qdrant `agent_memory` collection
- 语义搜索验证：`memory_vector_search` 返回评分结果，embed_provider=ollama 正常工作
- `.zshrc` `_wsl_services_start` 补充 `docker start qdrant`，确保 WSL 重启后 Qdrant 自动拉起

---

## [迭代 44] 2026-05-30 — Hermes hook 初始化脚本切换为 SQLite session

### 变更

- `scripts/hooks/lmmcp-ingest.py`: 同步运行时修复版本；Hermes transcript 抽取移除旧 `~/.hermes/sessions/session_<id>.json` 兼容，只读取当前 `~/.hermes/state.db` 的 `messages` 表。
- `scripts/hooks/lmmcp-ingest.py`: 后台模式启动子进程前保存 hook stdin JSON 到 `LMMCP_HERMES_HOOK_PAYLOAD`，避免 detached child 因 stdin=DEVNULL 丢失 `session_id`。
- `scripts/setup-hooks.sh`: Hermes `on_session_end` 初始化改为安装 `python3 ~/.hermes/agent-hooks/lmmcp-ingest.py --agent hermes --background`，timeout 降为 10 秒，并清理旧的不带 `--background` 的 lmmcp Hermes hook/allowlist 条目。
- `TODO.md`: 记录并完成 hooks 初始化脚本未跟进 Hermes SQLite session 存储变化的问题。

### 修复

- 修复重新运行 `scripts/setup-hooks.sh` 会把 Hermes hook 回退到旧 JSON session 抽取逻辑的问题；现在初始化脚本和 hook 均只按 `state.db` 新机制处理 Hermes。
- 修复 Hermes 后台 session_end hook 无法把 stdin payload 传给子进程，导致 `skip_empty_messages agent=hermes` 的问题。

### 验证

- 语法检查: `python3 -m py_compile scripts/hooks/lmmcp-ingest.py` 通过。
- 手动 hook: 使用当前 Hermes session id 调用 `lmmcp-ingest.py --agent hermes`，日志显示 `hermes_state_db_transcript ... messages=4` 与 `ingest_done ... errors=0 ... degraded=false`。
- 后台 hook: 使用 `--background` 调用后，日志显示 `background_spawned`、`hermes_state_db_transcript ... messages=4` 与 `ingest_done ... errors=0 ... degraded=false`。
- MCP 连接: `hermes mcp test local_memory` 连接成功，发现 36 tools；`lmmcp status` 显示 `http://127.0.0.1:8318/mcp` running。

### 已知问题

- 未运行全量 pytest；本次只修改 hook 初始化/脚本逻辑，未改服务端存储或 MCP tool。

### 回滚

`git checkout -- scripts/hooks/lmmcp-ingest.py scripts/setup-hooks.sh TODO.md ITERATION.md`

---

## [迭代 45] 2026-05-31 — 修复 prompt 检索弱相关记忆注入

### 变更

- `local_memory_mcp/storage/search.py`: 为 `build_context_pack()` 增加显式检索来源标记、轻量 lexical relevance 评分、中文 prompt 关键词/ngram 提取、相关性阈值过滤和 trace 阈值字段。
- `local_memory_mcp/storage/search.py`: FTS 无命中时改用关键词扫描兜底；空结果 fallback 只记录候选数量，不再把无关高权重记忆直接注入上下文。
- `tests/test_context_relevance.py`: 新增 prompt 相关性回归测试，覆盖中文 prompt 正向召回、无关 fallback 不注入、弱相关 vector-only 命中过滤。
- `TODO.md`: 将 prompt 后自动/显式 `memory_context` 检索相关性问题标记为已完成。

### 修复

- 修复输入提示词后，`memory_context` 可能因为空查询 fallback、向量低阈值或高 importance/type weighting 把弱相关记忆注入上下文的问题；现在相关性证据优先于泛化权重。

### 验证

- 语法检查: `.venv/bin/python -m py_compile local_memory_mcp/storage/search.py` 通过。
- 测试: `.venv/bin/python -m pytest tests/test_context_relevance.py tests/test_context_quality_metrics.py tests/test_context_pack_v2.py tests/test_phase10.py tests/test_context_injection_guard.py -q`，43/43 pass。

### 回滚

`git checkout -- local_memory_mcp/storage/search.py tests/test_context_relevance.py TODO.md ITERATION.md`

---

## [迭代 46] 2026-05-31 — 输出系统流程梳理并补充审计待办

### 变更

- `TODO.md`: 补充全盘扫描中发现的目标差距：context pack vector-only 范围隔离、多 agent 对话前自动检索注入统一、Gemini/opencode 回答后 transcript 写回、agent presence/capability 默认心跳与能力注册。
- `/mnt/d/Advancer/Desktop/output/lmmcp-system-flow-2026-05-31.html`: 生成自包含 HTML 流程梳理页，包含端到端流程、检索注入链路、回答后写回链路、状态流转、多 agent 协作、部署能力和缺口矩阵。

### 验证

- 文件检查: `test -s /mnt/d/Advancer/Desktop/output/lmmcp-system-flow-2026-05-31.html` 通过。
- 内容检查: `rg "目标端到端流程|本轮扫描写入 TODO 的新增缺口" /mnt/d/Advancer/Desktop/output/lmmcp-system-flow-2026-05-31.html` 通过。

### 已知问题

- 本轮仅完成系统流程梳理和待办记录，尚未开始修复新增 TODO 中的自动注入、写回覆盖、vector-only 范围隔离和自动心跳问题。

### 回滚

`git checkout -- TODO.md ITERATION.md && rm -f /mnt/d/Advancer/Desktop/output/lmmcp-system-flow-2026-05-31.html`

---

## [迭代 47] 2026-05-31 — 修复 vector-only 上下文召回范围隔离

### 变更

- `local_memory_mcp/storage/search.py`: `build_context_pack()` 合并 Qdrant vector-only 命中时，回 SQLite 取记录同步应用 `status='active'`、`valid_until`、`scope` 和 `project_path` 条件，和 FTS/keyword 路径保持一致。
- `tests/test_context_relevance.py`: 新增 vector-only 命中范围隔离回归测试，覆盖同 scope/project 可注入、global/空 project 可注入、错误 scope 或错误 project 不注入。
- `TODO.md`: 将 context pack 向量召回隔离问题标记为已完成。

### 修复

- 修复多 agent/多项目共享记忆库下，Qdrant 返回的 vector-only 记录可能绕过 `scope` / `project_path` 过滤，被注入到不相关 agent 或项目上下文的问题。

### 验证

- 语法检查: `.venv/bin/python -m py_compile local_memory_mcp/storage/search.py` 通过。
- 测试: `.venv/bin/python -m pytest tests/test_context_relevance.py tests/test_context_quality_metrics.py tests/test_context_pack_v2.py tests/test_phase10.py tests/test_context_injection_guard.py -q`，44/44 pass。

### 回滚

`git checkout -- local_memory_mcp/storage/search.py tests/test_context_relevance.py TODO.md ITERATION.md`

---

## [迭代 48] 2026-05-31 — start.sh 默认安装完整依赖

### 变更

- `start.sh`: 一键启动依赖安装从 `pip install -e .[extraction]` 改为 `pip install -e .[all]`，默认包含 extraction 与 Qdrant vector 依赖。
- `README.md`: 快速开始和手动安装说明同步改为 `.[all]`，避免文档继续引导新设备只安装抽取依赖。
- `tests/test_deployment.py`: 新增回归测试，确保 `start.sh` 默认安装完整 extras，README 也同步描述完整安装。
- `TODO.md`: 将 `start.sh` 默认安装完整依赖 `.[all]` 标记为已完成。

### 修复

- 修复新设备按 `bash start.sh` 快速启动时只安装 `.[extraction]`，导致 Qdrant client 缺失、语义检索/vector 能力降级的问题。

### 验证

- Shell 语法: `bash -n start.sh` 通过。
- 测试: `.venv/bin/python -m pytest tests/test_deployment.py -q`，6/6 pass。

### 回滚

`git checkout -- start.sh README.md tests/test_deployment.py TODO.md ITERATION.md`

---

## [迭代 49] 2026-05-31 — 修复前端向量搜索阈值参数

### 变更

- `local_memory_mcp/frontend.py`: `/api/vector/search` 调用 `VectorStore.search()` 时改用 `top_k=` 和 `score_threshold=` 关键字参数，避免第三个位置参数被解释为 `filters`。
- `tests/test_frontend.py`: 新增前端 vector search 回归测试，使用 fake vector store 验证 `score_threshold` 进入关键字参数且 `filters` 保持 `None`。
- `TODO.md`: 将前端 `/api/vector/search` 的 `score_threshold` 参数传递问题标记为已完成。

### 修复

- 修复前端控制台/API 调用语义搜索时 `score_threshold` 实际未生效的问题；该问题会影响向量检索结果过滤，导致前端看到低于阈值的弱相关结果。

### 验证

- 语法检查: `.venv/bin/python -m py_compile local_memory_mcp/frontend.py` 通过。
- 测试: `.venv/bin/python -m pytest tests/test_frontend.py -q`，8/8 pass（1 个 httpx 测试客户端弃用警告）。

### 回滚

`git checkout -- local_memory_mcp/frontend.py tests/test_frontend.py TODO.md ITERATION.md`

---

## [迭代 50] 2026-05-31 — 默认启用对话前自动记忆注入

### 变更

- `scripts/hooks/lmmcp-context.sh`: 扩展 prompt 字段读取，支持 `user_prompt` / `input`，并从 hook payload 的 `project_path` / `cwd` / `working_directory` / `workspace` 提取项目路径传给 `memory_context`。
- `scripts/setup-hooks.sh`: 默认为 Claude Code 和 Codex 注册 `UserPromptSubmit -> lmmcp-context.sh`，保留 Stop hook 后台调用 `memory_ingest` 写回 transcript。
- `scripts/setup-hooks.sh`: 更新写入 CLAUDE.md / AGENTS.md 的记忆规则，改为自动注入为主，显式 `memory_context` 仅作为自动上下文缺失或弱相关时的兜底。
- `scripts/connect_agents.py`: `--register-hooks` 同步默认注册 Claude/Codex 的 UserPromptSubmit context hook，并继续注册 Stop 写回 hook。
- `README.md`: Agent hook 部署说明补充回答前自动 context 注入脚本和回答后写回脚本。
- `tests/test_deployment.py`: 增加回归测试，锁定 setup-hooks/connect_agents 默认注册 prompt context injection，并验证 context hook 传递 `project_path`。
- `TODO.md`: 将 Claude/Codex 对话前自动检索注入问题标记为已完成，并新增 Hermes/Gemini/opencode pre-prompt 注入支持矩阵待办。

### 修复

- 修复 hook 初始化脚本虽然存在 `lmmcp-context.sh`，但默认移除/不注册 `UserPromptSubmit`，导致对话前无法自动语义检索并注入相关记忆的问题。

### 验证

- Shell 语法: `bash -n scripts/setup-hooks.sh scripts/hooks/lmmcp-context.sh` 通过。
- Python 编译: `.venv/bin/python -m py_compile scripts/connect_agents.py` 通过。
- 测试: `.venv/bin/python -m pytest tests/test_deployment.py -q`，7/7 pass。

### 已知问题

- Hermes 当前仍只注册 `on_session_end` 写回；Gemini/opencode 也尚未验证 pre-prompt 注入能力，后续需要补齐各 agent 的自动注入支持矩阵。

### 回滚

`git checkout -- scripts/hooks/lmmcp-context.sh scripts/setup-hooks.sh scripts/connect_agents.py README.md tests/test_deployment.py TODO.md ITERATION.md`

---

## [迭代 51] 2026-06-01 — SessionStart 自动注册 agent presence 与 capability

### 变更

- `scripts/hooks/session-start.sh`: 保留启动/标记会话行为，并在 SessionStart hook 中初始化 MCP session，使用短 timeout 调用 `agent_presence_update` 将当前 agent 标记为 `online`，再调用 `agent_capability_register` 注册默认能力；支持 `LMMCP_AGENT_ID`、`LMMCP_AGENT_NAMESPACE`、`LMMCP_AGENT_CAPABILITIES` 和 timeout 环境变量覆盖。
- `scripts/setup-hooks.sh`: 一键 hook 部署新增 Claude/Codex `SessionStart -> session-start.sh` 注册，命令中显式传入 `LMMCP_AGENT_ID`。
- `scripts/connect_agents.py`: `--register-hooks` 同步新增 Claude/Codex SessionStart hook；opencode 的 `session_start` 命令改为带 `LMMCP_AGENT_ID=opencode`。
- `README.md`: Agent Session Hook 部署说明补充启动注册脚本，以及 presence/capability 注册、读前注入、结束写回三段流程。
- `tests/test_deployment.py`: 增加部署回归测试，锁定 `session-start.sh` 的 MCP presence/capability 调用、短 timeout、非阻塞失败策略，以及 setup/connect 脚本的 SessionStart 注册。
- `TODO.md`: 将 agent presence/capability 自动心跳与能力注册入口标记为已完成。

### 修复

- 修复 handoff 自动路由依赖在线状态和能力注册、但 agent 启动时不会自动上报 presence/capability 的问题；现在 Claude/Codex/opencode 启动链路会带 agent id 进入 `session-start.sh`，默认能力可用于后续 `agent_handoff_create(auto_route=True)` 路由。

### 验证

- Shell 语法: `bash -n scripts/hooks/session-start.sh scripts/setup-hooks.sh` 通过。
- Python 编译: `.venv/bin/python -m py_compile scripts/connect_agents.py` 通过。
- 测试: `.venv/bin/python -m pytest tests/test_deployment.py tests/test_handoff.py tests/test_mailbox.py tests/test_mailbox_enhanced.py -q`，62/62 pass。

### 已知问题

- 本轮只补齐启动时 presence/capability 注册；Hermes/Gemini/opencode 的 pre-prompt 自动 `memory_context` 注入覆盖面仍按 TODO 后续处理。

### 回滚

`git checkout -- scripts/hooks/session-start.sh scripts/setup-hooks.sh scripts/connect_agents.py README.md tests/test_deployment.py TODO.md ITERATION.md`

---

## [迭代 52] 2026-06-01 — Embedding 降级链补齐 sentence-transformers

### 变更

- `local_memory_mcp/vector_store.py`: `EmbedConfig` 增加 `fallback_provider` 与 `sentence_transformers_model`；`embed_text()` 从单层 Ollama -> hashing 降级改为 Ollama -> sentence-transformers -> hashing，支持 `LOCAL_MEMORY_EMBEDDING_PROVIDER`、`LOCAL_MEMORY_EMBEDDING_FALLBACK_PROVIDER`、`LOCAL_MEMORY_SENTENCE_TRANSFORMERS_MODEL`、`LOCAL_MEMORY_EMBEDDING_DIM`、`LOCAL_MEMORY_OLLAMA_URL` 等环境变量覆盖。
- `local_memory_mcp/vector_store.py`: 新增 sentence-transformers 本地模型缓存和 embedding 维度规整，保证 fallback 输出与 Qdrant collection 维度一致。
- `local_memory_mcp/models.py` / `config.yaml`: 配置默认值与校验规则加入 `sentence-transformers` provider、fallback provider 和默认 fallback model。
- `pyproject.toml`: 新增 `embedding` optional extra，并将 `all` 扩展为 `vector + extraction + embedding`。
- `scripts/deploy.sh`: 写入 config 时同步 fallback provider/model；安装依赖时在 `requirements.txt` 后继续安装 `.[all]`，确保一键部署补齐 Qdrant、extraction 与 sentence-transformers fallback 依赖。
- `README.md` / `docs/deployment.md`: 更新语义检索降级说明和相关环境变量。
- `tests/test_vector_store.py` / `tests/test_config_validation.py` / `tests/test_deployment.py`: 增加 fallback 顺序、环境变量覆盖、配置校验和部署安装完整 extras 的回归测试。
- `TODO.md`: 将 Embedding sentence-transformers 降级和 `deploy.sh` 完整 extras 安装标记为已完成。

### 修复

- 修复 Ollama 不可用时只能降级到 hashing，导致语义检索质量明显变弱的问题；现在本机有 sentence-transformers 依赖/模型时会优先使用真实本地 embedding。
- 修复 `embed_config_from_dict()` 的默认 Ollama URL 回退值误写为 `127.0.0.1:12434` 的问题，统一为 `127.0.0.1:11434`。
- 修复 `deploy.sh` 只安装 `requirements.txt`，可能漏装 `qdrant-client`、`httpx` optional extra 和本地 embedding fallback 依赖的问题。

### 验证

- 语法检查: `.venv/bin/python -m py_compile local_memory_mcp/vector_store.py local_memory_mcp/models.py` 通过。
- Shell 语法: `bash -n scripts/deploy.sh` 通过。
- 测试: `.venv/bin/python -m pytest tests/test_vector_store.py tests/test_config_validation.py tests/test_deployment.py -q`，48/48 pass。
- 回归组合: `.venv/bin/python -m pytest tests/test_context_relevance.py tests/test_context_quality_metrics.py tests/test_context_pack_v2.py tests/test_phase10.py tests/test_context_injection_guard.py tests/test_vector_store.py tests/test_config_validation.py tests/test_deployment.py -q`，92/92 pass。

### 已知问题

- sentence-transformers fallback 依赖较重；`.[all]` 会补齐依赖，但首次使用具体模型时仍可能需要本机已有模型缓存或网络下载。

### 回滚

`git checkout -- local_memory_mcp/vector_store.py local_memory_mcp/models.py config.yaml pyproject.toml scripts/deploy.sh README.md docs/deployment.md tests/test_vector_store.py tests/test_config_validation.py tests/test_deployment.py TODO.md ITERATION.md`

---

## [迭代 53] 2026-06-01 — opencode 会话结束写回覆盖

### 变更

- `scripts/hooks/lmmcp-ingest.py`: 后台模式新增通用 `LMMCP_INGEST_HOOK_PAYLOAD` 透传，保留 Hermes 兼容变量；新增 hook payload session id 解析工具。
- `scripts/hooks/lmmcp-ingest.py`: 新增 opencode SQLite transcript 抽取，默认从 `~/.local/share/opencode/opencode.db` 读取最新 session 或 hook payload 指定 session，只保留 user/assistant 的 text part，过滤 tool/reasoning/step part。
- `scripts/hooks/lmmcp-ingest.py`: 新增 Gemini JSONL transcript 解析入口，支持 `GEMINI_SESSION_FILE`，将 Gemini `model` role 归一为 assistant。
- `scripts/connect_agents.py`: opencode `session_end` hook 改为 `python3 lmmcp-ingest.py --agent opencode --background`，避免写回阻塞 agent 退出。
- `tests/test_lmmcp_ingest_hook.py`: 新增 opencode SQLite 抽取和 Gemini JSONL 抽取回归测试。
- `tests/test_deployment.py`: 增加 opencode session_end 后台写回部署断言。
- `README.md`: 更新 Agent Session Hook 部署说明，补充 opencode 与 Gemini transcript 来源。
- `TODO.md`: 将 opencode 回答后自动写回覆盖标记为已完成，并拆出 Gemini 自动 session_end hook 待办。

### 修复

- 修复 opencode 虽然通过 `connect_agents.py --register-hooks` 写入了 `session_end`，但 `lmmcp-ingest.py` 不识别 `--agent opencode`，导致会话结束无法自动抽取并写回 lmmcp 的问题。

### 验证

- Python 编译: `.venv/bin/python -m py_compile scripts/hooks/lmmcp-ingest.py scripts/connect_agents.py` 通过。
- 测试: `.venv/bin/python -m pytest tests/test_lmmcp_ingest_hook.py tests/test_deployment.py tests/test_handoff.py tests/test_mailbox.py tests/test_mailbox_enhanced.py -q`，65/65 pass。
- Dry-run: `.venv/bin/python scripts/connect_agents.py --agents opencode --register-hooks --dry-run --no-probe` 正确显示会更新并注册 `/home/advancer/.config/opencode/opencode.json`。

### 已知问题

- Gemini 目前只有 `GEMINI_SESSION_FILE` 解析能力，本机未发现可验证的 Gemini CLI session_end hook/历史文件格式，自动 hook 注册仍在 TODO。
- Hermes/Gemini/opencode 对话前 pre-prompt/pre-LLM 自动 `memory_context` 注入矩阵仍未完成。

### 回滚

`git checkout -- scripts/hooks/lmmcp-ingest.py scripts/connect_agents.py README.md tests/test_lmmcp_ingest_hook.py tests/test_deployment.py TODO.md ITERATION.md`

---

## [迭代 54] 2026-06-01 — opencode 对话前自动 memory_context 注入

### 变更

- `scripts/hooks/opencode-lmmcp-plugin.js`: 新增 opencode plugin，通过 `experimental.chat.system.transform` 在 LLM 调用前读取当前 session 最近用户消息，按 MCP streamable HTTP 初始化 session 并调用 `memory_context`，将返回 context 追加到 system context。
- `scripts/connect_agents.py`: opencode hook 注册新增 plugin 配置写入，`--register-hooks` 会把 `opencode-lmmcp-plugin.js` 以 `plugin` 条目注册到 opencode config，并使用当前 `--endpoint` 作为 plugin 调用的 lmmcp URL。
- `tests/test_deployment.py`: 增加 opencode pre-LLM context 注入 plugin 注册与实现断言。
- `README.md`: Agent Session Hook 部署说明补充 opencode plugin 读前注入链路。
- `TODO.md`: 将 opencode 对话前自动检索注入标记为已完成，并将剩余 Hermes/Gemini pre-prompt 注入缺口拆分保留。

### 修复

- 修复 opencode 只有 MCP server、session_start 和 session_end，缺少对话前自动 `memory_context` 注入的问题；现在 opencode 在模型调用前会自动读取 lmmcp 相关记忆作为不可信背景上下文。

### 验证

- Python 编译: `.venv/bin/python -m py_compile scripts/connect_agents.py` 通过。
- JS 语法: `node --check scripts/hooks/opencode-lmmcp-plugin.js` 通过。
- 测试: `.venv/bin/python -m pytest tests/test_deployment.py -q`，11/11 pass。
- 回归组合: `.venv/bin/python -m pytest tests/test_deployment.py tests/test_lmmcp_ingest_hook.py tests/test_handoff.py tests/test_mailbox.py tests/test_mailbox_enhanced.py -q`，66/66 pass。
- Dry-run: `.venv/bin/python scripts/connect_agents.py --agents opencode --register-hooks --dry-run --no-probe` 正确显示会更新并注册 `/home/advancer/.config/opencode/opencode.json`。

### 已知问题

- Hermes/Gemini 的对话前 pre-prompt/pre-LLM 自动 `memory_context` 注入仍待补齐；Gemini 的自动 session_end hook 仍待确认可验证 hook 机制。

### 回滚

`git checkout -- scripts/hooks/opencode-lmmcp-plugin.js scripts/connect_agents.py README.md tests/test_deployment.py TODO.md ITERATION.md`

---

## [迭代 55] 2026-06-01 — Hermes 对话前自动 memory_context 注入与弱相关过滤收紧

### 变更

- `scripts/hooks/lmmcp-context.sh`: 兼容 Hermes `pre_llm_call` shell hook payload，从 `extra.user_message` 读取用户提示词，并在 Hermes 场景输出 `{"context": ...}`；Claude/Codex 仍输出 `additionalContext`。
- `scripts/hooks/lmmcp-context.sh`: 当 `memory_context` 返回 `used_ids=[]` 时静默跳过，避免注入只有 header 的空上下文。
- `scripts/connect_agents.py`: Hermes hook 注册补齐 `pre_llm_call -> lmmcp-context.sh`，继续注册 `on_session_end -> lmmcp-ingest.py --agent hermes --background`，并同步写入 shell hook allowlist。
- `scripts/setup-hooks.sh`: 一键 hook 部署会复制 Hermes context hook 到 `~/.hermes/agent-hooks/lmmcp-context.sh`，注册 `pre_llm_call` 与 allowlist。
- `local_memory_mcp/storage/search.py`: 收紧 context pack 相关性阈值，`min_relevance_score` 调整为 `0.22`，`min_vector_only_relevance_score` 调整为 `0.45`，新增 keyword lexical 最低阈值 `0.08`，过滤 medium-score vector-only 与弱中文 keyword overlap。
- `scripts/hooks/opencode-lmmcp-plugin.js`: 与 shell hook 一致，`used_ids=[]` 时不向 opencode system context 注入空记忆块。
- `tests/test_deployment.py` / `tests/test_context_relevance.py`: 增加 Hermes pre-LLM 注入注册、Hermes 输出格式、空 context 跳过、中文弱 keyword overlap 和 medium-score vector-only 过滤回归断言。
- `README.md`: 更新 Agent Session Hook 部署说明，补充 Hermes `pre_llm_call` 读前注入链路。
- `TODO.md`: 将 Hermes 对话前自动检索注入标记为完成，保留 Gemini 对话前注入缺口；新增 prompt 检索相关性持续评测集待办。

### 修复

- 修复 Hermes 只有 MCP server 与 `on_session_end` 写回、缺少回答前自动 `memory_context` 注入的问题。
- 修复短中文提示下，中等向量分数但零 lexical 命中的 vector-only 记录，以及只命中少量中文 ngram 的 keyword 兜底记录仍可能进入 context pack 的问题。
- 修复自动注入链路在无相关记忆时仍注入空 `memory_context` header 的问题。

### 验证

- Shell 语法: `bash -n scripts/setup-hooks.sh scripts/hooks/lmmcp-context.sh scripts/hooks/session-start.sh` 通过。
- Python 编译: `.venv/bin/python -m py_compile local_memory_mcp/storage/search.py scripts/connect_agents.py` 通过。
- JS 语法: `node --check scripts/hooks/opencode-lmmcp-plugin.js` 通过。
- 测试: `.venv/bin/python -m pytest tests/test_context_relevance.py tests/test_context_quality_metrics.py tests/test_context_pack_v2.py tests/test_phase10.py tests/test_context_injection_guard.py tests/test_deployment.py tests/test_lmmcp_ingest_hook.py -q`，60/60 pass。
- 真实 hook: 使用 Hermes `pre_llm_call` 形状 payload 调用 `scripts/hooks/lmmcp-context.sh`，在无相关记忆时输出 0 字节，不再注入弱相关记录或空 header。
- 服务状态: `systemctl --user restart lmmcp.service` 后 `scripts/lmmcp status` 显示 `http://127.0.0.1:8318/mcp` running。

### 已知问题

- Gemini 对话前自动 `memory_context` 注入和 Gemini 回答后自动 session_end hook 仍未完成，继续保留在 `TODO.md`。
- prompt 检索相关性仍需要真实失败样例沉淀为持续评测集，避免后续阈值/排序回退。

### 回滚

`git checkout -- local_memory_mcp/storage/search.py scripts/hooks/lmmcp-context.sh scripts/hooks/opencode-lmmcp-plugin.js scripts/connect_agents.py scripts/setup-hooks.sh README.md tests/test_deployment.py tests/test_context_relevance.py TODO.md ITERATION.md`

---

## [迭代 56] 2026-06-01 — Gemini 自动读前/写后 hooks 与 Docker Compose Qdrant 默认启用

### 变更

- `scripts/hooks/lmmcp-context.sh`: `BeforeAgent` hook 场景输出 Gemini 可识别的 `hookSpecificOutput.hookEventName=BeforeAgent` 与 `additionalContext`。
- `scripts/hooks/lmmcp-ingest.py`: Gemini 写回优先读取 hook stdin / background payload 里的 `transcript_path`，并支持 Gemini JSON transcript 与 JSONL transcript 两种格式。
- `scripts/connect_agents.py`: `--register-hooks` 新增 Gemini `SessionStart`、`BeforeAgent`、`SessionEnd` 注册，分别接入 presence/capability、读前 `memory_context` 注入和后台 `memory_ingest` 写回。
- `scripts/setup-hooks.sh`: 一键 hook 初始化同步写入 `~/.gemini/settings.json` 的 `mcpServers.local_memory`、`SessionStart`、`BeforeAgent`、`SessionEnd`。
- `Dockerfile`: 容器镜像改为从源码安装 `.[all]`，默认带 Qdrant client、extraction 与 embedding fallback 依赖，并设置容器内 Qdrant endpoint。
- `docker-compose.yml`: 默认启动 lmmcp + Qdrant，启用 `qdrant_data` / `lmmcp_data` 持久化 volume，lmmcp 依赖 Qdrant 服务并暴露健康检查。
- `README.md` / `docs/deployment.md`: 更新 Gemini hooks、Docker Compose 快速启动和 Qdrant 默认启用说明。
- `tests/test_deployment.py` / `tests/test_lmmcp_ingest_hook.py`: 增加 Gemini hook 注册、Gemini `transcript_path` JSON transcript 抽取、Docker Compose Qdrant/full extras 回归测试。
- `TODO.md`: 将 Gemini 对话前注入、Gemini 回答后写回和 Docker Compose Qdrant 默认启用标记为完成；新增 Gemini 真实 CLI 现场验证待办。

### 修复

- 修复 Gemini 仅配置 MCP server、但缺少自动读前 `memory_context` 注入和回答后自动 `memory_ingest` 写回的问题。
- 修复 Docker Compose 默认只启动 lmmcp、Qdrant 被注释且 Dockerfile 未安装完整 extras，导致容器部署缺少语义检索依赖的问题。

### 验证

- Shell 语法: `bash -n scripts/setup-hooks.sh scripts/hooks/lmmcp-context.sh` 通过。
- Python 编译: `.venv/bin/python -m py_compile scripts/connect_agents.py scripts/hooks/lmmcp-ingest.py` 通过。
- Docker Compose 配置: `docker compose config` 通过。
- 测试: `.venv/bin/python -m pytest tests/test_deployment.py tests/test_lmmcp_ingest_hook.py -q`，17/17 pass。
- 回归组合: `.venv/bin/python -m pytest tests/test_context_relevance.py tests/test_context_quality_metrics.py tests/test_context_pack_v2.py tests/test_phase10.py tests/test_context_injection_guard.py tests/test_deployment.py tests/test_lmmcp_ingest_hook.py tests/test_vector_store.py tests/test_config_validation.py -q`，102/102 pass。
- Dry-run: `.venv/bin/python scripts/connect_agents.py --agents gemini --register-hooks --dry-run --no-probe` 正确显示会更新 WSL 与 Windows Gemini settings，并注册 Gemini hooks。

### 已知问题

- 本机当前没有 `gemini` 命令，Gemini 真实 CLI BeforeAgent/SessionEnd 现场验证仍保留在 `TODO.md`。
- Docker Compose 已通过配置解析，但未执行真实 `docker compose up --build`，仍需在可接受拉取/构建耗时的窗口做一次容器端到端验证。

### 回滚

`git checkout -- Dockerfile docker-compose.yml scripts/hooks/lmmcp-context.sh scripts/hooks/lmmcp-ingest.py scripts/connect_agents.py scripts/setup-hooks.sh README.md docs/deployment.md tests/test_deployment.py tests/test_lmmcp_ingest_hook.py TODO.md ITERATION.md`

---

## [迭代 57] 2026-06-01 — start.sh venv 漂移自修复与 audit import 忽略策略显式化

### 变更

- `start.sh`: 新增 `venv_needs_rebuild()`，启动前检查 `.venv/bin/python` 是否可运行，以及 `.venv/bin/pip` / `.venv/bin/pytest` shebang 是否指向当前 checkout 的 `.venv/bin/python`。
- `start.sh`: 检测到 venv 路径漂移或 python 不可运行时，自动删除并重建 `.venv`，避免跨目录迁移后 `bad interpreter` 阻断一键启动。
- `local_memory_mcp/storage/transfer.py`: `memory_import()` 对 payload 中不支持导入的表返回 `ignored_tables`，并把该字段写入 `memory_import` 审计事件 detail。
- `tests/test_deployment.py`: 增加 `start.sh` venv 漂移检测回归断言。
- `tests/test_transfer.py`: 增加 `audit_events` 导出后导入被显式报告为 ignored 的回归测试。
- `TODO.md`: 将 `start.sh` venv 路径漂移检测和 audit 导入策略标记为完成。

### 修复

- 修复 `.venv` 从旧 checkout 迁移/复用时，pip/pytest 等入口脚本 shebang 指向旧路径导致一键启动失败的问题。
- 修复 `memory_export(include_audit=True)` 导出的 `audit_events` 在 `memory_import()` 中被静默忽略的问题；现在策略明确为不导入本机审计日志，但返回和审计记录都会报告 `ignored_tables=["audit_events"]`。

### 验证

- Shell 语法: `bash -n start.sh scripts/setup-hooks.sh scripts/hooks/lmmcp-context.sh` 通过。
- Python 编译: `.venv/bin/python -m py_compile local_memory_mcp/storage/transfer.py` 通过。
- 测试: `.venv/bin/python -m pytest tests/test_transfer.py tests/test_sync.py tests/test_deployment.py -q`，32/32 pass。

### 已知问题

- Docker Compose 真实容器端到端验证仍未执行，仅完成静态 `docker compose config`。
- Gemini 真实 CLI BeforeAgent/SessionEnd 验证仍受限于本机没有 `gemini` 命令。

### 回滚

`git checkout -- start.sh local_memory_mcp/storage/transfer.py tests/test_deployment.py tests/test_transfer.py TODO.md ITERATION.md`

---

## [迭代 58] 2026-06-01 — lmmcp 端到端应用流程扫描第一版

### 变更

- `TODO.md`: 将用户反馈“输入提示词后，检索到的记忆相关性不强”明确并入 prompt 后记忆检索相关性持续评测专项。
- `/mnt/d/Advancer/Desktop/output/lmmcp-system-flow-2026-06-01.html`: 生成第一版可视化系统流程梳理，覆盖部署、agent 接入、读前检索注入、回答后抽取写回、Qdrant/SQLite 双存储、curator/rollup 状态流转、agent 协作与当前符合度缺口，供用户确认。

### 验证

- 文档检查: `TODO.md` 已保留该问题的开放评测项，未新增重复待办。
- 输出文件: HTML 已按用户约定写入 `/mnt/d/Advancer/Desktop/output`。

### 已知问题

- 本轮只完成全盘流程梳理第一版；`semantic-*` CLI 仍是兼容提示、Gemini 真实 CLI 现场验证、Docker Compose 容器端到端验证仍保留在 `TODO.md`。

### 回滚

`git checkout -- TODO.md ITERATION.md && rm -f /mnt/d/Advancer/Desktop/output/lmmcp-system-flow-2026-06-01.html`

---

## [迭代 59] 2026-06-01 — semantic-* CLI 接入真实 Qdrant 向量层

### 变更

- `local_memory_mcp/server.py`: `semantic-status` 改为调用 `VectorStore.status()`，输出当前 Qdrant collection、embedding provider、count 等状态。
- `local_memory_mcp/server.py`: `semantic-search` 改为调用 Qdrant `VectorStore.search()`，支持 `--limit`、`--status` 和 `--score-threshold`，输出命中 id、score、text、payload。
- `local_memory_mcp/server.py`: `semantic-index` 改为调用 `memory_rebuild_vectors()`，默认 dry-run，传入 `--force` 后才实际从 SQLite 重建 Qdrant 向量。
- `tests/test_cli.py`: 增加 CLI 回归测试，使用 fake vector store/rebuild 函数验证 status/search/index 参数与输出，不依赖真实 Qdrant。
- `README.md`: 删除 `semantic-*` 仅返回兼容提示的过时说明，补充真实语义 CLI 用法。
- `TODO.md`: 将 `semantic-*` CLI 改为真实 Qdrant 功能标记为完成。

### 修复

- 修复 CLI 语义命令仍提示 sqlite-vec 已移除、无法作为部署和排障入口验证 Qdrant 语义层的问题。

### 验证

- 语法检查: `.venv/bin/python -m py_compile local_memory_mcp/server.py tests/test_cli.py` 通过。
- 测试: `.venv/bin/python -m pytest tests/test_cli.py tests/test_vector_store.py tests/test_degraded.py -q`，32/32 pass。

### 已知问题

- `semantic-search --status` 依赖 Qdrant payload 里的 `status` 字段；如果历史 payload 与 SQLite 状态失同步，需要先运行 `semantic-index --force` 或 `memory_rebuild_vectors(dry_run=False)` 重建向量。

### 回滚

`git checkout -- local_memory_mcp/server.py tests/test_cli.py README.md TODO.md ITERATION.md`

---

## [迭代 60] 2026-06-01 — deploy.sh 默认补齐 Docker/Ollama/Qdrant 运行时依赖

### 变更

- `scripts/deploy.sh`: 一键部署默认开启 host dependency bootstrap、Ollama 安装/启动与 embedding 模型拉取、非交互 package manager yes flag，和默认 Qdrant systemd service 形成完整运行时依赖补齐链路。
- `scripts/deploy.sh`: 新增 `--no-ollama` 与 `--no-assume-yes`，并让 `LMMCP_BOOTSTRAP_DEPS`、`LMMCP_WITH_OLLAMA`、`LMMCP_ASSUME_YES` 支持显式 `0/1` 覆盖默认策略。
- `tests/test_deployment.py`: 增加部署策略回归测试，锁定默认 `BOOTSTRAP_DEPS=1`、`WITH_OLLAMA=1`、`ASSUME_YES=1`、Docker/Qdrant/Ollama 补齐入口和关闭开关。
- `README.md` / `docs/deployment.md`: 更新一键部署说明，从“可选补齐依赖”改为“默认补齐依赖，可显式关闭”。
- `TODO.md`: 将 `deploy.sh` 默认自动补齐运行时依赖标记为完成。

### 修复

- 修复 `scripts/deploy.sh` 虽名为一键部署，但默认不启用 `--bootstrap-deps` / `--with-ollama`，在缺少 Docker/Ollama 的新机器上仍需用户额外理解并手动补参数的问题。

### 验证

- Shell 语法: `bash -n scripts/deploy.sh` 通过。
- Dry-run: `scripts/deploy.sh --dry-run --skip-tests` 显示默认 `bootstrap deps: 1 (assume_yes=1)`、`qdrant: 1`、`ollama: 1`、`pull images: 1`、`pull_models=1`。
- 测试: `.venv/bin/python -m pytest tests/test_deployment.py -q`，16/16 pass。

### 已知问题

- Docker Compose 真实容器端到端验证仍未执行。
- 默认自动安装 Docker/Ollama 仍依赖系统存在可用包管理器和 sudo/root 权限；受限环境需要使用 `--no-bootstrap-deps`、`--no-ollama` 或外部 Qdrant/Ollama。

### 回滚

`git checkout -- scripts/deploy.sh tests/test_deployment.py README.md docs/deployment.md TODO.md ITERATION.md`

---

## [迭代 61] 2026-06-01 — 前端测试恢复验证与 all extra 轻量化

### 变更

- `pyproject.toml`: 将 `.[all]` 收敛为默认运行依赖 `vector + extraction`，避免默认更新拉取 `sentence-transformers` 大依赖；新增 `.[full]` 作为包含 `embedding` 的显式重依赖 extra。
- `README.md` / `docs/deployment.md`: 更新安装说明，明确 `.[all]` 不再安装 `sentence-transformers`，需要本地 sentence-transformers fallback 时使用 `.[embedding]` 或 `.[full]`。
- `tests/test_deployment.py`: 增加 optional extras 结构回归测试，锁定 `all` 轻量、`full` 重依赖、`embedding` 显式安装路径。
- `TODO.md`: 记录并完成前端 TestClient 卡死验证项与 `.[all]` 安装过重问题。

### 修复

- 修复 `.[all]` / `start.sh` / `deploy.sh` 默认安装链路会尝试安装 `sentence-transformers`，在网络或大包下载较慢时导致一键更新长时间无进展的问题。
- 对 `tests/test_frontend.py` 单独运行卡在第一个 `TestClient` 用例的问题做运行态复验；当前在清理遗留进程并重启真实 `lmmcp.service` 后不再复现，前端测试已恢复稳定通过。

### 验证

- 依赖安装: `.venv/bin/python -m pip install -q -e '.[all]'` 成功完成，且 `importlib.util.find_spec('sentence_transformers') is not None` 返回 `False`。
- Shell 语法: `bash -n start.sh scripts/deploy.sh` 通过。
- Python 编译: `.venv/bin/python -m py_compile local_memory_mcp/vector_store.py` 通过。
- 相关测试: `.venv/bin/python -m pytest tests/test_frontend.py tests/test_deployment.py tests/test_vector_store.py tests/test_config_validation.py -q`，64/64 pass。
- 全量测试: `.venv/bin/python -m pytest -q`，393/393 pass。

### 已知问题

- `sentence-transformers` fallback 仍是可选重依赖；未显式安装 `.[embedding]` / `.[full]` 且 Ollama 不可用时，embedding 会继续降级到 deterministic hashing。
- 前端 TestClient 卡死未找到代码级稳定复现路径；当前证据指向上轮更新过程中遗留进程/运行态切换导致的临时阻塞，已用单文件与全量测试覆盖验证。

### 回滚

`git checkout -- pyproject.toml README.md docs/deployment.md tests/test_deployment.py start.sh TODO.md ITERATION.md`

---

## [迭代 62] 2026-06-01 — prompt 记忆检索相关性持续评测集

### 变更

- `tests/fixtures/context_relevance_cases.json`: 新增真实弱相关 prompt fixture，覆盖“输入提示词后检索到的记忆相关性不强”和“多客户端 first-token latency 应指向共享代理/上游”的场景。
- `tests/test_context_relevance.py`: 新增 fixture 驱动的持续评测测试，逐条校验 expected/rejected memory id、`hit_rate`、`filter_rate` 与 trace 字段。
- `TODO.md`: 将 prompt 后记忆检索相关性持续评测集标记为完成。

### 修复

- 修复相关性优化只有临时回归断言、缺少可扩展评测样例文件的问题；后续新增真实弱相关 prompt 可直接追加到 fixture。

### 验证

- 测试: `.venv/bin/python -m pytest tests/test_context_relevance.py -q`，7/7 pass。

### 已知问题

- 当前评测集仍是小样本；后续真实弱相关 prompt 应继续追加到 fixture，而不是只调阈值。

### 回滚

`git checkout -- tests/test_context_relevance.py tests/fixtures/context_relevance_cases.json TODO.md ITERATION.md`

---

## [迭代 63] 2026-06-01 — rollup 扫描测试隔离外部 LLM

### 变更

- `tests/test_curator_v3.py`: manual source 与 extraction source 的 rollup 扫描测试传入 stub summarizer，只验证 eligible/source_ids 扫描语义，不再触发默认 LLM summarizer。
- `TODO.md`: 将 rollup 测试隔离问题标记为完成。

### 修复

- 修复 `force=True` dry-run rollup 测试在本机存在真实 extraction 配置时可能调用外部 LLM 并超时的问题。

### 验证

- 测试: `.venv/bin/python -m pytest tests/test_curator_v3.py tests/test_rollup.py -q`，24/24 pass。

### 已知问题

- rollup 默认 summarizer 的真实 LLM 质量仍依赖运行时 extraction 配置；本轮只隔离测试，不改变生产行为。

### 回滚

`git checkout -- tests/test_curator_v3.py TODO.md ITERATION.md`

---

## [迭代 64] 2026-06-01 — 移除 agent 权限管理半成品

### 变更

- `local_memory_mcp/server.py`: 删除 MCP 工具 `agent_permission_grant` 与 `agent_permission_get`，工具数量从 36 收敛到 34。
- `local_memory_mcp/storage/crud.py`: 移除写入记忆时的 agent permission 检查，所有本地 agent 默认可写，保持个人本地总线的简单模型。
- `local_memory_mcp/storage/agents.py`: 移除 broadcast permission 检查和从 permission policy 补 namespace 的逻辑；广播改为发送给所有 online/idle agent（排除发送者）。
- `local_memory_mcp/storage/db.py` / `local_memory_mcp/storage/transfer.py`: 不再创建或导出 `agent_permissions` 表。
- `local_memory_mcp/frontend.py` / `README.md`: 删除 agent permission API 入口和工具文档条目，并更新 MCP 工具数量。
- `tests/test_agent_permissions.py`: 删除权限管理测试；`tests/test_mailbox.py` / `tests/test_transfer.py` 补充权限移除后的广播、presence 和导出断言。
- `TODO.md`: 将 agent/model 权限管理删除项标记为完成；Gemini 真实 CLI 验证项更新为当前缺少 `GEMINI_API_KEY` 的阻塞状态。

### 修复

- 修复 lmmcp 作为个人本地记忆总线仍维护半成品 RBAC，导致 agent 写入、广播、presence namespace 与同步导出行为复杂化的问题。

### 验证

- Python 编译: `.venv/bin/python -m py_compile local_memory_mcp/storage/crud.py local_memory_mcp/storage/agents.py local_memory_mcp/storage/__init__.py local_memory_mcp/storage/db.py local_memory_mcp/storage/transfer.py local_memory_mcp/server.py local_memory_mcp/frontend.py local_memory_mcp/__init__.py` 通过。
- 相关测试: `.venv/bin/python -m pytest tests/test_mailbox.py tests/test_transfer.py tests/test_sync.py tests/test_frontend.py -q`，46/46 pass。
- 全量测试: `.venv/bin/python -m pytest -q`，390/390 pass。
- Gemini 现场检查: `gemini mcp list` 显示 `local_memory` connected；`gemini -p ... --output-format json` 因缺少 `GEMINI_API_KEY` 退出 code 41，真实 BeforeAgent/SessionEnd 验证继续保留在 TODO。

### 已知问题

- 旧运行库如果已存在 `agent_permissions` 表，本轮不会主动 drop；新初始化 schema 和导出/导入路径已不再创建或使用它。
- Gemini 真实 CLI 端到端验证需要先配置 `GEMINI_API_KEY`。

### 回滚

`git checkout -- local_memory_mcp/server.py local_memory_mcp/storage/crud.py local_memory_mcp/storage/agents.py local_memory_mcp/storage/__init__.py local_memory_mcp/storage/db.py local_memory_mcp/storage/transfer.py local_memory_mcp/frontend.py local_memory_mcp/__init__.py local_memory_mcp/storage/permissions.py tests/test_agent_permissions.py tests/test_mailbox.py tests/test_transfer.py README.md TODO.md ITERATION.md`

---

## [迭代 65] 2026-06-01 — MCP 工具文档自动生成

### 变更

- `scripts/generate_tools_doc.py`: 新增 AST 文档生成脚本，从 `local_memory_mcp/server.py` 的 `@mcp.tool()` 函数签名、返回类型和 docstring 生成工具文档。
- `docs/tools.md`: 重新生成 MCP 工具参考，当前登记 34 个工具，并标记为生成文件。
- `tests/test_docs_consistency.py`: 增加 `scripts/generate_tools_doc.py --check` 一致性测试，确保 `docs/tools.md` 与实际工具注册同步。
- `TODO.md`: 将自动生成 MCP 工具文档标记为完成。

### 修复

- 修复 `docs/tools.md` 长期手写、工具数量和实际注册列表漂移的问题。

### 验证

- Python 编译: `.venv/bin/python -m py_compile scripts/generate_tools_doc.py` 通过。
- 文档检查: `.venv/bin/python scripts/generate_tools_doc.py --check` 通过。
- 相关测试: `.venv/bin/python -m pytest tests/test_docs_consistency.py -q`，3/3 pass。
- 全量测试: `.venv/bin/python -m pytest -q`，391/391 pass。

### 已知问题

- 生成文档只使用函数签名、返回类型和 docstring 摘要；参数语义说明仍依赖 docstring 后续继续完善。

### 回滚

`git checkout -- scripts/generate_tools_doc.py docs/tools.md tests/test_docs_consistency.py TODO.md ITERATION.md`

---

## [迭代 66] 2026-06-01 — MCP 工具面继续收敛

### 变更

- `local_memory_mcp/server.py`: 删除 MCP 工具 `memory_update_status` 与 `memory_consolidate`，工具数量从 34 收敛到 32。
- `local_memory_mcp/storage/curator.py`: 删除旧的 `consolidate()` report-only helper，统一使用 `curator_report()` 提供重复标题、低反馈和生命周期候选报告。
- `local_memory_mcp/frontend.py`: 删除 `/api/consolidate` 入口，前端/HTTP API 统一走 `/api/curator`。
- `local_memory_mcp/storage/__init__.py` / `local_memory_mcp/__init__.py`: 移除 `consolidate` re-export。
- `README.md` / `docs/tools.md`: 更新 MCP 工具数量和工具列表。
- `tests/test_curator.py` / `tests/test_phase10.py`: 更新状态修改和 curator 报告测试，覆盖 `memory_update` 可改 status、`curator_report` 替代 consolidate。
- `TODO.md`: 将 MCP 工具面收敛项标记为完成。

### 修复

- 修复 `memory_update_status` 与 `memory_update(status=...)`、`memory_consolidate` 与 `memory_curator_report` 之间的重复工具面，避免为低价值工具新增 admin profile 或额外权限复杂度。

### 验证

- Python 编译: `.venv/bin/python -m py_compile local_memory_mcp/server.py local_memory_mcp/frontend.py local_memory_mcp/storage/curator.py local_memory_mcp/storage/__init__.py local_memory_mcp/__init__.py` 通过。
- 文档检查: `.venv/bin/python scripts/generate_tools_doc.py --check` 通过。
- 相关测试: `.venv/bin/python -m pytest tests/test_curator.py tests/test_phase10.py tests/test_docs_consistency.py tests/test_frontend.py -q`，36/36 pass。
- 全量测试: `.venv/bin/python -m pytest -q`，391/391 pass。

### 已知问题

- 这是 MCP 工具面的破坏性收敛；旧客户端如果仍调用 `memory_update_status` 或 `memory_consolidate`，需要改为 `memory_update(status=...)` 与 `memory_curator_report()`。

### 回滚

`git checkout -- local_memory_mcp/server.py local_memory_mcp/storage/curator.py local_memory_mcp/frontend.py local_memory_mcp/storage/__init__.py local_memory_mcp/__init__.py README.md docs/tools.md tests/test_curator.py tests/test_phase10.py TODO.md ITERATION.md`

---

## [迭代 67] 2026-06-01 — 发布准备验证与剩余外部阻塞记录

### 变更

- `README.md`: 补充 PyPI 发布后的安装命令，覆盖默认 `local-memory-mcp[all]` 与包含 sentence-transformers fallback 的 `local-memory-mcp[full]`。
- `TODO.md`: 将“不新增 LLM 全自动记忆治理管线”决策项标记为完成；更新 PyPI 首发、Gemini 真实 CLI 验证、Docker Compose 端到端验证的当前阻塞条件。

### 修复

- 修复 TODO 中 Gemini 仍描述为“本机无 gemini 命令”的过时状态；当前 Gemini CLI 已安装且 `gemini mcp list` 能连上 `local_memory`，但真实 prompt 缺少 `GEMINI_API_KEY`。
- 明确 Docker Compose 端到端验证的当前失败点是 Docker mirror 拉取 `python:3.11-slim` metadata 返回 unexpected EOF，而不是 compose 配置解析问题。

### 验证

- 发布构建: `.venv/bin/python -m build` 成功生成 `local_memory_mcp-0.25.0.tar.gz` 与 `local_memory_mcp-0.25.0-py3-none-any.whl`。
- 发布校验: `.venv/bin/python -m twine check dist/*` 通过。
- 安装验证: Python 3.11 临时 venv 安装 wheel 后，`importlib.metadata.version('local-memory-mcp')` 返回 `0.25.0`，`local_memory_mcp.main` 可调用。
- PyPI 查询: `.venv/bin/python -m pip index versions local-memory-mcp` 返回 no matching distribution，说明当前尚未发布。
- Gemini 检查: `gemini mcp list` 显示 `local_memory` connected；`gemini -p ... --output-format json` 因缺少 `GEMINI_API_KEY` 退出 code 41。
- Docker Compose: `docker compose config` 通过；临时 compose 使用 18318/16333/16334 端口执行 `docker compose up --build -d` 时，拉取 `python:3.11-slim` 失败于 registry mirror unexpected EOF。
- 文档测试: `.venv/bin/python -m pytest tests/test_docs_consistency.py tests/test_deployment.py -q`，20/20 pass。

### 已知问题

- PyPI 首发仍需提交当前改动、打/推 tag，并确认 PyPI Trusted Publishing 已配置。
- Docker Compose 容器端到端验证等待 Docker registry/mirror 可用，或本机预先缓存 `python:3.11-slim`。
- Gemini 真实 BeforeAgent/SessionEnd 验证等待 `GEMINI_API_KEY`。

### 回滚

`git checkout -- README.md TODO.md ITERATION.md`

---

## [迭代 68] 2026-06-01 — Docker Compose E2E 镜像拉取阻塞复验

### 变更

- `TODO.md`: 补充 Docker Compose 端到端验证的复验细节，记录已尝试的 Docker registry/mirror 与共同失败原因。

### 验证

- Docker 基础镜像拉取: `docker pull python:3.11-slim` 仍失败，Docker daemon 经 `docker.1ms.run` 获取 metadata 时返回 `unexpected EOF`。
- Docker 备用镜像源: `docker pull docker.m.daocloud.io/library/python:3.11-slim`、`docker pull dockerproxy.com/library/python:3.11-slim`、`docker pull registry.dockermirror.com/library/python:3.11-slim` 均在 metadata HEAD 请求阶段返回 `unexpected EOF`。
- 本地镜像缓存: `docker images` 中仍无 `python:3.11-slim`，只有 `qdrant/qdrant:latest` 等其它镜像可用。
- 运行态: `lmmcp.service` active，`curl http://127.0.0.1:8318/health` 返回 ok。

### 已知问题

- Docker Compose 端到端验证继续等待可用 Docker registry/mirror 或本机预先缓存 `python:3.11-slim`。

### 回滚

`git checkout -- TODO.md ITERATION.md`

---

## [迭代 69] 2026-06-01 — TODO 外部阻塞复验与原始问题核验

### 变更

- `TODO.md`: 更新 Gemini 真实 CLI、PyPI 首发、Docker Compose E2E 三个未完成项的 2026-06-01 11:00 CST 复验证据。

### 验证

- 前端单测: `.venv/bin/python -m pytest tests/test_frontend.py -q`，8/8 pass，未复现首个 `TestClient` 用例卡死。
- 默认 extras: `.venv/bin/python -m pip install -e '.[all]' --dry-run` 成功解析默认安装集合，未包含 `sentence-transformers`。
- 可选 embedding 依赖: `.venv/bin/python -c ...` 检查 `sentence_transformers` 当前未安装，符合 `.[all]` 轻量化预期。
- Gemini: `gemini mcp list` 显示 `local_memory` connected；`gemini -p 'Respond with only: ok' --output-format json` 仍因缺少 `GEMINI_API_KEY` 退出 code 41。
- PyPI: `.venv/bin/python -m pip index versions local-memory-mcp` 仍返回 no matching distribution；`git ls-remote --tags origin 'v*'` 当前只看到 `v0.20.0`。
- Docker: `docker image inspect python:3.11-slim` 显示本机无缓存；`docker pull python:3.11-slim` 仍失败于 `docker.1ms.run` metadata HEAD `unexpected EOF`。

### 已知问题

- Gemini 真实 BeforeAgent/SessionEnd 验证等待 `GEMINI_API_KEY`。
- PyPI 首发仍需提交当前改动、打/推 `v0.25.0` tag，并确认 PyPI Trusted Publishing 已配置。
- Docker Compose 容器端到端验证继续等待可用 Docker registry/mirror 或本机预先缓存 `python:3.11-slim`。

### 回滚

`git checkout -- TODO.md ITERATION.md`

---

## [迭代 70] 2026-06-01 — GitHub Actions CI 依赖安装修复

### 变更

- `.github/workflows/ci.yml`: CI 依赖安装从 `requirements.txt` 改为 `pip install -e ".[dev,all]"`，确保 GitHub Actions 安装项目 runtime deps、默认 extras 与测试依赖。
- `TODO.md`: 记录并完成 CI 缺少项目依赖导致发布候选检查失败的问题。

### 修复

- 修复 main/tag CI 只安装 `requirements.txt` 时缺少 `pyyaml` 等 `pyproject.toml` runtime 依赖，导致 `tests/conftest.py` import package 失败的问题。

### 验证

- 远端失败证据: GitHub Actions run `26732839095` 在 `python -m pytest tests/ -q` 阶段报 `ModuleNotFoundError: No module named 'yaml'`。
- 本地文档/部署门禁: `.venv/bin/python -m pytest tests/test_docs_consistency.py tests/test_deployment.py -q`，20/20 pass。

### 已知问题

- 需推送修复提交后复验 GitHub Actions CI。

### 回滚

`git checkout -- .github/workflows/ci.yml TODO.md ITERATION.md`

---

## [迭代 71] 2026-06-01 — PyPI Publish Workflow 权限修复

### 变更

- `.github/workflows/publish.yml`: publish job permissions 增加 `contents: read`，保留 `id-token: write` 供 PyPI Trusted Publishing 使用。
- `TODO.md`: 记录并完成 publish workflow checkout 权限缺口。

### 修复

- 修复 job 级 `permissions` 只声明 `id-token: write` 后覆盖默认权限，导致 tag workflow 中 `actions/checkout` 无法读取仓库并报 `repository not found` 的问题。

### 验证

- 远端失败证据: GitHub Actions run `26732849249` 在 `actions/checkout@v4` 阶段对 `v0.25.0` tag fetch 报 `fatal: repository 'https://github.com/advancer9817-crypto/local-memory-mcp/' not found`。
- 权限修复: publish workflow 现在同时声明 `contents: read` 与 `id-token: write`。

### 已知问题

- 需推送修复提交，并在确认 `v0.25.0` 尚未发布到 PyPI 后，将 `v0.25.0` tag 移到修复后的提交重新触发发布。

### 回滚

`git checkout -- .github/workflows/publish.yml TODO.md ITERATION.md`

---

## [迭代 72] 2026-06-01 — v0.25.0 发布触发与 PyPI Trusted Publisher 阻塞定位

### 变更

- `TODO.md`: 更新 PyPI 首发项，记录 `main` / `v0.25.0` 已推送、tag CI 已通过，以及当前 publish 失败的 PyPI OIDC claims。

### 验证

- 远端提交: `main` 已推送到 `9e75f4d fix: repair ci and publish workflows`。
- 远端 tag: `v0.25.0` 已重新指向 `9e75f4d` 并推送。
- GitHub Actions main CI: run `26732900203` success。
- GitHub Actions tag CI: run `26732912402` success。
- GitHub Actions Publish: run `26732912393` 在 `pypa/gh-action-pypi-publish` 阶段失败，PyPI 返回 `invalid-publisher`。
- PyPI 查询: `.venv/bin/python -m pip index versions local-memory-mcp` 仍返回 no matching distribution，确认发布未产生包。

### 已知问题

- PyPI 首发等待 PyPI 账号侧配置 Trusted Publisher；当前 claims 为 repository `advancer9817-crypto/local-memory-mcp`、workflow `.github/workflows/publish.yml`、ref `refs/tags/v0.25.0`、environment `MISSING`。
- Gemini 真实 BeforeAgent/SessionEnd 验证等待 `GEMINI_API_KEY`。
- Docker Compose 容器端到端验证继续等待可用 Docker registry/mirror 或本机预先缓存 `python:3.11-slim`。

### 回滚

`git checkout -- TODO.md ITERATION.md`

---

## [迭代 73] 2026-06-01 — Gemini AfterAgent 写回补强

### 变更

- `scripts/setup-hooks.sh`: Gemini hook 注册增加 `AfterAgent -> lmmcp-ingest.py --agent gemini --background`，并在重装时清理旧的 lmmcp AfterAgent 写回项。
- `scripts/connect_agents.py`: `register_hooks_gemini()` 同步注册 `AfterAgent` 写回，保留 `SessionEnd` 作为退出兜底。
- `README.md`: 更新 Gemini 写回说明为 `AfterAgent` / `SessionEnd` 双 hook。
- `TODO.md`: 更新 Gemini 真实 CLI 验证状态，记录真实 `BeforeAgent` 已通过、headless `SessionEnd` 写回未稳定触发，并补 `AfterAgent` 作为回答后写回路径。
- `tests/test_deployment.py`: 增加 Gemini `AfterAgent` 写回注册门禁。

### 修复

- 修复 Gemini headless `gemini -p` 真实现场中只看到 `BeforeAgent` 注入、未看到 `SessionEnd` 触发写回的问题；回答后写回现在挂到更接近模型响应完成时机的 `AfterAgent`，`SessionEnd` 继续保留。

### 验证

- Gemini prompt: `gemini -p 'Return exactly: LMMCP-GEMINI-E2E-20260601-1115' --extensions '' --output-format json` 成功返回 marker。
- BeforeAgent 证据: Gemini transcript `session-2026-06-01T03-14-e5bca9e3.jsonl` 中用户消息包含 `<hook_context># memory_context for gemini`，证明真实 CLI prompt 前注入生效。
- SessionEnd 反证: 11:15 后 `journalctl --user -u lmmcp.service` 无 `memory_ingest` / extraction 写回调用，marker 也未进入 SQLite，说明只依赖 `SessionEnd` 不能证明 headless prompt 写回。

### 已知问题

- 需重新注册 Gemini hooks 后，复验 `AfterAgent` 是否能在真实 Gemini CLI headless prompt 后触发写回。
- PyPI 首发等待 PyPI 账号侧配置 Trusted Publisher。
- Docker Compose 容器端到端验证继续等待可用 Docker registry/mirror 或本机预先缓存 `python:3.11-slim`。

### 回滚

`git checkout -- scripts/setup-hooks.sh scripts/connect_agents.py README.md TODO.md tests/test_deployment.py ITERATION.md`

---

## [迭代 74] 2026-06-01 — Gemini CLI JSONL Transcript 真实格式解析修复

### 变更

- `scripts/hooks/lmmcp-ingest.py`: Gemini JSONL extractor 现在识别真实 CLI transcript 里的 `type: "gemini"` 为 assistant，并优先使用 `displayContent` 读取用户原始提示，避免把 `<hook_context>` 一起写入待抽取消息。
- `tests/test_lmmcp_ingest_hook.py`: 增加真实 Gemini CLI JSONL 形状回归测试，覆盖 `type=user` + `displayContent` 和 `type=gemini`。
- `TODO.md`: 更新 Gemini 写回 hook 说明，记录真实 JSONL 格式已纳入解析。

### 修复

- 修复 Gemini `AfterAgent` / `SessionEnd` hook 实际触发后，`lmmcp-ingest.py` 对真实 transcript 解析出 `messages=0` 并跳过写回的问题。

### 验证

- 现场证据: `/tmp/lmmcp-ingest.log` 显示 Gemini hook 已 spawn background，但真实 transcript `session-2026-06-01T03-17-aa4d3543.jsonl` 被解析为 `messages=0`。
- 真实格式: Gemini CLI JSONL 使用 `type: "user"` / `type: "gemini"`，用户消息另带 `displayContent`。

### 已知问题

- 需重新运行 Gemini 真实 prompt 复验写回链路。
- PyPI 首发等待 PyPI 账号侧配置 Trusted Publisher。
- Docker Compose 容器端到端验证继续等待可用 Docker registry/mirror 或本机预先缓存 `python:3.11-slim`。

### 回滚

`git checkout -- scripts/hooks/lmmcp-ingest.py tests/test_lmmcp_ingest_hook.py TODO.md ITERATION.md`

---

## [迭代 75] 2026-06-01 — Gemini 真实 CLI 读前写后 E2E 通过

### 变更

- `TODO.md`: 将 Gemini 真实 CLI 端到端现场验证标记为完成，记录 BeforeAgent 注入、AfterAgent 写回、SQLite marker 三类证据。

### 验证

- Gemini MCP: `gemini mcp list` 显示 `local_memory` connected。
- Gemini BeforeAgent: `gemini -p 'Return exactly: LMMCP-GEMINI-E2E-20260601-1115' --extensions '' --output-format json` 成功返回；对应 transcript `session-2026-06-01T03-14-e5bca9e3.jsonl` 中包含 `<hook_context># memory_context for gemini`。
- Gemini AfterAgent 写回: `gemini -p 'State this factual note exactly ... LMMCP-GEMINI-WRITEBACK-20260601-1120 ...' --extensions '' --output-format json` 成功返回。
- Hook 日志: `/tmp/lmmcp-ingest.log` 显示 `gemini_transcript ... session-2026-06-01T03-20-908ac36f.jsonl messages=2`、`ingest_start agent=gemini messages=2`、`ingest_done ... updated=1`。
- SQLite: `memory.sqlite3` 中存在 `source_agent='gemini'` 的 candidate 记忆，内容包含 `LMMCP-GEMINI-WRITEBACK-20260601-1120`。

### 已知问题

- PyPI 首发等待 PyPI 账号侧配置 Trusted Publisher。
- Docker Compose 容器端到端验证继续等待可用 Docker registry/mirror 或本机预先缓存 `python:3.11-slim`。

### 回滚

`git checkout -- TODO.md ITERATION.md`

---

## [迭代 76] 2026-06-01 — 全量回归与剩余发布/容器阻塞复验

### 变更

- `TODO.md`: 更新 PyPI 与 Docker Compose 两个剩余未完成项的 2026-06-01 11:22 CST 复验证据。

### 验证

- 全量测试: `.venv/bin/python -m pytest -q`，392/392 pass，1 个 httpx raw content deprecation warning。
- PyPI 查询: `.venv/bin/python -m pip index versions local-memory-mcp` 仍返回 no matching distribution，期间 PyPI/simple 请求出现一次 SSL EOF retry，但最终仍无包。
- Docker 基础镜像: `docker pull python:3.11-slim` 仍失败于 `docker.1ms.run` metadata HEAD `unexpected EOF`。

### 已知问题

- PyPI 首发等待 PyPI 账号侧配置 Trusted Publisher；当前 publish workflow 已能 checkout/build，但被 PyPI `invalid-publisher` 拒绝。
- Docker Compose 容器端到端验证继续等待可用 Docker registry/mirror 或本机预先缓存 `python:3.11-slim`。

### 回滚

`git checkout -- TODO.md ITERATION.md`

---

## [迭代 77] 2026-06-01 — CI 并发 SQLite 写入锁库修复

### 变更

- `local_memory_mcp/storage/db.py`: SQLite connection timeout 从默认值提高到 30 秒，`PRAGMA busy_timeout` 提高到 30000ms。
- `local_memory_mcp/storage/db.py`: `managed_conn()` 增加进程内 `threading.RLock()`，串行化本进程内 SQLite 事务，保留 commit retry 作为跨进程/外部锁兜底。
- `TODO.md`: 记录并完成 GitHub Actions CI 并发写入偶发锁库失败。

### 修复

- 修复 GitHub Actions main/tag CI 中 `test_concurrent_writes_no_corruption` 偶发 `sqlite3.OperationalError: database is locked`，导致发布链路被 CI 阻断的问题。

### 验证

- 远端失败证据: GitHub Actions runs `26733413919` 与 `26733419297` 均在 `tests/test_concurrent_and_migration.py::test_concurrent_writes_no_corruption` 报 `database is locked`。

### 已知问题

- 需推送修复后复验 main/tag CI。
- PyPI 首发等待 PyPI 账号侧配置 Trusted Publisher。
- Docker Compose 容器端到端验证继续等待可用 Docker registry/mirror 或本机预先缓存 `python:3.11-slim`。

### 回滚

`git checkout -- local_memory_mcp/storage/db.py TODO.md ITERATION.md`

---

## [迭代 78] 2026-06-01 — Docker Daemon 代理修复与 Compose 远程绑定配置补齐

### 变更

- `/etc/docker/daemon.json`: 本机 Docker daemon 代理从过期 WSL host IP `172.27.176.1:7890` 改为当前默认网关 `172.20.0.1:7890`；registry mirrors 收敛为现场可响应的 `docker.1ms.run` 与 `docker.m.daocloud.io`。
- `Dockerfile`: 容器默认设置 `LOCAL_MEMORY_FRONTEND_TOKEN=change-me`，满足 `0.0.0.0` 绑定安全检查。
- `docker-compose.yml`: Compose 默认注入 `LOCAL_MEMORY_FRONTEND_TOKEN`，可由宿主环境覆盖。
- `tests/test_deployment.py`: 增加 Dockerfile/Compose frontend token 配置门禁。
- `TODO.md`: 更新 Docker Compose E2E 当前进展。

### 修复

- 修复 Docker daemon 使用旧 WSL 网关代理导致 mirror manifest HEAD 阶段 `unexpected EOF`，无法拉取 `python:3.11-slim` 的问题。
- 修复 Compose 容器绑定 `0.0.0.0` 但未配置 frontend auth token，启动时报 `remote frontend bind requires --auth-token or --allow-insecure-remote` 的问题。

### 验证

- `curl --proxy http://172.20.0.1:7890 https://registry-1.docker.io/v2/` 返回 Docker registry 401 challenge。
- `docker pull python:3.11-slim` 成功，digest `sha256:a3ab0b966bc4e91546a033e22093cb840908979487a9fc0e6e38295747e49ac0`。
- 临时 Compose build 已成功完成 Python 依赖安装与镜像构建。
- 临时 Compose 首次启动失败证据: `lmmcp-e2e-lmmcp-1` 日志显示 `ValueError: remote frontend bind requires --auth-token or --allow-insecure-remote`。

### 已知问题

- 需重建 Compose 镜像后复验 `/health`、`/mcp`、`memory_vector_status`。
- PyPI 首发等待 PyPI 账号侧配置 Trusted Publisher。

### 回滚

`sudo cp /etc/docker/daemon.json.bak.<timestamp> /etc/docker/daemon.json && sudo systemctl restart docker`

`git checkout -- Dockerfile docker-compose.yml tests/test_deployment.py TODO.md ITERATION.md`

---

## [迭代 79] 2026-06-01 — Docker Compose Qdrant 环境覆盖与 E2E 闭环

### 变更

- `local_memory_mcp/vector_store.py`: `vector_store_config_from_dict()` 支持 `LOCAL_MEMORY_QDRANT_URL` / `QDRANT_URL`、`LOCAL_MEMORY_QDRANT_COLLECTION` / `QDRANT_COLLECTION`、`LOCAL_MEMORY_QDRANT_PATH` / `QDRANT_PATH` 环境变量覆盖，并在 `memory_vector_status` 结果中暴露 `url`。
- `Dockerfile`: 增加 `PIP_DEFAULT_TIMEOUT=120`、`PIP_RETRIES=10`、`PIP_DISABLE_PIP_VERSION_CHECK=1`，降低 Compose build 期间 Python wheel 下载读超时概率。
- `tests/test_vector_store.py`: 增加 Qdrant 环境变量覆盖与 `LOCAL_MEMORY_*` 优先级回归测试。
- `tests/test_deployment.py`: 增加 Dockerfile pip timeout/retries 门禁。
- `TODO.md`: 将 Docker Compose 容器端到端验证标记为完成。

### 修复

- 修复 Compose 已设置 `QDRANT_URL=http://qdrant:6333`，但服务端配置只读取 config file/default，导致容器内 `memory_vector_status.available=false` 并退回本地 `/root/.agent-memory/qdrant` 的问题。
- 修复 Compose build 下载 `numpy` 等依赖时遇到 `ReadTimeoutError` 后没有足够重试/超时余量的问题。

### 验证

- 焦点测试: `tests/test_vector_store.py tests/test_deployment.py` 43/43 pass。
- 全量测试: 394/394 pass，1 个既有 `httpx` deprecation warning。
- Docker Compose E2E: `docker compose -p lmmcp-e2e -f /tmp/lmmcp-e2e-compose.yml up --build -d` 成功，`lmmcp-e2e-lmmcp-1` healthy，Qdrant `/healthz` 返回 `healthz check passed`。
- HTTP health: `http://127.0.0.1:18318/health` 返回 `{"ok":true,"data":{"status":"ok","total_memories":0}}`。
- MCP: `/mcp` `initialize` 返回 200，`memory_vector_status` 返回 `available=true`、`url=http://qdrant:6333`、`collection=agent_memory`、`embed_provider=hashing`。
- Vector 写读: 通过 MCP `memory_add` 写入 `LMMCP-DOCKER-E2E-QDRANT-20260601-1311` 后，`memory_vector_search` 可查回同一条记录，随后 `memory_vector_status.count=1`。

### 已知问题

- PyPI 首发等待 PyPI 账号侧配置 Trusted Publisher。

### 回滚

`git checkout -- Dockerfile docker-compose.yml local_memory_mcp/vector_store.py tests/test_deployment.py tests/test_vector_store.py TODO.md ITERATION.md`

---

## [迭代 80] 2026-06-01 — PyPI API Token 发布路径接入

### 变更

- `.github/workflows/publish.yml`: `pypa/gh-action-pypi-publish` 增加 `password: ${{ secrets.PYPI_API_TOKEN }}`，支持通过 GitHub Actions secret 使用 PyPI API token 发布。
- `tests/test_deployment.py`: 增加 publish workflow 回归测试，锁定只引用 `PYPI_API_TOKEN` secret，并禁止把 `password: pypi-...` 这类明文 token 写进 workflow。
- `TODO.md`: 更新 PyPI 首发状态，记录 Trusted Publishing 仍为 `invalid-publisher`，改接 API token secret 路线，并标注已暴露 token 必须撤销后重新生成。

### 修复

- 修复用户已创建 PyPI API token 但 publish workflow 仍只走 Trusted Publishing OIDC，导致 GitHub Secret/API token 路线无法生效的问题。
- 避免将已暴露的 PyPI token 写入仓库；workflow 只引用 GitHub Secret 名称。

### 验证

- 焦点测试: `tests/test_deployment.py` 18/18 pass。
- GitHub Secrets: 当前仓库尚未配置 `PYPI_API_TOKEN` secret，需用户撤销已暴露 token、重新生成新 token 并写入 secret 后再触发 tag publish。

### 已知问题

- PyPI 首发仍未完成；等待新的 PyPI API token 写入 GitHub Actions secret `PYPI_API_TOKEN` 后 rerun publish。

### 回滚

`git checkout -- .github/workflows/publish.yml tests/test_deployment.py TODO.md ITERATION.md`

---

## [迭代 81] 2026-06-01 — PyPI v0.25.0 首发完成

### 变更

- `TODO.md`: 将 PyPI 首次发布标记为完成，记录发布 workflow、PyPI 版本可见性与临时 venv 安装验证结果。
- `ITERATION.md`: 记录 PyPI 首发完成状态与后续 Trusted Publishing 可选改进。

### 修复

- 通过重新写入有效的 GitHub Actions secret `PYPI_API_TOKEN`，修复上一轮发布中 PyPI API token 无效导致的 `403 Invalid or non-existent authentication information`。

### 验证

- GitHub Actions: `Publish to PyPI` run `26746195311` completed success，head `4f98155a08f612d0c4c4af85d2f2356450b43f8c`。
- GitHub Actions: tag CI run `26746195314` completed success。
- PyPI index: `pip index versions local-memory-mcp` 显示 `local-memory-mcp (0.25.0)`、`Available versions: 0.25.0`。
- PyPI install: 临时 Python 3.11 venv 执行 `pip install "local-memory-mcp[all]==0.25.0"` 成功，`importlib.metadata.version("local-memory-mcp")` 返回 `0.25.0`，import 路径为 venv `site-packages/local_memory_mcp/__init__.py`。

### 已知问题

- Trusted Publishing 仍未配置成功；当前 PyPI 发布依赖 GitHub Secret `PYPI_API_TOKEN`。后续可在 PyPI project publishing 页面补齐 GitHub publisher，再移除 token secret 路线。

### 回滚

`git checkout -- TODO.md ITERATION.md`

---

## 日志格式规范

每次迭代完成后在本文件 **底部** 追加一条记录，格式如下：

```markdown
## [迭代 N] YYYY-MM-DD — 标题

### 变更
- `<文件路径>`: 变更描述

### 修复
- `<文件路径>`: 问题描述 → 修复方式

### 验证
- 测试: N/N pass
- 端到端: 关键链路验证结果

### 已知问题
- 问题描述（若有）

### 回滚
`git revert HEAD`
```

> **规则**:
> - 新条目追加到文件底部（"下一阶段规划"之前），最新迭代在最下面。
> - 变更与修复分开列出；如果某次提交仅有修复无新功能，"变更"段可省略。
> - 测试结果必须写实际数字（如 362/362 pass），不允许占位符。
> - 已知问题如已在上个迭代修复，从列表中移除并改记入"修复"段。
> - 不要在迭代条目中包含 git diff stat、file change list、remote URL 等 repo sync 元数据。
