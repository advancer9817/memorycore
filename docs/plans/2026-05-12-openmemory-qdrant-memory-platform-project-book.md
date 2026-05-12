# OpenMemory + Qdrant Multi-Agent Memory Platform 项目书

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** 把现有 `local-memory-mcp` 从“自研主存储”升级/收敛为一个基于市面成熟产品的多 Agent 共享记忆平台：OpenMemory/mem0 负责主记忆与画像，Qdrant 负责向量检索，薄 MCP Adapter 负责 Hermes/Codex/Claude Code 的统一接入、context pack、治理与演进。

**Architecture:** 采用“成熟产品做能力底座 + 本地薄适配层做工作流治理”的架构。第一阶段保留现有 SQLite 作为反馈、审计、curator 状态与迁移缓冲；长期将事实记忆、语义检索和画像交给 OpenMemory/mem0 + Qdrant，时间演化、矛盾处理、事实过期逐步引入 Graphiti/Zep 风格的 episode/temporal layer。

**Tech Stack:** OpenMemory/mem0, Qdrant, Ollama Embeddings 或 sentence-transformers, FastMCP, Python 3.11+, SQLite, Hermes Agent, Codex CLI, Claude Code.

---

## 1. 背景与问题

当前项目路径：`/home/advancer/.agent-memory/local-memory-mcp`

现状能力：

- SQLite + FTS5 结构化长期记忆。
- MCP 工具：`memory_add`, `memory_search`, `memory_context`, `memory_timeline`, `memory_feedback`, `memory_curator_report`, `memory_semantic_*`。
- Hermes / Codex / Claude Code 多 Agent 共享同一套记忆接口。
- `memory_context` 支持按任务生成 compact context pack。
- curator 支持 duplicate、low feedback、stale、archive、contradiction、skill_candidate 候选。
- dashboard.html 提供本地治理视图。
- sqlite-vec 已接入，但当前 embedding 是 `hashing-384` fallback，不是真语义 embedding。

主要问题：

- 自研主存储继续扩展会变成完整 memory platform，维护成本高。
- 语义能力目前偏弱，hashing fallback 只能验证 plumbing。
- 自动记忆抽取、用户画像、事实更新、矛盾消解不是本项目最该自研的部分。
- 市面成熟产品已经能承担主记忆、embedding、向量检索、画像等底层能力。

核心判断：

- 不找单体平替。
- 把项目从“主数据库 + 全能力自研”收敛成“Agent Memory Adapter / Operations Layer”。
- 让 OpenMemory/mem0、Qdrant、未来可选 Graphiti/Zep 承担重能力。

---

## 2. 目标与非目标

### 2.1 目标

1. 用 OpenMemory/mem0 承担主记忆系统。
2. 用 Qdrant 承担向量检索。
3. 用真实 embedding 替换 `hashing-384`。
4. 保留并强化 `memory_context`：面向 Hermes/Codex/Claude Code 生成任务相关 context pack。
5. 保留 `scope`, `project_path`, `token_budget`, `source_agent`, `feedback`, `importance` 等治理维度。
6. 让时间演化、矛盾处理、事实过期成为平台级能力，而不是一次性脚本。
7. 保留本地可观测性：dashboard / curator report / audit log。
8. 支持渐进迁移：旧 SQLite 数据可读、可导出、可回滚。

### 2.2 非目标

1. 不从零实现完整 vector database。
2. 不从零实现完整 temporal knowledge graph。
3. 不强制一次性迁移所有历史记忆。
4. 不追求跨所有 Agent 的完全相同行为；只保证共享接口和一致治理策略。
5. 不把官方 `@modelcontextprotocol/server-memory` 当主系统；它只作为兼容/低配 fallback。

---

## 3. 推荐总体架构

