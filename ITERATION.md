# local-memory-mcp 迭代日志

## [迭代 9] 2026-05-19 — Agent Memory Hook Contract 与 Overmind 升级计划文档

**提交**: `Phase 9`（`git log --oneline --grep="Phase 9"` 可查具体 hash）

### 变更
- `docs/plans/2026-05-19-agent-memory-hook-contract.md`: 新增跨 Agent Hook / Wrapper / MCP 记忆接入协议，覆盖 context_pack、ingest_session、feedback_event、Hermes/Claude Code/Generic CLI adapter、风险防线与分阶段实施计划。
- `docs/plans/2026-05-19-overmind-inspired-lmmcp-evolution.md`: 纳入 Overmind 亮点到 lmmcp 演进计划，强调 client-neutral、URL-based MCP、fallback/degraded、图谱预警、反馈事件、技能推荐与可选 include adapter。
- `docs/plans/2026-05-19-local-memory-mcp-upgrade-plan-overmind.md`: 新增 local-memory-mcp 升级计划书，按 Phase 1-6 规划图谱增强、主动预警、反馈闭环、自动 consolidate、图谱扩展注入和可选自动注入。

### 修复
- （无代码修复；本轮为架构文档留存。）

### 验证
- 文档检查: 新增 Hook Contract 文档已写入 docs/plans，包含 before-agent / during-agent / after-agent 生命周期、三类核心 schema、adapter 边界、fallback 策略和风险矩阵。
- Git 检查: 仅暂存本轮文档与 ITERATION.md。

### 已知问题
- 尚未实现对应代码；后续需要走 design -> impl -> qa/review/security gates。
- Hermes design/security profile 此前调用失败：HTTP 401 Invalid API key，落地实现前需修复 profile 凭据。

### 下一步
1. Phase 10: 实现 `context_pack` v2，返回 sections/sources/warnings/suggested_skills/degraded/fallback_used。
2. Phase 11: 实现 `ingest_session` 和 feedback event taxonomy。
3. Phase 12: 增加 generic CLI wrapper 与 Hermes profile adapter。

---

## [迭代 8] 2026-05-19 — Curator 自动化 + memory_stats + Context Pack 质量报告

**提交**: `Phase 8`（`git log --oneline --grep="Phase 8"` 可查具体 hash）

### 变更
- `local_memory_mcp/storage.py`: 新增 `get_memory_stats()` — 按 type/status/source_agent 分组统计、avg confidence/importance/feedback_score、never_accessed_count、link_count
- `local_memory_mcp/server.py`: 新增 `memory_stats` MCP tool（第 16 个工具）
- `local_memory_mcp/storage.py`: `build_context_pack()` 返回值新增 `quality` 字段 — total_candidates、used_count、active_ratio、avg_importance、stale_in_results、estimated_tokens
- `scripts/lmmcp-curator.service`: 新增 systemd user service 单元
- `scripts/lmmcp-curator.timer`: 新增 systemd user timer（每小时，RandomizedDelaySec=300）
- `scripts/install_curator_timer.sh`: 新增一键安装脚本，自动 symlink 到 ~/.config/systemd/user/ 并 enable
- `tests/test_stats.py`: 新增 6 个测试覆盖 memory_stats 工具

### 修复
- `run_curator.sh`: 删除 `semantic-index` 调用 — 该命令 Phase 7 后已废弃，返回 error JSON 但被 `/dev/null` 静默，语义索引实际未执行
- `local_memory_mcp/storage.py` `consolidate()`: 重复检测 key 生成改为调用 `normalize_title_key()`，与 `curator_report()` 一致
- ive/low_feedback/skill_promotion 候选检测全部改为专用 SQL 查询，不再依赖 `list_recent()` 的 `updated_at DESC` 排序截断，确保最老记录也能被扫描到；apply 模式下去重逻辑改用 `seen_ids` set 替代 dict comprehension

### 验证
- 测试: **111/111 pass** (0 skipped，新增 6 个)
- `memory_stats` MCP tool: 空库返回 total=0 不报错，有数据时返回完整分布
- `build_context_pack` quality 字段: 向后兼容，现有调用方不受影响
- systemd timer: WSL2 systemd=true 环境下 install_curator_timer.sh 可正常安装

