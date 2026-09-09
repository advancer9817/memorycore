# MemoryCore

作者：advancer9817-crypto <advancer9817-crypto@users.noreply.github.com>

本地优先的智能记忆中枢。通过 MCP 为 AI 对话提供持久化长期记忆 — 对话前自动召回相关上下文，对话后自动提取关键经验，后台自动治理记忆质量。

## 定位

核心追求四件事：**记得准、记得牢、读得准、治得好**。

- **记得准**：对话结束时精准提取关键事实 — 决策、根因、修复方案、配置变更，结果导向而非过程记录。
- **记得牢**：SQLite + FTS5 + Qdrant 向量 + 实体索引多路存储，原子事实拆分，跨设备 git 同步。
- **读得准**：对话前 FTS5 + 向量 + 实体三路融合召回，交叉验证加成，不遗漏、不噪音。
- **治得好**：自动去重、归档过时、检测矛盾、建立图谱关联。自动化是默认，人工是例外。

技术特性：

- 统一入口：通过 MCP server 读写记忆，不维护孤岛。
- 上下文包装：按任务生成 compact context pack，控制 token budget，区分记忆类型。
- 自进化：curator 定期整理、降噪、归档、合并，高价值经验沉淀。
- 低心智负担：调用方不直接关心 SQLite/Qdrant 细节，只调用稳定 MCP tools。

## 路径

运行时根目录默认就是本项目 checkout；也可由环境变量控制：

```bash
MEM_ROOT="${LOCAL_MEMORY_ROOT:-$(pwd)}"
```

| 文件 | 路径 | 说明 |
|---|---|---|
| MCP server | `$MEM_ROOT/memorycore/` | FastMCP 协议与业务核心（端口 8318） |
| MCP 表现层 | `$MEM_ROOT/memorycore/mcp_views.py` | Agent 专属轻量 DTO 与表现层隔离 |
| 配置 | `$MEM_ROOT/config.yaml` | 记忆中枢、模型路由与检索策略配置 |
| Python venv | `$MEM_ROOT/.venv/bin/python` | 运行时虚拟环境（推荐 uv 驱动） |
| SQLite DB | `$MEM_ROOT/memory.sqlite3` | 结构化主存储（支持 FTS5 全文索引） |
| Web UI | `$MEM_ROOT/ui/` | 独立 Next.js 仪表盘服务（端口 18318） |
| MCP probe | `$MEM_ROOT/probe_mcp.py` | 端口与 MCP 协议连通性探针 |
| 运维脚本 | `$MEM_ROOT/scripts/mcore` | systemd 服务管控与启停 CLI |

代码默认使用项目目录内的 `memory.sqlite3`，可用 `LOCAL_MEMORY_DB` 覆盖数据库路径，`LOCAL_MEMORY_CONFIG` 覆盖配置文件路径。

## 快速开始

在任意支持 Python 3.11+ 的机器上，clone 仓库后一条命令完成全部初始化并启动服务：

```bash
git clone https://github.com/advancer9817-crypto/memorycore.git
cd memorycore
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
http://127.0.0.1:8318/mcp        FastMCP 服务端点（三端 Agent 核心接入通道）
http://127.0.0.1:8318/api/v1/*   核心 REST API、Hooks 与管理接口
http://127.0.0.1:8318/health     健康检查接口
http://127.0.0.1:18318/          MemoryCore 现代化 Web 仪表盘控制台 (Next.js)
```

> **注意**：按照架构隔离决策，8318 端口已彻底剥离内嵌旧前端，专注于高性能 MCP 与 REST API 通信；访问 `http://127.0.0.1:8318/` 会返回 404 并提示转向 18318。

## 多设备记忆同步

记忆通过 git 仓库在多台设备间同步。同步文件为 `memory-sync/memories.json`，只包含持久知识（memories / feedback_events / memory_links），不含设备私有的运行时状态。

### 自动模式（推荐）

`scripts/mcore` 服务脚本在 **启动前自动拉取**、**停止后自动推送**：

