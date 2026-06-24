# MemoryCore Audit Remediation Plan

Date: 2026-06-24
Last revised: 2026-06-24 (详化版 — 已用实测数据核实全部断言)

## Background

This plan follows a full project audit of MemoryCore, including backend capabilities,
governance behavior, desktop frontend UX, route coverage, component redundancy, and
whether the project currently reaches its intended goal.

MemoryCore's intended product shape is a multi-agent memory and governance control
plane:

- Unified MCP memory bus for Hermes, Codex, Claude Code, Gemini, opencode, and other agents.
- Stable context packs with low cognitive overhead for agents.
- Shared memory storage with SQLite/FTS5, Qdrant semantic search, links, audit, feedback, and entities.
- Curator and governance loops that reduce noise, archive stale information, detect contradictions,
  and keep manual review rare.
- A desktop operations console for memory health, review, graph exploration, app/source visibility,
  and configuration.

The audit conclusion: the backend feature surface is broad and mostly aligned with the control-plane
goal, but MemoryCore has not fully reached the "self-governing, low-burden memory system" target yet.
The main blockers are hard backend bugs, an oversized governance review queue, frontend information
architecture drift, unused UI remnants, and inconsistent app/source-agent mapping.

## Audit Verification (2026-06-24)

以下断言已全部用实测代码与运行数据核实，非推断：

### 已确认属实的 P0 缺陷

**1. temporal_governance.py 的 VectorStore 构造 bug（确凿，且为上一轮回归引入）**

- 位置：`memorycore/storage/temporal_governance.py:54` — `vs = VectorStore(cfg)`
- `VectorStore.__init__`（`vector_store.py:362`）要求 `VectorStoreConfig` 对象，传入 raw config dict 会失败
- 实测日志证据：`vector_store: init failed: 'dict' object has no attribute 'url'`
- 后果：向量相似度路径静默失败 → auto-supersession 退化为词法相似度（SequenceMatcher+Jaccard）
- 引入来源：2026-06-24 上一轮"auto-supersession 改用向量相似度"改动遗留
- 正确修复路径：`vector_store.py` 已提供 `get_vector_store(config)` 和 `vector_store_config_from_dict(cfg)`，应直接复用

**2. curator_llm.py 的 governance_ledger 表名错误（确凿，影响审计回滚完整性）**

- 位置：`memorycore/storage/curator_llm.py:1510` — `SELECT request_json FROM governance_ledger WHERE id = ?`
- 实际表名：`governance_mutation_log`（`db.py:324` 定义，`mutation_executor.py` 全程使用）
- 调用链：`_request_from_result()` 在 `curator_llm.py:1484` 被调用，用于回滚/审计时还原原始 LLM 请求
- 后果：所有 LLM curator mutation **无法正确回滚到原始请求上下文** → 审计完整性缺口
- 严重度：HIGH（不只是普通 P0，是审计回滚能力失效）
- 测试证据：`tests/test_curator_apply.py` 2 个失败，`sqlite3.OperationalError: no such table: governance_ledger`

### 量化基线（2026-06-24 实测）

**测试基线：**
```
4 failed, 484 passed, 3 skipped
- FAILED test_curator_apply.py::test_apply_llm_curator_logs_duplicate_merge_audit
- FAILED test_curator_apply.py::test_apply_llm_curator_archives_duplicate_atomic_facts
- FAILED test_temporal.py::test_context_pack_recency_soft_boost_prefers_newer_equally_relevant_memory
- FAILED test_temporal.py::test_context_pack_recency_weight_is_configurable
```

**治理队列现状（governance_decisions 共 4926 条）：**

