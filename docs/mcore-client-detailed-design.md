# mcore 客户端（mcore-client）详细设计

> **版本**：v1.0 ｜ **迭代**：253 ｜ **上游规划**：`docs/plans/2026-09-12-mcore-server-client-decoupling-architecture-plan.md`  
> **定位**：将规划中的四大机制（虚拟本地回环、单点配置中心、透明凭据注入、离线 WAL 韧性）落到可执行的工程细节：模块划分、接口契约、数据结构、状态机、并发与容错策略、部署形态与验收标准。

---

## 一、 技术选型与发布形态（决策记录）

| 决策点 | 选型 | 依据 |
|---|---|---|
| 运行时 | **Node.js ≥ 18，零第三方依赖（纯 stdlib：`http`/`https`/`fs`/`path`/`crypto`/`child_process`）** | ① 任何能跑 Claude Code 的机器必然已装 Node，客户端"零额外安装"；② 纯 stdlib 单文件分发，无 `node_modules`、无版本地狱；③ 跨 Linux/macOS/Windows(含 WSL) 一致行为 |
| 发布形态 | **单文件 `mcore-client.js`（~1 个文件，< 2000 行）+ 单文件 `mcore-client` CLI 包装（同文件内子命令分发）** | `curl -o` 或 `npm i -g` 皆可安装；升级 = 覆盖一个文件 |
| 监听地址 | `127.0.0.1:<port>`（默认 8318，可配） | 只绑定回环，杜绝局域网误暴露；公网穿透交给 SSH/Cloudflare 之外的既有通道 |
| 本地持久化 | **NDJSON 追加文件 + 原子改名标记状态**（不引入 SQLite） | 队列规模上限 1000 条，文件方案足够；避免原生模块编译依赖 |
| 进程托管 | Linux/macOS：systemd user unit 或 `pm2`；Windows：计划任务（登录自启）+ `node --max-old-space-size=128` | 与现有 Hermes/CPA 托管习惯一致 |

**明确不做**：不做 WebSocket、不做配置热重载监听、不做 GUI、不做本地向量检索——客户端是网络面组件，任何"聪明"都放服务端。

---

## 二、 进程结构与模块划分

```
mcore-client.js（单进程，单事件循环）
│
├── boot()                      # 启动装配：读配置 → 端口冲突探测 → 起 HTTP Server → 起 Dispatcher
│
├── config/                     # ── 配置子系统 ──
│   ├─ loadConfig()             # 读取 ~/.mcore/client.yaml（无 YAML 依赖：受限子集解析器，见 §3.2）
│   ├─ activeProfile()          # 返回当前激活 profile 的归一化视图
│   └─ switchProfile(name)      # 原子切换（临时文件 + rename），切换语义见 §7.3
│
├── ingress/                    # ── 本地接入面（http.Server 监听 127.0.0.1:port）──
│   ├─ route(req)               # 路由分派：/mcp | /api/v1/hooks/** | /api/v1/** | /health | /_admin/**
│   ├─ mcpHandler               # JSON-RPC 透明转发（会话头直通，见 §4.1）
│   ├─ hookContextHandler       # POST /api/v1/hooks/context（本地处理，见 §4.2）
│   ├─ hookIngestHandler        # POST /api/v1/hooks/ingest（入队 + 异步，见 §4.3）
│   ├─ passthroughHandler       # /api/v1/** 与 /health 的纯透传（§4.4）
│   └─ adminHandler             # /_admin/** 管理端点（仅回环，§6）
│
├── egress/                     # ── 上游出站面 ──
│   ├─ UpstreamPool             # Keep-Alive 连接复用（http.Agent, keepAlive=true, maxSockets=8）
│   ├─ callUpstream(reqSpec)    # 统一出站入口：注入凭据头 → 发送 → 超时/重试（§5.1）
│   └─ headerInjector           # X-Tenant-Id / X-API-Key / X-Client-Info 附加
│
├── resilience/                 # ── 韧性子系统 ──
│   ├─ ContextCache             # LRU（Map 实现，容量 64 条 key=promptHash），TTL 300s（§5.2）
│   ├─ WalQueue                 # NDJSON 预写日志队列（§5.3 状态机）
│   └─ RetryScheduler           # 指数退避调度器（5s→10min，±20% 抖动）
│
├── hooks/                      # ── 本地 Hook 业务逻辑（替代 mcore-context.sh / mcore-ingest.py）──
│   ├─ payloadAdapter           # 五生态 Hook Payload 解析（claude/hermes/gemini/opencode/codex，§4.2.1）
│   └─ transcriptExtractors     # 五源转录提取 claude(.jsonl)/hermes(state.db)/codex(.jsonl)/gemini(.jsonl)/opencode(sqlite)（§4.3.1）
│
└── cli/                        # ── 命令行（node mcore-client.js <cmd>）──
    └─ start|stop|restart|status|switch|config|bind|doctor（§7）
```