### 已知问题
- （无新增已知问题）

### 下一步
1. Phase 9: Agent Mailbox MVP — `agent_messages` / `agent_presence` 表 + 4 个 MCP 工具
2. README 同步修订（Phase 7/8 架构漂移，仍有旧 stdio/Mem0/sqlite-vec 描述）
3. 24 小时 curator dry-run 观察，确认 stale/archive 候选分布合理后开放 apply

---

## [迭代 7] 2026-05-18 — 模块重构 + MCP 循环导入彻底修复

**提交**: `Phase 7`（`git log --oneline --grep="Phase 7"` 可查具体 hash）

### 变更
- `local_memory_mcp/` 包结构: 将 1284 行的单文件拆分为 `models.py`/`storage.py`/`server.py`/`__init__.py`/`__main__.py`
- `local_memory_mcp/models.py`: 抽取常量、YAML 配置解析、类型验证、工具函数（无 MCP 依赖）
- `local_memory_mcp/storage.py`: 抽取 SQLite CRUD、FTS 搜索、curator、memory_links、dashboard 生成
- `local_memory_mcp/server.py`: FastMCP 实例、15 个 @mcp.tool() 注册、CLI main() 入口
- `local_memory_mcp/__main__.py`: 新增 `python -m local_memory_mcp` 入口
- `scripts/init_local_memory.sh`: 更新命令为 `python -m local_memory_mcp`
- `run_curator.sh`: 更新 SERVER 路径
- `probe_mcp.py`: 更新 MCP server 路径

### 修复
- `dedup.py`: 消除 `__main__` fallback 循环导入 → 改为直接从 `local_memory_mcp.storage` 导入（storage.py 无 MCP 依赖，彻底断绝循环链）
- **MCP 通道 `memory_ingest`**：此前即使显式传入函数引用，写入阶段仍因模块状态不一致失败。重构后 MCP 全链路验证通过（initialize → tools/list → memory_add → memory_ingest，全部正常返回）

### 验证
- 测试: **105/105 pass** (0 skipped)
- MCP 协议初始化: 正常握手，返回 `serverInfo: {"name": "local-memory-mcp", "version": "1.27.1"}`
- MCP tools/list: 返回 15 个工具（含 memory_ingest、memory_vector_search 等）
- MCP memory_add: 正常写入并返回记录
- CLI: `python -m local_memory_mcp init` 正常
- 导入验证: `from local_memory_mcp.storage import add_memory_record` + `from dedup import ingest` 无循环导入

### 已知问题
- （无新增已知问题；Phase 6 的 MCP 循环导入已修复）

### 下一步
1. curator cron job（定期去重/归档/矛盾检测）
2. 实体/关系迁移（从官方 server-memory，按需）
3. 多 Agent 集成增强

---

## 日志格式规范

每次提交必须在本文件顶部追加一条迭代记录，格式如下：

```markdown
## [迭代 N] YYYY-MM-DD — 标题

**提交**: `Phase N`（可通过 `git log --oneline --grep="Phase N"` 定位）

### 变更 (新增功能/接口/配置)
- `<文件路径>`: 变更描述

### 修复 (Bug 修复)
- `<文件路径>`: 问题描述 → 修复方式

### 验证
- 测试: N/N pass (skipped: N)
- 端到端: 关键链路验证结果

### 已知问题
- 问题描述（若有）

### 下一步
1. 下个迭代计划任务
```

> **规则**: 
> - 每次提交必须追加新条目（追加到文件顶部，即最新迭代在最上面）。
> - 变更与修复分开列出；如果某次提交仅有修复无新功能，"变更" 段可省略。
> - 测试结果必须写实际数字（如 105/105 pass），不允许占位符。
> - 已知问题如已在上个迭代修复，从列表中移除并改记入"修复"段。

---

## [迭代 6] 2026-05-15 — 端到端验证 + Qdrant server 模式 + 5 个 bug 修复

**提交**: `Phase 6`（`git log --oneline --grep="Phase 6"` 可查具体 hash）