```bash
scripts/mcore start   # git pull → import → 启动服务
scripts/mcore stop    # 停止服务 → export → git commit → git push
```

设置 `MCORE_AUTO_SYNC=0` 可禁用自动同步（git 操作失败时也不会影响服务启停）。

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
.venv/bin/python -m memorycore export memory-sync/memories.json --memories-only

# 导入（newer 策略：按 updated_at 保留更新的一条）
.venv/bin/python -m memorycore import memory-sync/memories.json --conflict-policy newer --apply
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
| `MCORE_AUTO_SYNC` | `1` | 设为 `0` 禁用 mcore 自动同步 |
| `SYNC_FILE` | `memory-sync/memories.json` | 同步文件路径（相对仓库根） |
| `SYNC_REMOTE` | `origin` | git remote 名称 |
| `SYNC_DEVICE` | `hostname -s` | commit message 中的设备标识 |

## 已验证功能

1. **SQLite + FTS5 结构化记忆层**：支持 type/scope/tags/status/importance/confidence/source_agent/effectiveness 等字段，FTS5 全文检索。
2. **HTTP MCP server**：22 个工具，任意 MCP 客户端可通过 `http://127.0.0.1:8318/mcp` 或 Cloudflare 权威端点 `https://mcore.099817.xyz/mcp` 连接。
3. **Context Pack 极简响应 (Slim)**：`memory_context` 按任务生成紧凑上下文包；默认采用 **Slim 模式**（仅返回 `{"context": text, "warnings": warnings}`，削减 98.6% 信封体积），仅在 `verbose=True` 时提供诊断 telemetry；支持 token budget 控制，按记忆类型分组，集成 active contradicts/supersedes warning 并将检索记忆标记为 untrusted data。
4. **MCP 专用表现层解耦 (mcp_views)**：MCP 工具层与底层数据库实体和 HTTP REST 解耦。面向 Agent 的查询工具（`memory_search`, `memory_get` 等）返回精炼的 6~7 个核心事实字段（`id`, `title`, `content`, `type`, `tags`, `updated_at`, `project_path`），单次搜索体积削减 70.9%；写操作（`memory_add`, `memory_feedback`）返回轻量确认回执，彻底切断底层 27 字段全量回弹。
5. **Curator 智能治理**：重复标题、低反馈、stale、archive、矛盾候选、skill_candidate 推广候选检测；支持 LLM Curator 语义去重、矛盾发现与实时决策推入；默认 dry-run。
6. **Feedback / effectiveness**：`memory_feedback` 记录反馈事件并更新 feedback_score、injected_count、ineffective_count、effectiveness_score。
7. **Memory links / warnings**：支持 `related_to`、`supersedes`、`contradicts`、`supports`、`part_of`；`memory_warnings` 可根据 active links 产生冲突/替代提示。
8. **Qdrant 语义检索**：`memory_vector_search` / `memory_vector_status` 通过 `vector_store.py` 使用 Qdrant + 可配置 embedding API；`auto` provider 优先使用配置的 OpenAI-compatible API，未配置时尝试 Ollama API，最后使用 hashing fallback。
9. **MemoryCore Web 控制台 (Next.js)**：独立部署于 18318 端口的现代化暗色极客面板，提供 4 项核心资产指标大卡、一键安全维护、实时 LLM 治理流式决策、知识血统对比（`DiffViewer`）与配置管理。
10. **多客户端全自动感知接入**：Hermes / Codex / Claude Code / Gemini / opencode 都作为标准 MCP 客户端接入；服务端支持通过 HTTP Header `X-Agent-Id` 与 FastMCP `clientInfo` 自动识别来源并自动打标归属。

Optional / degraded：

