# mcore 架构迁移功能对齐审计报告（Python → Java）

> **日期**：2026-09-12 ｜ **迭代**：261 ｜ **审计范围**：`/workspace/memorycore`
> **对照基线**：`docs/iteration-number-map-2026-09-02.md`（208 条冻结迭代）
> **方法**：逐模块函数级对照。Python 旧实现 `memorycore/`（44 模块 / 19,197 行）↔ Java 新实现 `mcore-spring/`（61 个 main 源文件）。
> **证据要求**：每项判定必须有 `grep` / `read` / `psql` 证据（文件路径 + 行号），禁止臆测。全程只读，未重启任何服务。

---

## 一、结论摘要

新架构（Java 17 + Spring Boot + PostgreSQL/pgvector）在**核心读写、检索、多租户、策展 dedup** 上已可用，但存在**大面积功能未迁移**：审计共确认 **26 项差距**，其中

- **P0（正在造成实际损害）5 项**
- **P1（功能整块缺失）10 项**
- **P2（工程与安全）11 项**

**最需要立即关注的三件事**：
1. 实体索引自 Java 接管后**停止增长并持续腐化**（真实回归，正在发生）
2. 治理决策**不落地**（面板显示"已应用"，记忆零变化）——静默假成功
3. **隐私脱敏与注入防护零实现**——密钥明文入库、记忆正文裸注入

---

## 二、判定纠正（避免误报）

审计过程中有两项初始假设被实证推翻，记录于此以免后续重复误判。

### 2.1 MCP 工具面 22 = 22，零差异

```
Python 注册工具（memorycore/server.py:229-692）  22 个
Java  注册工具（McpProtocolService.java:93-207） 22 个
差集                                             ∅
```

初次审计中怀疑缺失的 `memory_lineage` / `memory_rebuild_vectors` / `memory_vector_audit` / `profile_*` / `agent_*` **均为 Python 侧内部函数，从未注册为 MCP 工具**（历史上"MCP 精简"迭代 105/159/166/175 已收敛工具面）。**工具层无需回补。**

### 2.2 Agent 三张表：不是"新丢失"，而是"Python 已废弃 + hook 悬空"

`agent_messages` / `agent_presence` / `agent_capabilities` 三表在 Java 侧零引用、DB 实测 **0 行**。定性证据：

- **MCP 暴露面已主动拆除**：`memorycore/server.py` 的注册清单只有 `memory_*`，无任何 `agent_*` 工具。
- **有书面拆除计划**：`docs/plans/2026-08-24-governance-slimming.md:117-137`「I9.3 — 删除 agent 死代码」明确要删 `agent_handoff_create/update`、`agent_presence_update`、`agent_capability_register/search`。
- **有落库记录**：`memory-sync/memories.json:79775` 记载「删除 server.py 5 个未注册 agent wrapper…agent_messages/agent_permissions 空表暂保留」。

**但契约被留在代码里（真实待办）**：`scripts/hooks/session-start.sh:133-134` 与 `session-end.sh:40` 仍向 `8318/mcp`（=Java）调用 `agent_presence_update` / `agent_capability_register`，Java 无此工具 → 返回 `-32601 Unknown tool`，hook 以 `|| true` **静默吞掉**；`tests/test_deployment.py:149` 仍断言 hook 必须包含该工具名。

→ **正确处置是清理悬空 hook 调用（或恢复工具），而非把它当作新功能回补。**

---

## 三、P0 — 正在造成实际损害（5 项）

### P0-1 实体索引停止增长并持续腐化 ⚠️ 最严重的真实回归

**实测证据**
```
memory_entities  count = 7625   max(created_at) = 2026-09-10 04:49
memories         max(updated_at) = 2026-09-12 15:49
```

**根因**
- `EntityMapper.xml:7-10` 定义了 `insert`，但 `entityMapper.insert` / `deleteByMemoryId` 在 `mcore-spring` **全库零调用者**
- `MemoryRepository.java:63-75` 的 `insert` 只写 `memories`，不触碰 `memory_entities`
- DB 无 `memories → memory_entities` 触发器（`pg_trigger` 实测仅 `trg_sync_memories_json`）

