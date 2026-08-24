# mcore 迭代规划（统合版）— 2026-08-24

> 统合本次会话诊断出的全部问题点（应用面板口径、健康度评分、LLM 治理链路、数据收敛、手动维护功能），编号为可执行的迭代项。
> 关联文档：`docs/plans/2026-08-24-manual-data-maintenance.md`（D 组详细设计）、`docs/plans/2026-08-24-governance-slimming.md`（I11 遗留）
> 数据基线：2026-08-24 实测（memories 8023 条；context hit rate 79.7% 健康）

---

## 0. 背景与基线

| 维度 | 实测值 | 备注 |
|---|---|---|
| 记忆总量 | 8023 | active 1219 / archived 5556 / stale 954 / contradicted 231 / superseded 63 |
| 从未被召回 | 5722（全库 71%） | 其中 4445 条已归档（死数据影子）；**active 池内仅 226 条从未使用 → active 真实复用率 81.5%** |
| 上下文命中率 | 79.7%（近 3 天） | 检索质量健康，不是瓶颈 |
| memory_links | 5888 条 / 覆盖 3405 条记忆（42.4%） | 评分面板没接这个真实数据 |
| LLM curator 最近 job | 2026-06-29 failed | 错误 = 「Job was interrupted by service restart」；last_result 卡在 failed |
| 健康度总分 | 56（需要治理） | 由 A/B 组口径缺陷主导失真（详见 B 组） |

---

## 1. 迭代项总览

| 编号 | 迭代项 | 类型 | 优先级 | 工作量 |
|---|---|---|---|---|
| A1 | agent_presence 生命周期闭环（session-end 写 idle/offline） | 修复 | P1 | 0.5 天 |
| A2 | 应用页「记忆总数」口径标签修正（active vs 全量） | 修复 | P1 | 0.5h |
| A3 | source_agent 显示名映射补全 + 来源规范化 | 增强 | P2 | 0.5h |
| A4 | 「已访问记忆」统计接真实数据（修复硬编码占位） | 修复 | P1 | 0.5 天 |
| B1 | LLM 治理评分去掉写死 45 分 | 修复 | P0 | 0.5h |
| B2 | 复用覆盖改 active 池口径 | 修复 | P0 | 0.5h |
| B3 | 链接覆盖公式 bug 修复 + 接入真实 link 数据 + 降权重 | 修复 | P0 | 0.5h |
| B4 | 非归档比例口径/方向修正 | 修复 | P1 | 0.5h |
| B5 | 风险控制「检测断供」提示（LLM 挂掉时 100% 是空转） | 增强 | P2 | 0.5h |
| C1 | 恢复 LLM curator 运行 + last_result 状态写回修复 | 修复 | P0 | 0.5 天 |
| C2 | 数据收敛批处理（stale/superseded/contradicted 归档 + active 从未访问降级） | 治理 | P0 | 0.5 天 |
| C3 | semantic_duplicate 候补决策确认合并 | 治理 | P2 | 手动 |
| D1 | 手动维护功能 M1：archive 闭环 + Dashboard 入口 | 新功能 | P1 | 0.5 天 |
| D2 | 手动维护功能 M2：merge（确定性 + governance auto_approved） | 新功能 | P2 | 0.5 天 |
| D3 | 手动维护功能 M3：clean 白名单硬删 + 备份 + 确认 | 新功能 | P2 | 0.5 天 |
| D4 | 手动维护功能 M4：审计展示/回滚（可选） | 增强 | P3 | 可选 |
| F1 | 画像参与召回排序（个性化 rerank，纯本地） | 增强 | P0 | 0.5 天 |
| F2 | 画像驱动查询扩展（提高召回命中） | 增强 | P1 | 0.5 天 |
| F3 | 画像自动更新闭环（新鲜度检测 + 增量刷新 + soft 属性衰减） | 增强 | P1 | 0.5 天 |
| F4 | 画像冲突过滤（矛盾记忆转 warnings） | 增强 | P1 | 0.5h |
| F5 | 画像贡献度度量（feedback 映射 + Dashboard 展示，可选） | 增强 | P3 | 可选 |
| E1 | I11 前端 8→4 页重设（governance-slimming 遗留） | 重构 | P2 | 独立排期 |