- Qdrant、外部 embedding API、Ollama、外部 extraction LLM 都是可选增强；不可用时核心 SQLite/FTS5/context pack 仍可用。
- `memory_ingest` 会调用 extraction + dedup pipeline；外部模型或向量服务不可用时视为降级能力，不影响基础 CRUD/search/context。

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
| `memory_entity_search` | 按实体/别名索引搜索 active memories |
| `memory_ingest` | 从显式传入的对话消息抽取并去重写入 candidate |
| `memory_vector_search` | Qdrant 语义向量搜索 |
| `memory_vector_status` | Qdrant 向量存储状态 |
| `memory_link_add` | 创建/更新记忆之间的有向关系 |
| `memory_link_query` | 查询某条记忆 of incoming/outgoing links |
| `memory_supersede` | 将旧记忆标记为被新记忆替代并写入审计 |
| `memory_warnings` | 根据 active links 返回冲突/替代 warning |
| `memory_update` | 更新已有记忆的 title/content/status/confidence/importance |
| `memory_audit_log` | 查询记忆写入、更新、状态变更的审计事件日志 |
| `memory_export` | 导出 schema-versioned JSON 记忆数据 |
| `memory_import` | 导入记忆数据，支持 dry-run 冲突报告 |
| `memory_backup` | 使用 SQLite backup API 创建数据库备份 |
| `memory_stats` | 返回按 type/status/agent 分组的记忆统计与聚合分数 |

## CLI

```bash
MEM_ROOT="${LOCAL_MEMORY_ROOT:-$(pwd)}"
PY="$MEM_ROOT/.venv/bin/python"

"$PY" -m memorycore init
"$PY" -m memorycore add project_memory "标题" "内容"
"$PY" -m memorycore search memory
"$PY" -m memorycore context "继续实现多 agent 记忆架构"
"$PY" -m memorycore html
"$PY" -m memorycore curator --summary-only
```

语义 CLI 子命令：

```bash
"$PY" -m memorycore semantic-status
"$PY" -m memorycore semantic-search "多 agent 记忆检索" --limit 5 --score-threshold 0.35
"$PY" -m memorycore semantic-index --limit 5000        # dry-run
"$PY" -m memorycore semantic-index --limit 5000 --force # 重建 Qdrant 向量
```

## MCP 与控制台

系统采用服务隔离架构：后端 FastMCP 与核心 REST API 运行于 **8318** 端口，独立 Web 仪表盘控制台运行于 **18318** 端口。

```bash
# 启动后端 MCP 服务（由 mcore.service 托管）
"$PY" -m memorycore serve --host 127.0.0.1 --port 8318
```

服务端点布局：

```text
http://127.0.0.1:8318/mcp        FastMCP 服务端点（Agent 工具调用通道）
http://127.0.0.1:8318/api/v1/*   核心 REST API 与 Agent 原生 Hooks
http://127.0.0.1:8318/health     健康检查接口
http://127.0.0.1:8318/metrics    Prometheus 监控指标
http://127.0.0.1:18318/          MemoryCore 现代化 Web 控制台 (Next.js Standalone)
```

如需公网安全访问，推荐使用已配置的 Cloudflare Tunnel 权威 TLS 穿透端点：
`https://mcore.099817.xyz/mcp`

### 客户端接入配置

所有主流 Agent 均支持直连本地或权威 HTTPS 隧道：

**Hermes** (`config.yaml`)：

```yaml
mcp_servers:
  mcore:
    enabled: true
    type: http
    url: http://127.0.0.1:8318/mcp # 或 https://mcore.099817.xyz/mcp
```

**Codex** (`~/.codex/config.toml`)：

```toml
[mcp_servers.mcore]
type = "http"
url = "http://127.0.0.1:8318/mcp" # 或 https://mcore.099817.xyz/mcp
```

**Claude Code** (`~/.claude/settings.json`)：

```json
"mcpServers": {
  "mcore": {
    "type": "http",
    "url": "http://127.0.0.1:8318/mcp"
  }
}
```

> **Agent 身份自动识别**：服务端会通过请求头 `X-Agent-Id` 及 MCP 会话的 `clientInfo.name` 自动感知调用方身份（如 `hermes`、`claude`、`codex`），调用 `memory_add` 或 `memory_context` 时无需人工硬编码 `source_agent`。

## Agent Session Hook 部署

