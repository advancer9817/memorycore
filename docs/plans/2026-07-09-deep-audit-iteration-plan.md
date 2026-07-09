# MemoryCore 深度审计迭代计划（2026-07-09）

> 基于 `prompt-deep-audit-template.md` 对项目全量重新审计
> 审查日期：2026-07-09
> 审查范围：后端 17,149 行 Python / 前端 11,729 行 TSX / 数据库 547.7 MB / 7,264 条记忆
> 上次审计：2026-07-03（8 轮重构后的第 6 天复审）

---

## 一、项目现状快照

### 核心指标

| 指标 | 7/2 基线 | 7/9 现状 | 目标 | 状态 |
|------|---------|---------|------|------|
| active 未召回率 | 68.3% | **31.9%** (387/1211) | < 40% | **达标** |
| needs_review 积压 | 2,221 | **0** | < 200 | **超额达标** |
| MCP 工具数 | 46 | **23** | ~22 | **基本达标** |
| hit_rate (7d) | 0.816 | **0.804** | > 0.90 | **未达标，且在下降** |
| 代码总量 | 31,100 | **17,149** (后端) | < 28,000 | **达标** |
| 测试通过率 | 491/497 | **477/497** (17 failing) | 100% | **恶化** |

### 数据规模

| 维度 | 数值 |
|------|------|
| 总记忆数 | 7,264 |
| active 记忆 | 1,211 |
| archived | 5,134 |
| stale | 736 |
| 治理决策 | 15,339 (99.7% applied) |
| 审计事件 | 33,620 |
| 反馈事件 | 3,434 |
| 记忆链接 | 5,833 |
| 数据库大小 | 547.7 MB |
| 表数量 | 24 |

### 关键发现

1. **hit_rate 持续下降**：从 6/27 的 0.995 → 7/2 的 0.872 → 7/9 的 0.647，趋势明确恶化
2. **governance_split 仍是最大未召回源**：481 条中 226 条 (47.0%) 从未被注入
3. **effectiveness 分布严重偏低**：1,013/1,211 (83.6%) 在 mid(0.3-0.6) 区间，高分 (0.8+) 仅 39 条 (3.2%)
4. **测试退化**：从 493/497 → 477/497，新增 14 个失败用例
5. **重复记忆**：8 条同标题 "LLM Curator 降级为手动触发模式"
6. **14 个前端废弃依赖**：59 个 npm 依赖中至少 14 个完全未使用
7. **大文件未拆**：frontend.py(1624行)、governance.py(1281行)、search.py(1176行)、server.py(1155行)
8. **Phase 4 闭环增强完全未做**：提取 prompt 个性化、种子反馈、feedback_loop 均不存在
9. **Graph 模块样式硬编码**：35 处 inline style，33 处硬编码颜色值

---

## 二、优化建议（按优先级排序）

### P0 — 立即处理

#### 1. hit_rate 持续下降——召回算法急需修复

- **现状**：hit_rate 从 0.995 (6/27) 滑落至 0.647 (7/9)，14 天内下降 35%。同期 used_count 从 12.3 上升到 21.9，说明候选池在膨胀但精度在下降
- **根因**：
  1. `_MIN_VECTOR_ONLY_RELEVANCE_SCORE` 从 0.35 降到 0.30 扩大了噪声进入候选池
  2. `vector_top_k` 从 30 提高到 40，低质量候选更多
  3. governance_split 产出的碎片记忆 (avg_len=98) 稀释了候选池质量
  4. cross_retrieval_rate 仅 0.065（FTS 和向量几乎各找各的），融合效果差
- **操作**：
  1. `memorycore/storage/search.py`: `_MIN_VECTOR_ONLY_RELEVANCE_SCORE` 回调至 0.35
  2. `memorycore/storage/search.py`: `vector_top_k` 回调至 30
  3. `memorycore/storage/context_pack.py`: 在候选排序中增加 `content_length` 惩罚——content < 50 字符的记忆排序权重 ×0.5
  4. 对 governance_split 来源且 injected_count=0 且 age > 14d 的记忆批量降级为 stale