```text
Hermes Agent        Codex CLI         Claude Code
     |                 |                  |
     +-----------------+------------------+
                       |
                       v
        local-memory-mcp adapter / memory router
                       |
        +--------------+---------------+----------------+
        |                              |                |
        v                              v                v
OpenMemory / mem0               Qdrant Vector DB   SQLite Ops DB
主记忆、画像、事实抽取              语义检索            feedback、audit、curator
        |
        v
可选未来层：Graphiti / Zep temporal memory
事件、时间演化、矛盾、过期、事实生命周期
```

### 3.1 分层职责

#### Agent 接入层

使用者：Hermes、Codex、Claude Code。

职责：

- 通过 MCP 调用记忆能力。
- 不直接了解 OpenMemory/Qdrant/SQLite 的内部细节。
- 统一使用 `memory_context` 获取任务相关上下文。

#### Adapter / Router 层

路径：`/home/advancer/.agent-memory/local-memory-mcp`

职责：

- 对外暴露稳定 MCP 工具。
- 将 `memory_add/search/context` 路由到 OpenMemory/mem0 和 Qdrant。
- 将 `feedback/curator/audit` 写入 SQLite Ops DB。
- 生成 context pack。
- 做数据格式归一化：type/status/scope/project_path/source_agent。
- 做 token budget 压缩。

#### OpenMemory / mem0 层

职责：

- 主记忆系统。
- 用户画像。
- 自动抽取长期事实。
- 记忆更新、合并、检索。

#### Qdrant 层

职责：

- 向量存储。
- 语义召回。
- 支持 collection、payload filter、score threshold。

#### SQLite Ops DB 层

职责：

- 不是主记忆库。
- 保存治理元数据：feedback、audit、curator 状态、过期策略、人工标注、迁移映射。
- 作为回滚和调试缓冲层。

#### Temporal Layer 未来层

候选：Graphiti / Zep。

职责：

- episode 事件流。
- temporal fact validity。
- contradiction graph。
- stale / expired fact lifecycle。
- “用户偏好变了”这类时间演化问题。

---

## 4. 产品选型

### 4.1 OpenMemory / mem0

定位：主记忆和用户画像。

使用原因：

- 比官方 server-memory 更接近实际 agent memory 产品。
- 支持长期记忆抽取和检索。
- 已经在用户环境中出现 openmemory MCP 配置迹象。
- 能减少自研 schema、抽取、合并逻辑。

风险：

- 不是 MCP 官方插件。
- 数据模型与当前 `type/status/importance/feedback` 不完全一致。
- 需要 adapter 做字段映射和治理补充。

策略：

- 不直接让所有 Agent 随意调用 OpenMemory 原始工具。
- 通过 local adapter 统一入口。

### 4.2 Qdrant

定位：向量检索后端。

使用原因：

- 成熟、稳定、轻量可本地部署。
- payload filter 能很好支持 `scope`, `project_path`, `source_agent`, `type`, `status`。
- 比 sqlite-vec hashing fallback 更适合长期使用。

策略：

- 短期由 mem0/OpenMemory 使用 Qdrant。
- Adapter 只在必要时直接查询 Qdrant。

### 4.3 Embedding Provider

优先级：

1. 本地 Ollama embedding：适合隐私、本地化、部署简单。
2. sentence-transformers：适合 Python 本地稳定运行。
3. 云端 embedding：仅当本地效果不足时使用。

建议：

- 初期选一个本地 embedding，避免 WSL 网络延迟影响记忆检索。
- 记录 embedding model 名称和维度，避免后续混索引。

### 4.4 Graphiti / Zep

定位：未来 temporal memory layer。

使用时机：

- 当记忆规模变大。
- 当用户偏好、项目事实、环境事实频繁变化。
- 当矛盾处理不再适合用简单 curator heuristic。

短期不直接引入，先设计兼容字段。

### 4.5 官方 server-memory

定位：兼容层 / fallback / 简单 graph memory。

不作为主系统，原因：

- 能力偏简单。
- 缺少 context pack、feedback、curator、scope/project_path、过期治理。

---

## 5. 目标数据模型

### 5.1 Memory Record 标准视图

Adapter 内部统一使用以下逻辑模型：