| review_status | decision_type | 数量 |
|---|---|---|
| needs_review | importance_reassessment | 883 |
| needs_review | semantic_duplicate | 533 |
| needs_review | split_candidate | 183 |
| needs_review | contradiction | 160 |
| applied | importance_reassessment | 2263 |
| applied | semantic_duplicate | 755 |
| applied | contradiction | 98 |
| applied | split_candidate | 38 |
| applied | supersession | 5 |
| rejected | contradiction | 5 |
| rejected | importance_reassessment | 2 |
| rolled_back | importance_reassessment | 1 |

- **needs_review 共 1759 条**（占 35.7%）— "队列过大"属实且可量化
- 瓶颈在 importance_reassessment（883）和 semantic_duplicate（533），合计占 needs_review 的 80%
- 4 个测试失败中 2 个直接由 governance_ledger bug 导致

**记忆库现状（memories 共 3188 条）：**
- archived 2515 (78.9%) / active 332 (10.4%) / stale 268 (8.4%) / candidate 50 / contradicted 23

### 已确认属实的前端问题

**3. Apps/source-agent 过滤丢弃未知 agent（确凿）**
- 位置：`memorycore/frontend.py:846` — `if agent_raw not in _KNOWN_AGENTS: continue`
- `_KNOWN_AGENTS`（`frontend.py:804`）为硬编码白名单，未知 source_agent 被静默排除出 Apps 列表
- 但 app detail（`frontend.py:661`）和 app memory 路由仍能直接查询原始 source_agent → 路由不一致

**4. 前端冗余组件（部分过时，需修正）**
- 文档原断言"未接入路由"**不准确**
- 实测：`ui/app/governance/page.tsx:27` **实际在用** `useGovernanceCockpit`
- 真实问题是 Dashboard 与 `/governance` 存在两套 governance 组件路径，职责重叠而非废弃
- `ui/components/dashboard/intelligence/` 下部分组件（CurationActivityPanel/HealthMetricsPanel/SourceBreakdown）是 Dashboard 活跃组件，非全部废弃

## Current Capability Map

MemoryCore currently provides these major functions:

1. Memory storage: SQLite records, FTS5 search, memory links, feedback, audit events, entity index,
   governance tables, agent tables, and vector sync queue.
2. Retrieval and context: `memory_context` combines FTS, Qdrant, entity recall, scope/project filters,
   token budgeting, warning generation, and injection-risk handling.
3. Semantic layer: Qdrant vector search, vector status, vector audit, vector rebuild, Ollama/API/hash fallback.
4. Ingestion and dedup: `memory_ingest`, extraction, vector dedup, candidate-first writes, supersession metadata.
5. Curation: rule curator, LLM curator, atomization, rollup, stale/archive/decay/revival heuristics.
6. Governance: persisted governance decisions, policy gate, mutation executor, audit trail, batch apply,
   reject, rollback, and governance metrics.
7. Agent collaboration: presence, capability registry, handoff messages, inbox, and hooks for multiple clients.
8. Frontend: Dashboard, Memories, Apps, Graph, Governance, Settings.

## Main Gaps

### P0 backend correctness

1. `memorycore/storage/temporal_governance.py:54` constructs `VectorStore(cfg)` directly with a raw
   config dict. `VectorStore` expects a `VectorStoreConfig` object. This causes semantic temporal
   supersession to silently fall back to lexical similarity. **实测日志确认：`'dict' object has no attribute 'url'`。**
   正确做法：复用 `vector_store.py` 的 `get_vector_store(load_config())`（`vector_store.py:588`）或
   `VectorStore(vector_store_config_from_dict(cfg))`（`vector_store.py:329`）。

2. `memorycore/storage/curator_llm.py:1510` in `_request_from_result()` queries a nonexistent
   `governance_ledger` table. The actual table is `governance_mutation_log`（`db.py:324`）.
   **影响：LLM curator mutation 无法回滚到原始请求 → 审计完整性缺口，严重度 HIGH。**
   正确做法：改用 `query_governance_ledger` helper（`mutation_executor.py` 暴露，`server.py:60` 已 import）或直接查 `governance_mutation_log`。