- **预期收益**：hit_rate 恢复到 0.85+，used_count 回落到 14-16
- **风险**：可能丢失部分有效碎片记忆。缓解：先 stale 不删，观察 7 天后 hit_rate 趋势再决定是否永久归档
- **验证方法**：连续 3 天 `SELECT ROUND(AVG(hit_rate),3) FROM context_quality_events WHERE created_at > datetime('now','-3 days')` 稳定在 0.85+

#### 2. 测试套件退化——17 个失败必须修复

- **现状**：477/497 通过，17 个失败。按类别：
  - `test_docs_consistency` (3): README 与实际工具数不一致
  - `test_curator_apply` (3): curator apply 逻辑与 governance 变更不兼容
  - `test_context_relevance` (2): 召回阈值调整后测试断言过期
  - `test_graph_enhanced` (3): graph API 和 warning 行为变更
  - `test_phase10` (2): memory_warnings 行为变更
  - `test_temporal` (1): lineage 分支检测
  - `test_auto_supersession` (1): auto_approved 路由逻辑
  - `test_dashboard_ops` (1): dashboard 数据结构变更
  - `test_curator_llm_jobs` (1): curator job 执行链路
- **根因**：多轮重构后测试未同步更新，特别是 governance 自动化、MCP 工具精简、hit_rate 调参后的断言
- **操作**：按失败类别逐个修复：
  1. `test_docs_consistency`: 更新 README 中的工具数为 23，重新生成 `docs/tools.md`
  2. `test_curator_apply`: 适配 `auto_policy` 在豁免列表中的新行为
  3. `test_context_relevance`: 更新阈值断言匹配当前 `_MIN_VECTOR_ONLY_RELEVANCE_SCORE`
  4. 其余逐一排查断言与实际行为的 diff
- **预期收益**：测试通过率恢复到 497/497
- **风险**：低。修复测试不影响生产行为
- **验证方法**：`.venv/bin/python -m pytest tests/ -q --tb=short` 全部通过

---

### P1 — 短期处理（1-2 天）

#### 3. governance_split 碎片记忆清理

- **现状**：governance_split 来源有 481 条 active 记忆，47.0% 从未被召回；平均内容长度仅 98 字符，effectiveness 最低 (0.538)
- **根因**：LLM Curator 的 split 阶段将长记忆拆成多个碎片，这些碎片语义不完整、FTS 匹配率低
- **操作**：
  1. 批量将 `source='governance_split' AND injected_count=0 AND created_at < datetime('now','-14 days')` 的记忆状态改为 `stale`
  2. 在 `config.yaml` 中设置 `llm_curator.split_enabled: false`（如未配置则在 curator_llm 代码中默认跳过 split 阶段）
  3. 验证 `memorycore/storage/curator_llm/split_detector.py` 有可关闭的开关
- **预期收益**：active 记忆未召回率从 31.9% 降至 ~25%；hit_rate 改善（候选池噪声减少）
- **风险**：少量 split 碎片可能有价值。缓解：先 stale 不删，保留 rollback 可能
- **验证方法**：`SELECT COUNT(*) FROM memories WHERE status='active' AND source='governance_split' AND injected_count=0` 应为 0

#### 4. 重复记忆去重

- **现状**：8 条同标题 "LLM Curator 降级为手动触发模式"，另有 9 组重复（3x1 + 2x8）
- **根因**：extraction 或手动写入缺乏标题去重校验
- **操作**：
  1. 对每组重复，保留 `effectiveness_score` 最高的一条，其余标记为 `archived`
  2. 在 `memorycore/dedup.py` 的 `ingest()` 中添加标题精确匹配检查——若同 title + 同 type 的 active 记忆已存在，走 update 而非 add
- **预期收益**：消除 ~15 条重复记忆，减少召回噪声
- **风险**：低
- **验证方法**：`SELECT title, COUNT(*) c FROM memories WHERE status='active' GROUP BY title HAVING c > 1` 返回空

#### 5. 14 个废弃 npm 依赖清理

- **现状**：59 个 npm 依赖中有 14 个完全未被代码引用：
  - Radix UI: aspect-ratio, avatar, context-menu, hover-card, menubar, navigation-menu, radio-group, toggle, toggle-group (9个)
  - 其他: embla-carousel-react, input-otp, @hookform/resolvers, react-hook-form, sass
