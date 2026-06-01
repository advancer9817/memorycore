# local-memory-mcp

作者：advancer9817-crypto <advancer9817-crypto@users.noreply.github.com>

本地优先、MCP 暴露的多 agent 共享记忆与协作适配层。

给任何支持 MCP 的本地 agent/client 提供统一的长期记忆总线，替代把所有内容塞进某个单一客户端的记忆文件。

## 定位

不是完整的 memory platform，也不是 agent 调度框架。

定位是：**多 agent 记忆与协作控制面**。

- 统一入口：所有 agent 通过同一个 MCP server 读写记忆，不维护孤岛。
- 上下文包装：按任务生成 compact context pack，控制 token budget，区分记忆类型。
- 协作基础：共享记忆 + 未来 agent mailbox + presence，支持 Hermes 总控 + Codex/Claude 专职执行。
- 自进化：curator 定期整理、降噪、归档、合并，高价值经验沉淀为 skills/playbooks。
- 低心智负担：agent 不直接关心 SQLite/Qdrant 细节，只调用稳定 MCP tools。

## 路径

运行时根目录默认就是本项目 checkout；也可由环境变量控制：

```bash
MEM_ROOT="${LOCAL_MEMORY_ROOT:-$(pwd)}"
```

| 文件 | 路径 |
|---|---|
| MCP server | `$MEM_ROOT/local_memory_mcp/` |
| 配置 | `$MEM_ROOT/config.yaml` |
| Python venv | `$MEM_ROOT/.venv/bin/python` |
| SQLite DB | `$MEM_ROOT/memory.sqlite3` |
| Dashboard | `$MEM_ROOT/dashboard.html` |
| MCP probe | `$MEM_ROOT/probe_mcp.py` |
| 可选服务脚本 | `$MEM_ROOT/scripts/lmmcp` |

代码默认使用项目目录内的 `memory.sqlite3`，可用 `LOCAL_MEMORY_DB` 覆盖数据库路径，`LOCAL_MEMORY_CONFIG` 覆盖配置文件路径。

## 快速开始

在任意支持 Python 3.11+ 的机器上，clone 仓库后一条命令完成全部初始化并启动服务：

```bash
git clone https://github.com/advancer9817-crypto/local-memory-mcp.git
cd local-memory-mcp
bash start.sh
```

`start.sh` 自动完成：

1. 创建/复用 `.venv`（自动查找 python3.11/3.12/3.13）
2. 安装默认运行依赖（`pip install -e .[all]`，包含 extraction 与 Qdrant vector；不安装 PyTorch/CUDA/本地 ML 大依赖）
3. 初始化 SQLite 数据库（幂等）
4. 导入 `memory-sync/memories.json`（若存在，使用 `newer` 冲突策略）
5. 启动 HTTP MCP 服务（默认 `127.0.0.1:8318`）

常用参数：

```bash
bash start.sh                        # 前台运行
bash start.sh --daemon               # 后台守护进程
bash start.sh --no-import            # 跳过记忆导入
bash start.sh --host 0.0.0.0 --port 8318
```

服务启动后访问：

```text
http://127.0.0.1:8318/mcp     MCP endpoint
http://127.0.0.1:8318/        前端控制台
http://127.0.0.1:8318/health  健康检查
```

## 多设备记忆同步

记忆通过 git 仓库在多台设备间同步。同步文件为 `memory-sync/memories.json`，只包含持久知识（memories / feedback_events / memory_links），不含设备私有的运行时状态。

### 自动模式（推荐）

`scripts/lmmcp` 服务脚本在 **启动前自动拉取**、**停止后自动推送**：

```bash
scripts/lmmcp start   # git pull → import → 启动服务
scripts/lmmcp stop    # 停止服务 → export → git commit → git push
```

设置 `LMMCP_AUTO_SYNC=0` 可禁用自动同步（git 操作失败时也不会影响服务启停）。

### 手动同步

```bash
# 推送当前设备记忆到远端
scripts/sync-memory.sh push

# 从远端拉取并导入（有 dry-run 预览 + 交互式确认）
scripts/sync-memory.sh pull

# 完整双向同步
scripts/sync-memory.sh sync

# 查看同步状态
scripts/sync-memory.sh status
```

也可直接用 CLI：

