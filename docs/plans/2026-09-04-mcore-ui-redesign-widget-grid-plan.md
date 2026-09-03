# MemoryCore (mcore) UI 重构实施计划：方案 C 模块化磁贴控制台 (Modular Widget Grid)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 mcore 现有的长列滚动 Dashboard 全面重构为基于 12 列自适应响应式网格的现代深色石墨云母（Dark Mica / Graphite）模块化磁贴控制台。

**Architecture:** 
采用组件化磁贴矩阵模式。创建专门的 Widget 体系（HealthRadarWidget、OperationsWidget、AgentMatrixWidget、GovernanceStreamWidget、ContextLabProbeWidget），由顶部工具栏 DashboardToolbar 和响应式 12 栅格容器统一调度，实现兼具高信息密度与就地操作能力的前端控制台。

**Tech Stack:** Next.js 15, React 19, TypeScript, Tailwind CSS, Lucide Icons, Redux Toolkit, shadcn/ui.

## Global Constraints

- 视觉风格严格遵守 Dark Graphite & Mica，清除旧版紫色/暖色混杂。
- 双语 i18n 字典必须保持严格对称（`en.ts` 与 `zh.ts` 一致，通过 `as const satisfies Messages` 类型检查）。
- 严禁随意删除或破坏核心功能（规则扫描、LLM 异步治理唤醒、决策审批、Context 权重探测均需完整可用）。
- 构建验证必须通过（`pnpm build` 或 `tsc --noEmit` 零报错），并成功部署至 `mcore-ui.service` (18318 端口)。

---

### Task 1: 创建模态磁贴组件目录与核心小部件

**Files:**
- Create: `ui/components/dashboard/widgets/HealthRadarWidget.tsx`
- Create: `ui/components/dashboard/widgets/OperationsWidget.tsx`
- Create: `ui/components/dashboard/widgets/AgentMatrixWidget.tsx`
- Create: `ui/components/dashboard/widgets/GovernanceStreamWidget.tsx`
- Create: `ui/components/dashboard/widgets/ContextLabProbeWidget.tsx`
- Create: `ui/components/dashboard/widgets/DashboardToolbar.tsx`
- Create: `ui/components/dashboard/widgets/index.ts`

- [ ] **Step 1: 编写 HealthRadarWidget (健康与安全雷达磁贴)**
包含质量分 (78)、安全合规水位 (100%)、可用池条数 (2,393)、关联度与复用覆盖率。
- [ ] **Step 2: 编写 OperationsWidget (四宫格快捷调度中心)**
集成一键运行规则扫描器、唤醒 LLM 语义治理、清理冷记忆候选、一键安全归档，带状态指示灯与上次/下次运行时间。
- [ ] **Step 3: 编写 AgentMatrixWidget (多智能体来源矩阵与资产分类)**
条形进度条直观呈现 Hermes / Claude / Rollup / Codex 占比，并矩阵化展示 4 类关键记忆实体量级。
- [ ] **Step 4: 编写 GovernanceStreamWidget (治理裁决流磁贴)**
内嵌 12 条待审批治理建议，提供 ARCHIVE、SUPERSEDE、MERGE 标签与就地一键批准/忽略。
- [ ] **Step 5: 编写 ContextLabProbeWidget (实时召回实验探针)**
内嵌实时 query 输入框，测试向量分+词法分综合相关度，提供展开完整 Context Lab 弹窗/抽屉能力。
- [ ] **Step 6: 编写 DashboardToolbar (仪表盘工具栏)**
展示预设布局标签、磁贴统计、重置布局按钮。

---

### Task 2: 组装首页并重构 `ui/app/page.tsx`

**Files:**
- Modify: `ui/app/page.tsx`

- [ ] **Step 1: 重构 `ui/app/page.tsx` 为 12 列自适应网格**
引入全部 Widget，以 `grid grid-cols-12 gap-4` 组织布局：
  - Row 1: `HealthRadarWidget` (4宽) + `OperationsWidget` (4宽) + `AgentMatrixWidget` (4宽)
  - Row 2: `GovernanceStreamWidget` (7宽) + `ContextLabProbeWidget` (5宽)
- [ ] **Step 2: 保留原面板组件作为深层模态或按需后备**
确保 ContextLab 与详细调参能够无缝在弹层或抽屉中调用，完全不破坏已有交互。

---

### Task 3: 对齐并补充 i18n 双语字典

**Files:**
- Modify: `ui/lib/i18n/dictionaries/en.ts`
- Modify: `ui/lib/i18n/dictionaries/zh.ts`

- [ ] **Step 1: 在 `en.ts` 中补充 widget 字典节点**
- [ ] **Step 2: 在 `zh.ts` 中镜像补齐对应中文翻译并确保 satisfies 校验通过**

---

### Task 4: 构建、启动与端到端验证

**Files:**
- Test: 执行 `cd /home/advancer/project/memorycore/ui && pnpm build`
- Deploy: 执行 `systemctl --user restart mcore-ui.service`
- Verify: 验证 `curl -I http://127.0.0.1:18318` 正常且浏览器可正常加载

- [ ] **Step 1: 运行 TypeScript 编译与 Next.js 构建检查**
- [ ] **Step 2: 重启 mcore-ui systemd 服务**
- [ ] **Step 3: 浏览器自动化/HTTP 状态码验证**
