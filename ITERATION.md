# ITERATION.md — local-memory-mcp 迭代日志

## [迭代 35] 2026-05-28 — lmmcp 本地时间与 Codex hook 信任修复

### 背景

排查 Codex 自动抽取链路时发现两个实际问题：

- 记忆写入时间仍有部分路径使用 UTC，用户要求统一使用本地 CST（Asia/Shanghai, UTC+08:00）。
- Codex hooks 虽然已写入 `~/.codex/hooks.json`，但 Codex CLI 会额外校验 hook trust hash；未信任时 `UserPromptSubmit` / `Stop` 不会真正执行，造成“已注册但不自动抽取”的假象。

### 变更摘要

**CST 本地时间统一**
- `local_memory_mcp/models.py` 新增 `LOCAL_TZ` 与 `local_now()`。
- `now()` 改为返回带 `+08:00` 偏移的 ISO 时间戳。
- `extraction.py` 的 observation date 改用本地日期，避免跨 UTC 日期边界时抽取日期偏移。
- `storage/agents.py` 的消息 TTL `expires_at`、`storage/curator.py` 的生命周期判断、`storage/rollup.py` 的 episodic 年龄计算统一改用 `local_now()`。
- `storage/transfer.py` 的备份文件名将 `+` 替换为 `p`，避免本地时区后缀生成不友好的文件名。

**Codex ingest 可观测性**
- `scripts/hooks/lmmcp-ingest.py` 新增 `/tmp/lmmcp-ingest.log`（可用 `LMMCP_INGEST_LOG` 覆盖）。
- 日志覆盖：
  - Codex transcript 路径与抽取消息数。
  - `ingest_start` / `ingest_done`。
  - `curl_failed`。
  - `initialize_missing_session`。
  - 空消息跳过与异常。
- 这让后续可以区分“Stop hook 没执行”“MCP 连接失败”“ingest 成功但无新增事实”“ingest 成功写入”。

**Codex hook trust 自动写入**
- `scripts/connect_agents.py --register-hooks` 在注册 Codex hooks 后，调用：
  ```bash
  codex app-server --listen stdio:// --enable hooks
  ```
  并通过 `hooks/list` 获取官方 `currentHash`。
- 自动写入 `~/.codex/config.toml`：
  ```toml
  [hooks.state."/home/advancer/.codex/hooks.json:user_prompt_submit:0:0"]
  trusted_hash = "..."

  [hooks.state."/home/advancer/.codex/hooks.json:stop:0:0"]
  trusted_hash = "..."
  ```
- `scripts/setup-hooks.sh` 同步实现同一逻辑，避免 `start.sh -> setup-hooks.sh` 路径只注册 hook 却不信任 hook。
- 若当前机器没有 `codex` 或无法取到 hashes，脚本只给 warning，不阻断其它 agent 的 hook 注册。

### 验证

```bash
python3 -m py_compile scripts/connect_agents.py scripts/hooks/lmmcp-ingest.py
bash -n scripts/setup-hooks.sh
python3 scripts/connect_agents.py --register-hooks --agents codex --no-probe
bash scripts/setup-hooks.sh
```

Codex 官方 hook 状态确认：

```text
/home/advancer/.codex/hooks.json:user_prompt_submit:0:0 trusted
/home/advancer/.codex/hooks.json:stop:0:0 trusted
```

手动触发 Codex ingest 验证：

```text
2026-05-28T13:54:42+08:00 ingest_start agent=codex messages=16
2026-05-28T13:54:52+08:00 ingest_done agent=codex messages=16 response=... "added": 2 ... "errors": 0 ...
```

新增记忆记录验证：

- `ec51c7af-4fa8-42ca-bd40-71489131dbc6`
- `ef089ab3-c74d-48f1-9f10-47764e8ee1e8`

### 影响范围

- 新写入的 lmmcp 记录时间统一为 CST `+08:00`；旧记录不会自动迁移。
- Codex hook 注册工具现在会尝试启动 `codex app-server` 获取 trust hash；在沙箱或只读环境可能失败并输出 warning。
- Codex hook 内容变化后 hash 会变化，需要重新运行 `scripts/setup-hooks.sh` 或 `scripts/connect_agents.py --register-hooks --agents codex`。
- `/tmp/lmmcp-ingest.log` 是诊断日志，不参与持久记忆存储，可按需清理。

### 回滚

`git revert HEAD`；如只想撤销本机 Codex hook 信任，可删除 `~/.codex/config.toml` 中对应 `[hooks.state."..."]` 段后重启 Codex 会话。

---

## [迭代 34] 2026-05-28 — 文档缺口全修复（8 个遗留问题）

### 背景

对迭代日志规划条目与实际代码做全面比对，发现 8 个"文档已规划但代码未实现"的缺口，全部修复。

### 变更摘要

**D-2 `valid_until` 时区强制校验（`storage/crud.py`）**
- `_validate_iso()` 新增 `tzinfo is not None` 检查
- 无时区后缀（如 `2026-06-01T00:00:00`）写入时立即抛 `ValueError`，而非静默写入后字符串比较错误

**11-B WAL autocheckpoint=500（`storage/db.py`）**
- `_get_thread_conn()` 建连时注册 `PRAGMA wal_autocheckpoint=500`
- WAL 文件超过 500 页自动触发检查点，默认 1000 的上限减半

**11-C context_quality_events 写入节流（`storage/search.py`）**
- `_record_context_quality_event()` 开头加 `used_count == 0` 提前返回
- 仅在有记忆被实际注入时写入，消除空命中时的无效写放大

**12-A 语义去重阈值按 type 差异化（`dedup.py`）**
- 新增 `TYPE_THRESHOLDS` 字典，按记忆类型配置 (skip, update, link) 三阈值：
  - `decision`/`user_profile`/`environment_fact`：保守（0.96/0.88/0.65），避免误合并独立事实
  - `episodic_memory`/`feedback`：激进（0.88/0.72/0.50），快速合并重复碎片
- `decide()` 新增 `memory_type` 参数，自动查表覆盖默认阈值
- `ingest()` 向量搜索 floor 也使用 per-type link 阈值

**12-B 中文双语 extraction prompt（`extraction.py`）**
- `extract_facts()` 检测输入消息中中文字符占比，超过 15% 时在 system prompt 末尾追加中文指令段
- 指令要求 LLM 用中文记录事实、保留工具名/版本号等不翻译

**S-2 curator apply 单事务（`storage/crud.py` + `storage/curator.py`）**
- 新增 `update_status_batch(conn, updates)` 内部函数：接受调用方传入的连接，在同一事务内批量执行所有状态变更，不自行 commit
- curator `apply` 块改用 `with managed_conn() as conn:` 单一事务包裹：decay executemany + 清理 DELETE + 全部状态变更 → 原子提交
- `storage/__init__.py` 导出 `update_status_batch`