### 变更
- `local_memory_mcp.py`: 新增 `update_memory_content()` — 按字段更新记忆（content/title/status/confidence/importance）
- `vector_store.py`: Qdrant 新增 server URL 模式，优先 Docker Qdrant，fallback 本地文件
- `vector_store.py`: `VectorStoreConfig` 新增 `url` 字段
- `config.yaml`: 移除 openmemory 残留；修正 `llm_base_url` 补全 `/v1`；`llm_api_key` 直接写入
- `local_memory_mcp.py`: `memory_ingest` 显式传递 `_add_memory_fn` / `_update_memory_fn` 避免循环导入
- `ITERATION.md`: 新建迭代日志文件及格式规范

### 修复
- `local_memory_mcp.py`: `update_memory_content` 缺失 → 新增完整函数（含 content/title/status/confidence/importance 字段更新）
- `extraction.py`: `os.environ.setdefault()` 被 Hermes 安全空值拦截 → 改为直接赋值 `os.environ[k]=v`
- `dedup.py`: `add_memory_record(type=...)` 参数名错误 → 修正为 `memory_type`（2 处）
- `dedup.py`: 增加 `__main__` fallback 导入（兼容 MCP server 循环导入场景）
- `config.yaml`: DeepSeek `base_url` 缺 `/v1` 导致 401 → 补全

### 验证
- 测试: **105/105 pass** (0 skipped)
- CLI 端到端: DeepSeek 提取(3-4s/次) → Qdrant 去重 → SQLite 写入 → Qdrant 语义索引 — 全链路通过
- Qdrant Docker 模式: 连接成功，向量读写正常（4 条记录）
- Curator: 扫描 16 条记录，报告正常，无异常候选
- MCP 通道 `memory_ingest`: 提取成功，写入阶段仍有 `__main__` 循环导入问题（4 errors / 4 facts）

### 已知问题
- MCP `__main__` 循环导入：`dedup.ingest` 即使显式传入函数引用，仍因模块状态不一致导致写入失败。CLI 通道完整通过，MCP 通道待重构后验证。

### 下一步
1. 重构模块结构，消除 `__main__` 循环导入
2. 跑通 MCP 通道完整 ingestion
3. 实体/关系迁移（从官方 server-memory）
4. 增加 curator cron job（定期去重/归档/矛盾检测）
## 2026-05-19 14:17:19 +0800 - test(local-memory-mcp): update project iteration

- 项目: `local-memory-mcp`
- 分支: `main`
- 远端: `https://github.com/advancer9817-crypto/local-memory-mcp.git`
- 关联提交: `390ff382c4a7e79df1a86b7bb03f91b81c9a3184`
- 提交时间: `2026-05-19 14:14:00 +0800`
- 提交作者: `advancer9817-crypto <advancer9817-crypto@users.noreply.github.com>`

### 迭代说明

```text
- ITERATION.md                                       |   36 +
- README.md                                          |   74 +-
- config.yaml                                        |    7 +-
- dedup.py                                           |   12 +-
- docs/deployment.md                                 |   21 +-
- docs/memory-platform-briefing/data.js              |    2 +-
- docs/migration/2026-05-12-baseline.md              |   10 +-
- ...enmemory-qdrant-memory-platform-project-book.md |   66 +-
- docs/plans/frontend-design-brief.md                |    4 +-
- extraction.py                                      |    2 +-
- local_memory_mcp.py                                | 1226 --------------------
- probe_mcp.py                                       |    2 +-
```

### 修改范围统计

```text
ITERATION.md                                       |   36 +
 README.md                                          |   74 +-
 config.yaml                                        |    7 +-
 dedup.py                                           |   12 +-
 docs/deployment.md                                 |   21 +-
 docs/memory-platform-briefing/data.js              |    2 +-
 docs/migration/2026-05-12-baseline.md              |   10 +-
 ...enmemory-qdrant-memory-platform-project-book.md |   66 +-
 docs/plans/frontend-design-brief.md                |    4 +-
 extraction.py                                      |    2 +-
 local_memory_mcp.py                                | 1226 --------------------
 local_memory_mcp/__init__.py                       |   67 ++
 local_memory_mcp/__main__.py                       |    9 +
 local_memory_mcp/models.py                         |  267 +++++
 local_memory_mcp/server.py                         |  406 +++++++
 local_memory_mcp/storage.py                        |  848 ++++++++++++++
 probe_mcp.py                                       |    2 +-
 run_curator.sh                                     |    2 +-
 scripts/connect_agents.py                          |  335 ++++++
 scripts/init_local_memory.sh                       |   25 +-
 scripts/serve.sh                                   |    6 +
 tests/test_deployment.py                           |    3 +-
 vector_store.py                                    |   16 +-
 23 files changed, 2096 insertions(+), 1350 deletions(-)
```