单进程单事件循环即可承载：本地 Agent 的 QPS 是"人肉级"（每分钟个位数请求），Node 单线程 + Keep-Alive 连接池绰绰有余；WAL 回放与转录提取均为异步 IO。

---

## 三、 配置子系统详细设计

### 3.1 文件布局（`~/.mcore/`）

```
~/.mcore/
├── client.yaml          # 唯一事实源（权限 600）
├── mcore-client.pid     # 运行时 PID（stop/restart 依据）
├── mcore-client.log     # 单文件滚动日志（>5MB 截断保留后 2MB）
├── cache.json           # 上下文 LRU 缓存持久化（可选，重启续命）
└── queue/               # WAL 队列目录（§5.3）
    ├── 000123.pending   # 一批转录 = 一个文件，NDJSON 格式
    ├── 000124.inflight
    ├── 000125.dead      # 超过最大重试次数的死信（人工介入）
    └── .cursor          # 单调序号游标（文本文件，原子读写）
```

### 3.2 client.yaml 解析策略（无依赖 YAML 子集）

配置只用两级缩进 + `key: value` + 注释，解析器按行处理（≤80 行实现）。**schema 与默认值**：

| 键 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `version` | string | `"1.0"` | 配置版本 |
| `active_profile` | string | `"local"` | 当前激活 profile 名 |
| `profiles.<name>.server_url` | string | 必填 | 上游服务端基地址（含 scheme，不含路径） |
| `profiles.<name>.tenant_id` | string | `"default"` | 注入 `X-Tenant-Id` |
| `profiles.<name>.api_key` | string | `""` | 注入 `X-API-Key`；为空则不注入 |
| `profiles.<name>.timeout_ms` | int | 15000 | 单次出站超时（ingest 类自动放大到 60s） |
| `profiles.<name>.retry_max` | int | 2 | 出站瞬时错误重试次数 |
| `local_server.host` | string | `127.0.0.1` | 监听地址（禁止改为非回环，解析器直接拒绝） |
| `local_server.port` | int | 8318 | 监听端口 |
| `resilience.cache_ttl_s` | int | 300 | 上下文缓存 TTL |
| `resilience.queue_max_items` | int | 1000 | WAL 容量上限 |
| `resilience.retry_dead_after` | int | 8 | 单条队列最大尝试次数 → dead |

### 3.3 端口冲突与"本机即服务端"场景

启动时探测 `local_server.port`：
- 被占用且占用者 PID 的 cmdline 含 `mcore-server`/`java`（即本机就是服务端）→ 打印引导："本机检测到 mcore 服务端，Agent 直连即可；如仍需客户端，请将 `local_server.port` 改为 8319 并更新 Agent 配置"，然后以退出码 0 退出（不报错，避免误导）；
- 被其他进程占用 → 报错退出并列出占用者；
- 空闲 → 绑定，写 PID 文件。

---

## 四、 接口契约详细设计

### 4.1 `POST /mcp` —— JSON-RPC 透明转发

