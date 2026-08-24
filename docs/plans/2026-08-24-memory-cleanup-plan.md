# mcore 记忆库瘦身清理功能 — 详细实现方案

> 日期：2026-08-24
> 状态：待实现（设计定稿）
> 关联迭代：ITEATION.md 迭代 18
> 作者：Hermes Router（基于 2026-08-24 数据库实审）

---

## 1. 背景与目标

### 1.1 数据现状（实审数据，2026-08-24）

| 数据层 | 总量 | 可删/异常 | 占比 |
|---|---|---|---|
| SQLite memories | 8,071 | archived 5,556 条 | 68.8% |
| Qdrant 向量 | 14,725 | 孤儿 14,082 个 | 95.6% |
| memory_links | 5,892 | archived↔archived 死链 3,079（52.3%） | — |
| feedback_events | 6,383 | 默认分 0.5 的 6,177 条（96.8%） | — |
| memories_fts | 9,363 | 比 memories 多 1,292 行（残留待核对） | — |

**关键结论**：
- 有效数据仅约 **634 个向量 + 2,515 条非 archived 记忆**；
- 系统长期背负 90%+ 的垃圾数据运行，导致向量检索噪声高、embedding 成本浪费、curator 批处理窗口拉长。

### 1.2 功能目标

1. **一次性根治**：清理 14,082 个 Qdrant 孤儿向量 + 5,556 条 archived 记忆（含级联 links/feedback/entities）；
2. **可复用能力**：沉淀为 CLI 命令 + REST API + 前端入口（Dashboard 操作面板按钮）；
3. **自动触发**：跟随 `run_curator.sh`（每 12h curator 批处理后）自动执行；
4. **防复发机制**：修复"向量只增不减"的单向同步缺陷 + 周期性一致性对账。

---

## 2. 根因分析

### 2.1 孤儿向量为什么产生

**结论：不是召回策略问题，也不是数据质量问题，而是同步架构缺陷 + 历史遗留累积。**

证据链：
1. **测试数据写入未清理**：Qdrant 中采样到 `source_agent=pytest` 199 条 + `thread-0~19` 大量并发测试向量（如 `"Concurrent title 2 Content for thread 2"`、`"Export me Content to export"`）——测试直接写 Qdrant，未走状态生命周期；
2. **历史瘦身不同步**：lmmcp→mcore 迁移、以及 SQLite 从 382MB 压到 122MB 的 maintenance 删除大量行时，**未同步删除 Qdrant 对应点**；
3. **单向同步机制**：`_sync_to_vector`（crud.py:51）与 `memory_rebuild_vectors`（transfer.py）都只做 **SQLite → Qdrant upsert**，即"该有的要有"；删除仅在"状态从 active 变为非 active"时调用 `vs.delete`，且 `_delete_stale_vector_points`（transfer.py:390）只按 **payload.status** 过滤删除，**无法覆盖"id 已不在 SQLite 的孤儿"**。

一句话：**Qdrant 是"只进不出"的影子库**。

### 2.2 为什么 archived 记忆可以删

- archived 不参与 active 检索（`_VECTOR_RETAIN_STATUSES = {active, candidate}`）；
- archived 中 4,693 条从未被注入（`injected_count=0`）、4,445 条从未被访问（`last_accessed_at IS NULL`）；
- atomization 原子碎片（带 `parent_id`）语义已被父记忆承载，父归档后子碎片无独立价值；
- 用户确认：**所有 archived 记忆均可删除**，包括非碎片的独立归档记忆。

---

## 3. 整体架构

### 3.1 三阶段推进

| 阶段 | 内容 | 交付 |
|---|---|---|
| **Phase 1** | 一次性根治清理（本次上线执行） | `scripts/cleanup_memory_data.py` 可重复执行 + 报告 |
| **Phase 2** | 可复用功能固化 | CLI `cleanup` 子命令 + REST API + 前端入口 + 自动触发 |
| **Phase 3** | 防复发机制 | 双向同步修复 + 周期对账 + 测试隔离 |

### 3.2 模块划分