---

## 2. A 组 — 状态与统计口径修复（让面板数据可信）

### A1 — agent_presence 生命周期闭环
**问题**：`scripts/hooks/session-start.sh` 只写 `online`，无 session-end hook、无 TTL 降级 → claude/codex/gemini 的 presence 永久卡在 online（claude 最近真实心跳是 2026-07-02，仍显示绿色 online）；而刚活动过的 hermes 反而显示 idle（无 presence 记录时的 fallback 推断）。
**方案**：① `scripts/hooks/session-end.sh` 补 `agent_presence_update(status=idle)`，并部署到 Claude Code / Codex 的 Stop hook（`~/.claude/settings.json`）；② 后端 `_apps_list` 对 presence 加 TTL（如 last_seen 超过 24h 自动降级 idle → 超过 7 天 offline）。
**验证**：启动/关闭一次 Claude Code 会话，应用页状态应 online→idle；7 天前的 presence 不再显示 online。

### A2 — 应用页「记忆总数」口径标签
**问题**：应用页卡片「记忆总数 1210」= `WHERE status='active'`（= 看板「活跃」），看板「记忆总数 8010」= 全量含归档——同名不同义，用户困惑。
**方案**：应用页卡片改名「活跃记忆」（i18n en.ts/zh.ts 同步），或副标题注明「仅统计未归档」；不做数据变更。
**验证**：两页数字可互相解释（应用页总和 = 看板活跃数）。

### A3 — source_agent 显示名映射补全
**问题**：DB 内 source_agent 有 16+ 种原始名（hermes-cli / hermes-default / default-router / agent / memorycore-smoke-test / gemini / opencode…），`frontend_helpers._AGENT_DISPLAY_NAME` 只覆盖 8 个别名，「agent」被折叠进 claude 掩盖真实来源。
**方案**：补全映射表（opencode→opencode、gemini→gemini、memorycore-ui→frontend、memorycore-smoke-test→测试数据等）；同时给出**未映射原始名清单**展示真实来源。
**验证**：应用页列表与 DB 各 source_agent 计数对账一致。

### A4 — 「已访问记忆」统计接真实数据
**问题**：`frontend_v1.py` 中 `GET /api/v1/apps/{id}/accessed` 硬编码返回 `{"memories": [], "total": 0}`；`frontend_helpers._app_details` 硬编码 `total_memories_accessed: 0, first_accessed: None, last_accessed: None`。而 `memories.last_accessed_at` 实际有 2296+ 条非空数据（memory_context/memory_search 召回时已更新）——功能占位未实现。
**方案**：`_app_details` 按 app 的 source_agents 聚合 `last_accessed_at`（COUNT + MIN + MAX）；accessed 列表接口查 `last_accessed_at IS NOT NULL` 记录分页返回，附带 access_count（injected_count）。
**验证**：Claude 详情页「已访问记忆」显示真实数字（非 0），首次/最近访问时间与 DB 一致。

---

## 3. B 组 — 健康度评分体系修复（让指标说真话）

> 评分公式：`risk×0.34 + nonArchivedRatio×0.16 + connectedCoverage×0.18 + reuseCoverage×0.18 + llmGovernance×0.14`（`ui/components/dashboard/MemoryIntelligenceCenter.tsx`）

### B1 — LLM 治理评分去掉写死 45
**问题**：`llmGovernanceScore = llmStatus === "success" ? 100 : "running" ? 62 : 45` —— LLM curator 已是手动模式，没跑 ≠ 失败；现在被固定扣 45×0.14 = 6.3 分。
**方案**：改为「最近 N 次 LLM 运行成功率」（读 llm_curator_jobs 最近 5 条）；从未运行/无记录显示中性（如 「—」，计分时用中位或从公式临时剔除并归一化权重）。
**验证**：无运行记录时该指标不再亮红；成功跑一次后变绿。

### B2 — 复用覆盖改 active 池口径
**问题**：`reuseCoverage = inversePercentage(neverAccessed, totalMemories)`，分母是全库 8023（69% 已归档，4445 条归档死数据永不会再被召回）→ 显示 29% 假红。真实活跃池复用率 = (1219-226)/1219 = **81.5%**。
**方案**：指标改为 `active 池复用率 = (active - never_accessed_active) / active`；全库「死数据占比」降级为展示信息（不计分）。
**验证**：复用覆盖显示 ≈81% 绿色。