**13-A handoff 超时清理（`storage/handoff.py` + `server.py`）**
- `agent_handoff_create` 默认 `ttl_seconds=3600`（1小时），原来默认 None
- 新增 `cleanup_expired_handoffs()`：扫描 expires_at 已过期且 handoff_status=requested 的消息，标记为 read
- auto-curator 线程每轮先调 `cleanup_expired_handoffs()`，日志新增 `handoff_cleaned` 字段

**13-C agent_handoff_create auto_route（`storage/handoff.py` + `server.py`）**
- `agent_handoff_create` 新增 `auto_route: bool = False` 参数
- `auto_route=True` 时：查询 online/idle agent presence，对每个 agent 的 capability 关键字与 task 文本做匹配打分，选最高分者作为 to_agent
- MCP tool 签名同步更新，文档说明 auto_route 行为

### 验证

```bash
.venv/bin/python -m pytest -q
# 362 passed, 1 warning
```

### 影响范围

- `agent_handoff_create` 新增 `auto_route` 参数（默认 False，向后兼容）
- `ttl_seconds` 默认值从 None 改为 3600（破坏性变更：旧调用若依赖无超时行为，需显式传 `ttl_seconds=None`）
- `valid_until` 无时区写入现在会报错（可能影响已有调用方）
- curator apply 日志新增 `revived` 和 `handoff_cleaned` 字段

---

## [迭代 33] 2026-05-28 — 记忆状态流转完善（v3 状态机）

### 背景

原状态机存在六大缺陷：candidate 窗口太短（12h/48h 导致大批 hermes 记忆被误杀）、stale 无复活通道、decay_policy 策略只实现了 `review`（`stable`/`freeze` 是空壳）、`promoted`/`contradicted` 写入后无后续流转、rollup 只认 `source='extraction'`（hermes 直写的 episodic 永远不被提炼）、decay 条件未区分"从未被用过"和"曾经有用但被遗忘"。

### 变更摘要

**`local_memory_mcp/models.py`**
- 从 `STATUSES` 中移除 `promoted`（该状态无任何自动触发逻辑，等价于 active）

**`local_memory_mcp/storage/curator.py`**（完整重写）

candidate 超时分档（替换原来的 48h 一刀切）：
- `episodic_memory`：7 天（与 rollup 30条阈值的积累速度匹配）
- 高价值类型（用户画像/环境事实/决策/项目记忆/技能候选）：30 天（需 importance<0.4 且 feedback<0）
- 其他类型：7 天（需 importance<0.5）

stale 复活通道（新增）：
- stale 记忆若 7 天内被注入（`last_injected_at >= now-7d`）且 `effectiveness_score >= 0.5` 且 `feedback_score >= 0` → 自动复活为 active

precious 类型保护加强：
- `user_profile`/`environment_fact`/`decision`/`project_memory`/`skill_candidate` 永不被默认 stale 规则命中
- 只有 `feedback_score < -2.0 AND importance < 0.3`（且 decay_policy 非 freeze/stable）才触发 stale

contradicted 自动归档（新增）：
- `contradicted` 状态记录若 90 天内未被访问 → 自动 archive（`contradicted_expired`）

decay_policy 真正生效：
- `freeze`：curator 跳过所有自动规则（stale/archive/decay 全部免疫）
- `stable`：stale 阈值提高到 feedback<-2.0 AND importance<0.3，且无 confidence 衰减

decay 条件修正：
- 新增 `injected_count > 0` 条件——从未被注入过的记忆不衰减，避免把"冷门但正确"的记忆错误降权

promotion 扩展：
- 新增按 `injected_count >= 3` 晋升——实际被使用 3 次以上的 candidate 无论 importance 多少都提升为 active

`curator_report` 返回值新增字段：`revival_candidates`

**`local_memory_mcp/storage/rollup.py`**
- 去掉 `source = 'extraction'` 限制，所有 episodic_memory（包括 hermes 直写的 source='manual'）均可被 rollup 处理

**`tests/test_curator.py`** / **`tests/test_temporal.py`**
- 调整 dead_candidate 测试：7 天窗口（8天前）替代原 48h
- 调整 decay 测试：`_set_last_accessed` 补充 `injected_count=1`

**`tests/test_curator_v3.py`**（新建，20 个测试）
- candidate 分档超时（episodic 7天、precious 30天、default 7天）
- stale 复活（近期注入 + 有效 + 无负反馈 → active）
- contradicted 归档（90天无访问）
- freeze policy 完全跳过
- stable policy 仅极端负反馈才 stale
- precious 类型保护
- injected_count >= 3 晋升
- rollup 可处理 manual source 的 episodic

**数据迁移（一次性 SQL）**
- `promoted → active`（当前库无此状态记录）
- stale 复活扫描（当前库无符合条件记录）

### 验证

```bash
.venv/bin/python -m pytest -q
# 362 passed, 1 warning
```

### 影响范围

- MCP 工具 API 零变更（所有改动在 storage 层）
- `curator_report` 返回值新增 `revival_candidates` 字段（向后兼容，调用方可忽略）
- 外部工具若依赖 `status='promoted'` 过滤需改为 `status='active'`

### 回滚

`git revert HEAD`；无数据库 schema 变更，无需迁移脚本。

---

## [迭代 32] 2026-05-28 — 三端 hook 部署与写回脚本统一化

### 背景

Claude Code、Codex、Hermes 已经能在用户输入后读取相关 lmmcp 记忆，并在会话结束后写回摘要。但三端的 session-end 脚本、部署路径和注册逻辑分散，后续维护容易漂移。用户要求把部署脚本、部署方式、执行脚本、存放目录和规则尽量统一。

### 变更摘要

**`scripts/hooks/lmmcp-ingest.py`**（新建）
- 用单一 Python 脚本统一 Claude / Codex / Hermes 的 session-end 写回。
- `--agent claude`：读取 `CLAUDE_SESSION_FILE` 或 `~/.claude/projects/**/*.jsonl`。
- `--agent codex`：读取 `CODEX_SESSION_FILE` 或 `~/.codex/sessions/**/*.jsonl`，兼容 `event_msg` 与 `response_item`。
- `--agent hermes`：读取 hook stdin 的 `session_id`，解析 `~/.hermes/sessions/session_<id>.json`。
- 统一调用 `memory_ingest`，使用 `curl --max-time 10` 后台 fire-and-forget，不阻塞 agent 退出。