```json
{
  "id": "string",
  "backend": "openmemory|sqlite|server-memory|graphiti",
  "backend_id": "string",
  "type": "user_profile|environment_fact|project_memory|decision|timeline_event|skill_candidate|raw_event",
  "scope": "global|project|agent|user",
  "project_path": "string",
  "title": "string",
  "content": "string",
  "tags": ["string"],
  "source": "manual|conversation|tool|import|curator",
  "source_agent": "hermes|codex|claude|system",
  "status": "active|stale|archived|contradicted|candidate|promoted|expired",
  "importance": 0.0,
  "confidence": 0.0,
  "feedback_score": 0.0,
  "valid_from": "ISO8601|null",
  "valid_until": "ISO8601|null",
  "supersedes": ["id"],
  "superseded_by": ["id"],
  "contradicts": ["id"],
  "created_at": "ISO8601",
  "updated_at": "ISO8601",
  "last_accessed_at": "ISO8601|null",
  "metadata": {}
}
```

### 5.2 类型规范

- `user_profile`: 用户偏好、身份、长期习惯。
- `environment_fact`: 本机环境、工具安装、网络问题。
- `project_memory`: 某项目稳定约定。
- `decision`: 明确决策。
- `timeline_event`: 发生过的重要事件。
- `skill_candidate`: 可提升为 Hermes skill 的流程知识。
- `raw_event`: 尚未整理的事件输入。

### 5.3 状态规范

- `active`: 当前有效。
- `candidate`: 候选，等待验证。
- `stale`: 可能过时，不默认注入。
- `archived`: 归档，不参与默认检索。
- `contradicted`: 被新事实冲突，不参与默认注入。
- `promoted`: 已提升为 skill 或更高层知识。
- `expired`: 到期事实，不参与默认注入。

---

## 6. 时间演化、矛盾处理、事实过期设计

### 6.1 时间演化

每条事实逐步支持：

- `valid_from`
- `valid_until`
- `observed_at`
- `source_event_id`
- `supersedes`
- `superseded_by`

示例：

```text
旧事实：User prefers deepseek-v4-flash as default model.
新事实：User switched active model to gpt-5.5 via OpenAI Codex.
处理：旧事实不一定删除，而是根据 scope 和时间标记为 stale 或 superseded。
```

### 6.2 矛盾处理

矛盾来源：

- 同标题不同内容。
- 同类型同 scope 互斥事实。
- 用户明确纠正。
- 环境检测结果覆盖旧记录。

处理策略：

1. 写入新事实。
2. 检索可能冲突的旧事实。
3. 生成 contradiction candidate。
4. 高置信用户纠正可自动将旧事实标记为 `contradicted`。
5. 低置信冲突进入 curator report，等待人工/agent 审核。

### 6.3 事实过期

不同类型设置不同默认 decay policy：

| Type | 默认策略 |
|---|---|
| user_profile | review, 不自动过期 |
| environment_fact | refresh_after_30d |
| project_memory | review_after_60d |
| decision | never_expire unless superseded |
| timeline_event | archive_after_180d |
| raw_event | archive_after_14d |
| skill_candidate | promote_or_archive_after_30d |

过期不是删除，而是改变检索默认行为：

- `active`: 可注入。
- `stale`: 仅在相关度很高或用户要求时注入。
- `expired/archived`: 默认不注入。

### 6.4 Temporal Layer 引入时机

MVP 不引入 Graphiti/Zep。先在 SQLite Ops DB 保留 temporal 字段。

当满足任一条件再引入：

- 记忆记录 > 1000。
- 每周矛盾候选 > 20。
- 用户频繁问“之前怎么变成现在这样的”。
- 需要跨 episode 推理事实演化。

---

## 7. MCP 工具目标接口

### 7.1 保留稳定工具

- `memory_add`
- `memory_search`
- `memory_context`
- `memory_get`
- `memory_list_recent`
- `memory_feedback`
- `memory_update_status`
- `memory_timeline`
- `memory_curator_report`

### 7.2 新增工具

#### `memory_ingest_event`

用途：写入一个事件，让 backend 决定是否提取长期记忆。