```bash
# 导出（只含持久知识）
.venv/bin/python -m local_memory_mcp export memory-sync/memories.json --memories-only

# 导入（newer 策略：按 updated_at 保留更新的一条）
.venv/bin/python -m local_memory_mcp import memory-sync/memories.json --conflict-policy newer --apply
```

### 冲突策略

| 策略 | 行为 | 适用场景 |
|------|------|---------|
| `newer` | 保留 `updated_at` 更新的一条（默认） | 多设备日常同步 |
| `skip` | 本地优先，忽略外来变更 | 只读导入 |
| `replace` | 外来优先，无条件覆盖 | 全量覆盖恢复 |

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LMMCP_AUTO_SYNC` | `1` | 设为 `0` 禁用 lmmcp 自动同步 |
| `SYNC_FILE` | `memory-sync/memories.json` | 同步文件路径（相对仓库根） |
| `SYNC_REMOTE` | `origin` | git remote 名称 |
| `SYNC_DEVICE` | `hostname -s` | commit message 中的设备标识 |



已验证：

1. **SQLite + FTS5 结构化记忆层**：支持 type/scope/tags/status/importance/confidence/source_agent/effectiveness 等字段，FTS5 全文检索。
2. **HTTP MCP server**：35 个工具，Hermes 可通过 `http://127.0.0.1:8318/mcp` 作为普通 HTTP MCP 客户端连接。
3. **Context Pack**：`memory_context` 按任务生成 compact 上下文包，支持 token budget 控制，按记忆类型分组，集成 active contradicts/supersedes warning，并将检索记忆标记为 untrusted data；命中注入特征的记忆会从普通 context body 过滤到 warnings。
4. **Curator**：重复标题、低反馈、stale、archive、矛盾候选、skill_candidate 推广候选检测；默认 dry-run。
5. **Feedback / effectiveness**：`memory_feedback` 记录反馈事件并更新 feedback_score、injected_count、ineffective_count、effectiveness_score。
6. **Memory links / warnings**：支持 `related_to`、`supersedes`、`contradicts`、`supports`、`part_of`；`memory_warnings` 可根据 active links 产生冲突/替代提示。
7. **Qdrant 语义检索**：`memory_vector_search` / `memory_vector_status` / `memory_vector_audit` 通过 `vector_store.py` 使用 Qdrant + 可配置 embedding API；`auto` provider 优先使用配置的 OpenAI-compatible API，未配置时尝试 Ollama API，最后使用 hashing fallback。
8. **Dashboard**：本地交互式 HTML 面板，Alpine.js，无构建步骤；展示记录、时间线、反馈健康和 curator 候选摘要。
9. **多客户端接入方向**：Hermes / Codex / Claude Code / Gemini / OpenCode 都应作为普通 MCP 客户端接入；lmmcp 核心不依赖任一客户端配置仓库或私有 transcript。

Optional / degraded：

- Qdrant、外部 embedding API、Ollama、外部 extraction LLM 都是可选增强；不可用时核心 SQLite/FTS5/context pack 仍应可用。
- `memory_ingest` 会调用 extraction + dedup pipeline；外部模型或向量服务不可用时应视为降级能力，不影响基础 CRUD/search/context。

Removed / not current core：

- sqlite-vec 已移除；CLI `semantic-*` 子命令现在走 Qdrant，与 MCP `memory_vector_search` / `memory_vector_status` 使用同一向量层。
- Mem0 不是当前核心部署的一部分；不要从旧配置或旧文档重新引入 Mem0/OpenMemory 假设。

## MCP 工具列表