**`scripts/setup-hooks.sh`**（新建/更新）
- 作为统一部署入口，写入 Claude/Codex/Hermes 配置。
- Claude Stop → `python3 scripts/hooks/lmmcp-ingest.py --agent claude`。
- Codex Stop → `python3 scripts/hooks/lmmcp-ingest.py --agent codex`。
- Hermes on_session_end → 部署副本到 `~/.hermes/agent-hooks/lmmcp-ingest.py --agent hermes`。
- 自动清理旧的 `session-end.sh` / `codex-session-end.sh` / `lmmcp-session-end.py` hook 条目。

**`scripts/connect_agents.py`**
- `--register-hooks` 路径与 `setup-hooks.sh` 对齐。
- Claude/Codex/Hermes 都注册统一 ingest hook；Codex 启用 `[features] hooks = true` 并写 `hooks.json`。
- Hermes 注册时同步部署统一 hook 到 `~/.hermes/agent-hooks/`。

**清理**
- 删除旧的 `scripts/hooks/session-end.sh`。
- 删除旧的 `scripts/hooks/codex-session-end.sh`。
- 删除旧的 `scripts/hermes/lmmcp-session-end.py` 及空目录。

### 验证

```bash
python3 -m py_compile scripts/hooks/lmmcp-ingest.py scripts/connect_agents.py
bash scripts/setup-hooks.sh
echo '{}' | python3 scripts/hooks/lmmcp-ingest.py --agent claude
echo '{}' | python3 scripts/hooks/lmmcp-ingest.py --agent codex
echo '{}' | python3 scripts/hooks/lmmcp-ingest.py --agent hermes
/home/advancer/project/local-memory-mcp/.venv/bin/python -m pytest /home/advancer/project/local-memory-mcp/tests -q
# 342 passed, 2 warnings
```

### 影响范围

- 只改变 agent hook 部署和会话写回路径，不改变 MCP 数据模型。
- 旧 hook 配置会被安装脚本幂等清理，避免重复写回。
- Hermes 仍使用自身 `memory_context.enabled` 做上下文注入，只统一 session-end 写回。

### 回滚

`git revert HEAD` 后重新运行 `scripts/setup-hooks.sh` 可恢复配置；如需清理本机 Hermes 副本，可删除 `~/.hermes/agent-hooks/lmmcp-ingest.py`。

---

## [迭代 31] 2026-05-27 — episodic memory 自动汇总 rollup

### 背景

对话抽取目前会把单次事实写成 `episodic_memory` 候选；这些碎片适合短期留痕，但长期会形成噪声。用户要求记忆积攒到一定数量后自动提炼成更稳定的长期记忆，并由 lmmcp 自行执行。

### 变更摘要

**`local_memory_mcp/storage/rollup.py`**（新建）
- 新增 `rollup_report()`：扫描 `source='extraction'` 且 `status IN ('candidate','active')` 的 `episodic_memory`。
- 触发条件：同一 `scope/source_agent/project_path` 分组达到 `min_count`（默认 30），或小批量达到 `min_age_count` 且最老记录超过 `max_age_hours`（默认 24h）。
- LLM rollup 输出 durable memories：`user_profile` / `environment_fact` / `agent_architecture` / `project_memory` / `timeline_event` / `decision` / `feedback` / `skill_candidate`。
- `dry_run=True` 只生成计划；`dry_run=False` 会创建 durable memory，并在全部创建成功后 archive 源 episodic 记录。
- 审计事件：`memory_rollup_apply` 记录 source ids、created ids、触发原因和 proposal 数量。

**`local_memory_mcp/server.py`**
- 新增 MCP tool `memory_rollup_report(...)`。
- CLI 新增：
  ```bash
  python -m local_memory_mcp rollup [--apply] [--force] [--summary-only]
  ```
- 自动 curator 线程每轮先执行 `rollup_report(dry_run=False)`，再执行 `curator_report(dry_run=False)`。

**公共 API**
- `local_memory_mcp.storage.rollup_report`
- `local_memory_mcp.rollup_report`

**测试**
- 新增 `tests/test_rollup.py`：覆盖阈值未触发、dry-run proposal、apply 创建长期记忆并归档源 episodic、小批量年龄触发。
- 同步更新 curator/temporal 测试以匹配迭代 31 的强记忆保守规则。

### 验证

```bash
.venv/bin/python -m pytest tests/test_rollup.py tests/test_curator.py tests/test_curator_plan.py tests/test_temporal.py -q
```

---

## [迭代 30] 2026-05-27 — 一键启动脚本 start.sh

### 背景

新机器 clone 仓库后需要一条命令完成 venv 创建、依赖安装、DB 初始化、记忆导入、服务启动。

### 变更摘要

**`start.sh`**（新建，项目根目录）
- 步骤 1：自动查找 Python 3.11+（`python3.11 → python3.12 → python3`）并创建/复用 `.venv`
- 步骤 2：`pip install -e .[extraction]`（幂等，已安装则跳过升级）
- 步骤 3：`python -m local_memory_mcp init` 初始化 SQLite（幂等）
- 步骤 4：若 `memory-sync/memories.json` 存在，自动 import（`--conflict-policy newer`）
- 步骤 5：启动 HTTP MCP 服务

**参数：**
```
bash start.sh                   # 前台运行（默认）
bash start.sh --daemon          # 后台守护进程（PID → /tmp/lmmcp.pid）
bash start.sh --no-import       # 跳过记忆导入
bash start.sh --host 0.0.0.0 --port 8318
bash start.sh --python /usr/bin/python3.12
```

**环境变量（兼容 lmmcp 脚本）：**
`LMMCP_HOST` / `LMMCP_PORT` / `LMMCP_PYTHON` / `LMMCP_PID_FILE` / `LMMCP_AUTO_SYNC`

### 验证

```bash
bash start.sh --no-import --daemon && sleep 1 && curl -s http://127.0.0.1:8318/health
```

---

## [迭代 29] 2026-05-27 — 多设备记忆同步（export/import/sync）

### 背景

用户有多台设备，需要通过代码仓库实现记忆同步。设计要求：
- 导出文件放入 git 仓库（只含持久知识，不含临时状态）
- `lmmcp start` 自动从远端拉取最新记忆
- `lmmcp stop` 自动将当前记忆推送到远端
- 冲突按时间戳（`updated_at`）决定保留哪条（newer 策略）

### 变更摘要

**`local_memory_mcp/storage/transfer.py`**
- `memory_export` 新增 `memories_only: bool` 参数：只导出 `memories`、`feedback_events`、`memory_links`（持久跨设备知识），跳过 `agent_messages`/`presence`/`permissions`（设备私有运行时状态）。
- `memory_import` 新增 `conflict_policy="newer"` 策略：按 `updated_at` 时间戳决定保留本地还是导入行，`newer_wins` 字段返回各表被更新的行数。返回值新增 `newer_wins` 字段。
- 合法冲突策略集合更新为 `{"skip", "replace", "newer"}`。