**检索语义同时退化**
- `EntityRepository.java:25-33` 用 `normalized_entity LIKE %q% OR aliases_json::text LIKE %q%`
- **丢弃别名归一**：Python `canonical_entity`（`entities.py:44`）把 `local-memory-mcp` → `mcore`；Java 无法用 `memorycore` 命中 `normalized_entity='mcore'`
- 同时丢失 `status='active'`、`valid_until`、`scope` / `project_path` 过滤与 boost 排序
- `McpProtocolService.java:353` 硬编码 `limit=20` 忽略入参

**影响**：`memory_entity_search` 召回集随时间衰减，实体网络逐步腐化。

**修复**：在 `MemoryRepository.insert/update` 后接入实体同步（复用 `entities.py` 的归一/别名/权重规则）；`EntityRepository` 检索补齐状态与作用域过滤。

---

### P0-2 治理决策不落地（静默假成功）

**证据**
```java
GovernanceService.applyDecision   :141-151   UPDATE governance_decisions SET review_status='applied'
GovernanceService.batchApply      :162-176   同上（仅状态位）
CuratorService.applyCurator       :292-304   复用 batchApply，回「已应用 N 条决策」
LlmCuratorExecutor.insertDecision :471-513   只 INSERT 决策行
```
**全仓无 decisions → memories 的执行器**。而 `getCounts:30-43` 的 `applied` 计数照涨。

**影响**：auto_approved 或人工 apply 后，记忆行零变化；面板显示成功，检索无任何改变。

**修复**：新增执行器，把决策按 `recommended_action` 作用到 `memories`（归档/合并/标记矛盾/建链/升降重要度）。

---

### P0-3 写入端隐私脱敏零实现 ⚠️ 安全

**Python**（`privacy.py`，160 行）
- `_REDACT_DEFS:22-79` 八类规则：openai_key / github_token / aws_access_key / aws_secret / bearer_token / pem_private_key / connection_string / env_assignment
- `_redact_high_entropy_tokens:105`：20+ 字符且 Shannon 熵 ≥ 4.5 → `[REDACTED-HIGH-ENTROPY]`
- **强制写入口**：`crud.py:283`（新增）、`crud.py:345`（更新）

**Java**：`grep -i 'redact|privacy|REDACTED|entropy'` 仅命中 `TenantApiKeyService`（租户密钥哈希，语义无关）。`McpProtocolService.java:274-289`（memory_add）、`:296-304`（memory_update）、`ExtractionService` 均**直接落库**。

**影响**：经 Java 写入的记忆会把 API Key / Token / 私钥 / 含密码连接串**明文落库**，并被 `search` / `context` 召回回灌 Agent 上下文——机密泄露面显著扩大。

---

### P0-4 上下文注入防护零实现 ⚠️ 安全

**Python**：`context_pack.py:452-470` 输出 `BOUNDARY_NOTICE` + `## 强制护栏`（`hard_constraints.rules`）；`:501-509` 经 `check_memory_for_injection`（8 条正则）过滤高危记录，转 warnings 而不入正文。

**Java**：`ContextPackBuilder.java`（全文 50 行）**仅有 token 预算截断 + 行渲染**，无任何防护。

**影响**：记忆内容被原样当正文注入 Agent 上下文 → 提示注入风险直接暴露。

---

### P0-5 召回质量指标被伪造

```java
McpProtocolService.java:373   cStats.put("hit_rate", 0.94);        // 硬编码
McpProtocolService.java:374   cStats.put("average_recall_ms", 3.8); // 硬编码
```
而该工具描述（同文件 `:179`）自称「数据库真实聚合」。`ContextLabController.java:41-49` 的 trace 同样硬编码（`filtered_count=0`、`vector_avg_score=0.78`、`cross_retrieval_rate=0.65`，`hit_rate` 二值化）。

**对照**：Python `search.py:223-260` 真实采集 `context_quality_events`（现状 53 行全为 Python 时代遗产，时间区间 2026-09-08 ~ 09-10，已断档）。

**影响**：比"缺采集"更严重——下游 UI / 巡检依据假值判断健康度，**召回劣化无法被发现**。

**连带**：`injected_count` / `last_injected_at` 在 Java 侧**只有 SELECT 无 UPDATE**，召回-使用闭环断开；`StatsService.java:39` 的「从未注入」统计失真。

---

## 四、P1 — 功能整块缺失（10 项）

### P1-6 记忆主体上下文（subject_context）— **用户点名项**

