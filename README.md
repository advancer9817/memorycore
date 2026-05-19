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
- 低心智负担：agent 不直接关心 SQLite/Qdrant/Mem0 细节，只调用稳定 MCP tools。

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

代码默认使用项目目录内的 `memory.sqlite3`，可用 `LOCAL_MEMORY_DB` 覆盖数据库路径，`LOCAL_MEMORY_CONFIG` 覆盖配置文件路径。

## 当前状态

已完成：

1. **SQLite + FTS5 结构化记忆层**：支持 type/scope/tags/status/importance/confidence/source_agent 等字段，FTS5 全文检索。
2. **MCP server**：16 个工具，Hermes/Codex/Claude Code 均已配置并验证连接。
3. **Context Pack**：`memory_context` 按任务生成 compact 上下文包，支持 token budget 控制，按记忆类型分组。
4. **Curator**：重复标题、低反馈、stale、archive、矛盾候选、skill_candidate 推广候选检测；`run_curator.sh` 输出 JSON 报告并刷新 dashboard。
5. **Dashboard**：本地交互式 HTML 面板，Alpine.js，无构建步骤；支持搜索/类型/状态/排序过滤、决策时间线、反馈健康分布、curator 候选摘要、semantic index 状态。
6. **sqlite-vec 语义层**：本地 Ollama `nomic-embed-text`（768 维）embedding，`memory_semantic_*` MCP 工具；可用 `LOCAL_MEMORY_EMBEDDING_PROVIDER=hashing` 切回 hashing-384 fallback。
7. **Mem0 SDK 集成**：`memory_extract`（从对话抽取记忆）、`memory_smart_search`（FTS5 + sqlite-vec + Mem0 混合检索）、`memory_mem0_status`；LLM 使用 DeepSeek v4-flash，当前 Ollama 502 时 Mem0 自动降级，不影响主流程。
8. **HTTP MCP 服务**：可通过 `python -m local_memory_mcp serve --port 8318` 独立启动，客户端只需指向 `http://127.0.0.1:8318/mcp`。
9. **多客户端接入验证**：Hermes / Codex / Claude Code / Gemini / OpenCode 可作为普通 MCP 客户端接入；lmmcp 不依赖任一客户端配置仓库。

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
| `memory_consolidate` | curator 去重/stale 检测（dry-run） |
| `memory_curator_report` | curator 候选报告，可选标记 stale/archive |
| `memory_semantic_status` | 语义索引状态 |
| `memory_semantic_index` | 构建/更新 sqlite-vec 向量索引 |
| `memory_semantic_search` | 语义向量搜索 |
| `memory_extract` | 从对话抽取记忆（Mem0 LLM pipeline） |
| `memory_smart_search` | FTS5 + sqlite-vec + Mem0 混合搜索 |
| `memory_mem0_status` | Mem0 后端状态 |

## CLI

```bash
MEM_ROOT="${LOCAL_MEMORY_ROOT:-/home/advancer/project/local-memory-mcp}"
PY="$MEM_ROOT/.venv/bin/python"

"$PY" -m local_memory_mcp init
"$PY" -m local_memory_mcp search memory
"$PY" -m local_memory_mcp context "继续实现多 agent 记忆架构"
"$PY" -m local_memory_mcp html
"$PY" -m local_memory_mcp curator --summary-only
"$PY" -m local_memory_mcp semantic-index --force
"$PY" -m local_memory_mcp semantic-search "memory_context"
"$MEM_ROOT/run_curator.sh"
```

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

## 安装与测试

需要 Python 3.11+（`numpy==2.4.4` 不支持 Python 3.10）。

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

## 部署复用

在新机器上运行初始化脚本：

```bash
cd /path/to/local-memory-mcp
scripts/init_local_memory.sh
```

脚本会创建 `.venv`、安装依赖、生成 `config.yaml`、初始化 SQLite、生成 dashboard，并打印 MCP stdio 命令。完整说明见 [`docs/deployment.md`](docs/deployment.md)。

## 语义层说明

默认使用本地 Ollama `nomic-embed-text`（768 维）。Ollama 不可用时自动降级，不影响 FTS5 搜索和 context pack。

切换到 hashing fallback：

```bash
export LOCAL_MEMORY_EMBEDDING_PROVIDER=hashing
export LOCAL_MEMORY_EMBEDDING_DIM=384
```

## Mem0 说明

Mem0 SDK 已集成，LLM 使用 DeepSeek v4-flash，向量存储路径 `~/.agent-memory/mem0_qdrant`。

Mem0 不可用时（Ollama 502、key 缺失等）自动降级，`memory_smart_search` 仍返回 FTS5 + sqlite-vec 结果，`memory_extract` 报错但不影响主流程。

## 设计边界

当前 v0 解决"统一结构化存储 + MCP 工具 + context pack + 三 agent 共享记忆互通"问题。

不是完整自进化系统，不是 agent 调度框架，不是完整 SaaS memory platform。

下一阶段计划：

1. **Agent Mailbox MVP**：agent_messages / agent_presence 表，`agent_message_send/inbox/reply/mark_read`、`agent_presence_update/list` MCP 工具，让 Hermes/Codex/Claude 从"共享记忆"升级为"能基本协作通讯"。
2. **memory_context 集成协作状态**：context pack 附带当前 agent 未读消息摘要、相关 thread、task 阻塞项。
3. **Backend Router / MemoryRouter**：把 SQLite、sqlite-vec、Mem0 统一进 adapter 层，不让 `local_memory_mcp.py` 继续膨胀。
4. **Context Pack v2**：FTS5 + semantic + Mem0 混合检索，去重，可信度排序，feedback 加权，stale/contradicted 默认过滤。
5. **Curator automation**：cron 自动巡检，skill_candidate 推广，成长日记，现实反馈闭环。