### B3 — 链接覆盖公式 bug 修复 + 真实数据接入
**问题**：`connectedCoverage = percentage(total - neverAccessed, total)` 与复用覆盖**完全同公式** → 两指标永远相等（截图 29%/29% 即证据）；且未使用 `memory_links` 真实数据（5888 链接 / 42.4% 覆盖率）。
**方案**：接入 `stats.link_count` / 唯一覆盖记忆数（或后端返回 linked_memories 计数），公式改为 `linked_unique_memories / active` 或全库口径；权重 0.18 → ~0.08（链接非检索瓶颈）。
**验证**：链接覆盖 ≈42%，与复用覆盖数值解耦。

### B4 — 非归档比例口径/方向修正
**问题**：`nonArchivedRatio = inversePercentage(archived, total)` 惩罚高归档健康库（69% 归档是 curator 维护良好的表现）；「2456 可用」中其实一半是 stale/superseded 待清理项。
**方案**：改为「可用池待清理占比 = (stale + superseded + 超期 contradicted) / (active + stale + contradicted + superseded)」（当前 ≈50%，这才是真该治理的信号）；或中性展示非归档数。
**验证**：健康库不再因高归档率亮红。

### B5 — 风险控制「检测断供」提示
**问题**：riskScore 100% 来自治理队列空 = LLM 检测断供时必空转 100%，虚高。
**方案**：LLM 治理状态非 success 时，risk 卡片附「检测数据可能过期」角标；C1 恢复后重算。
**验证**：LLM failed 期间风险卡显示提示而非纯绿。

---

## 4. C 组 — LLM 链路恢复 + 数据收敛（治本）

### C1 — 恢复 LLM curator 运行
**问题**：最近 job 2026-06-29 failed（`Job was interrupted by service restart`，非模型错误）；此后 last_result 一直 failed，语义重复/矛盾检测断供 → B5 空转 100 的根源。
**方案**：① 手动触发一次 `POST /api/curator/llm`（dry_run 先跑通；config 已是百炼 deepseek-v4-flash-0731，注意 max_tokens≥4096）；② 修复 job 状态写回：服务重启中断的 running job 应标记 `interrupted` 而非永远 failed，`last_result` 取**最新成功** job。
**验证**：llm_curator_jobs 出现 success 记录；Dashboard LLM 治理指标转绿。

### C2 — 数据收敛批处理
**问题/清单**（实测）：

| 目标 | 数量 | 动作 |
|---|---|---|
| stale 且从未访问 | 883 | 归档 |
| superseded 未归档 | 47 | 归档 |
| contradicted 超 90 天 | ~231 | 归档 |
| active 且从未访问 | 226 | 降级 candidate → TTL 后归档 |

**方案**：复用 `curator_report` 规则手动 apply 一次（`/api/curator/apply` limit 放大或分批）；active 从未访问用 downgrade 规则。**不做**「浓缩+观察期」（ROI 低，已否决）。
**验证**：收敛后 active ≈ 993 条且全部有使用记录；看板 stale/superseded 显著下降。

### C3 — semantic_duplicate 候补合并（C1 成功后）
**问题**：6/29 中断 job 曾产出 195 条 semantic_duplicate 候补，未进确认流程。
**方案**：C1 重跑成功后，在治理页批量确认合并（或接入 D2 的 merge 通道）。
**验证**：重复记忆合并后，risk 指标反映真实紧实状态。

---

## 5. D 组 — 手动「清理·合并·归档」维护功能

> 详细设计见 `docs/plans/2026-08-24-manual-data-maintenance.md`。核心：两阶段 API（plan 预览 → execute 幂等执行）+ Dashboard「一键维护」入口；执行顺序 备份 → 归档 → 合并 → 清理 → 向量同步；clean 强制备份 + UI 确认；互斥定时 curator；合并产物绝不设 active（防止污染 79.7% 命中率）。