| 项 | Python | Java |
|---|---|---|
| 模块 | `subject_context.py`（203 行，5 函数） | **零**（`grep -i subject` = 0） |
| 核心函数 | `subject_config:31` / `discover_projects:42` / `resolve_project:79` / `infer_subject_from_title:148` / `active_context_block:178` | — |
| 写回行为 | 解析 project_path → 命中则写入**规范 project_path + 解析后 scope + `project:<name>` 标签** | `ExtractionService.java:119,271` 原样使用裸 `projectPath`，不解析不归一 |
| 提取 prompt | 注入 `SUBJECT_PROMPT_INSTRUCTION`（强制输出 `subject` 字段）+ Active Context 块 + 标题项目前缀规则 | prompt（`:360-415`）无这些内容 |
| 配置消费 | `config.yaml:129-143` 全段生效 | 该段**零读取点**（`ConfigService:81/127` 只透传 `rule_curator`/`llm_curator`/`governance`/`extraction_strategy`） |

**实测影响**：`memories` 共 4874 条，**`project_path` 为空 3725 条（76%）**；`scope='project'` 仅 768 条（16%）。

**注**：迭代 196 标注「规划中，未实施」，但 Python 后续已实现；迁移到 Java 后**再度丢失**。

---

### P1-7 规则策展引擎零实现（记忆生命周期）

**Python** `curator.py:34-427` `curator_report`：17 类候选分类 + 动作计划编排（revive→promote→mark_stale→archive）+ **置信度衰减执行**（`:340-350`，`_DECAY_STEP=0.05`、下限 0.15）。

**Java**：仅有只读候选查询（`CuratorService.listCandidates:129-181`）。

```
grep -ri "promote" → 0 文件
grep -ri "revive"  → 0 文件
全仓 "UPDATE memories SET" 仅 3 处，均为 status='archived'
无任何语句写 status='stale'，无任何语句写 confidence
```

**配置消费率**：`rule_curator` 共 **24 个参数**，Java **只消费 3 个**（`CuratorService.java:141` stale_days_default、`:142` stale_importance_threshold、`:148` contradicted_archive_days）。其余 21 个（`decay_step` / `decay_interval_days` / `decay_min_confidence` / `promote_*` / `revival_*` / `precious_*` / `candidate_ttl_*`）**零引用** → **死配置**。

**影响**：candidate 永不晋升、stale 永不复活、低价值记忆永不降权归档、`decay_policy` 三态语义（freeze/stable/review）不存在。

---

### P1-8 原子化拆分（atomization）零实现

**Python** `atomization.py`（304 行，11 函数）：`should_atomize:49`（≥1200 字符/≥10 行/≥5 句）→ `plan_child_facts:88`（50-520 字符、≤12 条）→ `fact_hash:41`（`sha256(parent_id:归一化事实)` 幂等键）→ `_atomize_record_impl:175`（建子记录 + **`part_of`/`supports` 双链** + 回写父 metadata）。

**调用点**：`crud.py:315-324` 在**写入路径**触发。

**Java**：`grep -ri atomiz` = 0；`part_of|supports|fact_hash` 在 Java 全库 0 命中；`LlmCuratorExecutor.java:286` 自报 `split` 属 pending 阶段。

**影响**：3000 字符的会话摘要永远是一条记录、一个向量 → 召回粒度粗、长内容稀释语义相似度、Top-K 被单条大记录挤占。

---

### P1-9 episodic 汇总（rollup）零实现

**Python** `rollup.py`（299 行，7 函数）：按 (scope, agent, project) 分组选组 → LLM 压缩为长期记忆 → 源 episodic **归档**。

**Java**：`grep -ri rollup` = 0；MCP 无 `memory_rollup_report`。

**影响**：`episodic_memory` **只进不出**，永远停留候选态；源记录不归档 → 表与向量库单调膨胀。

---

### P1-10 split 动作零实现

**Python**（真实实现不在名为 `_apply_split` 的函数，`grep` 0 命中）：
- 策展链 `curator_llm/apply._append_split_requests:163-224`：归档父 → 子事实 insert（metadata 含 `kind:atomic_fact` / `parent_id` / `fact_hash`）→ **幂等守卫** `_existing_split_child_id:301-314` + `uuid5` 确定性 child_id → **child→parent `part_of` + parent→child `supports`** 双向链
- 治理链 `governance_mutations._split_requests:126-195`：质量门（max_splits=5 / min_content_len=50）
- 幂等实测：`tests/test_curator_apply.py:37-45`（二次运行 `split_children_skipped==2`）