```
memorycore/
├── storage/
│   └── cleanup.py            # 新增：清理核心逻辑（可测试纯函数）
├── server_runtime.py         # 修改：新增 cleanup CLI 子命令
├── frontend.py               # 修改：REST 路由 /api/v1/cleanup/*
└── ui/
    └── components/dashboard/
        ├── MemoryOperationsView.tsx     # 修改：新增"清理"按钮+预览卡
        ├── MemoryOperationsPanel.tsx    # 修改：接入清理 API
        └── memory-operations-types.ts   # 修改：清理状态类型
scripts/
├── run_curator.sh            # 修改：末尾追加 cleanup --apply（门控）
└── cleanup_memory_data.py    # 新增：Phase 1 一次性执行脚本（幂等）
tests/
└── test_cleanup.py           # 新增：清理逻辑单测
```

---

## 4. Phase 1 — 一次性根治清理

### 4.1 执行脚本 `scripts/cleanup_memory_data.py`

```
流程（幂等，可重复执行）：
1. 服务健康检查（GET /health 200）
2. 备份：memory_backup() → backups/pre-cleanup-<ts>.sqlite3
3. Qdrant 孤儿向量清理：
   a. 收集 SQLite 全部 id（SELECT id FROM memories）
   b. scroll Qdrant 全部点 id
   c. orphans = qdrant_ids - sqlite_ids
   d. 分批 500 删除
4. SQLite archived 清理（级联）：
   a. 收集 archived 记忆 id（status='archived'）
   b. 删除 memory_links（source_id/target_id ∈ ids）
   c. 删除 feedback_events（memory_id ∈ ids）
   d. 删除 memory_entities（memory_id ∈ ids）
   e. 处理 user_profile_attrs.source_ids_json（移除已删 id）
   f. DELETE FROM memories WHERE status='archived'（FTS 触发器自动清）
5. VACUUM 压缩数据库
6. 审计：写 audit_events 一条汇总；生成 reports/cleanup-<ts>.json
```

### 4.2 安全护栏（硬性）

1. **只删 archived**：SQL 带 `WHERE status='archived'`，且 Python 侧二次断言（待删 id 集合中不允许出现 active/stale/candidate）；
2. **Qdrant 白名单对照**：孤儿 = Qdrant id − SQLite 全部 id，绝不按 payload 状态猜；
3. **删除前备份**：复用 `memory_backup()`，失败则 abort；
4. **dry-run 默认**：`--dry-run` 只出报告不动数据；`--apply` 才执行。

### 4.3 预期结果

| 指标 | 清理前 | 清理后 |
|---|---|---|
| Qdrant 向量 | 14,725 | ~634 |
| archived 记忆 | 5,556 | 0 |
| memory_links 死链 | 3,079+ | 0 |
| SQLite 体积 | 122MB | <60MB |

---

## 5. Phase 2 — 可复用功能固化

### 5.1 核心模块 `memorycore/storage/cleanup.py`

```python
def find_orphan_vector_ids(limit: int = 5000) -> list[str]:
    """返回 Qdrant 中 id 不在 SQLite 的孤儿点 id（白名单对照）。"""

def delete_orphan_vectors(ids: list[str], batch: int = 500) -> dict:
    """分批删除孤儿向量，返回 {deleted, failed}。"""

def find_archived_memories(limit: int | None = None) -> list[dict]:
    """查询 status='archived' 的记忆（预览用）。"""

def delete_archived_memories(ids: list[str], backup: bool = True) -> dict:
    """级联删除 archived 记忆（links/feedback/entities/profile attrs），返回统计。"""
    # 硬断言：任何待删 id 的当前 status 必须 == 'archived'

def cleanup_summary(dry_run: bool = True) -> dict:
    """综合报告：orphan_vectors / archived / links / feedback / entities 数量"""

def run_cleanup(scope: str = "all", dry_run: bool = True) -> dict:
    """scope: all | vectors | memories；内部编排上述函数。"""
```

导出到 `memorycore/storage/__init__.py` 供 CLI/API 使用。

### 5.2 CLI 子命令（server_runtime.py）

```
python -m memorycore cleanup [--dry-run|--apply] [--scope all|vectors|memories]
                             [--limit N] [--json]
```