- **根因**：shadcn/ui 初始化时批量安装，部分组件后来被删除但依赖未清理
- **操作**：`cd ui && pnpm remove @radix-ui/react-aspect-ratio @radix-ui/react-avatar @radix-ui/react-context-menu @radix-ui/react-hover-card @radix-ui/react-menubar @radix-ui/react-navigation-menu @radix-ui/react-radio-group @radix-ui/react-toggle @radix-ui/react-toggle-group embla-carousel-react input-otp @hookform/resolvers react-hook-form sass`
- **预期收益**：node_modules 减小；package.json 从 59 降到 45 个依赖
- **风险**：低。确认 `pnpm build` 仍通过
- **验证方法**：`pnpm build` 成功；`grep -r "removed-package-name" ui/app ui/components` 返回空

#### 6. 静默异常处理修复

- **现状**：至少 3 处 bare `except Exception:` 不记录日志：
  - `memorycore/storage/atomization.py:147` — 吞掉原子化错误
  - `memorycore/storage/atomization.py:252` — 吞掉原子化错误
  - `memorycore/storage/curator_llm/report.py:374,425` — 吞掉 curator 报告错误
- **根因**：早期代码防御性写法，异常被静默吞掉导致问题不可观测
- **操作**：为所有 bare except 添加 `logger.warning("...", exc_info=True)`
- **预期收益**：问题可观测性提升；调试效率大幅改善
- **风险**：低
- **验证方法**：`grep -rn "except.*:\s*$\|except.*pass" memorycore/ --include="*.py"` 返回空

---

### P2 — 中期重构（1-2 周）

#### 7. 四大文件拆分

- **现状**：4 个文件超过 1000 行：
  - `frontend.py` (1,624行, 42 函数) — API 路由 + 辅助函数混杂
  - `governance.py` (1,281行, 30 函数) — 决策创建 + mutation + 统计
  - `search.py` (1,176行, 35 函数) — FTS + 向量 + context pack 入口
  - `server.py` (1,155行, 60 函数) — MCP 工具 + CLI + 初始化
- **根因**：前期已做了抽取（api_helpers.py, api_routes.py, cli.py, context_pack.py, fts_search.py），但原文件未缩减——抽取的是副本而非迁移
- **操作**：

  **frontend.py → 3 个文件：**
  - `memorycore/api/routes.py` (~600行) — 所有 FastAPI 路由定义
  - `memorycore/api/helpers.py` (~500行) — 辅助函数和数据转换
  - `memorycore/api/__init__.py` (~100行) — app 创建和中间件
  - 删除 `memorycore/api_helpers.py` 和 `memorycore/api_routes.py`（当前是未使用的副本）

  **governance.py → 3 个文件：**
  - `memorycore/storage/governance_core.py` (~500行) — 决策创建和 apply
  - `memorycore/storage/governance_mutations.py` (~400行) — mutation 执行
  - `memorycore/storage/governance_stats.py` (~300行) — 统计和查询
  - `memorycore/storage/governance.py` — 保留为 re-export 入口

  **search.py → 确认抽取生效：**
  - 确认 `context_pack.py`(682行) 和 `fts_search.py`(137行) 是否被实际使用
  - 如果是副本未使用，则执行真正的迁移
  - 目标：search.py 缩减到 < 400 行

  **server.py → 2 个文件：**
  - `memorycore/mcp_tools.py` (~600行) — 所有 @mcp.tool 定义
  - `memorycore/server.py` (~400行) — 初始化、CLI 入口
  - 确认 `memorycore/cli.py` 是否实际被使用

- **预期收益**：所有文件 < 700 行；维护成本降低
- **风险**：中。import 链调整可能引入 bug。缓解：每个文件拆完立即跑测试
- **验证方法**：`find memorycore -name "*.py" -exec wc -l {} + | sort -rn | head -5` 最大文件 < 700 行

#### 8. Graph 模块样式统一

- **现状**：Graph 模块有 35 处 inline style、33 处硬编码颜色值（`#05070c`, `#52525b`, `rgba(255,255,255,0.06)` 等）。主要集中在：
  - `GraphTopbar.tsx` — 7 处 inline style
  - `GraphNodeList.tsx` — 4 处
  - `GraphFilterPanel.tsx` — 2 处
  - `Graph3D.tsx` — 约 15 处