**Java**：仅 `LlmCuratorExecutor.java:286` 的 `pending_stages` 提及。**连 `parent_id`/`fact_hash` 元数据约定都缺**。

---

### P1-11 治理执行台账与 undo 零实现

**Python**：`mutation_executor.py`（465 行）—— `ensure_governance_run:42` / `create_execution:67`（幂等键 + 并发守卫）/ 台账写入含 **inverse_json**（`:202/237/262/267`）/ `rollback_execution:363-380` / `_apply_inverse:383-421`；端点 `frontend.py:492-493`。

**Java**：`governance_executions` / `governance_mutation_log` 两表**零引用**（实测均 0 行）。`LlmCuratorExecutor.java:481-483` 写入的 `rollback_json` **无任何读取方** → **写了没人用的死字段（伪回滚能力）**。

**影响**：任何治理/维护写入**不可撤销**。这与既定治理目标「支持 undo logs」直接冲突。

---

### P1-12 向量缓存（vector_cache）零实现

**Python** `vector_store.py:226-311`：缓存键 `(sha256('title content'), model)`，`ON CONFLICT DO UPDATE`；批量路径三段式（命中跳过 → 未命中批量嵌入 → 批量回写）。**性能收益：141ms → 0.3ms**（迭代 171 降本增效核心）。

**Java**：`EmbeddingService.java`（284 行）`embedText:85-112` 与 `embedBatch:195-246` **直接打 HTTP，无任何缓存**；Caffeine 仅用于租户池与 API Key 鉴权，与嵌入无关。

**影响**：同一文本在 insert / update / rebuild / reembed / import 各路径**重复产生嵌入调用**。存量 14 行缓存为 768 维 nomic 数据，对 1024 维 bge-m3 查询永不命中且无清理路径。

**附带缺陷**：`embedOllama:141` 调用 `normalize()`，而 `embedBatch:221-226` **不调用** → 单条与批量路径归一化状态不一致。

---

### P1-13 向量同步队列（vector_sync_queue）零实现

**Python** `crud.py:105-201`：向量写入失败入队（`max_retries=3`）→ 由 auto-curator 线程每 6h 排空（`server_runtime.py:49-55`）；`retry_count` 超限后进入 exhausted。

**Java**：零引用，**且无任何 `@Scheduled`** → 无线程消费。

**影响**：Java 向量写入失败无重试、无死信、无退避。**缓解事实（须诚实标注）**：`embedText` 自身永不抛异常（最终 `return embedHashing`），故"服务不可达"在 Java 表现为**静默伪哈希落库**而非入队——失败模式从"队列积压"变成"数据污染"。这正是 `VectorBackfillService` 存在的原因。

---

### P1-14 用户画像学习环零实现

**Java `extractProfile` 是常量写入，不是抽取**：
- `UserProfileService.java:128-177` 为 **10 条硬编码 candidates**，与 `facts` 查询结果无因果关系
- DB `user_profile_attrs` 10 行的 `value` 与该常量**逐字符一致**；`source_ids_json` 全为 `[]`（对应 `:213` 的 `'[]'::jsonb`）；10 行 `updated_at` 同为 `2026-09-12 05:26:53`（一次批量写）
- `getProfile():71-75` 的 sources 用**字符串硬匹配伪造**（如 `content.contains("WSL")`）；`:114` `latest_extract_at` 直接填 `Instant.now()`

**零覆盖清单**：`profile_snapshot`（注入块）/ `decay_profile_attributes`（软衰减）/ `profile_freshness_warning`（过期告警）/ F1 `feature_words` / F1 `overlap_ratio` / F2 `query_expansion` / F4 `conflict_for_record`。

**影响**：画像对检索**零贡献**；266 条 `user_profile` 记忆与画像表无关联。**画像表有值 ≠ 画像在运行**。

---

### P1-15 上下文包构建零实现

**Python** `context_pack.py:98-677`：三路并发召回（FTS + 向量 + 实体）→ 合并去重 → 12 项加权打分 → 类型权重 → 原子事实剪枝 → 相似聚类省 token → 分组上限 → 注入防护 → 画像注入 → 冲突过滤 → 质量指标。

**Java** `ContextPackBuilder.java`（**50 行**）：仅 token 预算截断 + 行渲染。上游 `McpProtocolService.java:245-246` 直接 `hybridSearch(query, null, 15)`。