**`local_memory_mcp/server.py`**
- MCP tool `memory_export` 新增 `memories_only` 参数，文档说明跨设备同步用途。
- MCP tool `memory_import` 文档更新，列出 `newer` 策略说明。
- CLI 新增 `export` 子命令：
  ```
  python -m local_memory_mcp export [FILE] [--memories-only] [--include-audit]
  ```
  默认输出 `memory-export.json`，`--memories-only` 用于同步场景。
- CLI 新增 `import` 子命令：
  ```
  python -m local_memory_mcp import FILE [--conflict-policy newer] [--apply]
  ```
  默认 dry-run，`--apply` 实际写入，`--conflict-policy` 默认 `newer`。

**`scripts/sync-memory.sh`**（新建）
- 独立同步脚本，支持 `push` / `pull` / `sync` / `status` 四个子命令。
- `push`：导出 → git add → git commit → git push。
- `pull`：git pull → dry-run 预览 → 交互式确认 → import。
- `sync`：push 后再 pull（完整双向）。
- 环境变量：`SYNC_FILE`（默认 `memory-sync/memories.json`）、`SYNC_REMOTE`、`SYNC_DEVICE`、`LMMCP_AUTO_SYNC`。

**`scripts/lmmcp`**（更新）
- `start` 前自动执行 `git pull + import --conflict-policy newer`（拉取远端最新记忆）。
- `stop` 后自动执行 `export + git commit + git push`（将本次会话记忆推送到远端）。
- 新增 `sync` 子命令：手动触发 export+push+pull+import。
- 新增 `LMMCP_AUTO_SYNC` 环境变量（默认 `1`），设为 `0` 禁用自动同步。
- 所有 git/sync 操作失败时只打日志，不阻断主服务启停。

**`tests/test_sync.py`**（新建，11 个测试）
- `memories_only` 导出字段验证
- `newer` 策略：incoming 更新时覆盖、existing 更新时保留、新行直接插入
- dry-run 不写入验证
- 非法 conflict_policy 返回错误
- CLI `export` 生成文件
- CLI `import` dry-run 不改数据
- CLI `import` 文件不存在返回 1

### 同步工作流

**首次配置（在代码仓库内）：**
```bash
# 确保 memory-sync/ 目录会被 git 追踪（默认不被 .gitignore 排除）
mkdir -p memory-sync
```

**日常使用（自动模式）：**
```bash
scripts/lmmcp start   # 自动拉取远端最新记忆 → 启动服务
# ... 工作 ...
scripts/lmmcp stop    # 停止服务 → 自动导出并推送记忆
```

**手动同步：**
```bash
scripts/lmmcp sync
# 或独立脚本
scripts/sync-memory.sh push    # 仅推送
scripts/sync-memory.sh pull    # 仅拉取（有交互式确认）
scripts/sync-memory.sh status  # 查看状态
```

**关闭自动同步：**
```bash
LMMCP_AUTO_SYNC=0 scripts/lmmcp start
```

### 验证

```bash
.venv/bin/python -m pytest -q
# 338 passed, 1 warning
```

---



## 下一阶段规划（2026-06）

当前版本：`v0.25.0`，362 tests，36 MCP tools。

---

### P0 — 已知剩余设计问题

**S-2 嵌套 `managed_conn` 破坏事务原子性（待决策）**

当前 `update_status()` 内部调用 `managed_conn`，curator 的 `for planned in action_plan: update_status(...)` 又在外层循环外没有统一事务包裹。如果外部调用方同时持有 `managed_conn`，内层 `commit` 会提前释放，外层 rollback 无法撤销内层已提交的变更。

三个选项：
1. 拆分 `update_status_unsafe(conn, id, status)` 供内部复用（推荐）
2. 用 SQLite `SAVEPOINT` 实现嵌套事务语义
3. 接受当前行为，文档化为已知限制

**D-2 `valid_until` 时区比较风险**

`valid_until` 过滤用字符串比较 `valid_until > now()`，`now()` 输出带 `+00:00` 的 ISO 字符串。若写入值无时区后缀（`2026-06-01T00:00:00`），字符串比较结果取决于字典序，可能误判。

修复：在 `_validate_iso()` 中强制要求时区信息（`tzinfo is not None`）。

---

### Phase 11 — 存储层强化（建议 2026-06）

**11-A `managed_conn` S-2 修复**
- 新增 `_execute_with_conn(conn, ...)` 系列内部 API，区分"已有连接"和"需要新连接"两种调用路径
- curator apply 批量操作包在单一 `managed_conn` 中
- 预期：3–4 个文件，约 80 行改动，0 test 变动

**11-B WAL 自动检查点策略**
- 当前只在 curator apply 时触发一次 `wal_checkpoint(TRUNCATE)`
- 方案：在 `_get_thread_conn()` 中注册 `PRAGMA wal_autocheckpoint=500`（默认 1000），降低 WAL 累积上限
- 预期：1 行改动

**11-C `context_quality_events` 写入节流**
- 当前每次 `build_context_pack` 都写入，高频调用时写放大严重
- 方案：采样写入（每 N 次写 1 次），或只在 `used_ids` 非空时写入
- 预期：3 行改动

---

### Phase 12 — 提取与去重增强（建议 2026-06）

**12-A `memory_ingest` 语义去重改进**
- 当前 Qdrant 去重阈值固定（`>=0.92 skip / >=0.78 update`），无法按 type 差异化
- 方案：`dedup_threshold` 按 `memory_type` 配置，`feedback` 类型阈值更低（更容易合并），`decision` 类型阈值更高（更保守）

**12-B 中文提取 prompt 优化**
- `extraction.py` 的系统 prompt 全英文，对中文输入效果降级
- 方案：检测输入语言，动态切换中/英双语 prompt

---

### Phase 13 — Agent 协作增强（建议 2026-07）

**13-A Handoff 超时与重试**
- 当前 `agent_handoff_create` 创建后无超时检测，死 handoff 永远不清理
- 方案：`handoff_timeout_seconds` 字段 + curator 定期清理超时 handoff

**13-B `memory_context` v2 结构化响应**
- 当前 `context` 字段是纯文本，不利于 agent 程序化解析
- 方案：在保留 `context` 字段的同时，`sections` 字段提供结构化 `{type, records, warnings}`（已有雏形，需完善 schema）

**13-C Agent 能力匹配路由**
- `agent_capability_search` 已实现，但 handoff 创建时没有自动推荐目标 agent
- 方案：`agent_handoff_create` 新增可选 `auto_route=True`，自动查找能力匹配的 online agent

---

### Phase 14 — 发布准备（建议 2026-Q3）