**下游 → 客户端**：本地 Agent 发标准 JSON-RPC（`initialize` / `tools/list` / `tools/call`），可带 `Mcp-Session-Id` 头。

**客户端转发算法**：
1. 读 body（上限 8MB，超限 413）；
2. 若为 `initialize` 请求 → 直接透传上游，**捕获上游响应的 `Mcp-Session-Id` 响应头**，建立 `localSid → upstreamSid` 映射（TTL 30 分钟）；
3. 后续请求按映射替换会话头后转发（无映射则原样透传，服务端会自行生成）；
4. 响应回传时保留原 `Content-Type`（当前服务端为 `application/json`；若未来上游切 SSE，此处加格式转换器即可，接口不变）。

**错误语义**：上游不可达 → 返回 JSON-RPC error `-32001 upstream unreachable`（Agent 侧可感知），同时 `/health.upstream.status` 置为 `disconnected`。

### 4.2 `POST /api/v1/hooks/context` —— 上下文召回（本地即时处理）

#### 4.2.1 入参自适应（payloadAdapter）

同一路径兼容五种 Agent 生态的 payload：

| 来源 | 钩子事件与配置位置 | prompt 提取字段 | agent 推断 |
|---|---|---|---|
| Claude Code | `UserPromptSubmit`（`~/.claude/settings.json`，HTTP 原生钩子） | `tool_input.prompt` → `prompt` → `user_prompt` → `message`（依次回落） | 固定 `claude`（或 `X-Agent-Id` 头覆盖） |
| Hermes | `pre_llm_call`（mcore-memory 插件） | `user_message` | 固定 `hermes` |
| Gemini CLI | `BeforeAgent`（`~/.gemini/settings.json`，脚本钩子转调本端点） | `prompt` / `message` / `user_prompt` 回落链 | 固定 `gemini` |
| OpenCode | `chat.message` / 自定义插件（`opencode.json`，脚本钩子转调本端点） | `message` / `prompt` 回落链 | 固定 `opencode` |
| Codex | **无读前注入**（迭代 78 既定决策：读走 AGENTS.md 显式调用，避免可见钩子输出污染对话） | — | `codex` 仅出现在写路径 |

另提取 `project_path`（`cwd` / `working_directory` / `extra.cwd` 回落链），透传给 `memory_context` 以保住 subject 解析。

**Agent 接入的双模式适配（关键设计）**：各 Agent 的钩子能力面不一致，客户端提供两种接入形态，`bind` 时按 Agent 自动选择：

| 模式 | 适用 Agent | 形态 |
|---|---|---|
| **HTTP 原生** | Claude Code | `{"type":"http","url":"http://127.0.0.1:8318/api/v1/hooks/..."}` 直接进客户端，零脚本、零进程开销 |
| **超薄脚本适配** | Codex、Gemini CLI、OpenCode（三者钩子系统仅支持 command 型，不支持 HTTP 型） | 客户端分发两个单行脚本 `mcore-hook-context.sh` / `mcore-hook-ingest.sh` 至 `~/.mcore/bin/`（已加入 PATH 注入建议），脚本内容仅为 `curl -s --max-time 4 -X POST http://127.0.0.1:8318/api/v1/hooks/<x> -d @-`，**不含任何业务逻辑与路径判断**；Codex/Gemini/OpenCode 的钩子注册指向这两个脚本（以 `MCORE_AGENT_ID=<agent>` 环境变量前缀区分身份） |

超薄脚本与旧 `mcore-context.sh`/`mcore-ingest.py`（600+ 行、依赖仓库路径）的本质区别：业务逻辑全部下沉客户端进程内（payloadAdapter / transcriptExtractors），脚本退化为纯传输层，永不因端点变更而修改。

#### 4.2.2 处理流程与响应

