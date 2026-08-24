# mcore 治理瘦身与清理 — 迭代执行文档（2026-08-24）

> 状态：**待执行**（用户已确认方向，未开始实现）
> 前置：`ITERATION.md` 迭代 8（降本增效 P0+P1）已完成并提交 7cf7af9
> 关联：`docs/plans/2026-06-29-framework-redesign.md`（Phase 3/4 未完成项在此衔接）
> 数据基线：2026-08-24 实测

---

## 0. 背景与现状基线（实测数据）

### 0.1 规模

| 维度 | 数值 | 备注 |
|---|---|---|
| Python 代码 | 15,752 行 / 48 模块 | server.py 38 函数，仅注册 22 MCP 工具 |
| 前端 | 16,944 行 TS/TSX / 57 组件 / 8 路由页 | apps×2, governance, graph, memories, memory/[id], home, settings |
| 数据库表 | 24 张 + 2 FTS 影子表 | 含 5 张 sqlite-vec 死表 |
| 测试 | 55 文件 / 509 passed / 7 skipped | 全绿 |

### 0.2 记忆分布（memories 7,956 条）

| 状态 | 数量 | 占比 |
|---|---|---|
| archived | 5,511 | 69% |
| active | 1,172 | **14.7%** ← 治理/检索真正活动的量 |
| stale | 955 | 12% |
| contradicted/superseded | 318 | 4% |

近 7 天被召回过的记忆仅 ~445 条 —— **active 的 62% 从未被召回**。

### 0.3 已确认的问题清单（全部有代码/数据证据）

| # | 问题 | 证据 |
|---|---|---|
| P0-1 | LLM curator 治理域过大（不做使用过滤） | `curator_llm/core.py:355` `_fetch_active_memories` 无 `last_accessed_at` 过滤 |
| P0-2 | 数据库 5 张 sqlite-vec 死表 + 2 张空表 | `memory_vec*` 0 行无引用；`memory_embedding_index` 0 行；`agent_messages`/`agent_permissions` 0 行 |
| P0-3 | agent 整条线死代码（前端 0 调用） | `frontend.py:437-450` agents 路由；`server.py:599-648` agent_handoff/presence；前端 grep 空 |
| P0-4 | governance_runs 噪音（6% 使用率） | 6,717 条 runs / 每天 ~100 / 仅 424 关联 executions |
| P1-1 | 双 API 面并存且前端混用 | legacy `/api/*`（frontend.py 45+ 路由）与 `/api/v1/*`（frontend_v1.py 20 路由） |
| P1-2 | frontend 碎片 5 文件互相 import | `frontend.py:556/568/575` import helpers/metrics/http |
| P1-3 | MCP 死函数残留 | `memory_lineage`/`memory_rebuild_vectors`/`memory_vector_audit` 未注册但 re-export 于 `__init__.py` |
| P1-4 | 死前端组件 | `IterationMetricsPanel.tsx` 0 引用 |
| P1-5 | 前端 8 页 → 既定目标 4 页未完成 | 见 framework-redesign Phase 3 |

---

## 1. 执行总览

| 迭代 | 内容 | 风险 | 预计工作量 |
|---|---|---|---|
| **I9** | 死活治理收敛：require-accessed + 死表 + agent 死代码 + governance 噪音 | 低 | 半天 |
| **I10** | 架构碎片收敛：API 收敛 + frontend 合并 + 死函数/死组件清理 | 中 | 1 天 |
| **I11** | 前端 4 页重设（衔接 framework-redesign Phase 3/4） | 中高 | 独立排期 |

原则：
- 每迭代独立提交，`ITERATION.md` 追加记录。
- 每个改动必须提供验证命令与回滚路径。
- 不新增复杂机制（遵循"简化治理"既定方向）；本计划全部是**删除/收敛/过滤**，无新增功能面。

---

## 2. 迭代 9（I9）— 死活治理收敛（低风险，先做）

### I9.1 — LLM curator 只治理"被使用过"的记忆（require-accessed）

**目标**：LLM curator 不再为从未被召回的记忆花 deepseek token。
**证据**：active 1,172 条中近 7 天只召回 445 条 → 治理域应缩到有使用记录的集合。

**改动**：
```python
# memorycore/storage/curator_llm/core.py:355 _fetch_active_memories
# 增加选项参数 require_accessed: bool = False（保持默认行为向后兼容）
# 真实过滤条件：
WHERE status IN ('active', 'candidate') AND last_accessed_at IS NOT NULL
```
- `_fetch_memories_by_ids` 保持一致（候选对来自已过滤集合，无需改）。
- `server_runtime.py` `llm-curator` 子命令加 `--require-accessed` 参数。
- `run_curator.sh` 的 llm-curator 调用加 `--require-accessed`（curator 场景就是要活着的数据）。
- `config.yaml` `llm_curator.require_accessed: false`（默认关闭，显式开启）。

**验证**：
```bash
.venv/bin/python -m memorycore llm-curator --limit 50 --no-rebuild --require-accessed --summary-only
# summary.total_memories 应 ≈ 445（近7天召回）而非 1172
```