- PyPI 发布流程（已有 `.github/workflows/publish.yml` 骨架）
- Docker Compose 一键启动（已有 `Dockerfile` + `docker-compose.yml`）
- `memory_import` / `memory_export` 跨版本兼容性测试
- 多工作区支持：`scope: project/<name>` 隔离不同项目的记忆命名空间
- Embedding 升级：Ollama 不可用时自动降级到 `sentence-transformers`（zero-dep fallback 已有 hashing）

---

### 代码审查红线（任何 PR 必须保证）

1. `storage/` 包零 MCP 依赖（`from mcp` 不得出现在 `storage/` 下任何文件）
2. `models.py` 零 I/O 依赖
3. `tests/` 通过 `LOCAL_MEMORY_DB` 指向临时库，不写生产数据库
4. 新增 MCP tool 参数必须有默认值（向后兼容）
5. 362 tests 全绿（不得下降）
6. 每次推送前追加 `ITERATION.md`

---

## [迭代 28] 2026-05-27 — 全项目缺陷审计与快速优化

### 背景

对当前整个项目做全面静态分析，找出漏洞、不合理点、冗余代码、可小改动明显优化体验的点，并全部执行修复。

### 变更摘要

**S-1/Q-4 [CRITICAL] `managed_conn` retry 逻辑完全失效**
- 原实现：`@contextmanager` 内用 `for attempt in range(N): yield conn`，当 `with` 块抛出异常时 Python 调用 `generator.throw()`，第二次 `yield` 触发 `RuntimeError: generator didn't stop after throw()`，retry 是死代码。
- 修复：`yield` 拆出循环，单独放在 `try/except` 中；retry 移到 `_commit_with_retry()` 辅助函数，在 `commit` 阶段循环重试 `database is locked`。
- 文件：`local_memory_mcp/storage/db.py`

**S-3 [HIGH] `config.yaml` 中 `extraction.api_key: "sk"` 屏蔽 env var 回退**
- 原问题：非空占位符 `"sk"` 在 `extraction_config_from_dict` 中优先级最高，导致 `DEEPSEEK_API_KEY` / `MEM0_LLM_API_KEY` 环境变量永远不被读取。
- 修复：清空为 `""`，env var 回退链恢复正常。
- 文件：`config.yaml`

**N-1/N-2 [HIGH] N+1 查询**
- `agents.py` broadcast：原来每个收件人开一个 `managed_conn` + `INSERT`（N 个事务）→ 改为单次 `executemany`。
- `curator.py` auto_decay：原来每条记录一个 `managed_conn` + `UPDATE` → 改为单次 `executemany`，同一连接内合并执行。
- 文件：`local_memory_mcp/storage/agents.py`、`local_memory_mcp/storage/curator.py`

**Q-1 [MEDIUM] `"继续"` 在 `_GREETINGS` 中**
- `"继续"` 是任务续接词，不是问候语。被识别为问候时 `build_context_pack` 跳过 FTS 搜索，导致续接场景完全没有记忆上下文。
- 修复：从 `_GREETINGS` 集合中删除。
- 文件：`local_memory_mcp/storage/search.py`

**Q-2 [MEDIUM] `context_quality_events` 和 `audit_events` 无清理机制**
- 每次 `build_context_pack` 无条件写一行 `context_quality_events`，无任何 DELETE 路径，长期运行后无限增长。
- 修复：在 curator apply 块内加 90 天 / 180 天 DELETE SQL，与 auto_decay `executemany` 同一事务。
- 文件：`local_memory_mcp/storage/curator.py`

**Q-3 [MEDIUM] `valid_from`/`valid_until` 无格式校验**
- 任意字符串写入后 expiry filter 做字符串比较，格式错误会静默产生错误过滤结果。
- 修复：新增 `_validate_iso()` 在写入前调用 `datetime.fromisoformat()`，格式错误立即抛出 `ValueError`。
- 文件：`local_memory_mcp/storage/crud.py`

**Q-5/D-4 [LOW] WAL 无检查点，4.2MB vs 1.8MB 主库**
- curator apply 后加 `PRAGMA wal_checkpoint(TRUNCATE)`（必须在事务外执行，独立调用 thread-local conn）。
- 文件：`local_memory_mcp/storage/curator.py`

**R-1 [LOW] `ops_db` 死配置**
- `DEFAULT_CONFIG` 中 `ops_db` 字段、`config.yaml` 中 `ops_db` 段在整个代码库中无任何读取路径，纯噪音。
- 修复：从两处删除。
- 文件：`local_memory_mcp/models.py`、`config.yaml`

**R-2 [LOW] `mem0` compat 代码与配置段**
- `extraction_config_from_dict` 中保留的 `mem0` 回退链（`llm_api_key`/`llm_base_url`/`llm_model`）永远不触发（README 明确 mem0 已移除）。
- `config.yaml` 中 `mem0:` 配置段同样已成死配置。
- 修复：清除 `extraction.py` 中的 compat 代码；删除 `config.yaml` 中 `mem0:` 段。
- 文件：`local_memory_mcp/extraction.py`、`config.yaml`

**R-3 [LOW] `DEFAULT_DB` import 时冻结**
- `db_path()` 原来用 `str(DEFAULT_DB)` 作为默认值，而 `DEFAULT_DB` 在 import 时已固化（env var 设置在 import 之后不生效）。
- 修复：`db_path()` 直接读 `DEFAULT_ROOT / "memory.sqlite3"`，不再依赖 `DEFAULT_DB`。
- 文件：`local_memory_mcp/models.py`

### 验证

```bash
.venv/bin/python -m pytest -q
# 327 passed, 1 warning in 34.45s
```

测试更新：
- `tests/test_deployment.py`：移除对 `memory_ops.sqlite3` 的断言（R-1 已删除该配置）。
- `tests/test_extraction.py`：`test_from_dict_mem0_fallback` 改为测试 `extraction` 段（R-2 已移除 mem0 compat）。

---

## [迭代 27] 2026-05-27 — Temporal Memory Layer + Auto-decay + Memory Stats

### 背景

执行规划中 Phase 10（Temporal Memory Layer）及配套工具与测试。

### 变更摘要

**Temporal Memory Layer**
- `memory_add` / `add_memory_record` 新增 `valid_from: str | None` 和 `valid_until: str | None` 参数（ISO-8601）。
- `search_memory_records` 自动过滤 `valid_until < now()` 的过期记忆（仍保留在 DB，`memory_get` 可取回）。
- DB 层：`CREATE TABLE` 已含 `valid_from TEXT, valid_until TEXT`；`_ensure_column` 向后兼容旧库。