3. Backend tests currently show **4 failures**（实测）：
   - 2 个由 governance_ledger bug 导致
   - 2 个 temporal recency 失败（`test_context_pack_recency_*`），需确认是否由 VectorStore 构造 bug 间接导致

### Governance overload

The live governance queue has **1759 needs_review items** out of 4926 total decisions（实测 35.7%）.
瓶颈集中在 importance_reassessment（883）和 semantic_duplicate（533），合计占 needs_review 的 80%。

A review queue with ~1800 items means policy calibration, deduplication, and auto-apply boundaries
are not yet doing enough work.

The UI also exposes prominent "approve all" behavior, which is risky when the queue contains a large
mixed set of governance decisions.

### Frontend information architecture

The desktop UI is usable, but the Dashboard now mixes too many responsibilities:

- memory statistics
- curator status
- rule curator run controls
- LLM curator run controls
- LLM finding review
- tuning controls
- governance summary
- source breakdown

This is efficient for a maintainer, but it blurs product boundaries. Dashboard should summarize and
route. Governance should be the complete review surface. Settings should own tuning.

### Redundant frontend components

**修正原断言：** 这些组件并非全部"未接入路由"。

- `ui/components/dashboard/governance/GovernanceCockpit.tsx` — 实测 `ui/app/governance/page.tsx:27` 在用 `useGovernanceCockpit`
- `ui/components/dashboard/governance/useGovernanceCockpit.ts` — 同上，活跃
- `ui/components/dashboard/governance/api.ts` — 待确认是否仍被引用
- `ui/components/dashboard/intelligence/NeedsReviewQueue.tsx` — 待确认接入状态
- `ui/components/dashboard/intelligence/ReviewQueuePanel.tsx` — 待确认接入状态
- `ui/components/dashboard/intelligence/AutoAppliedStrip.tsx` — 待确认接入状态

真实问题：Dashboard 与 `/governance` 存在两套 governance 组件路径，职责重叠。应在统一为一套后，
移除未引用的组件，避免未来改动更新到错误的 UI 路径。**实施前需逐一 grep import 确认引用状态，不可假定废弃。**

### Apps/source-agent consistency

`/api/v1/apps`（`frontend.py:846`）filters source agents through `_KNOWN_AGENTS`（硬编码白名单），
丢弃未知 agent。App detail（`frontend.py:661`）和 app memory 路由仍能查询原始 source_agent。
Unknown source agents can create memories and be queried directly, but do not appear as stable
entries in the Apps list. This breaks the "who created/accessed this memory" workflow.

### Visual direction

The current Next.js UI is dark and operational, while older static dashboard/docs mention a Claude-like
warm paper palette. The warm direction is not ideal for MemoryCore's current product shape.

Recommended design direction: a dark mica/graphite operations console.

- Graphite/neutral dark background.
- Subtle translucent mica panels only for nav, sheets, overlays, and graph side panels.
- Cyan/blue for system, graph, vector, and connection states.
- Amber for risk, temporal warnings, and review states.
- Emerald for healthy/stable/applied states.
- Violet only as a secondary accent for LLM/intelligence, not the dominant global color.
- Dense tables and scan-friendly controls over decorative cards.

Mobile responsiveness is low priority because the primary user does not use the mobile UI.

## Execution Plan

### Phase 0: Baseline

Run and record the current verification state before changing behavior:

```bash
.venv/bin/python -m pytest tests/ -q
cd ui && pnpm build
cd ui && pnpm exec tsc --noEmit
cd ui && pnpm exec playwright test --reporter=list
```

**已知基线（2026-06-24）：pytest 4 failed / 484 passed / 3 skipped**

补充治理队列基线 SQL，供后续阶段对比：

```bash
.venv/bin/python -c "
import sqlite3
conn = sqlite3.connect('memory.sqlite3')
for r in conn.execute('SELECT review_status, decision_type, COUNT(*) c FROM governance_decisions GROUP BY 1,2 ORDER BY 3 DESC'):
    print(r)
"
```