### 文件变更清单

```text
M	ITERATION.md
M	README.md
M	config.yaml
M	dedup.py
M	docs/deployment.md
M	docs/memory-platform-briefing/data.js
M	docs/migration/2026-05-12-baseline.md
M	docs/plans/2026-05-12-openmemory-qdrant-memory-platform-project-book.md
M	docs/plans/frontend-design-brief.md
M	extraction.py
D	local_memory_mcp.py
A	local_memory_mcp/__init__.py
A	local_memory_mcp/__main__.py
A	local_memory_mcp/models.py
A	local_memory_mcp/server.py
A	local_memory_mcp/storage.py
M	probe_mcp.py
M	run_curator.sh
A	scripts/connect_agents.py
M	scripts/init_local_memory.sh
A	scripts/serve.sh
M	tests/test_deployment.py
M	vector_store.py
```

## Iteration - 2026-05-19 16:42:52 +0800

- Branch: `main`
- Remote: `https://github.com/advancer9817-crypto/local-memory-mcp.git`
- Purpose: 增强 local-memory-mcp 记忆治理、curator 统计与 dashboard 数据能力，新增 stats 测试和 curator timer 安装脚本/计划文档。
- Changed files:
  - `local_memory_mcp/server.py`
  - `local_memory_mcp/storage.py`
  - `run_curator.sh`
  - `docs/plans/2026-05-19-overmind-lessons-lmmcp-hardening.md`
  - `docs/plans/cpa-real-write-validation-2026-05-19.md`
  - `docs/plans/cpa-write-narrow-buffer-e2e-2026-05-19.md`
  - `scripts/install_curator_timer.sh`
  - `scripts/lmmcp-curator.service`
  - `scripts/lmmcp-curator.timer`
  - `tests/test_stats.py`
- Diff stat:
```
local_memory_mcp/server.py  |   1 +
 local_memory_mcp/storage.py | 126 +++++++++++++++++++++++++++++++++-----------
 run_curator.sh              |   1 -
 3 files changed, 95 insertions(+), 33 deletions(-)
```
- Untracked files intentionally included:
  - `docs/plans/2026-05-19-overmind-lessons-lmmcp-hardening.md`
  - `docs/plans/cpa-real-write-validation-2026-05-19.md`
  - `docs/plans/cpa-write-narrow-buffer-e2e-2026-05-19.md`
  - `scripts/install_curator_timer.sh`
  - `scripts/lmmcp-curator.service`
  - `scripts/lmmcp-curator.timer`
  - `tests/test_stats.py`
- Validation:
  - /home/advancer/.agent-memory/local-memory-mcp/.venv/bin/python -m pytest tests/test_stats.py -q => PASS (6 passed); python3 -m pytest tests/test_stats.py -q => FAIL: system python missing pytest
- Risk notes: 涉及记忆统计、curator 报告查询和运行脚本；系统 Python 缺少 pytest，已使用运行时 venv 验证新增测试。
- Rollback: 回滚本次提交可移除 stats API、curator timer 资产和相关计划文档。
- Commit message: `feat(memory): add curator stats and timer assets`
## Iteration - 2026-05-19 16:47:26 +0800

- Branch: `main`
- Remote: `https://github.com/advancer9817-crypto/local-memory-mcp.git`
- Purpose: 完全追踪 docs/ 与迭代文档变更；补充提交用户维护的 Phase 8 迭代记录。
- Changed files:
  - `ITERATION.md`
- Diff stat:
```
ITERATION.md | 34 ++++++++++++++++++++++++++++++++++
```
- Validation:
  - 文档/迭代日志更新，无代码路径变更；复用上一轮新增测试验证结果：`/home/advancer/.agent-memory/local-memory-mcp/.venv/bin/python -m pytest tests/test_stats.py -q => PASS (6 passed)`
- Risk notes: 仅文档记录更新。
- Rollback: 回滚本次提交即可移除新增迭代日志。
- Commit message: `docs: track phase 8 iteration log`
