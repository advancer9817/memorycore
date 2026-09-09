# MemoryCore 核心架构与协议接口参考规范 (2026-09)

> 本文档系统梳理 MemoryCore (mcore) 最新的服务分层架构、MCP 专属表现层协议契约、Agent Hook 接入规范与网络穿透方案，作为系统研发、多 Agent 接入与运维治理的权威技术准绳。

---

## 一、双端口物理隔离拓扑 (Dual-Port Architecture)

为解决 Web 管理控制台与 LLM Agent 上下文协议通道强耦合的问题，MemoryCore 在物理端口层面实施彻底的双向隔离：

```
                    ┌────────────────────────┐
                    │       LLM Agents       │ (Hermes, Claude Code, Codex, Gemini)
                    └───────────┬────────────┘
                                │ JSON-RPC (FastMCP over HTTP) / Native HTTP Hooks
                    ┌───────────▼────────────┐
                    │    后端 MCP 与 API     │
                    │   (端口: 8318, mcore)  │
                    │   FastMCP + REST API   │
                    └───────────┬────────────┘
                                │
   ┌────────────────────────────┼────────────────────────────┐
   │ 核心领域存储引擎 (Storage)       ▼                            │
   │   - SQLite + FTS5 全文索引 (memory.sqlite3)              │
   │   - Qdrant 向量检索服务 (:6333, agent_memory)            │
   │   - 实体别名图谱与主动上下文治理引擎                     │
   └────────────────────────────▲────────────────────────────┘
                                │
                    ┌───────────┴────────────┐
                    │    前端 Web 控制台     │
                    │ (端口: 18318, mcore-ui)│
                    │ Next.js 15 Standalone  │
                    └───────────▲────────────┘
                                │ HTTP (Web Browser)
                    ┌───────────┴────────────┐
                    │   工程师运维管理浏览器  │
                    └────────────────────────┘
```

### 端口职责划分
- **端口 8318 (`mcore.service`)**：
  - **`/mcp`**：FastMCP 协议入口，专为三端 Agent 工具调用服务。
  - **`/api/v1/*`**：后端核心 RESTful 接口与自动化运维调度端点。
  - **`/api/v1/hooks/*`**：Agent 原生会话钩子端点（如 `/api/v1/hooks/context`、`/api/v1/hooks/stop`）。
  - **`/health` & `/metrics`**：健康探测与 Prometheus 性能指标。
  - *注：8318 根路径 `/` 明确返回 404，已彻底剥离内嵌旧前端，杜绝协议干扰。*
- **端口 18318 (`mcore-ui.service`)**：
  - **`/`**：MemoryCore 现代化暗色极客 Web 仪表盘（Next.js 15.5 App Router Standalone）。
  - 承载 4 核心资产指标大卡、规则维护一键执行、LLM Curator 增量决策流呈现、知识血统对比（`DiffViewer`）等全量管理功能。

---

## 二、MCP 专用表现层与 Agent DTO 规范 (`mcp_views.py`)

### 1. 表现层隔离原理
底层 Storage 函数（如 `search_memory_records`、`get_record`、`add_memory_record`）产出的是包含 **27 个列的数据库完整实体（Database Row Entity）**（包括 `importance`、`injected_count`、`decay_policy`、`metadata` 等底层度量）。

Web UI（通过 `/api/v1/memories`）需要消费这 27 个字段进行状态审计和图标渲染。
然而，LLM Agent 绝不需要这些内部度量。`memorycore/mcp_views.py` 作为专用 DTO 拦截器，确保向 MCP 协议出口输出前完成瘦身转换：

### 2. 核心输出字段契约 (McpMemoryItem)
面向 Agent 的主动查询与检索工具（`memory_search`, `memory_get`, `memory_list_recent`, `memory_timeline`）统一过滤为 **6~7 个核心事实字段**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | `str` | 记忆唯一 UUID，供引用、追问或打分 |
| `title` | `str` | 记忆命题/标题纲要 |
| `content` | `str` | 事实详情（知识正文） |
| `type` | `str` | 知识分类（`decision`, `project_memory`, `environment_fact` 等） |
| `tags` | `list[str]` | 标签数组（如 `["project:mcore"]`） |
| `updated_at` | `str` | 极简日期 `YYYY-MM-DD`（消除冗余时区微秒，帮助模型理解时效） |
| `project_path` | `str` | 项目路径归属（仅在非空时出现） |