1. prompt 为空或 < 4 字符 → `200 {"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":""}}`（空注入，绝不阻塞对话）；
2. 查 ContextCache（key = sha256(prompt + activeProfile)）→ 命中且未过期 → 直接返回缓存（**离线也能注入最近召回**）；
3. 未命中 → 经 egress 调上游 `/mcp` 的 `memory_context`（`task`/`agent`/`project_path`/`token_budget=2000` 参数别名双写），解析 `result.content[0].text`；
4. 组装响应（写缓存旁路，不阻塞返回）：
   ```json
   { "hookSpecificOutput": { "hookEventName": "UserPromptSubmit", "additionalContext": "<context 文本>" } }
   ```
5. 超时（>5s 硬上限，防 Claude Code 钩子 5s 超时连坐）：返回空注入 + 记 WARN 日志。**读路径永远不进 WAL 队列**——宁可少注入，不可卡对话。

### 4.3 `POST /api/v1/hooks/ingest` —— 会话回写（入队即应答）

#### 4.3.1 处理流程

1. 收到 Stop/SessionEnd payload（Claude Code 含 `transcript_path`；Hermes 含 `session_id`；Codex/Gemini/OpenCode 的钩子 payload 透传原文；兼容 `CLAUDE_SESSION_FILE` 等环境变量兜底）；
2. **立即** `202 Accepted {"queued": true, "batch_id": "000126"}`（Agent 的 Stop 钩子 30s 超时再也不会被 LLM 提炼耗时拖垮）；
3. 异步：transcriptExtractors 按来源提取 `[{"role","content"}]`：
   - **claude** = 解析 `~/.claude/projects/**/*.jsonl`（优先 payload 的 `transcript_path`）最近 500 条 user/assistant；
   - **hermes** = 只读打开 `~/.hermes/state.db` 按 session_id 取 `messages`，无 id 则取最新活跃会话（无 session 时回落逻辑已实证有效）；
   - **codex** = 解析 `~/.codex/sessions/**/*.jsonl`（`event_msg` 的 `user_message`/`agent_message` 优先，`response_item.message` 兜底——与既有 `_extract_codex` 双层结构完全同口径）；
   - **gemini** = 按已知 transcript 定位规则解析 `~/.gemini/tmp/<hash>/checkpoint-*.jsonl`；
   - **opencode** = 只读打开 opencode 本地 SQLite（`message` + `part` 表 JOIN，提取 `user`/`assistant` part 文本——与既有 `_extract_opencode_from_db` 同口径）；
   - 提取器实现口径与 `scripts/hooks/mcore-ingest.py` 的五个 `_extract_*` 函数逐一等价（该脚本的提取逻辑已在生产验证多轮），客户端以 Node 内置 `node:sqlite`（Node 22+，无原生编译依赖）读取 SQLite 转录，旧机器 Node 18/20 则回落提示升级（不破坏其余功能）；
4. 提取结果（截断每条 2000 字符、总 500 条上限，与原脚本口径一致）写入 WAL `.pending` 文件；
5. RetryScheduler 拾取 → egress 调上游 `/mcp` `memory_ingest`（`messages`/`agent_id`/`project_path`）→ 成功则文件改 `.done` 并 60s 后物理删除；失败走状态机。

**空内容防线**：提取结果为空 → 直接 `.done` 并记 `skip_empty` 审计日志，**绝不向上游发送空 messages**（杜绝历史上空内容脏数据的复发路径）。

### 4.4 `/api/v1/**` 与 `/health` —— 纯透传

- `/api/v1/**`：方法/头/body 原样转发（供本地 Web UI 直连 `127.0.0.1:8318` 使用）；
- `/health`：**不透传**，返回客户端自聚合健康体（规范文档 §2.3 的 schema），其中 `upstream` 子对象由后台每 30s 探活（HEAD 上游 `/health`）刷新。

---

## 五、 韧性子系统详细设计

### 5.1 egress 出站统一策略

