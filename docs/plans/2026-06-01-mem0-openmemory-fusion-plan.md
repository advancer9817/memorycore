# Mem0/OpenMemory 融合方案 — 事实切割、实体召回与 UI 迁移

日期：2026-06-01

## 目标

本方案解决 lmmcp 当前记忆质量的系统级问题：长记忆块中包含的局部事实没有被拆成可独立召回、独立向量化、独立排序的原子事实，导致用户输入 `local_memory`、`lmmcp`、`memory.sqlite3`、`8318` 这类提示时，本应命中的路径、服务、存储位置、Qdrant 状态等事实可能被长文本整体语义稀释。

同时引入 OpenMemory UI 的产品体验，但保持 lmmcp 的架构边界：SQLite 是事实源，Qdrant 是可重建索引，MCP/REST 是正式接口。

## 已确认的问题

1. `memory_add` 当前主要按整条 `title + content` 写入 SQLite/FTS5，并同步整条文本到 Qdrant。对手动录入的长文档、迭代书、状态汇总，它没有自动生成子事实。
2. `memory_ingest` 已经有 LLM fact extraction，但它面向对话 transcript，写出的多为 `episodic_memory/candidate`；它不会回扫已有长记忆，也不会把长 parent memory 拆成可追溯的 child facts。
3. 现有 `memory_links` 已支持 `part_of`、`supports`，但没有系统化用于 parent/child memory。
4. Qdrant 当前主要索引 memory 级文本。长文本内的局部事实，比如源码路径、端口、数据库路径、服务名、别名，可能被整段 embedding 稀释。
5. `memory_context` 虽然已有 FTS + vector 双路召回和弱相关过滤，但缺少实体/别名层，`local_memory`、`local-memory-mcp`、`lmmcp` 这类同义查询仍依赖文本碰巧命中。

## Mem0 后端可借鉴点

参考源：

- `mem0/memory/main.py`: https://github.com/mem0ai/mem0/blob/main/mem0/memory/main.py
- `mem0/configs/prompts.py`: https://github.com/mem0ai/mem0/blob/main/mem0/configs/prompts.py
- OpenMemory UI package: https://github.com/mem0ai/mem0/blob/main/openmemory/ui/package.json
- License: https://github.com/mem0ai/mem0/blob/main/LICENSE

关键实现点：

1. **`infer=True` 默认抽取事实**：Mem0 的 add 入口默认由 LLM 从消息中抽取结构化 memories；`infer=False` 才偏原样写入。
2. **ADD-only extraction**：新版 prompt 明确只做 ADD，要求输出自包含、上下文丰富、15-80 words 左右的 memory，避免让 LLM 同时承担更新/删除决策。
3. **不要过度原子化**：Mem0 不是机械 chunk；它要求每条 memory 可以独立理解，同时保留具体名词、路径、日期、数量和上下文。
4. **batch embedding + hash 去重**：抽取出多条 memories 后批量 embedding，写入前用 hash 去重，避免同一事实重复写。
5. **entity linking**：Mem0 会为 memory 抽实体，写入独立 entity collection，并在搜索时用实体匹配给相关 memory 加分。
6. **hybrid retrieval**：搜索时融合 semantic vector、keyword/BM25、entity boost，而不是只靠向量相似度。
7. **history/metadata**：Mem0 在 payload 中保存 hash、时间、元数据，方便审计和更新。

不应照搬的点：

1. 不把 Mem0 SDK 作为 lmmcp 主存储。lmmcp 已有 SQLite/FTS5、状态机、audit、feedback、curator、rollup、multi-agent hooks 和 MCP 工具面。
2. 不直接让 OpenMemory API 接管读写。OpenMemory UI 可以 fork，API 应适配到 lmmcp 的事实源。
3. 不把 Qdrant 当事实源。向量索引必须可从 SQLite 重建。

## 目标架构

### 写入路径

