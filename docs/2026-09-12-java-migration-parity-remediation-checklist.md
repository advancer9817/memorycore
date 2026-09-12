# mcore 迁移功能对齐 · 修复跟踪清单

> 关联审计报告：`docs/2026-09-12-java-migration-parity-audit.md`
> 用法：每项完成后勾选并补提交号。**禁止把未完成项标为已完成**。

## 第一批 · 安全（最紧急）

- [x] **S1** 写入端隐私脱敏：移植 `privacy.py` 八类规则（openai_key/github_token/aws_access_key/aws_secret/bearer_token/pem_private_key/connection_string/env_assignment）+ Shannon 熵≥4.5 检测；接入 `memory_add` / `memory_update` / `ExtractionService` 写库前
      → `RedactionService.java`（214 行）+ `MemoryRepository.redactInPlace()` 统一守卫 + `memoryMapper.insertAuditEvent()` 真实审计写入（原 `insertAuditLog` 指向不存在的 `memory_audit_logs` 表，是死代码）
      → **实测**：长度 96→81、含 `[REDACTED`、审计 `{"count":2,"labels":["openai_key","connection_string"]}`
      → **踩坑**：`MemoryQueryService.createMemory:273` 直接调 `memoryMapper.insert` **绕过** `MemoryRepository`，导致首轮修复失效（`redacted_pos=0`）；已补齐该路径
- [x] **S2** 上下文注入防护：`BOUNDARY_NOTICE` + 强制护栏 + 注入正则过滤
      → `InjectionGuard.java`（8 条正则，对标 `injection_guard.py`）+ `ContextPackBuilder` 接线 + `ContextPackResponse.warnings/filteredCount` 字段
      → **实测**：注入探针被召回后从正文剔除、正文不含 `ignore all previous instructions`、过滤清单披露「因安全原因未展示」
- [x] **S3** 鉴权收紧
  - [x] S3.1 管理面 `/api/v1/tenant/**` 校验 key 归属与目标租户一致 + scope 校验
        → `TenantAuthFilter.extractAdminTargetTenant()` + `authorizeAdminTarget()`；`admin` scope 才可跨租户/枚举
        → **实测**（demo 密钥 scopes=[read,write] 模拟远端）：`/tenant/list` **403**、`/tenant/user_1002/keys` **403**、`DELETE /tenant/user_1002` **403**、`/tenant/demo/keys` **200**
  - [x] S3.2 `server.address: ${MCORE_BIND:127.0.0.1}`
        → **实测**：监听由 `*:8318` 变为 `[::ffff:127.0.0.1]:8318`
  - [x] S3.3 CORS 收敛为显式白名单（`mcore.cors.allowed-origins`，默认本地 UI 18318）
        → **实测**：`Origin: https://evil.example.com` 无 ACAO 头；`http://127.0.0.1:18318` 正常放行
  - [x] S3.4 `writeError` 按 ErrorCode 映射 401/403
        → **实测**：越权返回 **403**（原恒 401）
- [x] **S4** `/api/v1/config/raw` 与 `/api/v1/config` 对 `api_key` / `database.password` 脱敏为 `[REDACTED]`
      → `ConfigService.maskedRaw()` + `maskValue()` + 写入侧 `putIfPresent` 忽略哨兵（防设置页保存把真 key 覆写成 `[REDACTED]`）
      → **实测**：`config/raw` 返回 `extraction.api_key=[REDACTED]`、`database.password=[REDACTED]`；`embedding.api_key` 空值保持空（区分"未设置"）

## 第二批 · 止损（正在腐化）

- [x] **S5** 实体索引写回：`EntityExtractor`（抽取+别名归一，对标 `entities.py` 249 行）+ `EntityIndexService`（先删后插/ON CONFLICT/非 active 清除/项目兜底）；`EntityRepository.searchEntities` 由裸 LIKE 改为归一 IN + active/valid_until/scope/project_path 过滤 + 权重排序 + boost
      → **实测**：探针生成 5 条实体行（path 1.0 / file 0.9 / port 0.9 / `memorycore`→`mcore` / `ollama`）；查询 `memorycore` 命中 `normalized=mcore`；boost=0.30
      → **附带修复**：`EntityMapper.xml` insert 漏写 `aliases_json`+`weight` 且无 ON CONFLICT