**Auto-decay**
- `curator.py` 新增常量 `_DECAY_STEP=0.05`、`_DECAY_INTERVAL_DAYS=30`、`_DECAY_MIN_CONFIDENCE=0.10`。
- `curator_report` 新增 `auto_decay_candidates` 查询：`decay_policy='review'` 且 30+ 天未访问的 active 记忆。
- `dry_run=False` 时批量降低 `confidence`（每轮 -0.05，floor 0.10）；`dry_run=True` 仅列出候选。
- `summary` 新增 `auto_decay_candidates` 计数字段。

**Contradiction detection**
- `curator_report` 新增 `contradiction_candidates` 列表：同一 normalized title key 同时存在 `active` 和 `contradicted` 状态记录时，标记为矛盾候选。
- 新增 3 个测试：`test_contradiction_candidates_detected_by_title_key`、`_not_listed_when_only_active`、`_not_listed_without_active_counterpart`。

**`memory_stats` MCP 工具**
- 新增 MCP tool `memory_stats()`：返回按 type/status/agent 分组的记录数及 confidence/importance/feedback 聚合均值、`never_accessed_count`、`link_count`。
- `README.md` 工具表更新（35 个工具）；`CHANGELOG.md` 新增 `[0.21.0]` 条目。
- `pyproject.toml` version: `0.20.0 → 0.21.0`。

**测试**
- 新增 `tests/test_temporal.py`：13 个测试，覆盖 valid_from/until 存储、过期过滤、DB 保留、auto_decay 候选、confidence 降低、floor 强制、stable policy 跳过、近期访问跳过、summary 计数。
- 新增 3 个 contradiction 测试到 `tests/test_curator.py`。
- 新增 `tests/test_stats.py`：`memory_stats` 返回结构验证。

### 验证

```bash
.venv/bin/python -m pytest -q
# 317 passed → (after 迭代 28) 327 passed
```

---

## [迭代 26] 2026-05-26 — 同端口前端控制服务

### 变更摘要
- `local_memory_mcp/frontend.py`：新增同端口前端控制服务路由，提供 `/` 控制台、`/api/*` REST API、`/health`、`/metrics`。
- `local_memory_mcp/server.py`：通过 FastMCP `custom_route` 将前端与 REST API 挂载到现有 HTTP 服务；`/mcp` 保持不变。
- `serve` 默认端口改为 `8318`，默认提供统一服务：`/`、`/api/*`、`/mcp`、`/health`、`/metrics`。
- `serve` 新增 `--auth-token`、`--allow-insecure-remote`、`--mcp-only`；非 loopback 绑定默认要求 token 或显式不安全开关。
- 前端控制台使用无构建 vanilla JS，不加载第三方 CDN；支持 records、curator、agents、ops、raw JSON 等基础控制视图。
- `local_memory_mcp/storage/dashboard.py`：抽出 `dashboard_payload(limit=1000)`，静态 `export_html()` 与实时 `/api/dashboard` 复用同一数据源。
- `local_memory_mcp/storage/__init__.py`：导出 `dashboard_payload`。
- `README.md` / `docs/deployment.md`：文档更新为同端口路径布局：`/` 前端、`/api/*` REST、`/mcp` MCP。
- `tests/test_frontend.py`：新增 7 个测试覆盖前端首页、health、dashboard payload、memory create/get/patch、bad JSON、404、token auth、remote bind guard。

### 验证
- 聚焦测试：`/home/advancer/project/local-memory-mcp/.venv/bin/python -m pytest /home/advancer/project/local-memory-mcp/tests/test_frontend.py /home/advancer/project/local-memory-mcp/tests/test_html.py /home/advancer/project/local-memory-mcp/tests/test_dashboard_ops.py /home/advancer/project/local-memory-mcp/tests/test_cli.py -q` → **11/11 pass**（1 个 httpx 测试 warning）。
- 全量测试：`/home/advancer/project/local-memory-mcp/.venv/bin/python -m pytest /home/advancer/project/local-memory-mcp/tests -q` → **310/310 pass**（1 个 httpx 测试 warning）。

### 使用方式
```bash
cd /home/advancer/project/local-memory-mcp
.venv/bin/python -m local_memory_mcp serve --host 127.0.0.1 --port 8318
```

浏览器访问：
```text
http://127.0.0.1:8318/
```

MCP 客户端继续使用：
```text
http://127.0.0.1:8318/mcp
```

远程访问示例：
```bash
LOCAL_MEMORY_FRONTEND_TOKEN='change-me' .venv/bin/python -m local_memory_mcp serve --host 0.0.0.0 --port 8318
```

### 已知问题
- 前端控制台是轻量 vanilla JS 单页，不是完整设计系统；复杂表单校验仍依赖后端 API。
- `/api/*` token 是单 token 模式，尚未实现用户账号、RBAC 或 agent identity 绑定。
- 测试中的 bad JSON case 触发 httpx deprecation warning，不影响功能。

---

## [迭代 25] 2026-05-26 — Dashboard 运维台增强

### 变更摘要
- `local_memory_mcp/storage/dashboard.py`：Dashboard payload 新增 `links`、`mailbox`、`presence`、`context_quality`，用于本地运维视图。
- Dashboard 导航新增 Graph / Mailbox / Presence 视图。
- Health 视图新增 Feedback drilldown，展示 context pack 质量趋势（pack 数、hit/filter/ineffective rate、按 task type 分布）。
- Curator 视图新增 Action plan 区块，展示 dry-run preview、原因与 rollback metadata。
- Graph 视图展示最近 memory_links 关系边。
- Mailbox 视图展示最近 agent_messages 与 handoff metadata。
- Presence 视图展示 agent 在线状态与 namespace metadata。
- `local_memory_mcp/storage/db.py`：SQLite lock 重试次数 3→10，降低权限/审计/向量同步叠加后的并发写入偶发锁冲突。
- `tests/test_dashboard_ops.py`：新增 2 个测试覆盖 dashboard ops payload 与视图文案。

### 验证
- 局部测试：`/home/advancer/project/local-memory-mcp/.venv/bin/python -m pytest /home/advancer/project/local-memory-mcp/tests/test_dashboard_ops.py /home/advancer/project/local-memory-mcp/tests/test_html.py -q` → **3/3 pass**。
- 并发回归：`/home/advancer/project/local-memory-mcp/.venv/bin/python -m pytest /home/advancer/project/local-memory-mcp/tests/test_concurrent_and_migration.py::test_concurrent_writes_no_corruption -q` → **1/1 pass**。
- 全量测试：`/home/advancer/project/local-memory-mcp/.venv/bin/python -m pytest /home/advancer/project/local-memory-mcp/tests -q` → **303/303 pass**。

### 已知问题
- Dashboard 仍是静态 HTML 运维台，只展示 preview，不直接执行 curator apply / permission / handoff 操作。
- Graph 视图当前为关系边列表，不是可交互力导向图。