Acceptance criteria:

- Current failures are documented（已完成：4 failed，见上）.
- Later phases must reduce or preserve the failure count, never hide failures.

### Phase 1: Fix backend P0 bugs

#### 1.1 Fix temporal vector-store construction

Target:

- `memorycore/storage/temporal_governance.py:54`

Implementation:

```python
# 错误（当前）
vs = VectorStore(cfg)

# 正确（复用现有 helper）
from memorycore.vector_store import get_vector_store
vs = get_vector_store(load_config())
```

- `get_vector_store`（`vector_store.py:588`）内部调用 `vector_store_config_from_dict` 构造正确的 `VectorStoreConfig`，且带模块级单例缓存
- 保留 `_lexical_similarity` 作为向量不可用时的 fallback（已有）
- 不要让 config-shape 错误成为常态路径

Acceptance criteria:

- `tests/test_temporal.py` 的 2 个 recency 失败通过（需先确认是否由此 bug 导致）
- 日志不再出现 `'dict' object has no attribute 'url'`
- Auto-supersession 在 Qdrant 可用时使用向量相似度

#### 1.2 Fix curator LLM ledger lookup

Target:

- `memorycore/storage/curator_llm.py:1510`（`_request_from_result`）

Implementation:

```python
# 错误（当前）
"SELECT request_json FROM governance_ledger WHERE id = ? LIMIT 1"

# 正确 — 直接查实际表，或用 helper
# 方式 A：直接查 governance_mutation_log
"SELECT request_json FROM governance_mutation_log WHERE id = ? LIMIT 1"
# 方式 B（推荐）：用 mutation_executor 暴露的 query_governance_ledger helper
```

- 先确认 `governance_mutation_log` 是否有 `request_json` 列；若无，需通过 `execution_id` 关联到 `governance_executions` 或 `governance_runs` 取原始 request
- 决定是否保留旧 `apply_llm_curator()` 直接路径，还是统一走 `governance_decisions → policy_gate → mutation_executor`

Acceptance criteria:

- `tests/test_curator_apply.py` 2 个失败通过
- 所有 LLM-driven mutations 保持可审计、可回滚
- 回滚能还原原始 LLM 请求上下文

#### 1.3 记录上一轮已实施改动（避免重复实施）

2026-06-24 已实施的四项改动（commit `07e7a9c`），本计划不重复：

- `temporal.enabled` 默认 `True`，阈值 0.96→0.88 / 0.82→0.72
- `_similarity()` 优先向量相似度（**但构造方式有 bug，即 1.1 待修**）
- `atomization` 覆盖叙述型记忆（去掉 SIGNAL_RE span 过滤）
- `memory_ingest` 无 API key 时返回 warning 字段

### Phase 2: Reduce governance queue overload

Implementation direction:

- 分析队列：needs_review 1759 条，80% 是 importance_reassessment(883) + semantic_duplicate(533)
- 重点优化这两类的 policy_gate 阈值与 auto-apply 边界
- Tighten duplicate suppression for already applied/rejected/rolled-back candidate hashes
- Auto-apply only high-confidence, low-risk, reversible decisions
- Force review for recent, high-importance, positive-feedback, cross-scope, or destructive actions
- Make degraded warning reflect oversized or stale queues
- Change UI batch behavior so "approve all" is either scoped to the current filter/page or requires
  a stronger confirmation with visible risk/type distribution

Acceptance criteria:

- needs_review 从 1759 降至 < 500（目标减少 >70%）
- Queue age and size produce meaningful health signals
- Batch governance has tests for successful application and rollback/failure behavior

### Phase 3: Fix Apps/source-agent workflow

Target:

- `memorycore/frontend.py:804-846`（`_KNOWN_AGENTS` 与 `_apps_list`）
- `ui/app/apps/*`
- `ui/tests/openmemory-smoke.spec.ts`

