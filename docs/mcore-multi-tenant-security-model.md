# mcore 多租户安全模型与 API Key 鉴权规范

> 版本：1.0 ｜ 迭代 246 ｜ 适用：Java 17 + Spring Boot 3 后端（`mcore-server`，默认 8318 端口）

## 一、背景与修复的缺陷

早期实现中，`TenantAuthFilter` 仅从请求头 `X-Tenant-Id` 读取目标租户并直接写入 `TenantContextHolder`，**全程没有任何身份校验**。这意味着任意调用方只需追加一个 HTTP 头即可完整读写他人租户数据：

```bash
# 修复前：无凭证即可访问任意租户
curl -H "X-Tenant-Id: user_1002" http://127.0.0.1:8318/api/v1/stats
```

控制面 `sys_tenant_api_keys` 表早已存在（含 `key_hash`、`allowed_scopes`、`expires_at`），但完全未被使用。本次迭代将其接入鉴权主链路。

## 二、信任模型

系统区分两个平面，采用不同策略：

| 平面 | 路径 | 策略 |
|---|---|---|
| **数据面** | `/api/v1/memories/**` 等业务接口 | `default` 租户免密钥；其余租户必须持有效且归属一致的 API Key |
| **管理面** | `/api/v1/tenant/**`（开辟/销毁/枚举/密钥） | 仅限**本机直连**；外部来源一律需 API Key |
| **公开面** | `/health`、`/actuator/**`、`/error` | 完全免鉴权 |

### 2.1 为什么 `default` 租户免密钥

`default` 是共享租户，本地 Agent 钩子（`mcore-context.sh`、`session-start.sh` 等）经 `/mcp` 调用它且不携带任何凭证。强制鉴权会打断现有链路，因此保留其免密钥访问，作为向多租户平滑迁移的兼容层。

### 2.2 本机直连的判定（关键安全点）

Cloudflare Tunnel 回源到 `127.0.0.1`，**仅凭 `remoteAddr` 无法区分内外网**。若只用回环地址判定，则隧道流量会被误判为本地运维通道，导致管理面被公网任意访问。

因此判定「本机直连」需同时满足：
1. 来源地址为 `127.0.0.1` / `::1` / `0:0:0:0:0:0:0:1`；
2. **且**不含任何反向代理注入头：`X-Forwarded-For`、`X-Real-IP`、`CF-Connecting-IP`、`True-Client-IP`。

任一代理头出现即视为外部来源。

## 三、API Key 规范

### 3.1 密钥格式

```
mk_<8位hex>.<32位hex密钥>
└────┬────┘ └─────┬──────┘
   key_id       secret（128 位熵）
```

示例（仅示意，非真实密钥）：`mk_8a60eafa.1f3c...（共 44 字符）`

### 3.2 存储与校验

- 数据库**只存 secret 段的 SHA-256 散列**（64 位 hex），明文密钥仅在签发瞬间返回一次，此后无法二次读取；
- 校验采用 `MessageDigest.isEqual()` **恒定时间比较**，规避时序侧信道；
- 校验结果按「明文密钥的 SHA-256」为键缓存在 Caffeine 中（`maximumSize=2000`、`expireAfterWrite=60s`），既避免每次请求打控制面库，又保证吊销最长 60 秒内自愈——而显式吊销会调用 `invalidateAll()` 做到**即时生效**；
- 缓存键使用散列而非明文，杜绝缓存区内驻留明文密钥。

### 3.3 携带方式

优先 `X-API-Key` 头，其次标准 `Authorization: Bearer <key>`：

```bash
curl -H "X-Tenant-Id: user_1002" \
     -H "X-API-Key: mk_xxxxxxxx.yyyyyyyy..." \
     http://127.0.0.1:8318/api/v1/stats
```

## 四、管理接口

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/v1/tenant/provision?tenantId=<id>` | 开辟租户（物理库 + 控制面登记，幂等） |
| `GET` | `/api/v1/tenant/list` | 枚举全部已登记租户 |
| `DELETE` | `/api/v1/tenant/{tenantId}` | 销毁租户（驱逐连接 → DROP → 级联清理注册表） |
| `POST` | `/api/v1/tenant/{tenantId}/keys` | 签发密钥，支持 `name` / `scopes` / `ttlDays` |
| `GET` | `/api/v1/tenant/{tenantId}/keys` | 枚举密钥（脱敏，不含明文与散列） |
| `DELETE` | `/api/v1/tenant/{tenantId}/keys/{keyId}` | 立即吊销密钥 |

### 签发示例

```bash
curl -X POST "http://127.0.0.1:8318/api/v1/tenant/user_1002/keys?name=agent-key&ttlDays=30"
```

响应中的 `data.apiKey` 即明文密钥，**仅此一次返回**。

## 五、错误码

| 码 | HTTP | 含义 |
|---|---|---|
| `A0401` | 401 | 未提供有效鉴权凭证 |
| `A0403` | 403 | 密钥有效但无权访问目标租户（跨租户越权） |

## 六、配置项

```yaml
mcore:
  security:
    enabled: ${MCORE_SECURITY_ENABLED:true}      # 关闭后任意 X-Tenant-Id 均可访问，仅供本地调试
    default-tenant: ${MCORE_DEFAULT_TENANT:default}
```

## 七、威胁矩阵与实测结论

| 场景 | 请求特征 | 预期 | 实测 |
|---|---|---|---|
| 默认租户正常调用 | 无头 | 200 | ✅ 200 |
| 无凭证越权访问他租户 | `X-Tenant-Id: user_1002` | 401 | ✅ A0401 |
| 持正确密钥访问本租户 | `X-Tenant-Id` + 有效 key | 200 | ✅ 200 |
| 跨租户越权 | `X-Tenant-Id: demo` + user_1002 的 key | 403 | ✅ A0403 |
| 伪造密钥 | 随机 `mk_xxxx.yyyy` | 401 | ✅ A0401 |
| 隧道来源访问管理面 | `X-Forwarded-For` + 无密钥 | 401 | ✅ A0401 |
| 隧道来源访问管理面 | `CF-Connecting-IP` + 无密钥 | 401 | ✅ A0401 |
| 本机管理面 | 回环 + 无代理头 | 200 | ✅ 200 |
| 吊销后立即使用 | 已吊销 key | 401 | ✅ 401（缓存即时失效） |

## 八、后续演进建议

1. **管理面二次加固**：当前管理面依赖来源判定，建议后续叠加独立的管理员 Token（与租户密钥分离）；
2. **密钥轮换**：支持同一租户多密钥并行 + 宽限期双活，实现零停机轮换；
3. **scope 强制校验**：`allowed_scopes` 已落库并在鉴权时解析，但尚未在业务方法上做注解级校验，建议引入 `@RequireScope("write")` 拦截器；
4. **审计留痕**：鉴权成功/失败的 `tenant_id`、`key_id`、来源 IP 应写入 `audit_events` 供事后追溯。