Claude Code 会在 `SessionStart` 阶段更新 agent presence 并注册默认 capability，并在 `UserPromptSubmit` 阶段自动调用 `memory_context`；Codex 只保留 `SessionStart` presence/capability 与 `Stop` 写回 hook；Gemini 通过 `BeforeAgent` hook 注入 `memory_context`，并通过 `AfterAgent` + `SessionEnd` hooks 写回；Hermes 通过 `pre_llm_call` shell hook 在模型调用前注入 `memory_context`；opencode 通过 plugin 在 `experimental.chat.system.transform` 阶段调用 `memory_context`。

```bash
# 部署 Claude/Codex/Hermes session hooks
bash scripts/setup-hooks.sh

# 或注册所有已检测 agent 的 MCP server 与 session hooks
python3 scripts/connect_agents.py --register-hooks
```

**读前注入脚本**：`scripts/hooks/mcore-context.sh`  
**opencode 读前注入插件**：`scripts/hooks/opencode-mcore-plugin.js`  
**启动注册脚本**：`scripts/hooks/session-start.sh`  
**结束写回脚本**：`scripts/hooks/mcore-ingest.py`

| 参数 | 适用 | 读取来源 |
|---|---|---|
| `--agent claude` | Claude Code | `CLAUDE_SESSION_FILE` 或 `~/.claude/projects/**/*.jsonl` |
| `--agent codex` | Codex | `CODEX_SESSION_FILE` 或 `~/.codex/sessions/**/*.jsonl` |
| `--agent hermes` | Hermes | hook stdin `session_id` → `~/.hermes/state.db` |
| `--agent opencode` | opencode | hook stdin `session_id` 或最新 `~/.local/share/opencode/opencode.db` session |
| `--agent gemini` | Gemini | `AfterAgent` / `SessionEnd` hook stdin `transcript_path` 或 `GEMINI_SESSION_FILE` JSON/JSONL |

## 服务脚本

仓库提供可选脚本 `scripts/mcore`：

```bash
scripts/mcore start
scripts/mcore status
scripts/mcore logs 80
scripts/mcore stop
```

默认值可通过环境变量覆盖：

| 变量 | 默认值 |
|---|---|
| `MCORE_DIR` | `$HOME/project/memorycore` |
| `MCORE_PYTHON` | `$MCORE_DIR/.venv/bin/python` |
| `MCORE_HOST` | `127.0.0.1` |
| `MCORE_PORT` | `8318` |
| `LOCAL_MEMORY_DB` | `$MCORE_DIR/memory.sqlite3` |
| `MCORE_PID_FILE` | `/tmp/mcore.pid` |
| `MCORE_LOG_FILE` | `$MCORE_DIR/mcore.log` |

## 安装与测试

需要 Python 3.11+。日常启动推荐直接使用 `bash start.sh`。

手动安装：

```bash
MEM_ROOT="${LOCAL_MEMORY_ROOT:-$(pwd)}"
cd "$MEM_ROOT"
python3.11 -m venv .venv
.venv/bin/python -m pip install -e .[all]
```

运行测试：

```bash
.venv/bin/python -m pytest -q
```

### MemoryCore 控制台（Next.js 前端）

现代化暗色控制台源码位于 `ui/`，通过后端 `/api/v1/*` REST API 与原生 Hooks 交互，独立运行在 **18318** 端口。

#### 生产环境运行（推荐，Standalone 模式）

由用户级 systemd 单元 `mcore-ui.service` 托管，开机自启且崩溃自愈：

```bash
# 重启前端 UI 服务
systemctl --user restart mcore-ui.service

# 查看运行状态
systemctl --user status mcore-ui.service
```

手动构建与运行：

```bash
cd ui
pnpm install
pnpm build # 包含 postbuild 自动复制 static/public 到 standalone 目录
PORT=18318 HOSTNAME=0.0.0.0 node .next/standalone/server.js
```

#### 开发模式（热重载）

```bash
cd ui
pnpm dev:turbo # 启动 Turbopack 开发服务器（默认端口 18318）
```

该目录保留上游开源协议与 attribution，详见 `ui/LICENSE` 和 `ui/NOTICE.md`。