Implementation direction:

- 保留 `_KNOWN_AGENTS` 的 display-name 别名，但**不再丢弃**未知 source_agent
- 未知 agent 归入 "Other sources" 或作为原始 source_agent 展示，必须有稳定路由
- app list / app detail / app memories 的 id 与 source label 保持一致
- 保留 `source_agent=memorycore-smoke-test` 的 smoke test

Acceptance criteria:

- `/apps` 暴露或路由到未知 source agent
- `/apps/memorycore-smoke-test` 显示创建的 smoke memory
- Playwright app smoke test 通过

### Phase 4: Simplify frontend information architecture

Implementation direction:

- Rename `Install` to `MemoryOperationsPanel` or `CuratorOperationsPanel`
- Dashboard 聚焦 health / workload / last run / shortcuts
- 把 curator tuning 移到 Settings 或独立 Curator 区
- `/governance` 作为完整 review surface
- **统一两套 governance 组件为一套**，移除未引用组件（实施前 grep 确认）
- Desktop 为主要布局目标

Acceptance criteria:

- 无活跃路由 import 已移除的旧 governance cockpit 组件
- Dashboard 首屏是运维摘要，不是工具堆
- 只有一套 primary governance review workflow

### Phase 5: Apply desktop visual redesign

Implementation direction:

- 采用 dark mica/graphite operations-console 方向
- 更新全局 CSS 变量与共享组件 surface
- 减少主导 violet 用量
- mica blur 仅用于 nav / sheet / overlay / graph panel
- Graph branding 从 `NeuralGraph` 改为 `Memory Graph`
- 统一 Dashboard / Memories / Governance / Apps / Graph / Settings 视觉语言

Acceptance criteria:

- Desktop 截图显示一致的产品语言
- 表格保持高可读性
- Governance risk states 视觉更清晰
- Docs 不再声称 active UI 是 Claude warm paper theme

### Phase 6: Verification and documentation

Implementation direction:

- UI 命名定稿后更新 Playwright expectations
- 更新 README/docs 反映当前 governance 边界与视觉方向
- 确保 `docs/tools.md` 保持自动生成且准确（如触及 MCP tool doc 生成）
- 新增/更新测试：
  - temporal vector similarity construction（回归 1.1 bug）
  - curator LLM ledger lookup（回归 1.2 bug）
  - source-agent app listing
  - governance queue filtering and batch safety

Final acceptance criteria:

- `.venv/bin/python -m pytest tests/ -q` 通过（当前 4 failed → 0 failed）
- `cd ui && pnpm build` 通过
- `cd ui && pnpm exec tsc --noEmit` 通过
- `cd ui && pnpm exec playwright test --reporter=list` 通过
- Governance backlog 从 1759 materially reduced 或 clearly marked degraded
- Desktop product surface 有清晰入口，无 obsolete component path

## Priority Order

1. **Fix temporal vector-store construction**（1.1 — 阻断向量相似度，日志已确认）
2. **Fix LLM curator ledger lookup**（1.2 — 审计回滚完整性，HIGH）
3. Reduce governance queue overload and make batch approval safer（needs_review 1759 → <500）
4. Fix Apps/source-agent route consistency
5. Rename/split Dashboard operations and unify governance components
6. Apply dark mica/graphite desktop design system
7. Update tests and docs

## Non-goals

- Mobile-first redesign.
- Large backend rewrite.
- Replacing SQLite/Qdrant architecture.
- Making LLMs directly mutate the database.
- Recreating a Claude warm paper UI unless product direction changes again.

## Change Log

- 2026-06-24 初版：基于全项目审计的修复计划
- 2026-06-24 详化版：用实测数据核实全部断言，补充量化基线（测试 4 failed / 队列 1759 needs_review）、精确代码位置、正确修复路径、Phase 1.3 已实施记录、修正前端冗余组件断言
