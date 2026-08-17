# mcore llm-curator 资源占用优化 — 执行交接文档（Round 2）

> 状态：深度调查已完成，方案已比选，**待定方向后即可执行**
> 创建：2026-08-17
> 前序文档：`docs/2026-08-17-llm-curator-resource-optimization.md`（原始调查 + P0/P1/P2 方案清单）
> 本文档修正了前序文档的一个关键盲点：**全量 rebuild 并非纯浪费，它当前承担了 curator 变更后同步 Qdrant 的正确性职责**。因此 P0-1「直接关掉 rebuild」必须配套增量同步，否则留下正确性缺口。
> 项目：/home/advancer/project/memorycore

---

## 1. 背景与目标

解决 `llm-curator` 定时批量任务运行期间，主服务 `mcore.service`（:8318）API 响应严重变慢的问题（实测 `/api/v1/stats` 达 43s、`memory_add` MCP 120s 超时）。

罪魁祸首已确认：`run_llm_curator` / `run_llm_curator_incremental` 末尾 `rebuild_vectors=True` 触发 `memory_rebuild_vectors()`，对**全部非 archived 记录（≤5000）逐条 embed**。

---

## 2. 现状复核（代码行号已核对，无漂移）

| 位置 | 内容 |
|---|---|
| `memorycore/server_runtime.py:253-264` | `llm-curator` 子命令，`run_llm_curator(..., rebuild_vectors=True)` 硬编码在 :261 |
| `memorycore/storage/curator_llm/report.py:404-433` | `run_llm_curator`；rebuild 逻辑在 :427-433 |
| `memorycore/storage/curator_llm/report.py:250-401` | `run_llm_curator_incremental`；rebuild 逻辑在 :385-390 |
| `memorycore/storage/transfer.py:335-372` | `memory_rebuild_vectors(limit=5000)`，逐条 `vs.upsert`，无缓存 |
| `memorycore/vector_store.py:139` | `embed_text()` 无缓存；Ollama 单条调用（`_embed_ollama` :213） |
| `memorycore/vector_store.py:429-475` | `upsert` / `upsert_batch`（batch 内 embed 仍逐条，:462） |
| `memorycore/vector_store.py:477-548` | `search`（支持 `filters={"status": ...}`）/ `delete`（:535） |
| `memorycore/storage/crud.py:46-87` | **`_sync_to_vector`：active→upsert（异步），非 active→delete（同步），失败进 queue** |
| `memorycore/storage/crud.py:90-175` | `vector_sync_queue` 重试机制（`_enqueue_vector_sync` / `_drain_vector_sync_queue`） |
| `memorycore/storage/curator_llm/apply.py:18-74` | `apply_llm_curator`：构造 `MutationRequest` 列表后 `execute_batch` |
| `memorycore/storage/mutation_executor.py:170-237` | `_apply_request`：**只改 SQLite，不碰 Qdrant** |
| `memorycore/storage/governance.py:19` | `convert_llm_findings_to_decisions` → 仅 `execute_batch`，不碰 Qdrant |
| `memorycore/storage/curator_llm/core.py:355-364` | `_fetch_active_memories`：`WHERE status IN ('active','candidate')` |
| `memorycore/storage/curator_llm/core.py:386-421` | `_find_candidate_pairs`：`top_k=6`，结果 `if other_id not in by_id: continue` 兜底 |
| `run_curator.sh:68-70` | llm-curator 调用处（`--limit 200 --sim-threshold 0.72 [--apply]`） |
| `~/.config/systemd/user/mcore-curator.service` / `.timer` | 见第 5 节 |
| venv | `/home/advancer/project/memorycore/.venv/bin/python` |

---

## 3. ★核心发现：全量 rebuild 有隐藏的正确性职责

**curator 的变更链路完全不碰 Qdrant**，目前全靠最后那轮全量 rebuild 去冲刷：

```
run_llm_curator ──► convert_llm_findings_to_decisions ──► execute_batch
                        (governance.py:19)              (mutation_executor._apply_request
                                                        :170-237，只改 SQLite)
        └──► rebuild_vectors=True ──► memory_rebuild_vectors()  ← 唯一同步 Qdrant 的环节
```

对比在线写路径（`add/update_memory_record`）已经用 `_sync_to_vector` 同步 Qdrant，而 curator 的 archive/supersede/contradicted/split 变更**没有**走这条路。