### PyPI 安装

```bash
pip install "memorycore[all]"
memorycore serve --host 127.0.0.1 --port 8318
# 或使用短别名
mcore serve --host 127.0.0.1 --port 8318
```

## 一键部署

推荐在 Linux/macOS/WSL 上直接运行：

```bash
cd /path/to/memorycore
scripts/deploy.sh
```

它会完成：默认补齐系统依赖（apt/dnf/yum/brew 可用时）、创建/更新 `.venv`、安装 Python 依赖、生成/保留 `config.yaml`、初始化 SQLite、生成 dashboard、安装/启动 Ollama 并拉取 embedding 模型、安装并启动用户级 systemd 服务（Docker Qdrant、memorycore HTTP MCP server、curator timer）、预拉取 Qdrant 镜像、运行健康检查和 pytest。

常用选项：

```bash
scripts/deploy.sh --force-config
scripts/deploy.sh --root /opt/memorycore --port 8318
scripts/deploy.sh --no-bootstrap-deps           # 不自动安装 host 依赖
scripts/deploy.sh --no-ollama                   # 不安装/启动 Ollama，依赖 fallback embedding
scripts/deploy.sh --no-systemd                  # 只初始化，不安装服务
scripts/deploy.sh --no-qdrant                   # 使用外部 Qdrant
scripts/deploy.sh --skip-tests                  # 部署时跳过 pytest
```

Docker Compose 快速启动（同时启动 memorycore 和 Qdrant）：

```bash
docker compose up --build
```

## 语义层说明

当前语义层通过 `vector_store.py` 使用 Qdrant。配置位于 `config.yaml` 的 `qdrant` 和 `embedding` 段，也可由环境变量覆盖部分 embedding 设置。

默认 embedding provider 是 `auto`：优先使用 `LOCAL_MEMORY_EMBEDDING_API_URL` / `embedding.api_url` 指向的 OpenAI-compatible embedding API；未配置外部 API 时尝试 Ollama `/api/embed`；再失败则使用 deterministic hashing fallback，保证 SQLite/FTS5/context pack 不被 embedding 服务阻断。默认 `.[all]` 不安装 `sentence-transformers`、PyTorch 或 CUDA 大依赖。

## 设计边界与演进路线

当前版本已完成：
- **MCP 专用表现层隔离**：`memorycore/mcp_views.py` 实现 Agent 轻量 DTO 隔离，彻底屏蔽底层 27 字段 SQLite 表结构与内部度量。
- **上下文极简 Slim 信封**：`memory_context` 默认剥离 98.6% 冗余元数据，仅输出 context 与安全告警。
- **主体上下文治理**：四级项目识别（Title 前缀反查、环境变量、git 路径、显式配置），消除主体脱落。
- **全 Agent 原生 Hook 与远程接入**：Claude Code、Hermes、Codex 统一支持 Cloudflare Tunnel 权威端点与 HTTP 原生 Hooks。
- **前端现代化控制台**：18318 端口大卡布局、实时 LLM 治理流式决策、知识血统对比（`DiffViewer`）与全量维护操作。

下一阶段核心演进路线：

1. **PostgreSQL + pgvector 单一中枢重构**（架构首要任务）：
   - 彻底废除 SQLite + Qdrant 双栈架构，统一重构为 PostgreSQL 16 + pgvector 单一存储中枢。
   - 消除跨库双写一致性隐患、SQLite 文件锁争用与多服务运维复杂度，实现单条 SQL 混合检索（向量余弦 `<=>` + `pg_trgm` 词法融合）。
   - 详见完整实施计划：[`docs/mcore-pgvector-refactor-detailed-plan.md`](docs/mcore-pgvector-refactor-detailed-plan.md)。
2. **多 Agent 知识图谱主动发现**：强化跨 Agent 关系推理（`related_to`, `supersedes`, `contradicts`），从被动拆分走向主动关联。
3. **自适应检索校准与质量闭环**：基于 `context_quality_events` 实时指标闭环微调检索加权公式，维持 Hit Rate > 0.90 高基准。
