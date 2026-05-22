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
MEM_ROOT="${LOCAL_MEMORY_ROOT:-/home/advancer/project/local-memory-mcp}"
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

## 当前状态

已验证：

1. **SQLite + FTS5 结构化记忆层**：支持 type/scope/tags/status/importance/confidence/source_agent/effectiveness 等字段，FTS5 全文检索。
2. **HTTP MCP server**：18 个工具，Hermes 可通过 `http://127.0.0.1:8318/mcp` 作为普通 HTTP MCP 客户端连接。
3. **Context Pack**：`memory_context` 按任务生成 compact 上下文包，支持 token budget 控制，按记忆类型分组，集成 active contradicts/supersedes warning，并将检索记忆标记为 untrusted data；命中注入特征的记忆会从普通 context body 过滤到 warnings。
4. **Curator**：重复标题、低反馈、stale、archive、矛盾候选、skill_candidate 推广候选检测；默认 dry-run。
5. **Feedback / effectiveness**：`memory_feedback` 记录反馈事件并更新 feedback_score、injected_count、ineffective_count、effectiveness_score。
6. **Memory links / warnings**：支持 `related_to`、`supersedes`、`contradicts`、`supports`、`part_of`；`memory_warnings` 可根据 active links 产生冲突/替代提示。
7. **Qdrant 语义检索**：`memory_vector_search` / `memory_vector_status` 通过 `vector_store.py` 使用 Qdrant + Ollama embedding；Ollama embedding 不可用时使用 hashing fallback。
8. **Dashboard**：本地交互式 HTML 面板，Alpine.js，无构建步骤；展示记录、时间线、反馈健康和 curator 候选摘要。
9. **多客户端接入方向**：Hermes / Codex / Claude Code / Gemini / OpenCode 都应作为普通 MCP 客户端接入；lmmcp 核心不依赖任一客户端配置仓库或私有 transcript。

Optional / degraded：

- Qdrant、Ollama、外部 extraction LLM 都是可选增强；不可用时核心 SQLite/FTS5/context pack 仍应可用。
- `memory_ingest` 会调用 extraction + dedup pipeline；外部模型或向量服务不可用时应视为降级能力，不影响基础 CRUD/search/context。

Removed / not current core：

- sqlite-vec CLI 语义命令已移除；CLI `semantic-*` 子命令仅返回提示，请使用 MCP `memory_vector_search` / `memory_vector_status`。
- Mem0 不是当前核心部署的一部分；不要从旧配置或旧文档重新引入 Mem0/OpenMemory 假设。

## MCP 工具列表

| 工具 | 用途 |
|---|---|
| `memory_add` | 写入结构化记忆 |
| `memory_search` | FTS5 关键词搜索 |
| `memory_context` | 按任务生成 context pack |
| `memory_get` | 读取单条记忆 |
| `memory_list_recent` | 最近更新记录 |
| `memory_update_status` | 更新记忆状态 |
| `memory_feedback` | 记录记忆有用性反馈 |
| `memory_timeline` | 决策/事件时间线 |
| `memory_consolidate` | curator 去重/stale 检测（report-only） |
| `memory_curator_report` | curator 候选报告，可选标记 stale/archive |
| `memory_ingest` | 从显式传入的对话消息抽取并去重写入 candidate |
| `memory_vector_search` | Qdrant 语义向量搜索 |
| `memory_vector_status` | Qdrant 向量存储状态 |
| `memory_link_add` | 创建/更新记忆之间的有向关系 |
| `memory_link_query` | 查询某条记忆的 incoming/outgoing links |
| `memory_warnings` | 根据 active links 返回冲突/替代 warning |
| `memory_update` | 更新已有记忆的 title/content/status/confidence/importance |
| `memory_audit_log` | 查询记忆写入、更新、状态变更的审计事件日志 |

## CLI

```bash
MEM_ROOT="${LOCAL_MEMORY_ROOT:-/home/advancer/project/local-memory-mcp}"
PY="$MEM_ROOT/.venv/bin/python"

"$PY" -m local_memory_mcp init
"$PY" -m local_memory_mcp add project_memory "标题" "内容"
"$PY" -m local_memory_mcp search memory
"$PY" -m local_memory_mcp context "继续实现多 agent 记忆架构"
"$PY" -m local_memory_mcp html
"$PY" -m local_memory_mcp curator --summary-only
```

`semantic-status` / `semantic-index` / `semantic-search` CLI 子命令保留为兼容提示；实际语义检索通过 MCP 工具 `memory_vector_search` / `memory_vector_status`。

## MCP 接入配置

推荐独立运行 HTTP MCP 服务，然后让各客户端只指向同一个 URL：

```bash
"$PY" -m local_memory_mcp serve --port 8318
```

HTTP endpoint:

```text
http://127.0.0.1:8318/mcp
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

需要 Python 3.11+。

```bash
MEM_ROOT="${LOCAL_MEMORY_ROOT:-/home/advancer/project/local-memory-mcp}"
cd "$MEM_ROOT"
python3.11 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -r requirements.txt
```

运行测试：

```bash
.venv/bin/python -m pytest -q
```

`pytest.ini` 已配置 `pythonpath = .`。测试通过 `LOCAL_MEMORY_DB` 指向临时 SQLite，不读写生产 `memory.sqlite3`。

## 一键部署

推荐在 Linux/macOS/WSL 上直接运行：

```bash
cd /path/to/local-memory-mcp
scripts/deploy.sh
```

它会完成：创建/更新 `.venv`、安装 Python 依赖、生成/保留 `config.yaml`、初始化 SQLite、生成 dashboard、可选补齐系统依赖（`--bootstrap-deps`）、可选安装/启动 Ollama 并拉取 embedding 模型（`--with-ollama`）、安装并启动用户级 systemd 服务（Qdrant、lmmcp HTTP MCP server、curator timer）、预拉取 Qdrant 镜像、运行健康检查和 pytest。

常用选项：

```bash
scripts/deploy.sh --force-config
scripts/deploy.sh --root /opt/local-memory-mcp --port 8318
scripts/deploy.sh --bootstrap-deps --assume-yes  # apt/dnf/yum/brew 可用时补齐 host 依赖
scripts/deploy.sh --with-ollama                 # 确保 Ollama 可用并拉取 embedding 模型
scripts/deploy.sh --no-systemd                  # 只初始化，不安装服务
scripts/deploy.sh --no-qdrant                   # 使用外部 Qdrant
scripts/deploy.sh --skip-tests                  # 部署时跳过 pytest
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

默认 embedding provider 是 Ollama `nomic-embed-text`。Ollama 不可用时，`embed_text` 会使用 deterministic hashing fallback，保证语义相关能力可降级而不阻断基础 SQLite/FTS5 能力。

## 设计边界

当前 v0 解决“统一结构化存储 + MCP 工具 + context pack + 多 agent 共享记忆互通”问题。

不是完整自进化系统，不是 agent 调度框架，不是完整 SaaS memory platform。

下一阶段计划按优先级推进：

1. **P0 稳定化**：文档-工具-测试一致性、context injection guard（已实现基础版）、隐私脱敏、审计日志、degraded/fallback response contract。
2. **Context Pack v2**：在保留 legacy `context` 字段的同时增加 sections / records / warnings / trace。
3. **Graph / Warning 增强**：扩展 relation types，支持 blocked_by / causes / failure-pattern warnings。
4. **Agent Mailbox MVP**：在 P0/P1 防线完成后，再增加 agent_messages / agent_presence 与基础协作通讯工具。
