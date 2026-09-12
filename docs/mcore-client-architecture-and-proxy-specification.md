# mcore 客户端架构与反向代理规范 (mcore-client Specification)

> **版本**：v1.0 (迭代 252 规划)  
> **归属工程**：MemoryCore (`/workspace/memorycore/docs/`)  
> **定位**：运行于开发者本地工作站/笔记本的轻量级透明中继客户端，向上接管本地各类 AI Agent 与生命周期 Hooks，向下统一连接远端/本地 mcore 服务端。

---

## 一、 角色定位与设计哲学

在 mcore 整体架构解耦中，**客户端（mcore-client）** 扮演着“智能边车（Smart Sidecar）与统一安全网关”的角色：

1. **统一本地接入面（Unified Local Ingress）**：
   - 本地所有工具与组件（Claude Code, Hermes CLI/Serve, Codex, Gemini, OpenCode, VSCode/Cursor 插件, 浏览器前端）**强制且唯一**面向 `http://127.0.0.1:8318` 发起请求；
   - 本地 Agent 配置文件中永不出现外部公网域名或局域网 IP，屏蔽上游环境的所有复杂性。

2. **单点事实源配置中心（Single Point of Truth）**：
   - 远程服务端地址（`server_url`）、租户标识（`tenant_id`）、访问密钥（`api_key`）仅在客户端配置一次；
   - 切换生产云端、自建 NAS、本地沙箱时，只需一条指令更改客户端上游配置，全机所有 Agent 立即无缝漫游。

3. **双向安全与凭据代理（Security & Credential Broker）**：
   - 客户端负责出站请求的协议清洗、租户头（`X-Tenant-Id`）与鉴权凭据（`X-API-Key`）的透明组装；
   - 避免将明文 API Key 散落存储在各大 Agent 的设置文件或版本受控仓库中。

4. **端点自治与离线韧性（Resilience & Offline Autonomy）**：
   - 客户端维护本地轻量高速缓存与持久化预写日志队列（WAL Queue）；
   - 在远程服务端临时不可达、网络闪断或离线移动办公时，对记忆召回提供本地兜底，对会话提炼回写提供本地安全暂存与自动重放。

---

## 二、 协议接口与转发规范

客户端在本地 `127.0.0.1:8318` 监听并暴露三类核心接口：

### 2.1 FastMCP 协议透明转发 (`POST /mcp`)
- **下游（本地 Agent）**：接受标准 JSON-RPC 2.0 格式（`initialize`、`tools/list`、`tools/call` 等）；
- **上游（远端服务端）**：
  - 维持持久连接池（Connection Pool）与长连接复用；
  - 自动附加 HTTP 标头：
    ```http
    X-Tenant-Id: <client.tenant_id>
    X-API-Key: <client.api_key>
    X-Client-Info: mcore-client/<version>
    ```
  - 协议双模兼容：兼容将远端的标准 `application/json` 或流式 `text/event-stream` 平滑转化为下游 Agent 所期望的传输格式。

### 2.2 原生 HTTP Hook 端点 (`POST /api/v1/hooks/**`)
消灭在本地执行外部 Shell/Python 脚本的脆弱链条，客户端直接提供原生 HTTP 钩子：

1. **上下文自动召回 (`POST /api/v1/hooks/context`)**：
   - 接收 Claude Code / Hermes 的 Hook Payload（提取用户当前输入的 `prompt`）；
   - 内部透明调用 MCP `memory_context`；
   - 直接按各大 Agent 的原生协议组装 `hookSpecificOutput.additionalContext` 返回，实现 0 脚本进程开销的极速注入。

2. **会话结束自动提炼 (`POST /api/v1/hooks/ingest`)**：
   - 接收会话结束通知与转录路径；
   - 异步解耦提取对话轮次，投递至本地 WAL 队列并向上游提交 `memory_ingest`。

### 2.3 REST 与管理透传接口 (`/api/v1/**` 与 `/health`)
- 供本地 Web 仪表盘或探针直接访问；
- `/health` 返回复合健康状态：
  ```json
  {
    "ok": true,
    "client": {
      "status": "running",
      "version": "1.0.0",
      "active_profile": "cloud",
      "offline_queue_size": 0
    },
    "upstream": {
      "url": "https://mcore.099817.xyz",
      "status": "connected",
      "latency_ms": 42
    }
  }
  ```

---

## 三、 配置规范 (`~/.mcore/client.yaml`)

```yaml
version: "1.0"
active_profile: "cloud"

profiles:
  # 场景 A：连接远端云服务（默认生产）
  cloud:
    server_url: "https://mcore.099817.xyz"
    tenant_id: "user_1002"
    api_key: "[REDACTED]"
    timeout_seconds: 30
    retry_max_attempts: 3

  # 场景 B：连接本机 WSL / 沙箱服务（本地直连）
  local:
    server_url: "http://127.0.0.1:8318"
    tenant_id: "default"
    api_key: ""
    timeout_seconds: 10
    retry_max_attempts: 1

  # 场景 C：自建家庭/公司私有 NAS（局域网）
  home_server:
    server_url: "http://192.168.1.100:8318"
    tenant_id: "home_admin"
    api_key: "[REDACTED]"
    timeout_seconds: 20
    retry_max_attempts: 2

# 本地服务与守护配置
local_server:
  host: "127.0.0.1"
  port: 8318
  log_level: "INFO"

# 离线韧性与可靠性存储
resilience:
  enable_cache: true
  cache_ttl_seconds: 300
  enable_wal_queue: true
  queue_dir: "~/.mcore/queue"
  max_queue_items: 1000
```

---

## 四、 命令行交互规范 (CLI Specification)

客户端提供跨平台统一的快捷管理 CLI `mcore-client`：

```bash
# 1. 服务生命周期管理
mcore-client start             # 后台拉起本地客户端守护
mcore-client stop              # 停止本地客户端
mcore-client restart           # 重启客户端服务
mcore-client status            # 查看客户端及上游连通性状态

# 2. 一键漫游环境切换（核心特性）
mcore-client switch cloud      # 瞬间切换至公网云端 mcore（所有 Agent 零改动）
mcore-client switch local      # 瞬间切换回本地开发环境
mcore-client switch home_server# 切换至私有服务器

# 3. 配置管理
mcore-client config get        # 查看当前激活的配置信息（自动脱敏 Key）
mcore-client config set server_url <url> # 快速修改当前上游 URL
mcore-client config set api_key <key>    # 快速配置当前凭据

# 4. Agent 一键接管
mcore-client bind --all        # 一键将本机的 Claude, Hermes, Codex 自动绑定至本地客户端 (:8318)
```

---

## 五、 实施优势与安全边界

1. **环境与网络彻底隔离**：
   - 客户端是无状态的转发与缓存层，不包含复杂的数据库引擎（无 PG/无向量引擎开销），安装包仅需几兆，随手随地即可秒级安装；
2. **消灭凭据泄露风险**：
   - 凭据被收敛在受控的 `client.yaml` 单一文件中，权限收紧为 600，且在 CLI 查看与日志输出时严格遵守 `[REDACTED]` 规则；
3. **彻底终结维护痛苦**：
   - 上游无论做数据库割接、迁移域名、还是升级 Spring Boot，远程办公机上的 Agent 和 Hook 全程 100% 零感知、零修改。