- **凭据注入**：每个出站请求附加 `X-Tenant-Id`、`X-API-Key`（非空时）、`X-Client-Info: mcore-client/1.0.0`；
- **连接复用**：`http.globalAgent` 替换为专用 Agent（keepAlive、maxSockets 8、freeTimeout 30s）；HTTPS 复用 TLS Session；
- **瞬时错误重试**：仅对 `ECONNRESET`/`ETIMEDOUT`/HTTP 502/503/504 且方法为 POST `/mcp`（幂等的 tools/call 查询类）重试 `retry_max` 次，间隔 500ms；**ingest 上报永不就地重试**（交给队列状态机，避免重复写入）；
- **超时矩阵**：context 类 5s；一般透传 `timeout_ms`；ingest 上报 60s；探活 2s。

### 5.2 ContextCache

- 实现：`Map` + 插入序即 LRU 序，超容量 64 删最旧；`cache.json` 启动加载、每 60s 落盘（写临时文件后 rename）；
- 失效条件：TTL 过期 / profile 切换（整体清空）/ 收到上游对 `memory_add`/`memory_update`/`memory_ingest` 的成功响应（写后读一致性，清空对应 agent 命名空间）。

### 5.3 WALQueue 状态机

```
                write                 pick up                  ack(2xx)
  (HTTP 202) ─────────▶ PENDING ───────────────▶ INFLIGHT ───────────────▶ DONE
                          │                        │                        │(60s 后删除)
                          │ 溢出淘汰(容量>max)      │ 网络错误/5xx/超时
                          ▼                        ▼
                        EVICTED              attempts < dead_after ?
                                          ├─ 是 → 退避后重回 INFLIGHT
                                          │      (5s,10s,20s,40s,1m,2m,5m,10m ±20% 抖动)
                                          └─ 否 → DEAD（保留供人工重放：
                                                    mcore-client queue replay <id>）
```

- 文件即状态：改名 = 状态迁移（同目录 rename 原子）；
- 崩溃恢复：启动扫描 `queue/`，所有 `.inflight` 回退 `.pending`（至少一次投递语义；上游 `memory_ingest` 具备语义去重，重复投递安全）；
- 容量保护：`pending+inflight > queue_max_items` 时淘汰最旧 `.pending`（记 EVICTED 审计）；`.dead` 不占配额但超过 100 条告警。

### 5.4 离线模式的上下文兜底

上游 `disconnected` 期间 `/api/v1/hooks/context` 直接命中本地缓存路径（未命中则返回空注入）；`/mcp` 调用返回 `-32001`。**设计边界**：客户端不做本地检索引擎——缓存只服务"最近召回过的 prompt"。

---

## 六、 管理端点与可观测性

`/_admin/**`（仅接受回环来源）：

| 端点 | 语义 |
|---|---|
| `GET /_admin/stats` | 计数器：requests_total / mcp_calls / hook_context_hits(cache) / queue_depth / queue_dead / evicted / upstream_latency_ms(p95 环形桶) |
| `GET /_admin/queue` | 队列清单（id、状态、attempts、bytes、created_at） |
| `POST /_admin/queue/<id>/replay` | 重放死信 |
| `POST /_admin/cache/clear` | 清空上下文缓存 |
| `POST /_admin/shutdown` | 优雅停机（drain 5s → 关 server） |

日志格式：单行 JSON `{"ts","level","mod","msg",...}`；凭据与 prompt 全文永不落日志（prompt 只记 sha256 前 8 位）。

---

## 七、 CLI 详细设计（`node mcore-client.js <cmd>`）