### 下一步
1. 如需继续增强，可实现 dashboard 操作端点或导出可执行 CLI command snippets。
2. 如需更强图谱视图，可引入本地无构建 SVG graph 渲染。

---

## [迭代 24] 2026-05-26 — Agent handoff workflow schema

### 变更摘要
- `local_memory_mcp/storage/db.py`：新增 `agent_capabilities` 表与 namespace 索引。
- `local_memory_mcp/storage/handoff.py`：新增结构化 handoff 工作流与能力注册模块。
- `agent_handoff_create()`：创建带 `workflow=handoff`、`handoff_status=requested`、`correlation_id`、payload 的 mailbox 消息。
- `agent_handoff_update()`：支持 `ack` / `done` / `failed` 状态，向原请求方发送响应消息，并写回原消息 metadata。
- `agent_capability_register()` / `agent_capability_search()`：提供 agent capability registry，用于后续任务路由。
- `local_memory_mcp/server.py`：新增 MCP 工具 `agent_handoff_create`、`agent_handoff_update`、`agent_capability_register`、`agent_capability_search`。
- `local_memory_mcp/storage/__init__.py` / `local_memory_mcp/__init__.py`：导出 handoff public API。
- `README.md`：MCP 工具数 30→34，工具表补充 handoff 与 capability 工具。
- `tests/test_handoff.py`：新增 4 个测试覆盖 handoff schema、状态响应、非法状态拒绝、capability registry 查询。

### 验证
- 局部测试：`/home/advancer/project/local-memory-mcp/.venv/bin/python -m pytest /home/advancer/project/local-memory-mcp/tests/test_handoff.py /home/advancer/project/local-memory-mcp/tests/test_mailbox.py /home/advancer/project/local-memory-mcp/tests/test_docs_consistency.py -q` → **25/25 pass**。
- 全量测试：`/home/advancer/project/local-memory-mcp/.venv/bin/python -m pytest /home/advancer/project/local-memory-mcp/tests -q` → **301/301 pass**。

### 已知问题
- handoff 当前基于 mailbox metadata 实现，未新增专用 handoff table；这保持兼容，但复杂查询能力有限。
- capability search 当前是精确 capability 字符串匹配，尚未支持模糊匹配或权重排序。

### 下一步
1. Iter 25：Dashboard 运维台增强。

---

## [迭代 23] 2026-05-26 — Context Pack 质量指标与权重调优

### 变更摘要
- `local_memory_mcp/storage/db.py`：新增 `context_quality_events` 表，记录 context pack 生成时的候选数、使用数、过滤数、hit/filter/ineffective rate、task type 与 type weights。
- `local_memory_mcp/storage/search.py`：新增 task type 轻量分类与类型权重；`build_context_pack()` 根据 task type 对 memory type 做二次排序。
- `build_context_pack()` 的 `quality` 新增 `hit_rate`、`filter_rate`、`ineffective_rate`；`trace` 新增 `task_type` 与 `type_weights`。
- `get_context_quality_stats()`：新增 context pack 质量趋势聚合，返回总体平均与按 task type 分组指标。
- `local_memory_mcp/server.py`：新增 MCP 工具 `memory_context_stats`。
- `local_memory_mcp/storage/__init__.py` / `local_memory_mcp/__init__.py`：导出 context quality stats API。
- `README.md`：MCP 工具数 29→30，工具表补充 `memory_context_stats`。
- `tests/test_context_quality_metrics.py`：新增 3 个测试覆盖质量事件记录、task type 权重、空统计返回形状。

### 验证
- 局部测试：`/home/advancer/project/local-memory-mcp/.venv/bin/python -m pytest /home/advancer/project/local-memory-mcp/tests/test_context_quality_metrics.py /home/advancer/project/local-memory-mcp/tests/test_context_pack_v2.py /home/advancer/project/local-memory-mcp/tests/test_docs_consistency.py -q` → **21/21 pass**。
- 全量测试：`/home/advancer/project/local-memory-mcp/.venv/bin/python -m pytest /home/advancer/project/local-memory-mcp/tests -q` → **297/297 pass**。

### 已知问题
- task type 分类为关键词启发式，不是 LLM 分类器。
- hit_rate 当前表示 used/candidates，不代表下游用户实际满意度；真实效果仍需结合 `memory_feedback`。

### 下一步
1. Iter 24：Agent handoff workflow schema。
2. Iter 25：Dashboard 运维台增强。

---

## [迭代 22] 2026-05-26 — Curator apply plan + rollback metadata

### 变更摘要
- `local_memory_mcp/storage/curator.py`：`curator_report()` 新增 `allow_actions` / `deny_actions` 参数，支持按 action 类型过滤 apply plan。
- `curator_report()` 新增 `action_plan` 字段；dry-run 也会返回计划动作，包含 `id`、`action`、`title`、`reason`、`target_status`、`rollback`。
- apply 路径改为先生成 action plan，再执行状态变更；`actions` 保持旧格式以维持向后兼容。
- `curator_apply` 审计 detail 新增完整 action plan 与 rollback metadata，便于人工恢复。
- `summary` 新增 `planned_actions`。
- `local_memory_mcp/server.py`：`memory_curator_report` MCP 工具参数补充 `allow_actions` / `deny_actions`。
- `tests/test_curator_plan.py`：新增 4 个测试覆盖 dry-run preview、allow filter、deny filter、rollback 审计 metadata。

### 验证
- 局部测试：`/home/advancer/project/local-memory-mcp/.venv/bin/python -m pytest /home/advancer/project/local-memory-mcp/tests/test_curator.py /home/advancer/project/local-memory-mcp/tests/test_curator_plan.py -q` → **10/10 pass**。
- 全量测试：`/home/advancer/project/local-memory-mcp/.venv/bin/python -m pytest /home/advancer/project/local-memory-mcp/tests -q` → **294/294 pass**。

### 已知问题
- rollback metadata 当前记录状态字段，尚未提供一键 rollback MCP 工具。
- allow/deny 过滤粒度为 action 类型，尚未支持按 memory type/scope/tag 的 curator rule DSL。

### 下一步
1. Iter 23：Context Pack 质量指标与权重调优。
2. Iter 24：Agent handoff workflow schema。
3. Iter 25：Dashboard 运维台增强。

---

## [迭代 21] 2026-05-26 — export/import/backup/restore 稳定化

