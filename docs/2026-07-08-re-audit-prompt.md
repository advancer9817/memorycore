# MemoryCore 复审审计 Prompt（Day 6 适配版）

> 基于 prompt-deep-audit-template.md 适配，聚焦增量审计
> 日期：2026-07-08

---

你是一位资深全栈工程师，现在需要对项目 `/home/advancer/project/memorycore` 进行一次**复审审计**。

## 审计背景

这是对 2026-07-02 首次深度审计的**第 6 天跟进复审**。首次审计发现 3 个核心问题并制定了 8 周迭代路线图。

### 已完成（验证效果即可，不需重复审计）

1. **召回率**：69% → 38.1%（已达终极目标 <40%）
2. **治理积压**：2,221 → 0（已超标完成）
3. **代码重构**（验证提交后的完整性）：
   - curator_llm.py (1,654行) → 7 文件包
   - frontend.py 1,457 → 500 行
   - search.py 1,178 → 403 行
   - server.py 1,146 → 679 行
4. **前端修复**：Error Boundary、SSR 守卫、catch(err: any) → unknown、6 个 shadcn 组件删除
5. **工程规范**：Ruff 配置、前端构建检查开启、.env.example、CHANGELOG.md
6. **SQLITE_VEC_AVAILABLE 已移除**：`__init__.py` 中的变量和 `__all__` 导出已清理
7. **3 个 shadcn 死组件已删除**：toggle.tsx、pagination.tsx、form.tsx

### 重点审计领域

1. Context Pack hit_rate：0.854，目标 >0.90
2. governance.py：1,253 行未拆分
3. 前端样式：Graph 模块 14 内联样式 + 30+ 硬编码颜色
4. 前端交互：无空状态/骨架屏/操作确认
5. Graph3D.tsx：13 处 any 类型
6. CI：只有 pytest，缺 ruff/前端构建/覆盖率阈值
7. LLM Curator：Phase 3 完全跳过，运行状态未知
8. 数据库：545 MB，无 WAL 优化
9. 总代码量：~31,500 行（目标 <28,000）

---

## 复审流程（基于 prompt-deep-audit-template.md 适配）

### 一、变更验证（替代全量代码扫描）

1. 对已拆分模块检查导入链完整性（无 ImportError）
2. 运行 `python -m pytest tests/ -q` 确认通过
3. 运行 `cd ui && pnpm build` 确认前端可构建
4. 列出所有 >500 行的文件（识别新的巨型文件）

### 二、未完成模块评估

对以下模块逐一回答模板问题（做了什么/实际效果/问题/噱头吗/怎么改）：

| 模块 | 要求 |
|------|------|
| governance.py (1,253行) | 具体拆分方案，标注文件名和行数分配 |
| Graph3D 类型安全 | 13 处 any 的具体替代方案 |
| CI 流水线 | 分阶段扩展方案（ruff → 前端构建 → 覆盖率） |
| LLM Curator | 查表判断运行状态，给出优化/降级建议 |

### 三、生产数据验证（不可跳过）

**必须执行的 SQL 查询**：

```sql
-- 1. 按 source 分组的召回统计（验证改善持续性）
SELECT source, COUNT(*) total,
  SUM(CASE WHEN injected_count = 0 THEN 1 ELSE 0 END) never_injected,
  ROUND(100.0 * SUM(CASE WHEN injected_count = 0 THEN 1 ELSE 0 END) / COUNT(*), 1) pct
FROM memories WHERE status = 'active'
GROUP BY source ORDER BY total DESC;

-- 2. 最近 7 天 hit_rate 趋势
SELECT DATE(created_at) d, COUNT(*) n, ROUND(AVG(hit_rate), 3) avg_hr
FROM context_quality_events
WHERE created_at > datetime('now', '-7 days')
GROUP BY d ORDER BY d;

-- 3. 治理状态确认
SELECT status, COUNT(*) FROM governance_decisions GROUP BY status;

-- 4. LLM Curator 最新运行
SELECT * FROM llm_curator_jobs ORDER BY created_at DESC LIMIT 5;

-- 5. 反馈密度
SELECT DATE(created_at) d, COUNT(*) FROM feedback_events
WHERE created_at > datetime('now', '-7 days') GROUP BY d;

-- 6. 数据库表大小分布
SELECT name, (SELECT COUNT(*) FROM memories) FROM sqlite_master WHERE type='table' LIMIT 1;
```