- 默认 `--dry-run`（输出 summary + 样本）；
- `--apply` 才真正执行；执行前自动备份。

### 5.3 REST API（frontend.py, `_dispatch_api_sync`）

```
GET  /api/v1/cleanup/plan        → {orphan_vectors: N, archived_memories: N, links: N, feedback: N, entities: N, dry_run_only: true}
POST /api/v1/cleanup/execute     → body {scope: "all", apply: true}
                                  → {backup_path, deleted: {vectors, memories, links, feedback, entities}, audit_id}
```

- 鉴权沿用现有 frontend token 机制；
- `apply` 幂等：重复执行无副作用（孤儿/archived 为 0 时 no-op）。

### 5.4 前端入口（Dashboard 操作面板）

**MemoryOperationsView.tsx** 新增第三个按钮"清理归档数据"（与 Run Curator / Run LLM 并列）：

1. **预览**：点击 → `GET /api/v1/cleanup/plan` → 弹 AlertDialog 显示"将清理：14,082 个孤儿向量 / 5,556 条归档记忆 / 3,079 条死链 / 1,108 条反馈"；
2. **确认**：用户确认 → `POST /api/v1/cleanup/execute {apply:true}`；
3. **反馈**：显示已删统计 + 备份路径 + 耗时；
4. **状态**：memory-operations-types.ts 增加 `CleanupRunState`（idle/preview/confirming/running/succeeded/failed）与 `CleanupPlan` 类型；
5. **i18n**：en.ts / zh.ts 新增 `dashboard.cleanup*` 键。

### 5.5 自动触发（run_curator.sh 末尾追加）

```bash
# 归档数据物理清理：跟随 curator 批处理，默认与 curator apply 门控一致
CLEANUP_ENABLED="${LOCAL_MEMORY_CLEANUP_ENABLED:-1}"
if truthy_flag "$CLEANUP_ENABLED"; then
  CLEANUP_APPLY_FLAG=()
  append_apply_flag "LOCAL_MEMORY_CLEANUP_APPLY" \
    "${LOCAL_MEMORY_CLEANUP_APPLY:-${LOCAL_MEMORY_CURATOR_APPLY:-}}" CLEANUP_APPLY_FLAG
  "$PY" "$SERVER" cleanup "${CLEANUP_APPLY_FLAG[@]}" --scope all \
    > "$OUT_DIR/cleanup-$TS.log" 2>&1 || echo "[mcore] cleanup failed (non-fatal)" >&2
fi
```

- 跟随现有 `mcore-curator.timer`（每 12h，03:00 / 15:00 + 300s 随机延迟）顺带执行，不新增 timer；
- 默认受 `LOCAL_MEMORY_CURATOR_APPLY` 门控：curator 是 dry-run 时清理也 dry-run。

---

## 6. Phase 3 — 防复发机制

### 6.1 双向同步修复

- `crud.py delete_memory_record()`（如有新增 hard-delete）或 `update_status()` 归档路径：确认非 retain 状态已调用 `vs.delete`；
- `memory_rebuild_vectors()` 末尾追加孤儿清理步骤（比 `_delete_stale_vector_points` 更强：按 id 白名单对照）；
- 后端启动时可选做一次轻量对账（`--check-vectors-on-boot`，默认关）。

### 6.2 周期性对账

- `mcore-maintenance.timer`（每周）增加 cleanup 对账任务：
  ```
  python -m memorycore cleanup --scope vectors --dry-run
  ```
  若 orphan_vectors > 0 且 `LOCAL_MEMORY_CLEANUP_AUTO_APPLY=1`，则自动 `--apply`；
- 审计日志留痕，Dashboard 健康度指标可引用孤儿向量数为新的健康信号。

### 6.3 测试数据隔离

- pytest 使用独立 Qdrant collection（如 `agent_memory_test`）或测试 DB 全隔离；
- 确保测试 teardown 清理向量，避免再次污染生产 collection。

---

## 7. 验收标准