- **根因**：Graph 模块使用 Three.js 渲染，部分样式在 canvas overlay 上需要精确控制，但大量可用 Tailwind 替代
- **操作**：
  1. 将 `border: "1px solid rgba(255,255,255,0.06)"` → `border border-zinc-800`
  2. 将 `background: "#05070c"` → `bg-zinc-950`
  3. 将 `color: "#52525b"` → `text-zinc-600`
  4. 对 Three.js 画布上的颜色提取为 `lib/graph-theme.ts` 常量
  5. 保留 `style={{ width/height/transform }}` 等动态计算值
- **预期收益**：样式可维护性提升；深色模式一致性；删除 ~30 处 inline style
- **风险**：低。纯样式变更不影响功能
- **验证方法**：`grep -rn "style={{" ui/app/graph --include="*.tsx" | wc -l` < 5（仅保留动态值）

#### 9. Phase 4 提取-召回闭环（部分实施）

- **现状**：`docs/plans/2026-06-30-phase4-extraction-recall-loop.md` 中设计的 4 个子模块全部未实现：
  - 3.1 写入时原子化 — ExtractedFact 仍无 title 字段
  - 3.2 提取 prompt 个性化 — 无 `_build_memory_profile()`
  - 3.3 种子反馈 — 无 `_seed_feedback()`
  - 3.4 反向调节 — 无 `feedback_loop.py`
- **根因**：Phase 1-3 工作量超预期，Phase 4 一直被推迟
- **操作**（分步，先做 ROI 最高的两项）：

  **Step 1: ExtractedFact 增加 title 字段**
  - `extraction.py:213`: dataclass 增加 `title: str = ""`
  - `extraction.py` ADDITIVE_EXTRACTION_PROMPT: 要求 LLM 输出 `{"title": "...", "content": "...", ...}`
  - `dedup.py`: 使用 `fact.title` 而非 `fact.text[:80]` 作为记忆标题
  - 预期：标题语义完整性从 ~60% 提升到 95%+

  **Step 2: 种子反馈**
  - `dedup.py`: ingest 写入成功后，对新记忆调用 `_seed_feedback()`
  - 种子分计算：importance >= 0.8 (+0.3)、有 linked_ids (+0.2)、type 属于高召回类型 (+0.15)、content 长度 50-200 (+0.1)
  - 预期：新记忆冷启动加速，effectiveness_score 高分率从 3.2% 提升到 10%+

  **暂缓**：prompt 个性化 (3.2) 和反向调节 (3.4) 待 Step 1-2 效果验证后再决定

- **预期收益**：提取质量提升 → 召回精度提升 → hit_rate 改善
- **风险**：中。LLM 输出 schema 变更可能影响 ingest 稳定性。缓解：旧 schema 兼容解析
- **验证方法**：
  - `SELECT AVG(LENGTH(title)) FROM memories WHERE source='extraction' AND created_at > datetime('now', '-7 days')` > 20
  - `SELECT COUNT(*) FROM feedback_events WHERE note='auto:seed' AND created_at > datetime('now', '-7 days')` > 0

---

### P3 — 长期方向（2-4 周）

#### 10. 数据库瘦身（547 MB → < 200 MB）

- **现状**：547.7 MB 对 7,264 条记忆来说异常大。主要膨胀来源：
  - `governance_decisions`: 15,339 行 + `governance_executions`: 15,123 行 + `governance_mutation_log`: 19,928 行
  - `audit_events`: 33,620 行
  - `llm_curator_batches`: 2,855 行
  - 总治理/审计相关数据占 ~85,000 行
- **操作**：
  1. 归档 30 天前的 `audit_events` 到 `audit_events_archive` 表或导出 JSON
  2. 归档 30 天前的 `governance_mutation_log`
  3. 清理 `governance_executions` 中状态为 `completed` 且 > 30 天的记录
  4. 运行 `VACUUM` 回收空间
  5. 设置定期清理 cron（每周归档 > 30 天的审计/治理日志）