| 编号 | 内容 | 说明 |
|---|---|---|
| D1 (M1) | archive 最小闭环 + Dashboard 按钮 | 复用 curator_report + update_status_batch；先只做归档 |
| D2 (M2) | merge：确定性 title 合并 + governance auto_approved 语义合并 | supersede 语义 + related_ids 血缘 |
| D3 (M3) | clean：白名单硬删（candidate 超 TTL / 测试数据 / 碎片）+ 备份 + 确认 | DELETE + FTS + Qdrant + vector_cache 同步 |
| D4 (M4) | 审计展示 / 备份回滚（可选） | 视需要排期 |

**与 C2 的关系**：C2 可作为 D1 的首个真实执行用例（dogfood）；D1 实现后 C2 通过 UI 完成而不走裸 API。

---

## 6. F 组 — 用户画像增强与召回融合

> 现状：画像层已落地（迭代 9/15：14 维 schema、`user_profile_attrs` 表、`storage/profile.py`、context_pack 必达注入 `user_profile_snapshot`、Profile Tab）。**缺口**：画像只作为固定块注入上下文头部，与检索排序、查询扩展完全割裂；画像低频更新（curator 2x/天）可能把过时画像"必达"进上下文。
> 关联：`docs/plans/2026-08-24-user-profile-layer.md`（已实现部分）；参考 `references/aliyun-long-term-memory-api.md`

### F1 — 画像参与召回排序（个性化 rerank）【P0，核心】
**问题**：`context_pack.py` 召回排序只用 lexical/vector/recency/type_weights，画像不参与 → "记忆召回"与"用户是谁"无关。
**方案**：排序阶段新增 `_profile_boost(record, profile_attrs)`：
- 读 `user_profile_attrs` → 提取画像特征词（技术栈/项目/平台/工作领域 value 分词）；
- 候选 title/content 与特征词 overlap → `score += overlap_ratio × profile_boost_weight`（config `context_pack.profile_boost_weight`，默认 0.15，可调可关）；
- 候选 user_profile 类记忆与 immutable 画像值矛盾 → `score × 0.6`。
**成本**：纯本地字符串匹配，零 LLM。**不改召回集合，只调排序** → 不影响 79.7% 命中率基线。
**验证**：带画像时"千帆/Java"相关记忆 top-k 排名上升；`context_quality_events` hit_rate 回归不降。

### F2 — 画像驱动查询扩展（query enrichment）【P1】
**问题**：task 原文拿去 FTS/向量检索，缩写/领域词（如"周报助手""DSH"）依赖记忆文本自身命中。
**方案**：检索前，task 与画像属性值做词重叠 → 从重叠属性提取 ≤3 个关键词追加为扩展检索词（bigram），与原文检索结果合并重排。仅当重叠度 > 阈值才扩展（防漂移）。
**成本**：零 LLM。**验证**：task「周报助手方案」能召回千帆周报相关记忆；A/B 对比 hit_rate 不降。

### F3 — 画像自动更新闭环【P1】
**问题**：画像随 curator 2x/天聚合，新事实记忆产生后画像可能过时，"必达注入"变成"过时必达"。
**方案**：① 新鲜度检测：context_pack 注入前比较 `max(user_profile 记忆 created_at)` vs `user_profile_attrs.max(updated_at)`，滞后超阈值时注入块附「画像可能过时」标记；② 增量刷新：ingest 产生 user_profile 记忆后置 dirty，下次 curator 用 `extract_profile(only_new=True)` 只对新记忆 diff 抽取；③ soft 属性 confidence 衰减（每 30 天 ×0.95，immutable 不衰减）。
**成本**：每次刷新 1 次 LLM（有新鲜度门槛，不热路径）。**验证**：写入新 user_profile 记忆 → 检测到滞后 → 增量刷新 → 画像 updated_at 更新且注入块标记消失。

### F4 — 画像冲突过滤【P1，0.5h】
**问题**：召回的 user_profile 类记忆可能与画像当前值矛盾（旧记忆说 A、画像已是 B），两边同时注入上下文。
**方案**：context_pack 注入 user_profile 类型记忆时与画像当前值对比，矛盾者不注入正文、转入 warnings（附画像当前值提示，复用现有 injection_guard/contradicts 机制）。
**成本**：零 LLM。**验证**：旧记忆「模型偏好=阿里云」+ 画像「官方 DeepSeek」→ 旧记忆出现在 warnings 而非正文。

