# 手动「清理 · 合并 · 归档」数据维护功能 — 设计方案

- 日期：2026-08-24
- 状态：设计稿（未实现）
- 关联：`docs/plans/2026-08-24-governance-slimming.md`、`references/cleanup-audit-2026-08.md`

---

## 1. 背景与目标

当前库规模（实测 2026-08-24）：记忆总量 **8010** 条，其中：

| 状态 | 数量 | 占比 |
|---|---|---|
| archived（已归档） | 5556 | 69% |
| stale（过期） | 954 | 12% |
| active（活跃） | 1208 | 15% |
| contradicted（矛盾） | 231 | 3% |
| superseded（被取代） | 61 | 1% |

治理能力目前已分散在多处：Rule Curator 每小时自动清理归档、LLM Curator 手动触发生成语义决策、治理页人工确认决策队列、rollup 自动聚合 episodic。**缺口**：没有一个「手动、可预览、按动作分组、确认后一次执行」的数据维护入口；用户无法直观看到「我这次操作会归档多少、合并多少、删掉多少」。

**目标**：提供手动触发的一体化数据维护能力，包含三类动作——**归档**（archive 过期/无用数据）、**合并**（merge 重复/矛盾收敛）、**清理**（clean 确认无用的垃圾），并在前端 Dashboard 提供入口，全部操作**先预览后执行**。

---

## 2. 现状盘点（已存在的碎片能力，设计需复用而非重写）

| 能力 | 入口 | 说明 |
|---|---|---|
| Rule Curator（`curator_report` → `/api/curator` GET / `/api/curator/apply` POST） | Dashboard「运行 Curator」；定时器每小时自动跑 | 重复(tile)、stale、archive、contradicted archive、candidate 过期、promote、revival、碎片清理等规则；`allow_actions`/`deny_actions` 可裁剪 |
| LLM Curator（`/api/curator/llm` POST + job 轮询） | Dashboard「运行 LLM」；已从定时降级为手动 | 产出 governance decisions：semantic_duplicate / contradiction / importance_reassessment / split_candidate |
| Governance 决策队列（`/api/governance/*`） | 治理页 | apply/reject/rollback/batch apply；动作含 archive、archive_duplicate、archive_and_merge_duplicate、split、supersede、delete、hard_delete、keep |
| Rollup（自动 6h） | 无 UI | episodic 聚合：多条事件 → 一条 durable 记忆，来源归档 |
| 备份（`/api/backup` POST） | 无 UI | SQLite backup API |
| 向量重建/审计（`/api/vector/rebuild`） | 无 UI | Qdrant 一致性维护 |

**缺口总结**：① 无「一次触发、按动作分组先预览后执行」的统合入口；② Rule Curator 只改状态不硬删，无用数据会一直占行；③ 语义合并依赖 LLM 决策队列需多步人工确认；④ 合并/清理结果缺少可视化摘要与审计追溯。

---

## 3. 功能设计

### 3.1 动作模型（三类动作）

#### A. archive — 归档
- **候选来源**：复用 `curator_report` 的既有判定（stale 超期、candidate TTL 过期、contradicted 90 天无访问、superseded、unused 碎片），通过 `deny_actions` 裁剪掉 promote/revival 等非目标动作。
- **动作**：`update_status_batch(archived)`，一条 SQL 批量完成，可逆（reject 语义）。
- **默认保护**：precious 类型（user_profile / environment_fact / decision / project_memory / skill_candidate）除非 feedback < -2 且 importance < 0.3，否则不进入候选（复用现有规则）。

#### B. merge — 合并（确定性 + 半自动两级）
- **B1 确定性合并**：title 归一化（小写/去空格/去标点）匹配的 active 组 → 保留「最新 updated_at 或最高 importance 或有过访问记录」的一条，其余置 `superseded` 并写 `related_ids_json` 血缘（复用 `supersede_memory_record` / governance `archive_and_merge_duplicate` 语义，先归档后 merge 记录）。
- **B2 语义合并（可选并入）**：复用 governance 队列中 `review_status IN ('auto_approved')` 且 `recommended_action IN ('archive_duplicate','archive_and_merge_duplicate','supersede')` 的决策，在维护流程中勾选「一并应用已自动批准的语义合并决策」，调 `apply_governance_decisions_batch`。
- **红线（来自 2026-08-24 audit 结论）**：合并产物**绝不设为 active**——不美化 dead data、不把 consolidated 记录塞回检索池（当前上下文命中率 79.7%，不允许污染）。合并只收敛重复/矛盾，不做 never-accessed 汇总聚合。

#### C. clean — 清理（硬删，高确认门槛）
- **候选范围（白名单式）**：
  1. `status='candidate'` 且超过 TTL 且非 precious；
  2. 测试 agent 数据：`source_agent IN ('memorycore-smoke-test', ...)`；
  3. 碎片记录：`source IN (_FRAGMENT_SOURCES)`（atomizer / governance_split）且长度 < 阈值且从未访问；
- **动作**：`DELETE` 主记录 + FTS 同步 + Qdrant point 删除 + `vector_cache` 清理（governance `hard_delete` 已有先例，向量删除复用 transfer/vector_store 路径），随后可触发增量向量索引同步。
- **门槛**：clean 必须用户在 UI 勾选「我确认删除 N 条不可恢复数据」；执行前自动备份；daily 产生 `maintenance_clean` 审计事件，记录删除 id 清单（供追溯）。

### 3.2 后端 API 设计（v1 风格，两阶段 + 异步 job）