- **预期收益**：数据库从 547 MB 降到 < 200 MB；查询性能提升
- **风险**：中。审计数据丢失。缓解：先导出 JSON 备份
- **验证方法**：`ls -lh memory.sqlite3` < 200 MB

#### 11. cross_retrieval_rate 提升

- **现状**：cross_retrieval_rate 仅 0.065（目标 > 0.15），说明 FTS 和向量搜索几乎完全独立运行
- **根因**：
  1. FTS5 默认 Unicode 分词对中文不友好，导致 FTS 和向量返回的候选集几乎不重叠
  2. 融合策略是简单的 union，没有交叉加权
- **操作**：
  1. 在 `search.py` 的融合逻辑中，对同时被 FTS 和向量命中的记忆给予 1.5x 权重加成
  2. 考虑引入 jieba 分词预处理（在 FTS5 索引写入时）
  3. 定期重建 FTS 索引以适配新的分词策略
- **预期收益**：cross_retrieval_rate 从 0.065 提升到 0.15+；hit_rate 间接改善
- **风险**：中。分词库引入新依赖；FTS 重建耗时
- **验证方法**：`SELECT ROUND(AVG(cross_retrieval_rate),3) FROM context_quality_events WHERE created_at > datetime('now', '-7 days')` > 0.15

#### 12. 前端组件大文件拆分

- **现状**：3 个前端文件超过 400 行：
  - `form-view.tsx` (725行) — 通用表单组件
  - `MemoryOperationsPanel.tsx` (533行) — Dashboard 操作面板
  - `FilterComponent.tsx` (486行) — 记忆列表过滤器
- **操作**：
  - `form-view.tsx`: 拆分为 `FormField.tsx` + `FormLayout.tsx` + `FormView.tsx`
  - `MemoryOperationsPanel.tsx`: 拆分为 `CuratorControls.tsx` + `RunHistory.tsx` + `OperationsPanel.tsx`
  - `FilterComponent.tsx`: 拆分为 `FilterChips.tsx` + `FilterDropdown.tsx` + `FilterComponent.tsx`
- **预期收益**：每个文件 < 250 行；组件可复用性提升
- **风险**：低
- **验证方法**：`pnpm build` 成功；所有文件 < 300 行

#### 13. 前端 `any` 类型清理

- **现状**：75 处 `any` 类型（含 `as any`），主要集中在：
  - `Graph3D.tsx` — Three.js 相关约 13 处
  - API 响应类型未定义处
- **操作**：
  1. 为 Graph3D 的 Three.js 对象定义接口 `GraphNode3D`, `GraphLink3D`
  2. 为 API 响应定义 `types/api.ts` 类型文件
  3. 启用 `tsconfig.json` 中 `"noImplicitAny": true`（增量）
- **预期收益**：类型安全提升；IDE 提示改善
- **风险**：低
- **验证方法**：`grep -rn ": any\|as any" ui/ --include="*.tsx" --include="*.ts" | grep -v node_modules | wc -l` < 20

#### 14. form-view.tsx 废弃评估

- **现状**：`form-view.tsx` (725行) 是最大的前端组件，但 `react-hook-form` 和 `@hookform/resolvers` 都在废弃依赖列表中，暗示此组件可能已废弃
- **操作**：
  1. 确认 `form-view.tsx` 是否被任何页面引用
  2. 如果无引用，直接删除（连同依赖一起清理）
  3. 如果有引用，评估是否可以简化（去掉 react-hook-form 依赖）
- **预期收益**：删除 725 行死代码 + 2 个依赖
- **风险**：低。确认引用后操作
- **验证方法**：`grep -r "form-view" ui/app --include="*.tsx" | wc -l` 判断引用数

---

## 三、投入产出矩阵

```
                          高价值
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
        │  ①hit_rate修复    │                   │
        │  ②测试修复        │  ⑨闭环增强        │
        │  ③split清理       │  ⑪cross_retrieval │
        │  ④去重            │                   │
        │  ⑥静默异常        │                   │
        │                   │                   │
        ├───────────────────┼───────────────────┤
        │                   │                   │
        │  ⑤依赖清理        │  ⑦文件拆分        │
        │                   │  ⑧样式统一        │
        │                   │  ⑩DB瘦身          │
        │                   │  ⑫组件拆分        │
        │                   │  ⑬any清理         │
        │                   │                   │
        └───────────────────┼───────────────────┘
                            │
       低投入 ─────────────┼──────────────── 高投入
                          低价值
```