**回滚**：去掉 `--require-accessed` 或置 config false。

### I9.2 — 清理死表（DROP）

**目标**：24 表 → 15 表。删除从未使用、无代码引用的表。

**删除清单**：

| 表 | 类型 | 依据 |
|---|---|---|
| `memory_vec` / `memory_vec_chunks` / `memory_vec_info` / `memory_vec_rowids` / `memory_vec_vector_chunks00` | sqlite-vec 死表 | 0 行、无代码引用、pyproject 无 sqlite-vec 依赖 |
| `memory_embedding_index` | 空表 | 0 行，无人写入 |
| `agent_messages` | 空表 | 0 行，agent 线废弃 |
| `agent_permissions` | 空表 | 0 行，agent 线废弃 |

**改动**：在 `memorycore/storage/db.py` `init_db()` 的 `executescript` 末尾追加（已有 DROP 先例：db.py:534）：
```sql
DROP TABLE IF EXISTS memory_vec;
DROP TABLE IF EXISTS memory_vec_chunks;
DROP TABLE IF EXISTS memory_vec_info;
DROP TABLE IF EXISTS memory_vec_rowids;
DROP TABLE IF EXISTS memory_vec_vector_chunks00;
DROP TABLE IF EXISTS memory_embedding_index;
DROP TABLE IF EXISTS agent_messages;
DROP TABLE IF EXISTS agent_permissions;
```
> ⚠️ 注意 `memory_vec_info` 有 4 行（其余 0 行）—— 先确认无任何导出/备份依赖后再删。建议删除前执行一次 `mcore export --full` 做快照。

**验证**：
```bash
.venv/bin/python -c "from memorycore.storage.db import connect
with connect() as c:
    print([r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'memory_vec%' OR name LIKE 'agent_%' OR name='memory_embedding_index'\").fetchall()])"
# 预期: [] （启动后 init_db 自动执行 DROP）
```

**回滚**：从备份恢复快照表，或重新建表（表结构见 db.py 历史记录）。

### I9.3 — 删除 agent 死代码

**目标**：移除前端不调用、MCP 未注册的 agent 整条线。

**删除清单**：
- `frontend.py:437-450`：`agents/presence` GET/POST、`agents/{id}/inbox`、`agents/messages` POST、`agents/messages/cleanup`、`agents/{id}/capabilities` POST、`agents/capabilities` GET 路由分支。
- `frontend.py` 顶部对应 import（`list_agent_presence`、`update_agent_presence`、`agent_capability_register`、`agent_capability_search` 等）。
- `server.py:599-648`：`agent_handoff_create`、`agent_handoff_update`、`agent_presence_update`（未注册 MCP、无路由引用）。
- `frontend.py:451-455`：`handoffs` POST/PATCH 路由（前端 0 调用）。
- `storage/agents.py` 整个模块若无其他引用（实测仅 frontend.py 引用）。

**谨慎项**：删除前全局确认 `agent_capability_register` 是否被 `server.py:629` wrapper 使用（那里有一个同名函数 `agent_capability_register` 转调 storage —— 保留 wrapper，删除 storage 中的内部函数引用时要小心，先 grep 全库）。

**验证**：
- 前端：`grep -rn "agents\|handoffs" ui/app ui/components | grep -v i18n`（应为空）。
- 测试全量：`.venv/bin/python -m pytest tests -q --tb=no`。
- 启动后 `/api/agents*` 返回 404（旧路由删除）。

### I9.4 — governance_runs 噪音治理

**目标**：runs 表 6,717 条 / 仅 424 关联 executions；每天 ~100 条 run 大量是空跑。

**方案（二选一，默认 A）**：
- **A（推荐，简单）**：`governance_ops.py:333` 与 `mutation_executor.py:49` 的 `INSERT INTO governance_runs` 改为**仅在存在有效决策/执行时才写 run**。空决策批次跳过 run 创建。
- B（温和）**：停止记录无用 run 数据，改为清理：`mcore maintenance --apply` 已归档旧 governance 审计；或在 init_db 追加保留期清理。

**具体改动（方案 A）**：
```python
# mutation_executor.py ensure_governance_run 增加惰性创建：
# 只有 create_execution 被调用时才创建 run（不再预先为每个 mutation 建 run）
```
- `governance_ops.py` batch 路径：`valid_decisions` 为空时跳过 `INSERT INTO governance_runs`。

**验证**：
```bash
.venv/bin/python -c "from memorycore.storage.db import connect
with connect() as c:
    n=c.execute('SELECT COUNT(*) FROM governance_runs').fetchone()[0]
    print(n)"
# 手动触发一次无决策 curator -> runs 数不应增长
```

**回滚**：恢复两个 INSERT 语句（git revert）。

### I9 验收（提交 `I9: governance slimming — require-accessed + dead table/code cleanup`）

```bash
mcore status                       # 服务健康
.venv/bin/python -m pytest tests -q --tb=no   # 509+ 全绿
# 5 张 sqlite-vec 表 + 2 张 agent 空表已 DROP（15 表）
# LLM curator --require-accessed 治理域 ≈ 445
# governance_runs 不再空增长
```