| 命令 | 行为 | 关键细节 |
|---|---|---|
| `start [--daemon]` | 前台/后台拉起（后台=自身 `spawn` + `detached` + 输出重定向到日志文件） | 启动自检：配置合法、端口可用、上游可达性（不可达仅 WARN 不阻塞） |
| `stop` / `restart` | 按 PID 文件 SIGTERM → 等待 5s → SIGKILL | restart = stop + start |
| `status` | 打印客户端状态 + 上游健康 + 队列深度（读 `/_admin/stats`，客户端未运行则报错码 3） | 退出码：0 正常 / 1 上游断 / 3 未运行 |
| `switch <profile>` | 校验 profile 存在 → 改写 `active_profile` → 向运行中进程发 `SIGHUP` 触发热重载（重载 = 重读配置 + 清缓存 + 重建连接池；**不中断监听**） | 打印切换前后 diff（key 脱敏） |
| `config get [key]` | 打印归一化配置视图 | api_key 显示 `[REDACTED:前4后4]` |
| `config set <key> <value>` | 校验后原子改写（对 `profiles.<n>.<k>` 与顶层均支持点路径） | 同样触发 SIGHUP |
| `bind [--agents claude,hermes,codex,all]` | 一键接管：把本机 Agent 的 MCP 端点与 Hook 改写为指向本地客户端（复用 `connect_agents.py` 的写入逻辑，端点固定为 `127.0.0.1:<port>`；Claude Hook 改为 `{"type":"http","url":".../api/v1/hooks/..."}` 原生 HTTP 形态；写入前全量备份到 `~/.mcore/backups/<ts>/`） | 幂等：已是目标值则跳过；`--dry-run` 支持 |
| `doctor` | 体检清单逐项打勾：Node 版本 / 配置文件权限 600 / 端口占用 / 上游连通(含延迟) / 队列健康 / 各 Agent 配置是否指向客户端 | 全绿退出码 0 |

---

## 八、 Agent 接管后的最终形态（bind 之后）

| 组件 | 配置项 | 值（跨环境永久冻结） |
|---|---|---|
| Claude Code | `~/.claude.json → mcpServers.memorycore.url` | `http://127.0.0.1:8318/mcp`（头 `X-Agent-Id: claude` 保留） |
| Claude Code | `settings.json → hooks.UserPromptSubmit` | `{"type":"http","url":"http://127.0.0.1:8318/api/v1/hooks/context","timeout":5}` |
| Claude Code | `settings.json → hooks.Stop` | `{"type":"http","url":"http://127.0.0.1:8318/api/v1/hooks/ingest","timeout":10}` |
| Hermes | `config.yaml → mcp_servers.memorycore.url` | `http://127.0.0.1:8318/mcp`（头 `X-Agent-Id: hermes` 保留） |
| Hermes | 插件 `MCORE_URL` 常量 | `http://127.0.0.1:8318/mcp`（服务端同机部署场景无需改动插件） |
| Codex | `~/.codex/config.toml → mcp_servers` | `http://127.0.0.1:8318/mcp`（头 `X-Agent-Id: codex`） |
| Codex | `hooks.json → SessionStart / Stop` | `MCORE_AGENT_ID=codex bash ~/.mcore/bin/mcore-hook-ingest.sh`（**读前注入保持停用**，遵循迭代 78 决策） |
| Gemini CLI | `~/.gemini/settings.json → mcpServers` | `http://127.0.0.1:8318/mcp`（头 `X-Agent-Id: gemini`） |
| Gemini CLI | `hooks → BeforeAgent / AfterAgent / SessionEnd` | 超薄脚本 `~/.mcore/bin/mcore-hook-{context,ingest}.sh`（`MCORE_AGENT_ID=gemini` 前缀） |
| OpenCode | `opencode.json → mcp` | `http://127.0.0.1:8318/mcp` |
| OpenCode | `hooks → session_start / session_end` | 超薄脚本（`MCORE_AGENT_ID=opencode` 前缀）；既有 mcore 插件条目改为指向客户端端点 |
| 本地 Web UI | API 基地址 | `http://127.0.0.1:8318`（透传） |
| Windows 侧 Claude（可选） | `~/.claude/settings.json`（`/mnt/c/Users/<u>/...`） | 同 Claude Code 行（bind 自动扫描 Windows 用户目录，同现有 connect_agents.py 的 `windows_user_dirs()` 口径） |

**身份识别一致性**：`X-Agent-Id` 请求头（MCP 直连路径）与 `MCORE_AGENT_ID` 环境变量（钩子脚本路径）双通道统一映射到服务端 `source_agent`，与 commit 7ea97ad 建立的嗅探机制完全兼容；四主体收敛决策（hermes/claude/codex/mcore）不受影响——gemini/opencode 作为合法外部来源照常落库。