---

## 四、实施计划

### 阶段 A：急修（1-2 天）

| 编号 | 任务 | 预计时间 |
|------|------|----------|
| ①  | hit_rate 召回参数回调 + governance_split 碎片降级 | 2h |
| ③  | governance_split 碎片批量 stale | 1h |
| ④  | 重复记忆去重 | 30min |
| ⑥  | 静默异常处理修复 | 1h |

### 阶段 B：测试恢复 + 依赖清理（1-2 天）

| 编号 | 任务 | 预计时间 |
|------|------|----------|
| ②  | 17 个失败测试修复 | 4h |
| ⑤  | 14 个废弃 npm 依赖清理 | 30min |
| ⑭  | form-view.tsx 废弃评估 | 30min |

### 阶段 C：架构重构（1-2 周）

| 编号 | 任务 | 预计时间 |
|------|------|----------|
| ⑦  | 四大文件拆分 | 2d |
| ⑧  | Graph 模块样式统一 | 4h |
| ⑬  | any 类型清理 | 4h |

### 阶段 D：闭环增强（1 周）

| 编号 | 任务 | 预计时间 |
|------|------|----------|
| ⑨  | Phase 4 Step 1: ExtractedFact title + Step 2: 种子反馈 | 1d |
| ⑪  | cross_retrieval_rate 优化 | 1d |

### 阶段 E：长期维护（按需）

| 编号 | 任务 | 预计时间 |
|------|------|----------|
| ⑩  | 数据库瘦身 | 2h |
| ⑫  | 前端组件大文件拆分 | 4h |

---

## 五、验证矩阵

| 阶段 | 验证方法 | 通过标准 |
|------|----------|----------|
| A | hit_rate 连续 3 天 | > 0.85 |
| A | governance_split 未召回数 | 0 |
| B | pytest 通过率 | 497/497 |
| B | `pnpm build` | 0 errors |
| C | 最大 Python 文件行数 | < 700 |
| C | Graph inline style 数 | < 5 |
| D | effectiveness_score 高分率 | > 10% |
| D | cross_retrieval_rate | > 0.15 |
| E | 数据库大小 | < 200 MB |

---

## 六、与前序计划的关系

| 前序计划文档 | 状态 | 本计划对应 |
|-------------|------|-----------|
| `2026-06-29-framework-redesign.md` Phase 1 (MCP精简) | **已完成** | — |
| `2026-06-29-framework-redesign.md` Phase 2 (治理简化) | **已完成** | — |
| `2026-06-29-framework-redesign.md` Phase 3 (前端重设计) | **部分完成** | ⑧⑫⑬ |
| `2026-06-29-framework-redesign.md` Phase 4 (闭环增强) | **未开始** | ⑨ |
| `2026-07-02-iteration-roadmap.md` Phase 0-2 | **已完成** | — |
| `2026-07-02-iteration-roadmap.md` Phase 3 (LLM Curator) | **跳过** | 不再追踪 |
| `2026-07-02-iteration-roadmap.md` Phase 4 (代码重构) | **部分完成** | ⑦ |
| `2026-07-02-iteration-roadmap.md` Phase 5 (前端+验证) | **未开始** | ⑤⑧⑫⑬ |
| 新发现: hit_rate 退化 | **P0 新增** | ① |
| 新发现: 测试退化 | **P0 新增** | ② |
| 新发现: 重复记忆 | **P1 新增** | ④ |

---

## 七、总结

- **一句话定性**：MemoryCore 是一个实质项目，核心价值链（提取→存储→召回）已基本打通，但近期代码调参导致召回质量回退，需要立即修复
- **核心价值链**：`extraction.py` → `dedup.py` → `search.py/context_pack.py`（提取-去重-召回三件套）
- **最大风险**：hit_rate 持续下降趋势如不扭转，记忆系统的核心价值（精准召回）将被严重削弱
- **优化核心原则**：**先修复回退，再推进增强**——召回质量是一切的基础，在 hit_rate 恢复到 0.85+ 之前不应做其他大改动