1. 原始输入写成 parent memory，保留完整文本和现有 type/status/scope/project_path/tags。
2. 如果内容达到 atomization 条件，调用 atomizer 生成 child facts。
3. child facts 写入 `memories`，`metadata_json.kind = "atomic_fact"`。
4. 写入 parent/child links：
   - `child -> parent` 使用 `part_of`
   - `parent -> child` 使用 `supports`
5. child facts 与 parent 都进入 SQLite/FTS5；active child facts 单独同步到 Qdrant。
6. entity extractor 从 parent/child 中提取实体和别名，写入 `memory_entities`。

### 召回路径

1. `memory_context` 收到 query 后生成候选：
   - FTS5/keyword
   - Qdrant semantic
   - entity/alias lookup
2. 融合排序：
   - semantic score
   - lexical score
   - entity boost
   - project_path/scope match
   - confidence/importance/effectiveness/feedback
   - freshness/status
3. 默认优先注入 child facts。
4. 多个 child 来自同一个 parent 时进行分组压缩，最多展示最相关的 1-3 条。
5. parent 默认只展示 title/id 和“可展开”提示；只有 `include_parent=true` 或 debug/recall 模式才注入 parent 摘要。

## 数据设计

优先复用现有 schema，避免大规模迁移。

### `memories.metadata_json`

child fact 示例：

```json
{
  "kind": "atomic_fact",
  "parent_id": "<uuid>",
  "fact_hash": "sha256(parent_id + normalized_fact)",
  "source_span": {"start": 0, "end": 240},
  "atomizer_version": "mem0-inspired-v1",
  "source_type": "parent_memory"
}
```

parent memory 示例：

```json
{
  "kind": "parent_memory",
  "atomized_at": "2026-06-01T...",
  "atomizer_version": "mem0-inspired-v1",
  "child_count": 8
}
```

### `memory_entities`

新增表：

```sql
CREATE TABLE IF NOT EXISTS memory_entities (
  id TEXT PRIMARY KEY,
  memory_id TEXT NOT NULL,
  entity TEXT NOT NULL,
  normalized_entity TEXT NOT NULL,
  aliases_json TEXT NOT NULL DEFAULT '[]',
  entity_type TEXT NOT NULL DEFAULT 'concept',
  weight REAL NOT NULL DEFAULT 1.0,
  created_at TEXT NOT NULL,
  FOREIGN KEY(memory_id) REFERENCES memories(id) ON DELETE CASCADE
);
```

索引：

```sql
CREATE INDEX IF NOT EXISTS idx_memory_entities_memory ON memory_entities(memory_id);
CREATE INDEX IF NOT EXISTS idx_memory_entities_norm ON memory_entities(normalized_entity);
CREATE INDEX IF NOT EXISTS idx_memory_entities_type ON memory_entities(entity_type);
```

## 新增/调整接口

### MCP tools

1. `memory_atomize_report(record_id="", dry_run=true, limit=100, min_chars=600)`
   - dry-run 默认。
   - 可指定单条 parent，也可批量回扫长 memory。
   - 返回 planned child facts、links、duplicate skipped、vector sync plan。

2. `memory_entity_search(query, limit=20)`
   - 根据 entity/alias 找 memory。
   - 返回 entity match、linked memory ids、boost explain。

3. `memory_vector_audit(dry_run=true)`
   - 检查 SQLite active memories 与 Qdrant points 的一致性。
   - 报告 missing vectors、orphan vectors、status mismatch、dimension mismatch。

### 现有 tools

1. `memory_add`
   - 新增 `atomize: "auto" | true | false = "auto"`。
   - 默认只对长文本或结构化内容 atomize。

2. `memory_context`
   - 新增 `retrieval_mode: "strict" | "balanced" | "recall" = "strict"`。
   - 新增 `prefer_atomic: bool = true`。
   - 新增 `include_parent: bool = false`。

3. `memory_rebuild_vectors`
   - 支持重建 child facts 与 entity payload。

## OpenMemory UI 融合

### 方式