```
POST /api/v1/maintenance/plan      # 只读分析，永不写库
  body: { modes: ["archive","merge","clean"], limit: 500,
          include_semantic_merge: false, filters?: {source_agent?, status?} }
  resp: { plan_token, stats: { archive: N, merge_groups: M, merge_records: K, clean: N },
          groups: { archive: [{id,title,reason,type}...首5条],
                    merge:   [{keep:{id,title}, dups:[{id,title}], basis:"title|governance_auto"}...首5组],
                    clean:   [{id,title,reason}...首5条] } }

POST /api/v1/maintenance/execute   # 幂等：必须携带 plan_token（含 plan 摘要 hash）
  body: { plan_token, confirm_clean: true }
  resp: { job_id }                  # 异步执行，避免长事务阻塞

GET  /api/v1/maintenance/{job_id}  # 进度/结果轮询（复用 llm_curator_job 模式）
GET  /api/v1/maintenance/latest    # 前端刷新恢复正在运行的 job（localStorage 模式）
```

执行顺序（execute 内部）：**备份 → archive → merge → clean → 向量同步/审计**。
- 备份：`memory_backup()` 快照到 `backups/maintenance-<ts>.sqlite3`，结果里返回路径。
- 互斥：内存维护锁 + `llm_curator_jobs` 同款 job 状态（`running` 时拒绝新计划/执行）；维护 job 运行期间跳过/等待定时 Rule Curator（避免 SQLite 写竞争与 curator 窗口卡顿——参考 `LOCAL_MEMORY_LLM_CURATOR_ENABLED=0` 的既有隔离思路）。
- 幂等：execute 校验 plan_token 摘要与当前库快照计数一致，防止过期预览误执行。

### 3.3 前端设计

**入口位置（推荐组合，不新建独立页——贴合 8→4 页重组方向）**：
1. Dashboard → 记忆运维面板（`MemoryOperationsPanel`）：在「运行 Curator / 运行 LLM」旁新增 **「一键维护」** 主按钮（主入口）。
2. 治理页：加轻量「打开维护」链接（治理页后续会被内联进 4 页重组，不承载重逻辑）。

**交互流程（模态 / 抽屉）**：
1. **模式选择**：勾选 归档 / 合并 / 清理，参数 limit、是否包含语义合并决策；
2. **生成预览**：`POST /api/v1/maintenance/plan` → 三张卡片分别展示「将归档 N 条 / 将合并 M 组(K 条) / 将删除 N 条」，各展开前 5 条样本；clean 卡片红色警示 + 必选确认勾选框；
3. **执行**：`POST /api/v1/maintenance/execute` → job 进度条（复用 MemoryOperationsPanel 现有轮询 + localStorage 恢复模式）→ 完成后展示 summary（各动作计数、耗时、备份路径、「查看审计」链接）。

**复用清单**：轮询 hook（`MemoryOperationsPanel.pollJob`）、run-state 展示（`MemoryOperationsView`）、i18n 双字典（en.ts/zh.ts 同步新增 `maintenance.*` keys）、getApiBaseUrl/fetch 模式。
**新增组件**：`MaintenanceDialog.tsx`（或并入 MemoryOperationsView 的 `MaintenancePlanCards.tsx`），控制在 2 个以内。

---

## 4. 边界与安全（防止误删/误并）

1. **clean 白名单**：只允许 candidate / 测试 agent / 确认碎片；active + 高 importance + 有访问记录的永远不出现在 clean 候选。
2. **merge 保护**：合并组必须有确定性 title 匹配或 governance auto_approved 支撑；不合并已归档（除非 governance 决策明确）。
3. **默认备份**：每次 execute 自动备份，结果页给出路径；clean 单独再要求 UI 确认勾选。
4. **可逆性分级**：archive / merge（supersede）可逆（reject / rollback 语义）；clean 不可逆，永远最后执行且有强确认。
5. **性能**：默认 limit 500，分批执行；避免 03:00/15:00 定时 curator 窗口；job 内长事务拆批提交，控制 SQLite 锁持有时间。

---

## 5. 里程碑（小步实现，每步可独立交付）

| 里程碑 | 内容 | 预估 |
|---|---|---|
| M1 | 后端 plan/execute/status 最小闭环（仅 archive 动作，复用 curator_report + update_status_batch）+ Dashboard「一键维护」按钮与预览/确认/结果展示 | 半天 |
| M2 | merge 动作：确定性 title 合并 + 可选应用 governance auto_approved 语义合并 | 半天 |
| M3 | clean 动作：白名单硬删 + 向量同步 + 强制备份 + UI 确认勾选 | 半天 |
| M4（可选） | 维护历史/审计展示 + 备份回滚实验 | — |

每个 M 提交均更新 `ITERATION.md`；改配置后需重启服务。

---

## 6. 验收标准

- [ ] `plan` 返回三类分组与数量、样本，且为只读（库零写入）；
- [ ] `execute` 幂等：重复提交同 plan_token 不重复执行；过期 plan_token 被拒绝；
- [ ] 执行后看板 stats 变化可预期（archive/merge/clean 计数对账一致）；
- [ ] 与定时 Rule Curator 互斥，无 SQLite `database is locked` 报错；
- [ ] clean 必须备份 + UI 确认后才可执行；审计事件完整（维护任务、动作、删除清单）；
- [ ] 前端刷新后可从 `latest` 恢复运行中 job 并继续轮询；
- [ ] 不把合并产物置 active；检索命中率不受影响（回归验证 context hit rate）。