**结论**：直接关掉 rebuild（前序文档 P0-1）会留下正确性缺口：

| 影响 | 严重度 |
|---|---|
| Qdrant 无限累积 stale point（磁盘/索引膨胀） | 中 |
| `_find_candidate_pairs` 的 `top_k=6` 被 stale point 挤占，可能**漏掉真正的去重/矛盾候选对** | 中 |
| 已归档记忆仍可能被 `memory_context` / `semantic-search` 检索出来（检索路径 status 过滤需再确认） | 中 |

> 兜底事实：`_find_candidate_pairs` 有 `if other_id not in by_id: continue`，所以 stale point **不会造成错误去重**，只是浪费一次搜索返回 + 可能漏真候选。

---

## 4. 方案对比

| 方案 | 做法 | 优点 | 代价/风险 |
|---|---|---|---|
| **A｜只关 rebuild** | `server_runtime.py:261` 加 `--no-rebuild`（或直接 `rebuild_vectors=False`），`run_curator.sh` 传入 | 一行、立竿见影（embed 5000→200） | Qdrant stale 累积、可能漏候选、archived 仍被搜到 |
| **B｜关 rebuild + 增量同步** ⭐ 推荐 | 关 rebuild + curator apply 后对**受影响记录**增量同步 Qdrant（复用 `_sync_to_vector`：archive/supersede/contradicted→delete，split 子记忆→upsert） | 正确性完整，embed 洪流 5000→受影响记录数（通常几十~几百），顺带根治 stale | 改动稍多（mutation 路径挂增量同步 + 统一 status 语义） |
| **C｜不关，只加速** | 保留 rebuild + 哈希缓存 + 批量 embed（前序 P1-4/5） | 风险最低 | 仍有 embed 洪流（虽变快），不解决 stale |

---

## 5. systemd 调度优化（P0-2/P0-3，独立于方案选择，建议一并做）

`~/.config/systemd/user/mcore-curator.service` 的 `[Service]` 段追加：

```ini
Nice=10
CPUWeight=10
IOWeight=10
```

`~/.config/systemd/user/mcore-curator.timer` 的 `[Timer]` 段改为：

```ini
OnCalendar=*-*-* 03:30:00,15:30:00
RandomizedDelaySec=600
Persistent=true
```

> 规则 curator 保持 hourly 无妨；LLM curator 每天 2 次足够（`review_cooldown=900s` + `reviewed_ids` 12h 冷却已限制重复评审）。改完后 `systemctl --user daemon-reload`。

---

## 6. 推荐方案 B 的详细执行步骤（待方向确认后执行）

### 6.1 关掉全量 rebuild

1. `server_runtime.py:139-143` 给 `llm-curator` 子 parser 加参数：
   ```python
   p_llm_curator.add_argument("--no-rebuild", action="store_true",
       help="skip full vector rebuild after curation (incremental sync is used instead)")
   ```
2. `server_runtime.py:261` 改为 `rebuild_vectors=not args.no_rebuild`。
3. `run_curator.sh:68-70` 的 llm-curator 调用处追加 `--no-rebuild`。
4. 保留手动全量重建能力（`llm-curator` 不带 `--no-rebuild` 时仍走旧逻辑，供需要时手动跑）。

### 6.2 增量同步 Qdrant（关键，缺了正确性不完整）

**挂点选择**：在 `apply_llm_curator`（`apply.py:18`）`execute_batch` 返回后，或直接在 `mutation_executor._apply_request` 变更后，对受影响记录调用增量同步。注意 `_sync_to_vector` 在 `crud.py`，需函数内 import 避免循环导入。

受影响记录的处理语义（复用 `_sync_to_vector`）：

| curator 变更 | SQLite 结果 | Qdrant 应做 |
|---|---|---|
| `memory_archive`（duplicate/importance/low-value） | status→archived | `delete(point)` |
| `memory_status_update`（contradiction） | status→contradicted | `delete(point)` |
| `memory_supersede` | status→superseded | `delete(point)` |
| `memory_insert`（split 子记忆） | 新增 active 记录 | `upsert`（embed + 写入，仅新增的几十条） |
| `memory_importance_update` | importance 变化 | payload 更新或忽略（text/向量不变，可跳过） |

**实现建议**：从 `execute_batch` 的 `results` 里收集所有 `target_id`，变更后统一按「最终 status」做增量同步（active/candidate→upsert，其余→delete）。这样一次批量、不逐条发请求，且天然幂等。