参数：

```json
{
  "event": "string",
  "source_agent": "hermes",
  "scope": "global",
  "project_path": "",
  "metadata": {}
}
```

#### `memory_resolve_contradiction`

用途：处理冲突候选。

参数：

```json
{
  "winner_id": "string",
  "loser_id": "string",
  "resolution": "supersede|contradict|merge|ignore",
  "note": "string"
}
```

#### `memory_refresh_facts`

用途：刷新可能过期的环境事实或项目事实。

参数：

```json
{
  "scope": "global",
  "project_path": "",
  "limit": 50,
  "dry_run": true
}
```

#### `memory_backend_status`

用途：检查 OpenMemory/Qdrant/SQLite/embedding 状态。

---

## 8. 实施路线图

## Phase 0: 基线冻结与备份

目标：确保现有系统可回滚。

任务：

1. 备份 `memory.sqlite3`。
2. 导出当前 README 和 dashboard 状态。
3. 确认 Hermes/Codex/Claude Code 当前 MCP 配置。
4. 写 migration notes。

验收：

- 旧 `local-memory-mcp` 可继续运行。
- 备份文件存在。
- 当前工具列表和配置已记录。

## Phase 1: Backend Abstraction

目标：把现有直接 SQLite 调用抽象为 backend 接口。

新增文件建议：

- `local_memory_mcp/backends/base.py`
- `local_memory_mcp/backends/sqlite_ops.py`
- `local_memory_mcp/backends/openmemory.py`
- `local_memory_mcp/models.py`
- `local_memory_mcp/context_pack.py`

核心接口：

```python
class MemoryBackend:
    def add(self, record: MemoryRecord) -> MemoryRecord: ...
    def search(self, query: MemoryQuery) -> list[MemoryRecord]: ...
    def get(self, id: str) -> MemoryRecord | None: ...
```

验收：

- 现有测试仍通过。
- MCP 工具行为不变。
- SQLite backend 仍可作为 fallback。

## Phase 2: OpenMemory Integration

目标：把主记忆 add/search 路由到 OpenMemory。

任务：

1. 增加 OpenMemory client。
2. 增加字段映射层。
3. `memory_add` 支持写 OpenMemory + SQLite audit。
4. `memory_search` 支持从 OpenMemory 读，再归一化为 MemoryRecord。
5. 增加 backend status。

验收：

- 添加一条测试记忆后，可通过 adapter 查回。
- OpenMemory 不可用时自动 fallback 到 SQLite 或返回明确错误。
- Codex/Hermes/Claude Code 不需要改调用方式。

## Phase 3: Qdrant + Real Embeddings

目标：替换 hashing-384，启用真实语义检索。

任务：

1. 选择 embedding provider。
2. 启动/配置 Qdrant。
3. 建立 collection schema。
4. payload 包含：type/status/scope/project_path/source_agent/tags。
5. `memory_semantic_search` 改为 Qdrant 查询。
6. 保留 sqlite-vec 作为 fallback 或移除。

验收：

- `memory_backend_status` 显示 Qdrant 和 embedding 可用。
- 中英文模糊检索结果优于 FTS。
- filter 能正确限制 project_path/scope。

## Phase 4: Context Pack v2

目标：让 `memory_context` 成为核心产品能力。

排序策略：

综合分数 = semantic_score + importance + confidence + feedback_score + recency - staleness_penalty。

输出结构：

```text
# memory_context for hermes

## User profile
- ...

## Environment facts
- ...

## Project memory
- ...

## Recent decisions
- ...

## Warnings / stale candidates
- ...
```

验收：

- token_budget 生效。
- stale/expired/contradicted 默认不进入主上下文。
- 高相关 stale 事实进入 warning section，而不是主事实区。

## Phase 5: Feedback + Curator v2

目标：治理不再只是报告，而是形成闭环。

任务：

1. feedback 写 SQLite Ops DB。
2. curator 综合 OpenMemory/Qdrant/SQLite 信息。
3. 增加 contradiction candidates。
4. 增加 stale/expired candidates。
5. dashboard 显示 backend 状态和候选。

