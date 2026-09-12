# mcore-client — MemoryCore 本地接入边车

> 设计依据：[`docs/mcore-client-detailed-design.md`](../docs/mcore-client-detailed-design.md)（迭代 253/254）

把 mcore 拆成**服务端**与**客户端**：本地所有 Agent 只连 `127.0.0.1:8318`，由客户端统一代理到可随时切换的上游服务端。

```
Claude Code ┐
Hermes      │
Codex       ├──► http://127.0.0.1:8318 ──► mcore-client ──► 上游服务端（可切换）
Gemini CLI  │        （端点永久冻结）         │  自动注入 X-Tenant-Id / X-API-Key
OpenCode    ┘                                └─ 离线 WAL 队列（断网零丢失）
```

## 解决什么

| 痛点 | 客户端方案 |
|---|---|
| 换环境要改 5~6 处 Agent 配置 | Agent 端点永久冻结为回环；换环境只 `switch` 一次 |
| Hook 脚本硬编码仓库绝对路径 | 业务逻辑下沉客户端；Codex/Gemini/OpenCode 只用一行 `curl` 超薄脚本 |
| API Key 散落在各 Agent 明文配置 | 凭据收敛在 `~/.mcore/client.yaml`（600），出站自动注入 |
| 断网时会话记忆直接丢失 | 转录先落盘 WAL 队列，恢复后自动补投（至少一次投递） |
| Codex 读前注入噪声 | 泛化短查询跳过召回；单 Agent 可单独关闭注入 |

## 安装

零第三方依赖，只需要 Node ≥ 18（任何能跑 Claude Code 的机器都已具备）。

```sh
mkdir -p ~/.mcore/bin
curl -fsSL <repo>/mcore-client/mcore-client.js -o ~/.mcore/mcore-client.js
chmod +x ~/.mcore/mcore-client.js
ln -sf ~/.mcore/mcore-client.js ~/.mcore/bin/mcore-client
```

## 快速开始

```sh
node mcore-client.js start --daemon      # 后台启动
node mcore-client.js status              # 查看状态与上游连通性
node mcore-client.js bind                # 一键接管本机 5 个 Agent
node mcore-client.js doctor              # 环境体检
```

## 命令

| 命令 | 说明 |
|---|---|
| `start [--daemon]` | 启动（`-d` 后台守护） |
| `stop` / `restart` | 停止 / 重启 |
| `status` | 客户端 + 上游 + 队列状态（退出码 0 正常 / 1 上游断 / 3 未运行） |
| `switch <profile>` | 切换上游 Profile（SIGHUP 热重载，**监听不中断**） |
| `config get [path]` | 查看配置（api_key 自动脱敏） |
| `config set <path> <value>` | 点路径改配置，如 `profiles.cloud.api_key` |
| `bind [--dry-run]` | 一键接管 Agent（MCP + Hooks），幂等、自动备份 |
| `queue [list\|replay <id>]` | 队列查看 / 死信重放 |
| `doctor` | 体检：Node 版本、配置权限、进程、队列健康 |

## 配置（`~/.mcore/client.yaml`）

唯一事实源。`active_profile` 决定当前连哪台上游：

```yaml
active_profile: "local"
profiles:
  local:
    server_url: "http://127.0.0.1:8318"
    tenant_id: "default"
    api_key: ""
  cloud:
    server_url: "https://mcore.099817.xyz"
    tenant_id: "user_1002"
    api_key: "mk_xxx.yyy"
local_server:
  host: "127.0.0.1"     # 非回环会被拒绝启动
  port: 8318
resilience:
  cache_ttl_s: 300
  queue_max_items: 1000
  retry_dead_after: 8
```

切换环境：

```sh
node mcore-client.js switch cloud     # 全机 Agent 1 秒漫游，配置零改动
```

## 端点

| 端点 | 用途 |
|---|---|
| `POST /mcp` | FastMCP 透明转发（会话头直通，凭据自动注入） |
| `POST /api/v1/hooks/context` | 上下文召回（五生态 payload 自适应，5s 硬超时，命中缓存 < 50ms） |
| `POST /api/v1/hooks/ingest` | 会话回写（立即 200，异步提取 + WAL 入队） |
| `/api/v1/**` | REST 透传 |
| `GET /health` | 客户端 + 上游 + 队列 复合健康 |
| `/_admin/**` | 管理面（**仅回环**）：stats / queue / reload / cache clear / shutdown |

## 离线韧性

```
ingest 请求 ──► 立即 200 ──► 转录落盘 .pending ──► 异步投递上游
                                 │
                    失败 ──► 退避重试 5s→10s→…→10m（±20% 抖动）
                                 │
                    超限 ──► .dead ──► `queue replay <id>` 手工重放
```

- 崩溃恢复：启动时 `.inflight` 自动回退 `.pending`
- 容量保护：超过 `queue_max_items` 淘汰最旧 `.pending`
- 空转录防线：提取为空直接跳过，绝不向上游发空 messages

## Agent 接管后的形态

| Agent | MCP | 读前注入 | 回写 |
|---|---|---|---|
| Claude Code | `127.0.0.1:8318/mcp` | `UserPromptSubmit`（HTTP 原生） | `Stop` |
| Hermes | 同上 | 插件 `pre_llm_call` | 插件 `on_session_end` |
| Codex | 同上 | `UserPromptSubmit`（超薄脚本） | `Stop` |
| Gemini CLI | 同上 | `BeforeAgent`（超薄脚本） | `AfterAgent` |
| OpenCode | 同上 | `session_start`（超薄脚本） | `session_end` |

ID 识别双通道：MCP 走 `X-Agent-Id` 头，钩子走 `MCORE_AGENT_ID` 环境变量。

## 托管

- **Linux/macOS**：见 `templates/mcore-client.service`（systemd user unit）
- **Windows**：见 `templates/register-task.ps1`（登录自启的计划任务，**不注册系统服务**）

## 安全

- 监听地址非回环 → 配置解析器**直接拒绝启动**（代码级断言）
- `client.yaml` 权限自动收紧 600
- `/_admin/**` 仅回环可访问
- 凭据在日志、CLI 输出、管理面三处统一 `[REDACTED]`；prompt 只记 hash 前 8 位

## 已知限制

- OpenCode 转录提取依赖其本地 SQLite；无 OpenCode 实例的环境该路径跳过
- SQLite 读取优先 `node:sqlite`（Node 22+），回落 `sqlite3` CLI；两者都不可用时跳过对应 Agent 的提取
- 本机即服务端时（8318 被占用），客户端需改 `local_server.port` 或直接让 Agent 直连
