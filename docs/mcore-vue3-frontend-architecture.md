# MemoryCore (mcore) Vue 3 + Vite + TypeScript 前端现代化重构架构详案

> **归档位置**：`/workspace/output/mcore-vue3-frontend-architecture.md`  
> **战略定调**：将 mcore 现有的 Next.js 15 (React 19) 前端彻底重构为 **Vue 3.4+ (Composition API `<script setup>`) + Vite 5+ + TypeScript + Pinia + Tailwind CSS + ECharts** 的现代化全栈工程架构。

---

## 一、 核心架构优势与单 JAR 部署

1. **纯静态 SPA，摆脱 Node.js 运行时**：
   - 彻底告别 Next.js 15 的 `node server.js` 独立进程，无需在沙箱中长期常驻 Node 进程；
   - Vite 一键打包输出 `dist/` 纯静态产物。
2. **Spring Boot 静态资源嵌入（单 JAR 终极姿态）**：
   - 将 Vue 3 的 `dist/*` 直接复制到 Spring Boot 后端的 `src/main/resources/static/`；
   - 单个 `mcore-server.jar` 启动后：
     - `http://127.0.0.1:8318/mcp` ➔ Spring AI MCP 工具协议；
     - `http://127.0.0.1:8318/api/v1/*` ➔ 后端 REST API；
     - `http://127.0.0.1:8318/` ➔ 原生直接渲染 Vue 3 前端看板！
     - **端口从原来的双端口（8318 + 18318）彻底收敛为一个端口，节省系统内存与进程管理成本**！

---

## 二、 核心前端组件与多租户切换

### 1. 多租户 Axios 拦截器 (`src/api/client.ts`)
```typescript
import axios, { AxiosInstance } from 'axios';
import { useTenantStore } from '@/stores/tenant';

const apiClient: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  timeout: 30000,
});

apiClient.interceptors.request.use((config) => {
  const tenantStore = useTenantStore();
  if (tenantStore.currentTenantId) {
    config.headers.set('X-Tenant-Id', tenantStore.currentTenantId);
  }
  return config;
});

export default apiClient;
```

### 2. ECharts 知识图谱组件 (`src/components/graph/KnowledgeGraph.vue`)
采用 Apache ECharts 替代原先脆弱的 3D Canvas 堆砌，力导向图随当前租户的向量聚类自适应渲染。