环境迁移示例（从公司网切到公网云）：远程机器上仅执行 `mcore-client switch cloud`，1 秒内全机 Agent 完成漫游，任何 Agent 配置文件零改动。

---

## 九、 安全设计要点

1. **监听硬约束**：配置解析器拒绝非回环 `host`（代码级断言，非文档约定）；
2. **凭据存储**：`client.yaml` 权限 600；启动时若检测 group/other 可读则自动收紧并告警；CLI/日志/`/_admin` 输出全链路 `[REDACTED]`；
3. **管理面隔离**：`/_admin/**` 校验来源 IP 为回环（即便端口被误改也不会暴露管理面）；
4. **上游传输**：生产 profile 强制 `https://`（解析器对非回环上游 + http 打印显著告警）；
5. **队列内容**：转录含会话明文，`queue/` 目录权限 700，`.done` 删除即抹除；不上传任何凭据到日志。

---

## 十、 验收标准（Definition of Done）

| # | 场景 | 通过标准 |
|---|---|---|
| A1 | 全新纯净目录 `node mcore-client.js start`，`switch cloud` 指向真实服务端 | `/health` 返回 client=running, upstream=connected |
| A2 | Claude Code（hooks 为 HTTP 形态）提问 | 自动注入 `# mcore context` 附加上下文，耗时 < 1.5s（命中缓存 < 50ms） |
| A2b | Gemini CLI（BeforeAgent 超薄脚本）提问 | 注入成功，`source_agent=gemini` 正确落库身份 |
| A2c | Codex 提问 | **无读前注入**（符合迭代 78 决策），AGENTS.md 显式 memory_context 经客户端透传正常返回 |
| A3 | Stop 钩子触发会话回写 | `202` 即返回；60s 内上游 `memory_ingest` 成功，记忆列表出现新事实 |
| A3b | Codex/Gemini/OpenCode 会话结束回写 | 三者转录各自正确提取（codex=.jsonl 双层结构、opencode=sqlite JOIN），`source_agent` 分别为 codex/gemini/opencode |
| A4 | 回写期间断上游（iptables/停服模拟） | 队列出现 `.pending` 重试；恢复上游后自动补投，记忆最终落库，零丢失 |
| A5 | 重试超限 | 转入 `.dead`；`queue replay` 手工重放成功 |
| A6 | `switch` 热切换 profile | 不中断监听；缓存清空；后续请求走新上游（日志可证） |
| A7 | 同机部署冲突 | 检测到本机服务端占用 8318 时给出引导而非崩溃 |
| A8 | `bind --all` 幂等执行两次 | 第二次零变更；备份目录存在 |
| A9 | 离线（上游断）提问 | 对话不卡死（空注入或缓存注入），`/mcp` 报 `-32001` |
| A10 | 凭据安全 | `config get`、日志、`/_admin/stats` 三处均无明文 key |

---

## 十一、 实施切分（对应总规划 Phase 1-3 的工程任务序列）

| 任务 | 内容 | 产出 |
|---|---|---|
| T1 | 配置子系统 + ingress 骨架 + `/mcp` 透传 + egress 凭据注入 | 可用代理（Phase 1 核心） |
| T2 | `hooks/context` + ContextCache + payloadAdapter | 读路径闭环（A1/A2/A9） |
| T3 | WALQueue + RetryScheduler + `hooks/ingest` + transcriptExtractors | 写路径闭环（A3/A4/A5） |
| T4 | CLI 全量子命令 + SIGHUP 热切换 + `/_admin` | 管理闭环（A6/A8） |
| T5 | `bind` 接管器 + doctor + 服务托管模板（systemd/计划任务） | 分发闭环 |
| T6 | 全量验收 A1~A10 + 文档（README-client）+ ITERATION 记录 | 生产就绪 |

依赖关系：T1 → T2/T3（并行）→ T4 → T5 → T6。每个任务独立可验证，均以真实 curl/Agent 调用作为完成证据。