| 工具 | 用途 |
|---|---|
| `memory_add` | 写入结构化记忆 |
| `memory_search` | FTS5 关键词搜索 |
| `memory_context` | 按任务生成 context pack |
| `memory_context_stats` | 查询 context pack 质量趋势指标 |
| `memory_get` | 读取单条记忆 |
| `memory_list_recent` | 最近更新记录 |
| `memory_feedback` | 记录记忆有用性反馈 |
| `memory_timeline` | 决策/事件时间线 |
| `memory_curator_report` | curator 候选报告，可选标记 stale/archive |
| `memory_rollup_report` | 将累计 episodic 记忆滚动总结为长期记忆 |
| `memory_atomize_report` | 规划或执行 parent memory 到 atomic child facts 的拆分 |
| `memory_entity_search` | 按实体/别名索引搜索 active memories |
| `memory_ingest` | 从显式传入的对话消息抽取并去重写入 candidate |
| `memory_vector_search` | Qdrant 语义向量搜索 |
| `memory_vector_status` | Qdrant 向量存储状态 |
| `memory_vector_audit` | 检查 SQLite active memories 与 Qdrant points 的一致性 |
| `memory_link_add` | 创建/更新记忆之间的有向关系 |
| `memory_link_query` | 查询某条记忆的 incoming/outgoing links |
| `memory_warnings` | 根据 active links 返回冲突/替代 warning |
| `memory_update` | 更新已有记忆的 title/content/status/confidence/importance |
| `memory_audit_log` | 查询记忆写入、更新、状态变更的审计事件日志 |
| `memory_export` | 导出 schema-versioned JSON 记忆数据 |
| `memory_import` | 导入记忆数据，支持 dry-run 冲突报告 |
| `memory_backup` | 使用 SQLite backup API 创建数据库备份 |
| `memory_rebuild_vectors` | 从 SQLite 记录重建 Qdrant 向量索引 |
| `memory_stats` | 返回按 type/status/agent 分组的记忆统计与聚合分数 |
| `agent_send` | 向指定 agent 发送消息 |
| `agent_handoff_create` | 创建结构化 agent handoff 请求 |
| `agent_handoff_update` | 更新 handoff 状态并发送响应 |
| `agent_capability_register` | 注册 agent 能力用于任务移交 |
| `agent_capability_search` | 按能力和 namespace 查找 agent |
| `agent_inbox` | 读取 agent 收件箱，支持按状态过滤和自动标记已读 |
| `agent_presence_update` | 更新 agent 在线状态（心跳） |
| `agent_presence_list` | 列出 agent 在线状态，支持按状态过滤 |
| `agent_messages_cleanup` | 清理所有已过期的 agent 消息，返回删除数 |

## CLI

```bash
MEM_ROOT="${LOCAL_MEMORY_ROOT:-$(pwd)}"
PY="$MEM_ROOT/.venv/bin/python"

"$PY" -m local_memory_mcp init
"$PY" -m local_memory_mcp add project_memory "标题" "内容"
"$PY" -m local_memory_mcp search memory
"$PY" -m local_memory_mcp context "继续实现多 agent 记忆架构"
"$PY" -m local_memory_mcp html
"$PY" -m local_memory_mcp curator --summary-only
```

语义 CLI 子命令：

```bash
"$PY" -m local_memory_mcp semantic-status
"$PY" -m local_memory_mcp semantic-search "多 agent 记忆检索" --limit 5 --score-threshold 0.35
"$PY" -m local_memory_mcp semantic-index --limit 5000        # dry-run
"$PY" -m local_memory_mcp semantic-index --limit 5000 --force # 重建 Qdrant 向量
```

## MCP 与前端控制台

推荐独立运行统一 HTTP 服务，让浏览器前端、REST API 和 MCP 客户端共用同一个端口：

```bash
"$PY" -m local_memory_mcp serve --host 127.0.0.1 --port 8318
```

同端口路径：

```text
http://127.0.0.1:8318/        前端控制台
http://127.0.0.1:8318/api/*   前端 REST API
http://127.0.0.1:8318/mcp     MCP endpoint
http://127.0.0.1:8318/health  健康检查
http://127.0.0.1:8318/metrics 指标
```

如需远程绑定，默认要求 Bearer token：

```bash
LOCAL_MEMORY_FRONTEND_TOKEN='change-me' "$PY" -m local_memory_mcp serve --host 0.0.0.0 --port 8318
```

纯 MCP 模式可用：

```bash
"$PY" -m local_memory_mcp serve --mcp-only --host 127.0.0.1 --port 8318
```

Hermes 作为普通 MCP 客户端时可使用：

```yaml
mcp_servers:
  local_memory:
    enabled: true
    type: http
    url: http://127.0.0.1:8318/mcp
```

Codex `~/.codex/config.toml`：

```toml
[mcp_servers.local_memory]
type = "http"
url = "http://127.0.0.1:8318/mcp"
```

Claude Code `~/.claude.json`（user scope，全局可用）：

```json
"mcpServers": {
  "local_memory": {
    "type": "http",
    "url": "http://127.0.0.1:8318/mcp"
  }
}
```