将 OpenMemory `openmemory/ui` fork 到本仓库 `ui/`，而不是把 OpenMemory 后端作为主服务。UI 走 lmmcp 的 REST compatibility layer。

### 许可证

Mem0/OpenMemory 使用 Apache-2.0。fork UI 时必须：

1. 保留上游 `LICENSE`。
2. 在 `ui/NOTICE.md` 记录上游仓库、原始 license、fork 日期、基线 commit。
3. 在本仓库 README 说明 UI 来源和改动边界。

### REST compatibility layer

新增或扩展 lmmcp REST API：

- `GET /api/v1/memories`
- `GET /api/v1/memories/filter`
- `POST /api/v1/memories`
- `PATCH /api/v1/memories/{id}`
- `DELETE /api/v1/memories/{id}` 或状态归档
- `GET /api/v1/stats`
- `GET /api/v1/entities`
- `GET /api/v1/context-traces`

这些 API 只读写 lmmcp SQLite/Qdrant，不调用 Mem0 SDK。

## 实施分期

### Phase 1: 代码审计与设计落档

- 记录 Mem0 后端可借鉴实现点。
- 保存本方案源档案。
- TODO 分条入库。
- 不写功能代码，避免把大范围功能和规划提交混在一起。

### Phase 2: Atomization v1

- 新增 `atomization.py`。
- 实现 parent 保留、child facts 生成、fact hash 幂等、links 写入。
- 对 `memory_add` 和 backfill 工具接入 atomization。
- child facts 独立同步 Qdrant。

### Phase 3: Entity/Alias

- 新增 `memory_entities` 表和 CRUD。
- 实体提取先用规则 + LLM 可选增强。
- 支持别名归一，例如 `local_memory`、`local-memory-mcp`、`lmmcp`。

### Phase 4: Hybrid Retrieval

- `memory_context` 融合 semantic、lexical、entity boost。
- 默认优先 child facts。
- 增加 trace，解释每条结果的来源和分数。

### Phase 5: OpenMemory UI Fork

- vendor `openmemory/ui` 到 `ui/`。
- 添加 license/notice。
- 实现 lmmcp REST compatibility layer。
- 用 Playwright 做 smoke test。

### Phase 6: Backfill 与质量评测

- 对历史长 memories dry-run atomization。
- 针对高价值 parent 执行 apply。
- 建立 fixture 覆盖长记忆局部事实、别名查询、跨项目隔离、弱相关过滤。

## 验证计划

后端：

```bash
pytest tests/test_context_relevance.py tests/test_vector_sync.py tests/test_frontend.py tests/test_deployment.py -q
pytest tests/test_atomization.py tests/test_entity_retrieval.py tests/test_openmemory_ui_api.py -q
```

UI：

```bash
cd ui
pnpm install
pnpm build
pnpm exec playwright test
```

手工验收：

1. 查询 `local_memory` 能召回 lmmcp 源码路径、MCP endpoint、SQLite DB、Qdrant storage 等 child facts。
2. 查询长记忆里的局部事实时，child fact 排在 parent 前。
3. 多个 child 来自同一 parent 时 context 不膨胀。
4. parent 可追溯，child 可独立引用。
5. archived/stale/contradicted parent 不会产生 active child 污染。

## 回滚

1. Atomization 功能可通过 `atomize=false` 或配置开关禁用。
2. child facts 使用 `metadata_json.kind="atomic_fact"`，可批量归档或删除，不影响 parent 原文。
3. Qdrant 可通过 `memory_rebuild_vectors` 从 SQLite 重建。
4. OpenMemory UI fork 与 REST compatibility layer 可独立回滚，现有 lightweight frontend 保留。

## 决策

1. lmmcp 继续是事实源。
2. Mem0 SDK 不作为运行时强依赖。
3. 借鉴 Mem0 后端代码结构和算法，不照搬其数据所有权。
4. OpenMemory UI fork 到本仓库，改 API client 对接 lmmcp。
5. 默认优化目标是少注入优先，提高语义相关性和可解释性。