验收：

- 低反馈事实会降低 context 注入概率。
- stale/expired 事实默认不注入。
- curator report 能解释每个候选原因。

## Phase 6: 时间演化 / 矛盾处理 / 事实过期

目标：正式引入 temporal semantics。

任务：

1. 给 MemoryRecord 增加 temporal 字段。
2. 新增 `memory_ingest_event`。
3. 新增 `memory_resolve_contradiction`。
4. 新增 `memory_refresh_facts`。
5. 对用户纠正进行高优先级处理。
6. 对环境事实增加 refresh policy。

验收：

- 新事实可 supersede 旧事实。
- 被 supersede/contradicted 的事实不再默认注入。
- curator 可以展示事实演化链。

## Phase 7: Graphiti/Zep 评估接入

目标：当启发式 temporal layer 不够用时，引入成熟 temporal graph 产品。

任务：

1. 评估 Graphiti。
2. 评估 Zep。
3. 写 PoC：导入 50 条 timeline_event。
4. 比较矛盾检测、时间查询、运维成本。
5. 决定是否引入。

验收：

- 有明确 yes/no 决策。
- 若引入，adapter 接口不变。

---

## 9. 迁移策略

### 9.1 数据迁移原则

- 先双写，再切读。
- 先低风险类型，再高风险类型。
- 不自动删除旧 SQLite 记录。
- 每条迁移记录保存 `legacy_id -> backend_id` 映射。

### 9.2 迁移顺序

1. `environment_fact`
2. `user_profile`
3. `project_memory`
4. `decision`
5. `timeline_event`
6. `skill_candidate`
7. `raw_event`

### 9.3 双写阶段

`memory_add` 行为：

```text
写 OpenMemory/mem0
写 SQLite audit/mapping
必要时写 Qdrant payload
返回统一 MemoryRecord
```

### 9.4 切读阶段

`memory_search` 行为：

```text
优先 OpenMemory/Qdrant
补充 SQLite Ops DB 状态
fallback SQLite legacy records
返回统一 MemoryRecord 列表
```

### 9.5 回滚

回滚方式：

- 设置 `MEMORY_BACKEND=sqlite`。
- Adapter 只读旧 SQLite。
- OpenMemory/Qdrant 数据不删除。

---

## 10. 配置设计

建议新增配置文件：

`/home/advancer/.agent-memory/local-memory-mcp/config.yaml`

示例：

```yaml
backend:
  primary: openmemory
  fallback: sqlite

openmemory:
  url: http://localhost:8765
  user_id: e-pengyang
  timeout: 30

qdrant:
  url: http://localhost:6333
  collection: agent_memory
  timeout: 30

embedding:
  provider: ollama
  model: nomic-embed-text
  dim: 768

context_pack:
  default_token_budget: 2000
  include_stale_warnings: true
  max_records_per_group: 6

temporal:
  enabled: true
  contradiction_detection: heuristic
  auto_supersede_user_corrections: true

ops_db:
  path: /home/advancer/.agent-memory/local-memory-mcp/memory_ops.sqlite3
```

---

## 11. 验收标准

### 11.1 功能验收

- Hermes、Codex、Claude Code 都能通过同一 MCP adapter 使用记忆。
- `memory_context` 能返回稳定、可读、预算内的 context pack。
- OpenMemory 不可用时有明确 fallback 或错误。
- Qdrant 可用时语义检索明显优于 FTS。
- stale/expired/contradicted 不默认注入。
- 用户纠正能使旧事实降权或失效。

### 11.2 质量验收

- 有单元测试覆盖字段映射、context pack、status filter、fallback。
- 有集成测试覆盖 OpenMemory mock、Qdrant mock。
- 有迁移脚本 dry-run。
- 所有破坏性操作默认 dry-run。
- README 更新。

### 11.3 运维验收