## Agent Session Hook 部署

Claude Code 会在 `SessionStart` 阶段更新 agent presence 并注册默认 capability，并在 `UserPromptSubmit` 阶段自动调用 `memory_context`；Codex 只保留 `SessionStart` presence/capability 与 `Stop` 写回 hook，读前记忆按 `AGENTS.md` 规则由模型显式调用 `memory_context`，避免把弱相关 hook 输出直接显示在对话里。Gemini 通过 `BeforeAgent` hook 注入 `memory_context`，并通过 `AfterAgent` + `SessionEnd` hooks 传入 `transcript_path` 写回；Hermes 通过 `pre_llm_call` shell hook 在模型调用前注入 `memory_context`；opencode 通过 plugin 在 `experimental.chat.system.transform` 阶段调用 `memory_context`。这些读前上下文会注入回答前上下文；Claude Code / Codex / Gemini / Hermes / opencode 会话结束时自动将对话摘要写回 lmmcp，由统一脚本处理：

```bash
# 部署 Claude/Codex/Hermes session hooks
bash scripts/setup-hooks.sh
```

或通过 `connect_agents.py`：

```bash
# 注册所有已检测 agent 的 MCP server 与 session hooks
python3 scripts/connect_agents.py --register-hooks
```

**读前注入脚本**：`scripts/hooks/lmmcp-context.sh`

**opencode 读前注入插件**：`scripts/hooks/opencode-lmmcp-plugin.js`

**启动注册脚本**：`scripts/hooks/session-start.sh`

**结束写回脚本**：`scripts/hooks/lmmcp-ingest.py`

| 参数 | 适用 | 读取来源 |
|---|---|---|
| `--agent claude` | Claude Code | `CLAUDE_SESSION_FILE` 或 `~/.claude/projects/**/*.jsonl` |
| `--agent codex` | Codex | `CODEX_SESSION_FILE` 或 `~/.codex/sessions/**/*.jsonl` |
| `--agent hermes` | Hermes | hook stdin `session_id` → `~/.hermes/state.db` |
| `--agent opencode` | opencode | hook stdin `session_id` 或最新 `~/.local/share/opencode/opencode.db` session |
| `--agent gemini` | Gemini | `AfterAgent` / `SessionEnd` hook stdin `transcript_path` 或 `GEMINI_SESSION_FILE` JSON/JSONL |

`session-start.sh` 使用短 timeout 调用 `agent_presence_update` 和 `agent_capability_register`，服务不可用时静默跳过；`lmmcp-context.sh` 使用短 timeout 调用 `memory_context`，并按调用方输出 Claude/Gemini 的 `additionalContext` 或 Hermes 的 `{"context": ...}`，服务不可用时静默跳过，不阻塞用户输入；Codex 不注册读前 context hook；`lmmcp-ingest.py` 后台调用 `memory_ingest`，失败不阻塞 agent 退出。

## 服务脚本

仓库提供可选脚本 `scripts/lmmcp`：

```bash
scripts/lmmcp start
scripts/lmmcp status
scripts/lmmcp logs 80
scripts/lmmcp stop
```

默认值可通过环境变量覆盖：

| 变量 | 默认值 |
|---|---|
| `LMMCP_DIR` | `$HOME/project/local-memory-mcp` |
| `LMMCP_PYTHON` | `$LMMCP_DIR/.venv/bin/python` |
| `LMMCP_HOST` | `127.0.0.1` |
| `LMMCP_PORT` | `8318` |
| `LOCAL_MEMORY_DB` | `$LMMCP_DIR/memory.sqlite3` |
| `LMMCP_PID_FILE` | `/tmp/lmmcp.pid` |
| `LMMCP_LOG_FILE` | `$LMMCP_DIR/lmmcp.log` |

## 安装与测试

需要 Python 3.11+。日常启动推荐直接使用 `bash start.sh`（见上方"快速开始"）。

手动安装：

```bash
MEM_ROOT="${LOCAL_MEMORY_ROOT:-$(pwd)}"
cd "$MEM_ROOT"
python3.11 -m venv .venv
.venv/bin/python -m pip install -e .[all]
```

默认安装不包含 sentence-transformers/PyTorch/CUDA。`.[embedding]` 和 `.[full]` 保留为兼容入口；如果后续自行安装本地模型 fallback，可配合这些命令管理环境：

