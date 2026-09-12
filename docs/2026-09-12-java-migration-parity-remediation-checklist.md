# mcore 迁移功能对齐 · 修复跟踪清单

> 关联审计报告：`docs/2026-09-12-java-migration-parity-audit.md`
> 用法：每项完成后勾选并补提交号。**禁止把未完成项标为已完成**。

## 第一批 · 安全（最紧急）

- [ ] **S1** 写入端隐私脱敏：移植 `privacy.py` 八类规则（openai_key/github_token/aws_access_key/aws_secret/bearer_token/pem_private_key/connection_string/env_assignment）+ Shannon 熵≥4.5 检测；接入 `memory_add` / `memory_update` / `ExtractionService` 写库前
- [ ] **S2** 上下文注入防护：`BOUNDARY_NOTICE` + 强制护栏 + 注入正则过滤 + `warnings` 信封（当前 Java 直接丢弃 warnings）
- [ ] **S3** 鉴权收紧
  - [ ] S3.1 管理面 `/api/v1/tenant/**` 校验 key 归属与目标租户一致 + scope 校验（当前任意有效 key 可跨租户开辟/销毁库、签发/吊销密钥）
  - [ ] S3.2 `application.yml` 增加 `server.address: ${MCORE_BIND:127.0.0.1}`，非回环且无 token 则拒绝启动（对标 Python `validate_frontend_bind`）
  - [ ] S3.3 CORS 从 `allowedOriginPatterns("*")` 收敛为显式白名单
  - [ ] S3.4 `writeError` 按 ErrorCode 映射 401/403（当前恒 401，与文档宣称的 403 不符）
- [ ] **S4** `/api/v1/config/raw` 与 `/api/v1/config` 对 `api_key` / `database.password` 脱敏为 `[REDACTED]`

## 第二批 · 止损（正在腐化）

- [ ] **S5** 实体索引写回：`MemoryRepository.insert/update` 后同步 `memory_entities`；检索补齐别名归一（`canonical_entity`）+ `status='active'` / `valid_until` / scope 过滤 + 权重排序；移除硬编码 `limit=20`
- [ ] **S6** 治理决策执行器：把 `governance_decisions` 按 `recommended_action` 真正作用到 `memories`（当前只改 review_status，前端假成功）
- [ ] **S7** 摘除伪造指标：`McpProtocolService:373-374` 的 `hit_rate=0.94` / `average_recall_ms=3.8`、`ContextLabController:41-49` 硬编码 trace；接入真实 `context_quality_events` 采集 + `injected_count` 回写

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

- [ ] **S23** `GovernanceService.executeMaintenance:247-248`：`default` 分支把**任何未知 action（含 merge）**执行为「归档全部 stale」；需改为显式 action 白名单 + 未知即拒绝
- [ ] **S24** 维护执行补：强制备份、跨进程锁、`plan_token` 内容哈希校验与幂等重放（当前 token 为随机 UUID 且执行时不比对）