**彻底剥离的底层字段**（节省 70.9% Token）：
`importance`, `confidence`, `feedback_score`, `effectiveness_score`, `injected_count`, `ineffective_count`, `last_accessed_at`, `last_injected_at`, `status`, `decay_policy`, `source`, `source_agent`, `metadata`, `valid_from`, `valid_until`, `superseded_by`, `fact_lineage_root`, `related_ids`, `created_at`。

### 3. 操作类工具回执规范
彻底切断原样回弹整条 27 字段记录的陈旧逻辑：
- `memory_add`：返回 `{id, status, title, type, source_agent}`
- `memory_update`：返回 `{id, updated: true, title, type}`
- `memory_feedback`：返回 `{id, feedback_id, recorded: true, score}`

---

## 三、上下文包极简信封与质量闭环 (`memory_context`)

`memory_context` 是 AI 对话前自动召回的核心入口。为防范 Codex / Claude / Hermes 的 Token 预算被元数据吞噬，实施双模响应：

### 1. 默认 Slim 模式 (`verbose=False`)
```json
{
  "context": "# memory_context for hermes\ntask: ...\n## project_memory\n- [id] title: content...",
  "warnings": []
}
```
- 非 context 信封体积从 2,251 字符骤降至 31 字符（削减 **98.6%**）。
- 质量事件埋点（`_record_quality`）前置落库，保障质量分析看板不受 Slim 模式影响。

### 2. 诊断模式 (`verbose=True`)
仅在前端 Context Lab 或评测调试时显式启用，返回包含 `records`、`filtered_ids`、`telemetry` 的完整遥测字典（`trace` 与 `quality` 已深度合并去重）。

---

## 四、Agent 身份多级感知机制

在多 Agent 协同场景下，调用方无需在工具入参中手动传递 `source_agent`，服务端装饰器 `_threaded_tool` 自动按以下优先级提取身份并完成打标：
1. **HTTP 请求头**：`X-Agent-Id`（或 `X-Mcore-Agent`）。
2. **FastMCP 握手元数据**：`clientInfo.name`（如识别出 `Claude Code` ➔ `claude`，`OpenAI Codex` ➔ `codex`，`hermes` ➔ `hermes`）。
3. **显式入参保护**：若调用方显式传入了非缺省的 `source_agent`，严格保留其传参值。

---

## 五、三端 Agent 接入与网络穿透

### 1. 网络穿透与接入端点
- **本地回环直连**：`http://127.0.0.1:8318/mcp`
- **公网权威端点 (Cloudflare Tunnel)**：`https://mcore.099817.xyz/mcp`
- **备用 HTTPS 穿透**：`https://<REMOTE_HOST>:8443/mcp`（配备自签名 SAN 证书终结反代）

### 2. 客户端配置范例
- **Hermes** (`config.yaml`)：
  ```yaml
  mcp_servers:
    mcore:
      enabled: true
      type: http
      url: https://mcore.099817.xyz/mcp # 或本地 http://127.0.0.1:8318/mcp
  ```
- **Claude Code** (`~/.claude/settings.json`)：
  ```json
  "mcpServers": {
    "mcore": {
      "type": "http",
      "url": "https://mcore.099817.xyz/mcp"
    }
  }
  ```
- **Codex** (`~/.codex/config.toml`)：
  ```toml
  [mcp_servers.mcore]
  type = "http"
  url = "https://mcore.099817.xyz/mcp"
  ```

### 3. 会话钩子 (Session Hooks) 自动化
- **读前注入**：`scripts/hooks/mcore-context.sh`（支持原生 HTTP Hook 或 MCP 调用）。
- **写后提取**：`scripts/hooks/mcore-ingest.py`（对话结束异步派发 LLM 提取 + Qdrant 去重）。
- **启动注册**：`scripts/hooks/session-start.sh`。

---

## 六、未来重大架构重构路线 (pgvector)

根据规划（详见 `docs/mcore-pgvector-refactor-detailed-plan.md`），系统将实施向 **PostgreSQL 16 + pgvector** 的单一中枢重构：
- **废除组件**：彻底废除 SQLite 文件锁架构与 Docker Qdrant 独立服务。
- **技术突破**：在 PostgreSQL 内部利用 `pgvector` 扩展实现单 SQL 混合检索（向量余弦距离 `<=>` 与 `pg_trgm` 词法匹配加权融合）。
- **数据连续性**：提供一键迁移工具（`scripts/migrate_sqlite_to_pg.py`），无损转储 4,800+ 存量事实、血统与链接关系。
