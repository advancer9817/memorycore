# MemoryCore 全面重构计划

**日期**: 2026-07-02  
**审计范围**: 前端 + 后端完整代码库  
**目标**: 修复所有 bugs、删除死代码、统一样式、优化架构

---

## 执行摘要

### 前端问题统计
- 🔴 **Critical**: 4 个严重问题
- 🟠 **High**: 5 个高优先级问题  
- 🟡 **Medium**: 7 个中优先级问题
- 🔵 **Low**: 5 个低优先级问题

### 后端问题统计
- 🔴 **Critical**: 2 个严重问题
- 🟠 **High**: 2 个高优先级问题
- 🟡 **Medium**: 4 个中优先级问题
- 🔵 **Low**: 4 个低优先级问题

---

## Phase 1: Critical 严重问题修复（第1天）

### 1.1 后端 Critical 修复

#### 🔧 移除废弃的 SQLITE_VEC_AVAILABLE
**文件**: `memorycore/__init__.py:28`, `memorycore/server.py:115`

```python
# 删除这两处声明
# SQLITE_VEC_AVAILABLE = False  
```

#### 🔧 修复缺失的 yaml 导入
**文件**: `memorycore/api_helpers.py`

```python
# 在文件顶部添加
import yaml
```

### 1.2 前端 Critical 修复

#### 🔧 添加全局错误边界
**文件**: `ui/app/error.tsx` (新建)

```tsx
'use client';

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html>
      <body>
        <div className="flex h-screen items-center justify-center">
          <div className="text-center">
            <h2 className="text-2xl font-bold">Something went wrong!</h2>
            <button onClick={() => reset()}>Try again</button>
          </div>
        </div>
      </body>
    </html>
  );
}
```

#### 🔧 修复 useEffect 依赖项
**文件**: `ui/app/settings/page.tsx:61`, `ui/app/memories/page.tsx:25`

修复所有缺失的依赖项警告。

#### 🔧 替换所有 `any` 类型
**文件**: 15 个文件，共 62 处

使用 `unknown` + 类型守卫替换。

---

## Phase 2: High 高优先级修复（第2-3天）

### 2.1 后端 High 修复

#### 🔧 注册未暴露的 MCP 工具
**文件**: `memorycore/server.py:242-285`

```python
@mcp.tool()
@_safe_tool
def memory_curator_report(
    dry_run: bool = True,
    limit: int = 500,
) -> dict[str, Any]:
    """Rule-based curator: mark stale/archive records without deleting."""
    return curator_report(dry_run=dry_run, limit=limit)

@mcp.tool()
@_safe_tool
def memory_rollup_report(
    dry_run: bool = True,
    user_id: str = "default",
) -> dict[str, Any]:
    """Roll up episodic memories into long-term summaries."""
    return rollup_report(dry_run=dry_run, user_id=user_id)

@mcp.tool()
@_safe_tool
def memory_atomize_report(
    dry_run: bool = True,
    limit: int = 100,
) -> dict[str, Any]:
    """Split large memory records into atomic facts."""
    return atomize_report(dry_run=dry_run, limit=limit)
```

#### 🔧 统一 LLM Curator 状态管理
**文件**: `memorycore/frontend.py`, `memorycore/storage/llm_curator_jobs.py`

移除内存字典 `_llm_curator_jobs`，完全使用 SQLite。

### 2.2 前端 High 修复

#### 🔧 统一颜色系统
**文件**: `ui/lib/design-tokens.ts` (新建)

```typescript
export const colors = {
  background: {
    primary: '#020408',
    secondary: '#18181b',
    tertiary: '#27272a',
  },
  border: {
    default: 'rgba(255,255,255,0.06)',
    focus: 'rgba(139,92,246,0.5)',
  },
  text: {
    primary: '#ffffff',
    secondary: '#a1a1aa',
    muted: '#52525b',
  },
  accent: {
    violet: '#8b5cf6',
    violetHover: '#7c3aed',
  },
} as const;
```

修改所有硬编码颜色的文件（33 处）。

#### 🔧 统一 API 错误处理
**文件**: `ui/lib/api-client.ts` (新建)

```typescript
import axios from 'axios';
import { getApiBaseUrl } from './api-url';

export const apiClient = axios.create({
  baseURL: getApiBaseUrl(),
  timeout: 10000,
});

apiClient.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    const message = error instanceof Error 
      ? error.message 
      : 'An unknown error occurred';
    
    // 统一错误处理
    console.error('[API Error]', message);
    return Promise.reject(new Error(message));
  }
);
```

重构所有 hooks 使用 `apiClient`。

#### 🔧 修复内存泄漏风险
**文件**: `ui/hooks/useMemoriesApi.ts`, `ui/hooks/useAppsApi.ts`

为所有异步操作添加清理函数：

```typescript
useEffect(() => {
  let cancelled = false;
  
  const fetch = async () => {
    const data = await api();
    if (!cancelled) setData(data);
  };
  
  fetch();
  return () => { cancelled = true; };
}, []);
```

---