**影响**：`context_pack` 全段配置（`max_total_records` / `max_records_per_group` / `profile_boost_weight` / `hard_constraints` / `recency_weight`）**全部无效**；Python 的 `warnings` 信封（注入告警/冲突告警）在 Java 被丢弃。

---

## 五、P2 — 工程与安全（11 项）

| # | 问题 | 证据 | 等级 |
|---|---|---|---|
| P2-16 | **测试覆盖极低**：61 个 main 源文件仅 **2 个测试类（5 个用例）**；`mcore-server`/`mcore-tenancy`/`mcore-common` 的 pom **未声明测试依赖**（不可能新增单测） | `find` 63 个 .java（main 61/test 2）；`grep spring-boot-starter-test` 仅 2 个 pom | 高 |
| P2-17 | **管理面越权**：`/api/v1/tenant/**` 只验"key 有效"，**不比对 key 归属与目标租户** → 持有 A 租户任意 key 可跨租户开辟/销毁数据库、签发/吊销他人密钥 | `TenantAuthFilter.java:83-93`；实测 `/tenant/list` 本机免鉴权 200 | 高 |
| P2-18 | **default 租户免鉴权 + 监听全网卡**：`application.yml` 无 `server.address` → 远端匿名读写默认库；Python 有 `validate_frontend_bind` 护栏，Java 无 | `ss -ltnp` 实测 `*:8318` | 高 |
| P2-19 | **CORS 全开放**：`allowedOriginPatterns("*")` + 全部方法 + 全部头 | `CorsConfig.java` | 高 |
| P2-20 | **`/api/v1/config/raw` 回吐密钥**（含 `database` 段明文口令）；`ConfigService:55/68` 原样放入 `api_key`；无脱敏 | `ConfigController.java:65-68`；实测 `extraction.api_key` present | 中 |
| P2-21 | **连接池 128 > PG `max_connections=100`**：默认池 5 + 系统池 3 + 40×3 = 128；`MAX_ACTIVE_POOLS` 仅 `log.warn` 不拒绝；文档/UI 三处宣称 150 | `DynamicTenantRoutingDataSource.java:26,72-75`；`show max_connections`=100 | 高 |
| P2-22 | **JDBC URL 参数注入面**：`createTenantDataSource:77-79` 仅把 `-`→`_`，`?`/`&`/`=`/`#` 原样进 URL；开辟路径有正则校验（`SAFE_TENANT_ID_PATTERN`），**读路径无** | `DynamicTenantRoutingDataSource.java:77-79` vs `TenantDatabaseProvisioner.java:30,186-190` | 高 |
| P2-23 | **无后台调度**：`grep @Scheduled` = 0 → 待审决策永不自动过期、向量孤儿无对账、策展无定时 | `server_runtime.py:50-57` 有对应物 | 高 |
| P2-24 | **`extraction_strategy` 16 参数零消费**；去重阈值硬编码 0.92/0.85（`config.yaml` 写 0.88/0.82）；无类型阈值/标题匹配/批内 n-gram/时间守卫/supersede | `ExtractionService.java:245,254`；`ConfigService:84,127` 仅透传 | 高 |
| P2-25 | **`MCP dim=768` 硬编码**（实际列与产出均为 1024）→ Agent 侧按错误维度理解检索 | `McpProtocolService.java:268`、`:107`、`:116` | 中 |
| P2-26 | **三处静默吞异常使健康分虚高**：`catch (Exception ignored) {}` 使治理聚合归零 → `riskScore` 变 100 | `StatsService.java:42,52,137` | 低 |

**附带（维护链数据危险）**：`GovernanceService.executeMaintenance:247-248` 的 `default` 分支把**任何未知 action（含 `merge`）**执行为「归档全部 `stale`」——用户以为在合并重复，实际批量归档。且维护执行**无备份、无跨进程锁、无 plan_token 校验**（Java 的 token 是随机 UUID，`GovernanceService.java:192`，执行时 `:235` 不比对）→ "确认后执行"退化为"随时执行当前状态"。

---

## 六、修复路线图

### 第一批 · 安全（最紧急）
| 序 | 任务 | 对应 |
|---|---|---|
| 1 | 写入端隐私脱敏（移植 `privacy.py` 八类规则 + 熵检测） | P0-3 |
| 2 | 上下文注入防护（`BOUNDARY_NOTICE` + 注入正则 + warnings 信封） | P0-4 |
| 3 | 鉴权收紧：管理面校验 key 归属与 scope；绑定 `127.0.0.1`；CORS 白名单 | P2-17/18/19 |
| 4 | `/api/v1/config/raw` 与 `/api/v1/config` 密钥脱敏 | P2-20 |