- [x] **S6** 治理决策执行器：`executeDecision()` 真正作用到 `memories` + 台账 `governance_executions`/`governance_mutation_log` + `rollbackDecision()` + rollback 端点
      → **实测**：status active→archived、台账 before/after/inverse 完整、归档后实体行清零、二次 apply 幂等（1→1）、回滚 archived→active
- [x] **S7** 摘除伪造指标：新增 `QualityMetricsRepository` 真实聚合；`ContextLabController` trace 按实际命中分数推导
      → **实测**：`hit_rate` 0.94→**0.6613**；`average_recall_ms` 3.8→**null** + `latency_available:false`（审计表无耗时字段，如实留空）

## 第三批 · 功能补齐

- [ ] **S8** 主体上下文（subject_context）：`resolve_project` / `infer_subject_from_title` / `discover_projects` / `active_context_block`；提取 prompt 注入 subject 字段与标题前缀规则；打通 `config.yaml:129-143`（当前 76% 记忆 project_path 为空）
- [ ] **S9** 规则策展引擎：promote / revive / mark_stale / archive + **置信度衰减执行**；打通 `rule_curator` 剩余 21 个参数（当前 24 个只消费 3 个）
- [ ] **S10** 向量缓存 `vector_cache`：内容哈希键 `(sha256(title+space+content), model)`，读路径短路 + 批量回写；顺带修正 `embedBatch` 缺 `normalize()` 的不一致
- [ ] **S11** 治理台账 + undo：`governance_executions` / `governance_mutation_log` 写入 + inverse 链 + 回滚端点（当前 `rollback_json` 是死字段）
- [ ] **S12** 原子化拆分 + split 动作：`should_atomize` / `plan_child_facts` / `fact_hash` 幂等键 / `part_of`+`supports` 双链 / uuid5 确定性 child_id
- [ ] **S13** 画像学习环：LLM 抽取替换硬编码常量 + `profile_snapshot` 注入 + F1（feature_words/overlap_ratio）/ F2（query_expansion）/ F4（conflict_for_record）+ `decay_profile_attributes` + `profile_freshness_warning`
- [ ] **S14** 上下文包构建：三路召回（FTS + 向量 + 实体）+ 加权排序 + 类型权重 + 原子剪枝 + 相似聚类 + 分组上限
- [ ] **S15** episodic 汇总 rollup
- [ ] **S16** 向量同步队列（持久化重试 + 退避 + 死信）

## 第四批 · 工程基线

- [ ] **S17** 测试补网：`mcore-server` / `mcore-tenancy` / `mcore-common` 补 `spring-boot-starter-test`；优先 `TenantAuthFilter` 鉴权矩阵 / 租户库名派生 / `ConfigFileStore` / 连接池
- [ ] **S18** 连接池预算收敛（128 → ≤97）或提升 PG `max_connections` 并同步 `ITERATION.md`、`Settings.vue` 的 150 文案
- [ ] **S19** 库名派生收敛为单一工具类（当前 3 份重复）+ JDBC URL 参数校验 + 参数化测试（含 `../`、`?`、`#`、超长）
- [ ] **S20** 定时调度（自动过期 / 向量对账 / 策展）
- [ ] **S21** `extraction_strategy` 16 参数接入；去重阈值改读配置（当前硬编码 0.92/0.85，配置写 0.88/0.82）
- [ ] **S22** 清理悬空 hook 调用：`scripts/hooks/session-start.sh:133-134`、`session-end.sh:40` 的 `agent_presence_update` / `agent_capability_register`（Java 无此工具，返回 -32601 被 `|| true` 静默吞掉）；同步修正 `tests/test_deployment.py:149` 断言

## 维护链数据危险项（建议并入 S6/S11 一起修）

- [x] **S23** `executeMaintenance` 的 `default` 分支改为显式白名单，未知动作一律拒绝且零写入
      → **实测**：`action=merge` → `unsupported_maintenance_action`
- [x] **S24** 维护执行补：`plan_token`=sha256(动作+排序候选id) 落库可校验 + 漂移检测 + 强制快照 + PG advisory lock + 幂等重放；候选集谓词与执行谓词统一
      → **实测**：缺/伪造 token 拒绝；漂移 `plan_drift`（planned 1→current 0）；幂等重放返回既有结果