## Phase 3: Medium 中优先级改进（第4-7天）

### 3.1 前端架构重构

#### 📦 统一类型定义
**文件**: `ui/lib/types/` (新建目录)

```
ui/lib/types/
  ├── memory.ts      // 统一所有 Memory 类型
  ├── app.ts         // 统一所有 App 类型
  ├── api.ts         // API 响应类型
  └── index.ts       // 导出
```

删除重复的类型定义。

#### 📦 拆分 Graph 页面复杂度
**文件**: `ui/app/graph/hooks/` (新建目录)

将 `useGraphPage.ts` 拆分为：
- `useGraphData.ts` - 数据获取
- `useGraphFilters.ts` - 筛选逻辑
- `useGraphSelection.ts` - 选择状态
- `useGraphEditing.ts` - 编辑模式

#### 📦 提取缓存逻辑
**文件**: `ui/hooks/useApiCache.ts` (新建)

```typescript
export function useApiCache<T>(
  key: string, 
  fetcher: () => Promise<T>,
  ttl = 30_000
) {
  // 统一缓存逻辑
}
```

#### 📦 国际化系统
**文件**: `ui/i18n/` (新建目录)

```
ui/i18n/
  ├── zh-CN.json
  ├── en-US.json
  └── index.ts
```

### 3.2 后端架构重构

#### 📦 拆分 curator_report
**文件**: `memorycore/storage/curator.py`

```python
def _categorize_candidates(rows, config) -> dict[str, list]:
    """将记录分类为 decay/stale/archive/promote 候选"""
    pass

def _apply_curator_actions(actions, dry_run) -> dict:
    """批量应用curator决策"""
    pass

def curator_report(dry_run, limit, ...) -> dict:
    rows = _fetch_candidates(limit)
    candidates = _categorize_candidates(rows, config)
    if not dry_run:
        return _apply_curator_actions(candidates, dry_run)
    return {"dry_run": True, "candidates": candidates}
```

#### 📦 分离 frontend.py 职责
**文件**: 重构为 3 个文件

```
memorycore/
  ├── frontend.py         # Starlette 路由 + 静态资源
  ├── background_jobs.py  # LLM curator 后台线程
  └── api_routes.py       # REST API（现有）
```

---

## Phase 4: 样式统一和组件优化（第8-10天）

### 4.1 设计系统规范

#### 🎨 创建设计系统文档
**文件**: `ui/docs/design-system.md`

```markdown
# MemoryCore Design System

## Colors
- Primary: zinc-900 (#18181b)
- Accent: violet-500 (#8b5cf6)
- Background: zinc-950 (#09090b)

## Typography
- Heading: font-semibold
- Body: font-normal
- Code: font-mono

## Spacing
- xs: 0.25rem (1)
- sm: 0.5rem (2)
- md: 1rem (4)
- lg: 1.5rem (6)
- xl: 2rem (8)

## Border Radius
- sm: 0.25rem
- md: 0.375rem
- lg: 0.5rem
- xl: 0.75rem
- full: 9999px
```

#### 🎨 统一组件样式
修改所有组件遵循设计系统。

### 4.2 删除无用组件

#### 🗑️ 删除未使用的 shadcn/ui 组件
**目录**: `ui/components/ui/`

运行依赖分析：
```bash
npx depcheck
```

删除未使用的组件。

#### 🗑️ 合并重复的 Skeleton 组件
**文件**: `ui/components/ui/skeleton-loader.tsx` (新建)

合并：
- `MemorySkeleton.tsx`
- `MemoryCardSkeleton.tsx`
- `MemoryTableSkeleton.tsx`

---

## Phase 5: 响应式和无障碍性（第11-12天）

### 5.1 响应式优化

#### 📱 Graph 页面移动端支持
**文件**: `ui/app/graph/page.tsx`

添加移动端降级显示：
```tsx
{isMobile ? (
  <MobileGraphView />
) : (
  <Graph3D />
)}
```

#### 📱 表格横向滚动优化
**文件**: `ui/app/governance/page.tsx`

添加响应式表格容器。

### 5.2 无障碍性改进

#### ♿ 添加 ARIA 标签
为所有交互元素添加 `aria-label`。

#### ♿ 键盘导航
确保所有功能可用键盘操作。

---

## Phase 6: 性能优化（第13-14天）

### 6.1 前端性能

#### ⚡ 代码分割
**文件**: `ui/next.config.mjs`

```javascript
const nextConfig = {
  experimental: {
    optimizePackageImports: ['lucide-react', 'recharts'],
  },
};
```

#### ⚡ 图片优化
使用 Next.js Image 组件。

### 6.2 后端性能

#### ⚡ 修复 N+1 查询
**文件**: `memorycore/storage/entities.py`

使用 JOIN 或批量查询。

#### ⚡ 添加批量 API
**文件**: `memorycore/storage/crud.py`

```python
def add_memory_record_batch(records: list[dict]) -> list[dict]:
    """批量插入记录"""
    pass

def add_link_batch(links: list[dict]) -> list[dict]:
    """批量添加链接"""
    pass
```