### 第二批 · 止损（正在腐化）
| 序 | 任务 | 对应 |
|---|---|---|
| 5 | 实体索引写回 + 检索别名归一与作用域过滤 | P0-1 |
| 6 | 治理决策执行器（decisions → memories 落地） | P0-2 |
| 7 | 摘除伪造指标，接入真实 `context_quality_events` 采集 + `injected_count` 回写 | P0-5 |

### 第三批 · 功能补齐
| 序 | 任务 | 对应 |
|---|---|---|
| 8 | 主体上下文（`resolve_project` / `infer_subject_from_title` / prompt 注入 / 标题前缀规则） | P1-6 |
| 9 | 规则策展引擎（promote / revive / stale / **置信度衰减**），打通 24 个 `rule_curator` 参数 | P1-7 |
| 10 | 向量缓存 `vector_cache`（内容哈希，含 `embedBatch` 归一化修正） | P1-12 |
| 11 | 治理台账 + undo（inverse 链 + 回滚端点） | P1-11 |
| 12 | 原子化拆分 + split 动作（含幂等守卫与 `part_of`/`supports`） | P1-8/10 |
| 13 | 画像学习环（LLM 抽取 + snapshot 注入 + F1/F2/F4 检索增强） | P1-14 |
| 14 | 上下文包构建（三路召回 + 加权排序 + 剪枝） | P1-15 |
| 15 | episodic 汇总 rollup | P1-9 |
| 16 | 向量同步队列 | P1-13 |

### 第四批 · 工程基线
| 序 | 任务 | 对应 |
|---|---|---|
| 17 | 测试补网：三个模块补测试依赖；优先鉴权矩阵 / 租户路由 / 配置优先级 / 连接池 | P2-16 |
| 18 | 连接池预算收敛（或提升 PG `max_connections` 并同步文档与 UI 文案） | P2-21 |
| 19 | JDBC URL 派生校验收敛为单一工具类 + 参数化测试 | P2-22 |
| 20 | 定时调度（自动过期 / 向量对账 / 策展） | P2-23 |
| 21 | `extraction_strategy` 参数接入；去重阈值改为读配置 | P2-24 |
| 22 | 清理悬空 hook 调用（`agent_presence_update` / `agent_capability_register`） | §2.2 |

---

## 七、附录

### 7.1 审计可复现命令

```bash
# MCP 工具面差异
grep -A2 '@_threaded_tool(mcp)' memorycore/server.py | grep -oE 'def [a-z_]+' | sed 's/def //' | sort -u
grep -rhoE 'case "[a-z_]+"' mcore-spring/mcore-mcp/ | sort -u

# 孤岛表（有表无码）
for t in $(psql -d mcore -tAc "SELECT tablename FROM pg_tables WHERE schemaname='public'"); do
  n=$(grep -rl "$t" --include='*.java' --include='*.xml' mcore-spring/ | grep -v target | wc -l)
  echo "$t: $n"
done

# 配置段消费率
grep -rn 'rule_curator\|subject_context\|extraction_strategy' --include='*.java' mcore-spring/ | grep -v target

# 实体索引时间戳错位
psql -d mcore -c "SELECT max(created_at) FROM memory_entities"
psql -d mcore -c "SELECT max(updated_at) FROM memories"
```

### 7.2 关键数据快照（2026-09-12）

| 项 | 值 |
|---|---|
| memories | 4874 条（project_path 空 3725 / 76%） |
| memory_entities | 7625 行（**止于 2026-09-10**） |
| memory_links | 2286 |
| audit_events | 54（含 Python 时代） |
| context_quality_events | 53（**止于 2026-09-10**） |
| user_profile_attrs | 10（全为 Java 硬编码常量写入） |
| governance_decisions | 0 |
| governance_executions / mutation_log | 0 / 0（**零实现**） |
| vector_cache / vector_sync_queue | 14（768 维 nomic 残留）/ 0（**零实现**） |
| agent_* 三表 | 0 / 0 / 0（Python 侧已废弃） |

### 7.3 相关文档

- 历史基线：`docs/iteration-number-map-2026-09-02.md`
- 多租户安全模型：`docs/mcore-multi-tenant-security-model.md`
- agent 拆除计划：`docs/plans/2026-08-24-governance-slimming.md`