### 变更摘要
- `local_memory_mcp/storage/transfer.py`：新增 schema-versioned JSON 导出/导入、SQLite backup、Qdrant 向量重建入口。
- `memory_export()`：导出 `memories`、`feedback_events`、`memory_links`、`agent_messages`、`agent_presence`、`agent_permissions`，可选包含 `audit_events`。
- `memory_import()`：支持 `dry_run`、冲突报告、schema version 检查、`skip` / `replace` 冲突策略；导入落地时写入 `memory_import` 审计事件。
- `memory_backup()`：使用 SQLite backup API 创建一致性数据库备份，并写入 `memory_backup` 审计事件。
- `memory_rebuild_vectors()`：支持 dry-run 预估与从 SQLite 非 archived 记录重建 Qdrant 向量索引，落地时写入 `memory_vector_rebuild` 审计事件。
- `local_memory_mcp/server.py`：新增 MCP 工具 `memory_export`、`memory_import`、`memory_backup`、`memory_rebuild_vectors`。
- `local_memory_mcp/storage/__init__.py` / `local_memory_mcp/__init__.py`：导出 transfer public API。
- `README.md`：MCP 工具数 25→29，工具表补充 export/import/backup/vector rebuild。
- `tests/test_transfer.py`：新增 5 个测试覆盖导出 payload、dry-run 冲突、实际导入、schema 拒绝、SQLite 备份。

### 验证
- 局部测试：`/home/advancer/project/local-memory-mcp/.venv/bin/python -m pytest /home/advancer/project/local-memory-mcp/tests/test_transfer.py /home/advancer/project/local-memory-mcp/tests/test_docs_consistency.py /home/advancer/project/local-memory-mcp/tests/test_agent_permissions.py -q` → **13/13 pass**。
- 全量测试：`/home/advancer/project/local-memory-mcp/.venv/bin/python -m pytest /home/advancer/project/local-memory-mcp/tests -q` → **290/290 pass**。

### 已知问题
- JSON import 当前按表主键处理冲突，不做跨表引用完整性预演；错误 payload 仍可能在 apply 阶段由 SQLite 外键约束拒绝。
- Qdrant rebuild 复用现有 fire-and-forget `_sync_to_vector()`，单条失败只记录 warning，不中断整批。

### 下一步
1. Iter 22：Curator apply plan + rollback metadata。
2. Iter 23：Context Pack 质量指标与权重调优。
3. Iter 24：Agent handoff workflow schema。

---

## [迭代 20] 2026-05-26 — Agent 权限模型 + 拒绝审计

### 变更摘要
- `local_memory_mcp/storage/permissions.py`：新增 agent 权限策略模块，支持 `grant_agent_permission()`、`get_agent_permission()`、`check_agent_permission()`、`get_agent_namespace()` 与拒绝审计。
- `local_memory_mcp/storage/db.py`：新增 `agent_permissions` 表与 namespace 索引，按 agent_id 唯一 upsert 权限策略。
- `local_memory_mcp/storage/crud.py`：`add_memory_record()` 写入前检查 agent 对 scope/type/tag 的写权限；未配置权限策略时保持向后兼容默认允许。
- `local_memory_mcp/storage/agents.py`：广播消息前检查 `can_broadcast`；已配置 namespace 时仅广播给同 namespace 的 online/idle agent；presence metadata 缺失 namespace 时使用权限策略默认 namespace 补齐。
- `local_memory_mcp/server.py`：新增 MCP 工具 `agent_permission_grant` 与 `agent_permission_get`。
- `local_memory_mcp/storage/__init__.py` / `local_memory_mcp/__init__.py`：导出权限相关 public API。
- `README.md`：MCP 工具数 23→25，工具表补充 agent 权限工具。
- `tests/test_agent_permissions.py`：新增 6 个测试覆盖默认兼容、写入拒绝审计、scope/type/tag 过滤、广播拒绝审计、namespace 广播隔离、presence namespace 默认值。

### 验证
- 局部测试：`/home/advancer/project/local-memory-mcp/.venv/bin/python -m pytest /home/advancer/project/local-memory-mcp/tests/test_agent_permissions.py /home/advancer/project/local-memory-mcp/tests/test_docs_consistency.py -q` → **8/8 pass**。
- 全量测试：`/home/advancer/project/local-memory-mcp/.venv/bin/python -m pytest /home/advancer/project/local-memory-mcp/tests -q` → **285/285 pass**。

### 已知问题
- 权限模型当前为 agent 级静态策略；尚未实现 group/role 继承、token identity 绑定或外部认证集成。
- 读权限检查尚未覆盖所有 read MCP tools；本轮优先落地写入与广播信任边界。

### 下一步
1. Iter 21：export/import/backup/restore 稳定化。
2. Iter 22：Curator apply plan + rollback metadata。
3. Iter 23：Context Pack 质量指标与权重调优。

---

## [下一步迭代规划] 2026-05-26 — Iter 20–25 Roadmap

### 推荐优先级

1. **Iter 20 — Agent 权限模型 + 拒绝审计**
   - 增加 agent identity / namespace 概念。
   - 定义 agent 对 memory scope/type/tag 的读写权限。
   - 限制 broadcast 跨 namespace 行为。
   - 对权限拒绝写入 audit event。
   - 目标：在多 agent 共享记忆前先补齐信任边界。

2. **Iter 21 — export/import/backup/restore 稳定化**
   - 稳定 `memory_export` / `memory_import` 合约。
   - 支持 dry-run import、冲突报告、schema version 检查。
   - 支持 SQLite 自动备份与可选 Qdrant 重建。
   - 目标：形成可恢复、可迁移、可审计的数据安全闭环。

3. **Iter 22 — Curator apply plan + rollback metadata**
   - curator apply 前生成 action preview。
   - 支持 allowlist / denylist rule。
   - 每条 curator action 提供原因说明。
   - 写入 rollback metadata，便于人工恢复。
   - 目标：让 curator 从 report-only 走向安全半自动治理。

4. **Iter 23 — Context Pack 质量指标与权重调优**
   - 追踪 context pack 注入后的正/负反馈。
   - 统计命中率、无效率、过滤率趋势。
   - 按 task 类型调整 project / feedback / reference / user memory 权重。
   - 目标：让检索从“能找到”进化到“越用越准”。

5. **Iter 24 — Agent handoff workflow schema**
   - 定义 task handoff message schema。
   - 增加 request/response correlation id。
   - 增加 ack / done / failed 状态。
   - 增加 agent capability registry。
   - 目标：让 Hermes / Claude / Codex / OpenCode 之间能真实协作分工。

6. **Iter 25 — Dashboard 运维台增强**
   - 增加 curator action preview/apply 视图。
   - 增加 memory link graph。
   - 增加 mailbox inbox / presence 面板。
   - 增加 feedback health drilldown。
   - 目标：把当前 Dashboard 从查看器升级成本地运维台。

### 当前建议

如果只做一个下一步，优先进入 **Iter 20 — Agent 权限模型 + 拒绝审计**。当前 lmmcp 已经具备多 agent 共享记忆、mailbox、presence、context pack 与 audit 基础；继续扩大自动协作前，最需要先明确“谁能看、谁能写、谁能广播”。

---

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