### F5 — 画像贡献度度量（可选，P3）
**方案**：`memory_feedback` 与画像属性 source_ids 关联 → 属性级正向反馈率；Profile 页展示「画像贡献度」。用于指导 schema 调整。可选排期。

---

## 7. E 组 — 遗留衔接

### E1 — I11 前端 8→4 页重设（governance-slimming 遗留）
目标：8 路由页 → 4 核心页（Dashboard+Context Lab / Memories / Graph / Settings），Apps/Governance 内联。**依赖 A 组/B 组完成后数据面板可信**，D 组入口纳入 Dashboard 内联。独立排期。

---

## 8. 依赖与执行顺序

```
B1-B4 + A2/A4 (口径修复, ~半天)
      │
      ▼
C1 (恢复 LLM, 半天) ──► C3 (合并候补)
      │
      ▼
C2 (数据收敛) ──► 与 D1 合流 (D 组作为收敛的 UI 化实现)
      │
      ▼
F1/F4 (画像召回融合, 纯本地) ──► F2 (查询扩展) ──► F3 (更新闭环, 依赖 C1 LLM 健康)
      │
      ▼
A1/A3/B5 + D2/D3 (增强项)
      │
      ▼
E1 (前端 4 页, 独立排期)
```

- **B 组先行**：先让指标可信，C/D 的动作效果才能被正确度量（否则"治理完还是 56 分"）。
- **C1 先行于 C2/C3**：LLM 恢复后，风险/重复检测才有供给。
- **D1 与 C2 合流**：数据收敛通过手动维护功能完成，UI 化交付。
- **F1/F4 可与 B 组并行**（纯本地、不依赖 LLM、只动排序）；F3 需 C1 后（依赖 LLM 抽取链路健康）。
- **F1/F2 安全约束**：只调排序/扩展词，不扩大最终注入集 → 不破坏 79.7% 命中率基线；所有系数 config 可调 + `enabled` 开关。

---

## 9. 风险与回滚

| 风险 | 缓解 |
|---|---|
| C2 批量归档误伤有用记忆 | 先 dry-run 报告核对；归档可逆（reject 语义）；contradicted 只处理超 90 天 |
| B 组改评分后指标口径变化引发困惑 | i18n 同步更新说明文案；detail 行保留原始数字 |
| D3 硬删不可逆 | 强制自动备份 + UI 二次确认 + 审计记录删除清单 |
| C1 LLM 运行耗时长/失败 | dry_run 先行；max_tokens≥4096；沿用 job 轮询不阻塞请求 |
| A1 session-end hook 影响 Claude/Codex 启动 | hook 遵循现有「失败不阻断会话」设计（exit 0 always） |
| F1/F2 个性化加权顶起无关记忆 | boost 系数保守（0.15）+ 冲突降权有限 + config 开关；改后跑 hit_rate 回归 |
| F2 查询扩展词漂移导致无关召回 | 重叠度阈值门槛 + 扩展词 ≤3 + A/B 对比验证 |
| F3 自动刷新引入热路径 LLM 成本 | 仅新鲜度超阈值才触发；增量 diff 抽取（only_new）；soft 衰减不调 LLM |
| F3 画像过时注入误导 | 注入块附「可能过时」标记；min_confidence 门槛保留 |

---

## 10. 验收口径（全局）

- [ ] 应用页与看板所有数字口径一致、可互相解释；
- [ ] 健康度各指标基于真实数据、口径正确，红牌只反映真问题；
- [ ] LLM curator 恢复运行且状态正确回写；
- [ ] 数据收敛后 active 池复用率 ≥ 80% 且无从未访问的 active 残留；
- [ ] 手动维护功能 D1-D3 可用（预览→确认→执行→结果+备份路径）；
- [ ] 画像参与召回排序且 hit_rate 回归不降（F1）；查询扩展命中领域记忆且不漂移（F2）；画像新鲜度检测与增量刷新闭环（F3）；矛盾记忆入 warnings（F4）；
- [ ] 全程测试全绿、每迭代独立 commit、ITERATION.md 按完成情况追加记录。