### 6.3 ★统一 status 语义（需拍板）

`_sync_to_vector` 当前是 `active→upsert / 其它→delete`，而 `memory_rebuild_vectors` 是「保留所有非 archived」（含 candidate/contradicted/superseded/stale）。两者不一致。

**建议准绳**：与 `_fetch_active_memories` 对齐——Qdrant 只保留 `active` + `candidate`，其余（archived/contradicted/superseded/stale）一律 delete。需把 `_sync_to_vector` 的判定改为 `status in ("active","candidate")→upsert`，否则 `candidate` 会被误删。

---

## 7. 待用户决策点（执行前请确认）

1. **方案**：A / B / C 选哪个？（推荐 B）
2. **status 语义**：Qdrant 是否只保留 `active+candidate`？（推荐是）
3. **执行范围**：本次只做 P0（关 rebuild + 增量同步 + systemd 调度），还是连 P1（哈希缓存 + 批量 embed）一起？
4. **`--no-rebuild` 参数形式**：用命令行 flag 保留手动重建能力（推荐），还是直接硬编码 `False`？

---

## 8. 验证方法

1. 改完后手动跑一轮：`cd /home/advancer/project/memorycore && ./run_curator.sh`（或 `mcore` 脚本），观察 `reports/llm-curator-*.json` 的 summary **不再有 `rebuild_vectors` 字段**、耗时明显下降。
2. curator 运行期间并发测主服务：`curl -w "%{time_total}" http://127.0.0.1:8318/api/v1/stats` 应保持 <1s。
3. `journalctl --user -u mcore.service --since "5 min ago"` 里 `11434/api/embed` 请求不再密集刷屏。
4. **正确性（方案 B 专属）**：archive 一批记忆后，用 venv 直接查 Qdrant 确认对应 point 已删除：
   ```bash
   cd /home/advancer/project/memorycore && .venv/bin/python - <<'PY'
   import sys; sys.path.insert(0, '.')
   from memorycore.vector_store import get_vector_store
   from memorycore.models import load_config
   vs = get_vector_store(load_config())
   print("collection count:", vs.count())
   # 抽查：取一条已 archived 记忆 id，search 其文本，确认不再返回该 id
   PY
   ```
5. MCP `memory_add` 在 curator 窗口内不再超时（或走前序 P1-6 异步后彻底免疫）。

---

## 9. 关键路径清单

- 服务：`~/.config/systemd/user/mcore.service`、`mcore-curator.service`、`mcore-curator.timer`
- 脚本：`/home/advancer/project/memorycore/run_curator.sh`
- 调度入口：`memorycore/server_runtime.py`（`llm-curator` 子命令，`rebuild_vectors=True` 在 :261）
- curator 报告/rebuild：`memorycore/storage/curator_llm/report.py`（`run_llm_curator` :404、`run_llm_curator_incremental` :250）
- 全量重建：`memorycore/storage/transfer.py:335` `memory_rebuild_vectors(limit=5000)`
- **增量同步（现成可复用）**：`memorycore/storage/crud.py:46` `_sync_to_vector` + :90 `vector_sync_queue`
- curator apply：`memorycore/storage/curator_llm/apply.py:18` `apply_llm_curator`
- mutation 执行器（不碰 Qdrant，需挂同步）：`memorycore/storage/mutation_executor.py:170` `_apply_request`
- 向量/embed：`memorycore/vector_store.py`（`embed_text` :139、`upsert` :429、`upsert_batch` :453、`search` :477、`delete` :535）
- 候选扫描：`memorycore/storage/curator_llm/core.py:386`
- 配置：`/home/advancer/project/memorycore/config.yaml`（`llm_curator:` 段）
- venv：`/home/advancer/project/memorycore/.venv/bin/python`

---

## 10. 风险与回滚

- **方案 B 的循环导入风险**：`mutation_executor` / `apply.py` 引入 `_sync_to_vector` 时，必须在函数体内 import（`from memorycore.storage.crud import _sync_to_vector`），不要放模块顶层。
- **回滚**：所有改动都是单文件小改 + systemd 配置，`git diff` 可精确回退；`--no-rebuild` 去掉即恢复旧全量重建行为。
- **增量同步失败兜底**：`_sync_to_vector` 已有 `vector_sync_queue` 重试机制，单条失败不丢，下次 drain 会重试；不会静默漏删。
