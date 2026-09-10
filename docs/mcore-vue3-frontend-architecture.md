# MemoryCore (mcore) Vue 3 + Vite + TypeScript 前端现代化重构架构详案

> **归档位置**：`docs/mcore-vue3-frontend-architecture.md`  
> **战略定调**：将 mcore 现有的 Next.js 15 (React 19) 前端彻底重构为 **Vue 3.4+ (Composition API `<script setup>`) + Vite 5+ + TypeScript + Pinia + Tailwind CSS + ECharts** 的现代化全栈工程架构。  
> **部署与工程原则**：**前端与后端严格彻底分离，独立工程目录、独立构建打包、独立服务部署**。

---

## 一、 前后端分离与独立打包部署体系

### 1. 架构定位与物理边界解耦
- **后端定位（Java 17 + Spring Boot 3）**：专注于 FastMCP 协议接口（8318 端口 `/mcp`）、RESTful 核心业务 API（`/api/v1/*`）、多租户物理库路由与 pgvector 向量计算。后端工程不包含任何前端静态资源，产物为纯净的 `mcore-server.jar`。
- **前端定位（Vue 3 + Vite 5）**：纯静态单页面应用（SPA），专注于现代化多租户管理看板、力导向知识图谱可视化、记忆审查与系统观测。
- **解耦价值**：
  - **独立构建打包**：前端采用 `pnpm build` 秒级产出纯静态 `dist/`，后端采用 `mvn clean package` 产出独立 JAR，互不依赖对方编译环境（Node.js 与 JDK/Maven 彻底解耦）。
  - **独立服务部署**：前端由高性能静态 Web 服务器（如 Nginx / Caddy / 轻量 Web 服务）独立承载；后端由独立 Linux 服务守护进程（如 systemd `mcore-backend.service`）托管，彼此生命周期独立。
  - **零停机平滑更新**：前端样式、图表与界面逻辑变更仅需替换静态文件与刷新 CDN/浏览器缓存，后端无需重启，MCP 连接与长任务零抖动；后端升级维护不影响前端静态页面的稳定呈现。

---

## 二、 生产与开发环境部署拓扑

```
+-------------------------------------------------------------+
|                      Client (Browser)                       |
+------------------------------+------------------------------+
                               |
            +------------------+------------------+
            | HTTP / HTTPS                        | HTTP / HTTPS
            v                                     v
+-----------------------+             +-----------------------+
|   Frontend Service    |             |    Backend Service    |
| (Nginx / Caddy / Web) |             |    (Spring Boot 3)    |
|      Port: 18318      |             |      Port: 8318       |
|                       |             |                       |
|  - Vue 3 纯静态 SPA   |             |  - Spring AI MCP (/mcp)
|  - dist/* 静态资源    |             |  - REST API (/api/v1) |
|  - ECharts 渲染       |             |  - 多租户物理路由库   |
+-----------+-----------+             +-----------+-----------+
            |                                     ^
            | (跨域 CORS / Nginx 反向代理)        |
            +-------------------------------------+
```

### 1. 推荐部署模式（Nginx 动静分离反代）
在生产网关（如宿主机 Nginx 或 Caddy）层配置统一代理：
```nginx
server {
    listen 18318;
    server_name localhost;

    # 1. 前端纯静态 SPA 托管
    location / {
        root /workspace/memorycore/ui/dist;
        index index.html;
        try_files $uri $uri/ /index.html;
    }

    # 2. 接口反向代理至独立后端 (8318)
    location /api/ {
        proxy_pass http://127.0.0.1:8318;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    # 3. FastMCP 协议接口代理
    location /mcp {
        proxy_pass http://127.0.0.1:8318/mcp;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}
```

### 2. 双端口独立直连模式（CORS 跨域解耦）
若前端与后端跨不同端口或不同域名部署：
- **后端配置**：Spring Boot 注入标准 WebMvc CORS 规则，放行前端独立来源（如 `http://localhost:18318` 或指定管理后台域名），允许带凭据与 `X-Tenant-Id` 请求头。
- **前端配置**：前端打包时注入环境变量：
  ```bash
  VITE_API_BASE_URL=http://127.0.0.1:8318/api/v1
  ```

---

## 三、 核心前端组件与多租户状态

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
采用 Apache ECharts 替代原先脆弱的 3D Canvas 堆砌，力导向图随当前租户的向量聚类自适应渲染，支持平滑缩放、点击跳转与多租户拓扑对比。