- `memory_backend_status` 一眼看出 OpenMemory/Qdrant/SQLite/embedding 是否可用。
- dashboard 能展示 backend 状态、curator 候选、过期事实。
- 所有配置路径使用绝对路径或 `$HOME` 推导，不写死 Windows 用户名。

---

## 12. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| OpenMemory 数据模型不匹配 | 字段丢失 | Adapter 统一模型 + SQLite Ops DB 保存治理字段 |
| Qdrant/embedding 运维变重 | 本地复杂度上升 | Docker/本地二选一，提供 fallback |
| 多 Agent 写入冲突 | 记忆污染 | source_agent、scope、feedback、curator 审计 |
| 自动矛盾处理误伤 | 删除/隐藏有效事实 | 不删除，只改状态；高风险进入 dry-run report |
| 事实过期策略过激 | 丢上下文 | stale 进入 warning，不直接消失 |
| WSL 网络问题 | API 慢/失败 | 优先本地 embedding/Qdrant/OpenMemory |

---

## 13. 具体任务清单

### Task 1: 创建项目配置文件

**Objective:** 新增 adapter 配置，不影响旧逻辑。

**Files:**
- Create: `/home/advancer/.agent-memory/local-memory-mcp/config.yaml`
- Create: `/home/advancer/.agent-memory/local-memory-mcp/tests/test_config.py`

**Verification:**

Run:

```bash
cd /home/advancer/.agent-memory/local-memory-mcp
.venv/bin/python -m pytest -q
```

Expected: PASS.

### Task 2: 拆出 MemoryRecord 模型

**Objective:** 建立统一记录模型，避免 backend 泄漏到 MCP 工具层。

**Files:**
- Create: `/home/advancer/.agent-memory/local-memory-mcp/local_memory_mcp_models.py`
- Modify: `/home/advancer/.agent-memory/local-memory-mcp/local_memory_mcp.py`
- Test: `/home/advancer/.agent-memory/local-memory-mcp/tests/test_models.py`

**Verification:** 模型能 round-trip JSON，兼容现有 row_to_dict 输出。

### Task 3: 增加 backend abstraction

**Objective:** 将 SQLite 操作包成 backend，为 OpenMemory 接入做准备。

**Files:**
- Create: `/home/advancer/.agent-memory/local-memory-mcp/backends/base.py`
- Create: `/home/advancer/.agent-memory/local-memory-mcp/backends/sqlite_backend.py`
- Test: `/home/advancer/.agent-memory/local-memory-mcp/tests/test_backend_sqlite.py`

**Verification:** 现有 MCP 工具行为不变。

### Task 4: 增加 OpenMemory client mock

**Objective:** 先用 mock 固定接口，不依赖真实服务。

**Files:**
- Create: `/home/advancer/.agent-memory/local-memory-mcp/backends/openmemory_backend.py`
- Test: `/home/advancer/.agent-memory/local-memory-mcp/tests/test_backend_openmemory.py`

**Verification:** mock add/search/get 全通过。

### Task 5: 实接 OpenMemory

**Objective:** 调通本地 OpenMemory endpoint。

**Files:**
- Modify: `/home/advancer/.agent-memory/local-memory-mcp/backends/openmemory_backend.py`
- Modify: `/home/advancer/.agent-memory/local-memory-mcp/README.md`

**Verification:** `memory_add` 写入后可通过 `memory_search` 查回。

### Task 6: 增加 Qdrant backend status

**Objective:** 先只检测 Qdrant，不切语义检索。

**Files:**
- Create: `/home/advancer/.agent-memory/local-memory-mcp/vector/qdrant_client.py`
- Test: `/home/advancer/.agent-memory/local-memory-mcp/tests/test_qdrant_status.py`

**Verification:** Qdrant 未启动时返回 degraded，不崩溃。

### Task 7: 替换 semantic_search

**Objective:** 用 Qdrant + real embedding 替换 hashing fallback。

**Files:**
- Modify: `/home/advancer/.agent-memory/local-memory-mcp/local_memory_mcp.py`
- Create: `/home/advancer/.agent-memory/local-memory-mcp/embeddings/provider.py`
- Test: `/home/advancer/.agent-memory/local-memory-mcp/tests/test_semantic_qdrant.py`