---

## Phase 7: 测试和文档（第15-16天）

### 7.1 添加单元测试

#### 🧪 前端测试
**工具**: Vitest + React Testing Library

```bash
cd ui
pnpm add -D vitest @testing-library/react @testing-library/jest-dom
```

优先测试：
- `useApiCache` hook
- API client 错误处理
- 类型守卫函数

#### 🧪 后端测试
**工具**: pytest（已有）

优先测试：
- `dedup.decide()` 核心去重逻辑
- `curator_report()` 生命周期规则
- `governance.policy_gate()` 安全策略

### 7.2 更新文档

#### 📝 API 文档
**文件**: `docs/api-reference.md`

记录所有 MCP 工具和 REST 端点。

#### 📝 开发指南
**文件**: `docs/development-guide.md`

包含：
- 本地开发设置
- 代码规范
- 测试指南
- 部署流程

---

## Phase 8: 代码质量工具（第17天）

### 8.1 前端工具

#### 🔧 启用 TypeScript 严格模式
**文件**: `ui/tsconfig.json`

```json
{
  "compilerOptions": {
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "noImplicitReturns": true
  }
}
```

#### 🔧 配置 ESLint 规则
**文件**: `ui/.eslintrc.json`

```json
{
  "rules": {
    "@typescript-eslint/no-explicit-any": "error",
    "@typescript-eslint/no-unused-vars": "error",
    "react-hooks/exhaustive-deps": "error"
  }
}
```

#### 🔧 添加 Pre-commit Hooks
**文件**: `ui/.husky/pre-commit`

```bash
#!/bin/sh
npm run lint
npm run type-check
```

### 8.2 后端工具

#### 🔧 配置 Ruff
**文件**: `pyproject.toml`

```toml
[tool.ruff]
line-length = 120
select = ["E", "F", "I", "N", "W"]
ignore = ["E501"]

[tool.ruff.per-file-ignores]
"__init__.py" = ["F401"]
```

#### 🔧 配置 mypy
**文件**: `pyproject.toml`

```toml
[tool.mypy]
python_version = "3.11"
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true
```

---

## 执行清单

### 第 1 天 - Critical 修复
- [ ] 后端：移除 SQLITE_VEC_AVAILABLE
- [ ] 后端：添加 yaml 导入
- [ ] 前端：添加全局错误边界
- [ ] 前端：修复 useEffect 依赖项
- [ ] 前端：开始替换 any 类型

### 第 2-3 天 - High 修复
- [ ] 后端：注册 3 个 MCP 工具
- [ ] 后端：统一 LLM Curator 状态管理
- [ ] 前端：创建统一颜色系统
- [ ] 前端：重构 API client
- [ ] 前端：修复内存泄漏

### 第 4-7 天 - Medium 改进
- [ ] 前端：统一类型定义
- [ ] 前端：拆分 Graph 页面
- [ ] 前端：提取缓存逻辑
- [ ] 前端：国际化系统
- [ ] 后端：拆分 curator_report
- [ ] 后端：分离 frontend.py

### 第 8-10 天 - 样式统一
- [ ] 创建设计系统文档
- [ ] 删除无用组件
- [ ] 统一所有组件样式

### 第 11-12 天 - 响应式和无障碍
- [ ] Graph 页面移动端优化
- [ ] 表格响应式优化
- [ ] 添加 ARIA 标签
- [ ] 键盘导航支持

### 第 13-14 天 - 性能优化
- [ ] 前端代码分割
- [ ] 图片优化
- [ ] 修复后端 N+1 查询
- [ ] 添加批量 API

### 第 15-16 天 - 测试和文档
- [ ] 添加前端单元测试
- [ ] 添加后端单元测试
- [ ] 更新 API 文档
- [ ] 编写开发指南

### 第 17 天 - 代码质量工具
- [ ] 启用 TypeScript 严格模式
- [ ] 配置 ESLint
- [ ] 添加 Pre-commit Hooks
- [ ] 配置 Ruff 和 mypy

---

## 风险和依赖

### 高风险项
1. 统一 LLM Curator 状态管理（可能影响现有功能）
2. 拆分 Graph 页面（复杂度高）
3. 启用 TypeScript 严格模式（可能暴露大量错误）

### 依赖关系
- Phase 2 依赖 Phase 1 完成
- Phase 4 依赖 Phase 3 类型系统完成
- Phase 8 依赖所有功能稳定

---

## 成功指标

### 代码质量
- [ ] TypeScript 严格模式无错误
- [ ] ESLint 0 错误
- [ ] 测试覆盖率 > 60%
- [ ] `any` 类型使用 < 10 处

### 性能
- [ ] 首屏加载 < 2 秒
- [ ] API 响应 < 500ms
- [ ] Bundle 大小 < 500KB

### 用户体验
- [ ] 所有页面支持移动端
- [ ] 键盘导航完整
- [ ] 无 console 错误

---

**预计总工期**: 17 天  
**优先级**: Critical > High > Medium > Low  
**并行任务**: 前端和后端可同时进行