### 四、前端审计

#### 4.1 Bug 扫描（增量）
- 定位 Graph3D.tsx 剩余 any，逐一给出具体类型替代
- `pnpm build` 输出的 warning 清单
- AbortController 清理检查（5 处）

#### 4.2 组件瘦身（增量）
- 检查 Radix UI 未使用依赖
- 确认无其他 0 引用组件

#### 4.3 样式统一性（全量，重点 Graph 模块）
逐文件输出完整迁移清单：
- 所有 `style={{}}` → Tailwind 替代
- 所有 `#XXXXXX` → Tailwind token
- 格式：`文件:行号 | 违规类型 | 当前值 | 应改为`

#### 4.4 美观性评分（全量）
对 7 个页面（Dashboard、Memories、Memory Detail、Graph、Governance、Apps、Settings）：
- 逐维度评估（视觉层次、色彩和谐、留白、一致性、微交互、图标、深色模式、空状态、数据可视化）
- 每页评分 1-10 + Top 3 改进

#### 4.5 易用性评分（全量）
同上 7 页，逐维度评估（加载反馈、空状态引导、错误反馈、操作确认、表单、搜索、批量、键盘、无障碍）

#### 4.6 效率评分（全量）
同上 7 页，逐维度评估（步数、信息密度、导航、快捷键、记忆负担、响应式、首屏价值、数据刷新）

### 五、数据质量
- 545 MB 合理性评估 + 增长趋势
- WAL checkpoint 策略
- `memorycore/memory.sqlite3` 文件处理（0 字节副本？）

### 六、后端审计（增量）
- governance.py 1,253 行拆分方案
- N+1 查询定位（重点 api_routes.py）
- LLM Curator 内存字典 vs SQLite 状态一致性

### 七至十二、按原模板全量执行
- 部署体验（clone → 可用步骤和时间）
- 定时任务（LLM Curator 频率/效果）
- 工程规范清单
- 测试与 CI（51 文件 / 492 函数 / 覆盖率）
- 性能基准（冷启动、API P50/P99、Lighthouse）
- 开发者体验（一键启动、热重载、种子数据）
- 可维护性（i18n、依赖健康、扩展机制）

---

## 优化建议格式

每条建议：

```
### [编号]. [标题]
- **现状**：用数据描述
- **操作**：改哪个文件、改成什么
- **收益**：量化预期
- **验证**：改完怎么确认
- **路线图对应**：Phase X / Round Y / 新发现
```

P0 (功能已坏/安全/崩溃/数据丢失) → P1 (死代码/样式/状态不一致) → P2 (架构/部署) → P3 (测试/性能)
要求 12-20 条，至少 2 条 P0。

---

## 输出报告结构

（按原模板 15 节 + 新增第 16 节）

## 十六、复审对比

| 维度 | 首审评分 | 复审评分 | 变化 | 说明 |
|------|---------|---------|------|------|
| 功能完整性 | — | — | — | — |
| 代码质量 | — | — | — | — |
| 前端美观性 | — | — | — | — |
| 易用性 | — | — | — | — |
| 部署简易性 | — | — | — | — |
| 工程规范 | — | — | — | — |
| 安全性 | — | — | — | — |
| 测试覆盖 | — | — | — | — |
| 性能 | — | — | — | — |
| 开发者体验 | — | — | — | — |
| **综合** | **/100** | **/100** | — | — |

## 原则
- 用数据说话，不重复已完成工作
- 聚焦未完成项和新发现
- 建议落地到文件/行号/数值/命令
- 每条建议标注路线图对应关系

现在开始复审审计。