**Verification:** 语义搜索支持 filter 和 fallback。

### Task 8: Context Pack v2

**Objective:** 统一多源检索结果，生成预算内上下文。

**Files:**
- Create: `/home/advancer/.agent-memory/local-memory-mcp/context_pack.py`
- Test: `/home/advancer/.agent-memory/local-memory-mcp/tests/test_context_pack_v2.py`

**Verification:** stale/expired/contradicted 默认不进入主 context。

### Task 9: Temporal fields

**Objective:** 增加时间演化字段，不改变旧调用。

**Files:**
- Modify: `/home/advancer/.agent-memory/local-memory-mcp/local_memory_mcp.py`
- Modify: `/home/advancer/.agent-memory/local-memory-mcp/local_memory_mcp_models.py`
- Test: `/home/advancer/.agent-memory/local-memory-mcp/tests/test_temporal_fields.py`

**Verification:** 旧记录字段缺失时有默认值。

### Task 10: Contradiction candidates

**Objective:** curator 能报告潜在矛盾。

**Files:**
- Modify: `/home/advancer/.agent-memory/local-memory-mcp/local_memory_mcp.py`
- Test: `/home/advancer/.agent-memory/local-memory-mcp/tests/test_contradictions.py`

**Verification:** 同 scope 同 type 冲突记录进入 report，不自动删除。

### Task 11: Fact expiration

**Objective:** 引入 decay policy 和 expired 状态。

**Files:**
- Modify: `/home/advancer/.agent-memory/local-memory-mcp/local_memory_mcp.py`
- Test: `/home/advancer/.agent-memory/local-memory-mcp/tests/test_fact_expiration.py`

**Verification:** expired 事实不默认注入，但可显式查询。

### Task 12: Dashboard 更新

**Objective:** dashboard 展示 backend、temporal、curator 状态。

**Files:**
- Modify: `/home/advancer/.agent-memory/local-memory-mcp/local_memory_mcp.py`
- Test: `/home/advancer/.agent-memory/local-memory-mcp/tests/test_html.py`

**Verification:** `html` 命令生成页面并包含 backend status。

---

## 14. 推荐里程碑

### Milestone 1: Adapter 化完成

范围：Phase 0-1。

产出：

- 配置文件。
- Backend abstraction。
- SQLite fallback 完整。

### Milestone 2: OpenMemory 主存储可用

范围：Phase 2。

产出：

- OpenMemory add/search。
- SQLite audit。
- MCP 工具调用不变。

### Milestone 3: 真语义检索可用

范围：Phase 3。

产出：

- Qdrant collection。
- embedding provider。
- semantic search v2。

### Milestone 4: Context Pack 成熟

范围：Phase 4-5。

产出：

- context pack v2。
- feedback 影响排序。
- curator report v2。

### Milestone 5: Temporal Memory MVP

范围：Phase 6。

产出：

- supersede/contradict/expire。
- 用户纠正闭环。
- 环境事实刷新机制。

### Milestone 6: Graphiti/Zep 决策

范围：Phase 7。

产出：

- 是否引入 temporal graph 的决策文档。

---

## 15. 最终建议

当前最佳路线不是废弃 `local-memory-mcp`，而是把它降级并升级为：

```text
Agent Memory Adapter + Governance Layer
```

主能力交给成熟产品：

- OpenMemory/mem0：记忆抽取、画像、主记忆。
- Qdrant：向量检索。
- Ollama/sentence-transformers：本地 embedding。
- Graphiti/Zep：未来 temporal graph，按需引入。

自己保留最有差异化、最贴合用户工作流的部分：

- `memory_context`
- 多 Agent 统一 MCP 入口
- `project_path/scope/token_budget`
- feedback / curator / dashboard
- 时间演化与过期策略的治理视图

这条路线能最大化复用成熟产品，同时保留你对 Hermes/Codex/Claude Code 多 Agent 工作流的控制权。