---

## 3. 迭代 10（I10）— 架构碎片收敛（中风险）

### I10.1 — 前端 API 收敛到 v1

**目标**：消除双 API 面，前端统一 `/api/v1/*`。

**现状**（实测）：
- 前端混用：`/api/curator/status`（legacy）、`/api/curator/apply`（legacy）、`/api/curator/llm/*`（legacy）、`/api/governance/counts`（legacy）、`/api/v1/stats`、`/api/v1/memories/filter`、`/api/v1/context/test`。

**方案**：在 `frontend_v1.py` 补齐缺失的 v1 路由（curator status/apply/llm、governance counts），前端全部切换到 `/api/v1/*`；legacy 路由保留**但标注 deprecated**（先不删，避免其他 agent/脚本依赖炸掉），下个迭代再删。

**验证**：打开 UI 各页，Network 面板确认无 `/api/` （非 v1）请求；`/api/v1/stats` 返回 200。

### I10.2 — frontend 碎片文件合并

**目标**：5 个 frontend 碎片 → 1 个 `frontend.py`（或 v1 分离清晰）。

**现状**：`frontend.py:556/568/575` `# noqa: E402` import helpers/metrics/http —— 五文件互相引用是历史分层搬家残留。

**方案**：将 `frontend_helpers.py`、`frontend_metrics.py`、`frontend_http.py` 的内容并入 `frontend.py` 或 `frontend_v1.py`（按实际路由归属），删除碎片文件。

**验证**：`python -c "import memorycore.server"` 无 ImportError；全量测试绿。

### I10.3 — MCP 死函数清理

**目标**：server.py 38 函数 → 仅保留 MCP 注册的 22 + 必要内部 helper。

**待清理**（未注册 MCP 且无路由引用）：
- `memory_lineage`（server.py:456）
- `memory_rebuild_vectors` 的 server.py alias（若 HTTP 路由已删）
- `memory_vector_audit`（frontend.py:527 若 I10.1 移到 v1 后 legacy 未用）
- `governance_decisions`（server.py:494，未注册 MCP）

**同步清理**：`memorycore/__init__.py`、`storage/__init__.py` 中对应 re-export。

### I10.4 — 死前端组件清理

**清单**：`IterationMetricsPanel.tsx`（0 引用）。删除文件 + 确认无 import。

### I10 验收

```bash
.venv/bin/python -c "import memorycore.server; print('import ok')"
.venv/bin/python -m pytest tests -q --tb=no
# 前端 grep 无已删组件引用
```

---

## 4. 迭代 11（I11）— 前端 4 页重设（衔接 framework-redesign Phase 3/4）

**目标**：8 路由页 → 4 核心页：**Dashboard+Context Lab**、**Memories**、**Graph**、**Settings**；Apps/Governance 收敛为内联区块；新增写入时纯规则拆分（Phase 4 提取-召回闭环）。

> 详细设计见 `docs/plans/2026-06-29-framework-redesign.md`（Phase 3/4），本计划只做衔接说明，不重复展开。建议在 I9/I10 稳定后独立排期。

**预置校验**：
- I10.1 完成后 API 已统一 v1，前端重设不依赖 legacy 路由。
- Apps 页（`app/apps/*`）若继续维护，则保留为 Dashboard 内联区块，不单独成页。
- Governance 页改为"列表视图 + 自动执行状态"，遵循用户"自动治理、减少手动审批"偏好。

---

## 5. 决策记录与偏好遵循

| 用户既定偏好 | 本计划对应 |
|---|---|
| 简化治理、自动执行、减少手动审批 | I9.4 去掉空 run 噪音；I11 Governance 自动执行 |
| 无非必要不新增复杂机制 | 本计划全部为删除/收敛，无新增功能面 |
| MCP 工具精简（46→22 已达成） | I10.3 不再扩大工具面，清理残留 |
| 前端 4 页重设方向 | I11 衔接 Phase 3/4 |
| 可复用、可移植 | 每迭代独立提交 + ITERATION.md 记录 + 验证命令 |

---

## 6. 风险与回滚总表

| 风险 | 缓解 |
|---|---|
| I9.2 DROP 表误删被依赖数据 | 先 `mcore export --full` 快照；`memory_vec_info` 单独确认 |
| I9.3 agent 代码删除导致 MCP 启动失败 | 删除前 grep 全库确认无引用；先跑测试 |
| I10.1 收敛 API 破坏旧 agent 脚本 | legacy 路由保留 deprecated（先加后删两段式） |
| I10.2 合并碎片引入循环 import | 合并后立即 `import memorycore.server` 验证 |
| 任何一步失败 | `git revert <commit>`，ITERATION.md 记录 |

---

## 7. 附注

- 本计划文档将同步写入 mcore 记忆库（`memory_add` decision/project_memory 类型），便于跨会话检索。
- 未列入本计划的更深问题（如 `_sync_record_indexes` 异步化、serve 内 embed LRU）保留在 HANDOFF.md §6 待办，不并进本执行计划。