| 编号 | 验收项 | 验收方式 |
|---|---|---|
| AC-1 | Qdrant 孤儿向量 = 0（仅留有效向量 ~634） | `cleanup --scope vectors --dry-run` 输出 0 |
| AC-2 | archived 记忆 = 0（非 archived 记忆不受影响） | SQL: `SELECT COUNT(*) FROM memories WHERE status='archived'` = 0；active/stale/candidate 计数不变 |
| AC-3 | 死链/孤儿反馈/实体 = 0 | SQL 关联计数 = 0 |
| AC-4 | 删除前有备份且可恢复 | backups/pre-cleanup-*.sqlite3 存在 |
| AC-5 | CLI 可复用 | `python -m memorycore cleanup --help`；dry-run/apply 均可用 |
| AC-6 | API 可复用 | GET plan 200；POST execute 幂等 |
| AC-7 | 前端入口可用 | Dashboard 按钮 → 预览 → 确认 → 反馈 |
| AC-8 | 自动触发生效 | curator 日志出现 cleanup 段；report 生成 |
| AC-9 | 单测覆盖 | pytest tests/test_cleanup.py 全绿 |
| AC-10 | 数据安全 | 无 active/stale/candidate 记录被误删（审计断言） |

---

## 8. 风险与缓解

| 风险 | 等级 | 缓解 |
|---|---|---|
| 误删 active/stale 数据 | 高 | 硬断言 + 白名单对照 + 备份 + dry-run 默认 |
| 服务并发写冲突 | 中 | SQLite busy_timeout=60s；清理走独立进程（跟随 curator 批处理模式） |
| Qdrant 批量删除超时 | 中 | 分批 500/批 + 进度日志 |
| 删除后召回质量下降 | 低 | archived 本就不参与 active 检索，语义无损失 |
| 自动触发误删用户预期数据 | 中 | 门控默认跟随 CURATOR_APPLY；config 可关 |

---

## 9. 实施顺序（Task Checklist）

1. [ ] `memorycore/storage/cleanup.py`（核心逻辑 + 硬断言）
2. [ ] `tests/test_cleanup.py`（单测：孤儿查找、级联删除、幂等、误删保护）
3. [ ] `server_runtime.py` cleanup CLI 子命令
4. [ ] `frontend.py` `/api/v1/cleanup/*` 路由
5. [ ] `scripts/cleanup_memory_data.py`（Phase 1 包装脚本）
6. [ ] `run_curator.sh` 追加自动触发段
7. [ ] 前端：MemoryOperationsView/Panel/types/i18n
8. [ ] 端到端验证（先 dry-run → 备份 → apply → 对账）
9. [ ] Phase 1 实际执行 + 报告
10. [ ] Phase 3 双向同步修复 + 周对账任务
11. [ ] ITERATION.md 迭代 18 记录 + commit + push

---

## 10. 附录

### 10.1 关键代码定位

- `_sync_to_vector`：`memorycore/storage/crud.py:51`
- `_VECTOR_RETAIN_STATUSES`：`memorycore/storage/crud.py:30` = `{active, candidate}`
- `_delete_stale_vector_points`：`memorycore/storage/transfer.py:390`
- `memory_backup`：`memorycore/server_runtime.py` MCP `memory_backup`（server.py:475 附近）
- `run_curator.sh`：`/home/advancer/project/memorycore/run_curator.sh`
- Dashboard 操作面板：`ui/components/dashboard/MemoryOperationsView.tsx` / `MemoryOperationsPanel.tsx`
- CLI 子命令模式：`memorycore/server_runtime.py:112` 起 argparse subparsers

### 10.2 数据量参考（复测命令）

```bash
# 孤儿向量
.venv/bin/python - <<'PY'
import sqlite3
from qdrant_client import QdrantClient
conn = sqlite3.connect('memory.sqlite3')
db_ids = {str(r[0]) for r in conn.execute('SELECT id FROM memories')}
conn.close()
client = QdrantClient(host='127.0.0.1', port=6333)
offset = None; q_ids = []
while True:
    pts, nxt = client.scroll('agent_memory', limit=1000, offset=offset, with_payload=False, with_vectors=False)
    q_ids += [str(p.id) for p in pts]
    if nxt is None: break
    offset = nxt
print(len(set(q_ids) - db_ids))
PY
```