```bash
.venv/bin/python -m pip install -e .[embedding]
# 或一次性安装所有可选能力：
.venv/bin/python -m pip install -e .[full]
```

运行测试：

```bash
.venv/bin/python -m pytest -q
```

PyPI 发布后可直接安装默认运行能力：

```bash
python3.11 -m pip install "local-memory-mcp[all]"
local-memory-mcp serve --host 127.0.0.1 --port 8318
```

如果需要保留完整可选安装入口：

```bash
python3.11 -m pip install "local-memory-mcp[full]"
```

## 一键部署

推荐在 Linux/macOS/WSL 上直接运行：

```bash
cd /path/to/local-memory-mcp
scripts/deploy.sh
```

它会完成：默认补齐系统依赖（apt/dnf/yum/brew 可用时）、创建/更新 `.venv`、安装 Python 依赖、生成/保留 `config.yaml`、初始化 SQLite、生成 dashboard、安装/启动 Ollama 并拉取 embedding 模型、安装并启动用户级 systemd 服务（Docker Qdrant、lmmcp HTTP MCP server、curator timer）、预拉取 Qdrant 镜像、运行健康检查和 pytest。

常用选项：

```bash
scripts/deploy.sh --force-config
scripts/deploy.sh --root /opt/local-memory-mcp --port 8318
scripts/deploy.sh --no-bootstrap-deps           # 不自动安装 host 依赖
scripts/deploy.sh --no-ollama                   # 不安装/启动 Ollama，依赖 fallback embedding
scripts/deploy.sh --no-systemd                  # 只初始化，不安装服务
scripts/deploy.sh --no-qdrant                   # 使用外部 Qdrant
scripts/deploy.sh --skip-tests                  # 部署时跳过 pytest
```

Docker Compose 快速启动会同时启动 lmmcp 和 Qdrant，并安装默认运行 extras：

```bash
docker compose up --build
```

部署后 endpoint：

```text
http://127.0.0.1:8318/mcp
```

## 部署复用

在新机器上运行初始化脚本：

```bash
cd /path/to/local-memory-mcp
scripts/init_local_memory.sh
```

脚本会创建 `.venv`、安装依赖、生成 `config.yaml`、初始化 SQLite、生成 dashboard，并打印 MCP stdio 命令。完整说明见 [`docs/deployment.md`](docs/deployment.md)。

## 语义层说明

当前语义层通过 `vector_store.py` 使用 Qdrant。配置位于 `config.yaml` 的 `qdrant` 和 `embedding` 段，也可由环境变量覆盖部分 embedding 设置。

默认 embedding provider 是 `auto`，不是固定绑定 Ollama。`auto` 会优先使用 `LOCAL_MEMORY_EMBEDDING_API_URL` / `embedding.api_url` 指向的 OpenAI-compatible embedding API；未配置外部 API 时尝试 Ollama `/api/embed`；再失败则使用 deterministic hashing fallback，保证 SQLite/FTS5/context pack 不被 embedding 服务阻断。默认 `.[all]` 不安装 `sentence-transformers`、PyTorch 或 CUDA 大依赖。

## 设计边界

当前 v0 解决”统一结构化存储 + MCP 工具 + context pack + 多 agent 共享记忆互通”问题。

不是完整自进化系统，不是 agent 调度框架，不是完整 SaaS memory platform。

已完成：P0 稳定化（injection guard、隐私脱敏、审计日志、degraded/fallback）、Context Pack v2（sections/records/warnings/trace）、Agent Mailbox（TTL、广播、cleanup）、Temporal Memory（valid_from/until、auto-decay）、Episodic Rollup、Hooks 统一化。

下一阶段计划按优先级推进：

1. **Phase 11 存储层强化**：`managed_conn` 嵌套事务修复（S-2）、WAL 自动检查点、context_quality_events 写入节流。
2. **Phase 12 提取与去重增强**：语义去重阈值按 type 差异化、中文提取 prompt 双语支持。
3. **Phase 13 Agent 协作增强**：handoff 超时与重试、`memory_context` v2 结构化响应完善、能力匹配自动路由。
4. **Phase 14 发布准备**：PyPI 正式发布、Docker Compose 一键启动、跨版本兼容性测试、多工作区支持。
