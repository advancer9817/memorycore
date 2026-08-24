# mcore 用户画像层 — 实现方案（2026-08-24）

> 状态：**待实现**（设计已完成，代码未开始）
> 背景：向阿里云百炼长期记忆的用户画像（User Profile）功能学习；目标是把"固定 schema 结构化画像、必达注入"能力搬进 mcore，作为 Hermes 系统提示词的一部分。
> 关联：`docs/plans/2026-08-24-governance-slimming.md`（本方案为独立增量，不删除任何现有功能，与其并行无冲突）
> 参考：`~/.hermes/skills/software-development/mcore-operations/references/aliyun-long-term-memory-api.md`

---

## 1. 目标与设计原则

### 1.1 目标

1. **画像必达**：系统提示词中固定携带结构化用户画像（姓名/职业/偏好等），不再依赖向量召回的 79.7% 命中率。
2. **属性级一致**：新增事实覆盖旧值，无矛盾记忆竞争；immutable 属性不可被覆盖。
3. **低成本**：画像聚合抽取复用现有 user_profile 记忆（已由 ingest 免费产出），不增加对话热路径 LLM 调用。
4. **零工具面膨胀**：不新增 MCP 工具（用户偏好精简工具面），只加 CLI 子命令 + 内部注入。

### 1.2 与阿里云机制的对应

| 阿里云 | mcore 实现 |
|---|---|
| `CreateProfileSchema` | config.yaml `user_profile.schema[]` |
| `AddMemory` 传入 profile_schema 抽取 | `profile-extract` 命令：扫描 active user_profile 记忆 → LLM 按 schema 聚合抽取 |
| `GetUserProfile` | `user_profile_attrs` 表（user_id, attribute, value, confidence, updated_at, source_ids） |
| 画像注入 Prompt | `build_context_pack` 输出固定 `## user_profile_snapshot` 块（不靠召回） |
| immutable 属性 | schema 内 `immutable: true` 属性不被覆盖 |

### 1.3 设计决策（为什么不做对话级抽取）

- mcore 的 ingest 已从对话提取 `user_profile` 类型记忆（现存 91 条 active）。
- 若再在 ingest 热路径加一次按 schema 的 LLM 调用 = 每轮对话多一次 DeepSeek 调用，成本翻倍，违背降本方向（¥0.5/周目标）。
- **结论**：画像层以"聚合器"形态存在 —— 输入是幂等的 user_profile 记忆，输出是结构化画像快照。低频执行（随 curator 2x/天或手动），成本 ≈ 1 次 LLM 调用/次。

---

## 2. 数据模型

### 2.1 config.yaml 新增段

```yaml
user_profile:
  enabled: true
  extract_limit: 200        # profile-extract 每次扫描的最大 active user_profile 记忆数
  max_snapshot_chars: 800   # context 注入画像块的最大字符数（token 上限控制）
  schema:
    - name: 姓名
      description: 用户的姓名
    - name: 职业
      description: 用户的职业/岗位
    - name: 雇主
      description: 用户所在公司或雇主名称
    - name: 工作领域
      description: 用户日常工作涉及的领域、平台、系统
    - name: 技术栈
      description: 用户的技术背景、技能与开发环境
      immutable: true
    - name: 沟通偏好
      description: 用户偏好的回答语言、风格、格式、交互方式
    - name: 模型偏好
      description: 用户偏好的模型/供应商/路由（如官方 DeepSeek、百炼 Coding Plan）
    - name: 学习方向
      description: 用户当前的学习重点与转型目标
```

**schema 约束（借鉴阿里云最佳实践）**：
- 属性名语义唯一（"姓名"/"名字"/"名称"不同时出现）。
- description 具体、避免抽象，直接作为抽取 prompt 的字段描述。
- 默认 8 个属性；新增属性只需在 config 加一行（表结构不需变更）。
- `immutable: true` 表示该属性一经确定不随后续新记忆覆盖。

### 2.2 新表 `user_profile_attrs`（db.py init_db 追加）

```sql
CREATE TABLE IF NOT EXISTS user_profile_attrs (
  user_id        TEXT NOT NULL DEFAULT 'default',
  attribute      TEXT NOT NULL,
  value          TEXT NOT NULL,
  confidence     REAL NOT NULL DEFAULT 0.5,
  immutable      INTEGER NOT NULL DEFAULT 0,
  source_ids_json TEXT NOT NULL DEFAULT '[]',
  updated_at     TEXT NOT NULL,
  PRIMARY KEY (user_id, attribute)
);
CREATE INDEX IF NOT EXISTS idx_user_profile_attrs_user ON user_profile_attrs(user_id);
```

- 行语义：`(user_id, attribute)` 唯一；profile-extract 全量重建时按属性 upsert（`INSERT OR REPLACE`）。
- `source_ids_json`：证据记忆 id 列表，便于追溯与 UI 展示。

---

## 3. 模块设计（新增 `memorycore/storage/profile.py`，~200 行）

### 3.1 公开 API

```python
def schema_from_config(cfg: dict[str, Any] | None = None) -> list[dict[str, str]]
    """读取 config.yaml 的 user_profile.schema；无则返回空。"""

def get_user_profile(user_id: str = "default") -> list[dict[str, Any]]
    """读 user_profile_attrs 全部属性（按 schema 顺序排序）。"""

def profile_snapshot(user_id: str = "default", cfg=None, max_chars: int | None = None) -> str
    """生成 '## user_profile_snapshot\n- 姓名: xxx\n...' 文本，超 max_chars 截断。"""
    # 无画像时返回 ''（不注入空块）

def extract_profile(
    *,
    user_id: str = "default",
    apply: bool = False,
    limit: int | None = None,
    cfg: dict[str, Any] | None = None,
    _summarize_fn=None,
) -> dict[str, Any]
    """核心：扫描 active user_profile 记忆 -> LLM 按 schema 抽取 -> upsert 画像表。

    extract_profile 是 'dry-run'，apply=True 才写库。返回:
    {"scanned": N, "attributes": [...], "updated": N, "errors": [...], "dry_run": bool}
    """
```

### 3.2 LLM 聚合抽取（复用 extraction 的 `_call_llm`，成本 = 1 次调用）

- **输入**：schema（属性名+描述）、最近 `limit` 条 active user_profile 记忆（title/content/created_at）。
- **prompt**（`_PROFILE_EXTRACT_PROMPT`）：

```
你是用户画像信息抽取器。根据以下用户画像字段定义与历史记忆，
抽取每位用户最稳定、最准确的属性值。

# 画像字段
- 姓名: 用户的姓名
- 职业: 用户的职业/岗位
...

# 历史记忆（每条含 created_at，多条可能表述同一事实）
[...]

# 规则
1. 只输出 JSON: {"attributes": [{"name": "姓名", "value": "杜鹏洋", "confidence": 0.9}]}
2. 属性名必须来自上面的字段定义；没有稳定证据的属性不要输出。
3. 多条记忆冲突时：取 created_at 最新的；若最新信息明确是"纠正"，以纠正为准。
4. 未知/无法确定的属性省略（不要填"未知"）。
5. 仅返回合法 JSON，无 prose。

# 输出
```

- **解析**：`_parse_profile_response(raw, schema)` —— 属性名白名单过滤、confidence 夹取 [0,1]、value 去除多余空白、超长 value 截断（200 字符）。
- **覆盖规则**（upsert 前）：
  - 新 confidence ≥ 旧 confidence → 覆盖（保留旧 source_ids + 追加新）。
  - 新 confidence < 旧 confidence → 保留旧值。
  - schema 属性 `immutable: true` 且旧值非空 → 不覆盖。
  - 非 schema 属性不写入。

### 3.3 注入 context（改造 `memorycore/storage/context_pack.py`）

**位置**：`build_context_pack` 的 `lines` 初始化后、`rank_capped` 循环前插入：

```python
# 固定画像快照（不依赖召回，必达；无画像时为空串不注入）
if load_config().get("user_profile", {}).get("enabled", False):
    snap = profile_snapshot(user_id="default", max_chars=cfg.get("context_pack", {}).get("default_token_budget", 2000) // 2)
    if snap:
        lines.append(f"## user_profile_snapshot\n{snap}\n")
```

**输出效果**（注入后 memory_context 开头）：

```
# memory_context for hermes
task: ...
scope: ...
project_path: ...
safety: ...

## user_profile_snapshot
- 姓名: 杜鹏洋
- 职业: 技术工程师（Java 全栈 → AI 应用开发）
- 工作领域: 千帆平台/得帆AI网关/动力AI门户/MaxKB 技术支持与运维
- 沟通偏好: 中文；直接给原始数据/凭据；不繁琐确认；kawaii 风格
- 模型偏好: 官方 DeepSeek 默认，编码场景百炼 Coding Plan
- 开发环境: WSL/Ubuntu

## user_profile        <- 以下仍为召回的相关记忆
- [id] ...
```

**Token 成本**：10 属性 × ~30 字 ≈ 400-600 token/次，固定上限由 `max_snapshot_chars` 控制。

---

## 4. CLI 子命令（server_runtime.py，3 个子命令）

```python
p_profile = sub.add_parser("profile-extract", help="aggregate active user_profile memories into structured user profile attrs")
p_profile.add_argument("--apply", action="store_true")
p_profile.add_argument("--limit", type=int, default=0)          # 0 = 用 config
p_profile.add_argument("--summary-only", action="store_true")

p_profile_get = sub.add_parser("profile-get", help="show current user profile snapshot")
p_profile_get.add_argument("--json", action="store_true")

p_profile_status = sub.add_parser("profile-status", help="show profile config + attr counts")
```

调用方式（`server_runtime.py` 的 `args.cmd` 分支追加）：
```python
elif args.cmd == "profile-extract":
    from memorycore.storage.profile import extract_profile
    print(json.dumps(extract_profile(apply=args.apply, limit=args.limit or None), ensure_ascii=False, indent=2))
elif args.cmd == "profile-get":
    from memorycore.storage.profile import get_user_profile
    print(json.dumps(get_user_profile(), ensure_ascii=False, indent=2))
```

**定时集成（可选）**：`run_curator.sh` 末尾追加（低频聚合，与 LLM curator 共享 deepseek 预算）：
```bash
if [ "${LOCAL_MEMORY_PROFILE_EXTRACT:-1}" = "1" ]; then
  "$PY" "$SERVER" profile-extract --apply --limit "${LOCAL_MEMORY_PROFILE_EXTRACT_LIMIT:-200}" \
     >> "$OUT_DIR/profile-extract.log" 2>&1 || echo "[mcore] profile-extract failed (non-fatal)" >&2
fi
```

---

## 5. 代码改动清单（精确到文件/行）

| 文件 | 改动 |
|---|---|
| `memorycore/storage/db.py` | `init_db` executescript 追加 `user_profile_attrs` 表（~463 行之后，vector_cache 表旁） |
| `memorycore/storage/profile.py` | **新增**（schema、get/snapshot/extract、prompt、解析、upsert） |
| `memorycore/storage/context_pack.py` | 在 `lines` 构建后（~396 行之后）插入画像快照注入 |
| `memorycore/server_runtime.py` | 新增 `profile-extract`/`profile-get`/`profile-status` 子命令注册 + 分发 |
| `memorycore/models.py` | `_DEFAULTS` 增加 `user_profile` 段默认值；`load_config` 增加校验（enabled bool、schema list） |
| `config.yaml` | 增加 `user_profile:` 段（见 §2.1） |
| `run_curator.sh` | 末尾追加 profile-extract 挂载（可选） |
| `tests/test_profile.py` | **新增**（见 §6） |
| `memorycore/storage/__init__.py` | `profile` 相关导出（如 `get_user_profile`, `extract_profile`） |

---

## 6. 测试设计（tests/test_profile.py，~6 case）

1. `test_schema_from_config_default_empty`：无配置时 schema 为空，不报错。
2. `test_profile_upsert_confidence_rule`：新 confidence 高→覆盖；低→保留旧值。
3. `test_profile_upsert_immutable`：immutable 属性已有值，新值不覆盖。
4. `test_parse_profile_response_whitelist`：LLM 返回含非 schema 属性 → 过滤；confidence 夹取。
5. `test_profile_snapshot_format`：快照文本格式 `## user_profile_snapshot\n- 姓名: ...`；超 max_chars 截断；无画像返回空串。
6. `test_extract_profile_dry_run`：mock `_summarize_fn` 返回固定 attributes，dry-run 不写库，apply 写库（monkeypatch `_managed_conn`）。

---

## 7. 验证方案

```bash
# 1) 手动跑一次聚合（dry-run 看结果）
cd /home/advancer/project/memorycore
.venv/bin/python -m memorycore profile-extract --limit 50
# 预期: {"scanned": 50, "attributes": [{"name":"姓名","value":"杜鹏洋"...}], "dry_run": true}

# 2) 应用
.venv/bin/python -m memorycore profile-extract --apply --limit 200

# 3) 查看画像
.venv/bin/python -m memorycore profile-get

# 4) 验证注入
curl -s -X POST http://127.0.0.1:8318/api/context -H 'Content-Type: application/json' \
  -d '{"task":"用户是谁","agent":"hermes","token_budget":800}' | grep -A8 "user_profile_snapshot"
# 预期: 快照块出现在 context 头部

# 5) 全量测试
.venv/bin/python -m pytest tests -q --tb=no   # 516+ passed / 7 skipped
```

---

## 8. 成本估算

| 项 | 成本 |
|---|---|
| profile-extract 每次 | 1 次 DeepSeek 调用（输入 200 条记忆 ≈ 4-6k token 输入 + 500 token 输出 ≈ ¥0.01-0.02） |
| 频率（随 curator 2x/天） | 每日 2 次 ≈ ¥0.02-0.04/天 ≈ ¥0.2/周 |
| context 注入 | 固定 ~400-600 token/次，无额外 LLM 调用 |
| **净增** | **≈ ¥0.2/周**（相比当前已优化后的 ¥3/周，占比 ~7%） |

**理由**：不增加对话热路径 LLM 调用；只复用已有 user_profile 记忆做低频聚合。

---

## 9. 风险与回滚

| 风险 | 缓解 |
|---|---|
| 抽取质量不稳定（错误画像注入系统提示词） | confidence 门槛（<0.6 不写入）；dry-run 默认；`enabled: false` 一键关闭 |
| 注入增加 token 开销 | `max_snapshot_chars` 上限；无画像时零注入 |
| 与治理计划冲突 | 本方案只新增表+模块，不触碰 I9/I10/I11 的删除面 |
| immutable 误设导致画像固化错误 | schema 可随时改；`profile-extract --apply` 幂等重建 |
| 回滚 | `git revert`；DROP `user_profile_attrs`；移除 context 注入 2 行；config `user_profile.enabled: false` |

---

## 10. 实施顺序（预计 1-1.5 天）

```
Step 1  db.py 建表 + models.py 默认值/校验        (15 min)
Step 2  storage/profile.py 核心模块               (2-3 h)
Step 3  context_pack.py 注入                     (15 min)
Step 4  server_runtime.py 3 个子命令              (30 min)
Step 5  run_curator.sh 挂载（可选）               (10 min)
Step 6  tests/test_profile.py                    (1 h)
Step 7  验证（§7）+ 手动 profile-extract 实测      (30 min)
Step 8  ITERATION.md 迭代 9 记录 + 提交
```

**执行依赖**：无（独立于 governance-slimming；可与 I9 并行或串行）。

---

## 11. 未来扩展（本期不做）

- MCP 工具 `memory_profile_get`：**不新增**（工具面已精简）；如需 Web UI 展示画像，走现有 `/api/v1` 加一个只读端点（待 I10 API 收敛后统一加）。
- 画像历史版本（时间线）：阿里云画像无失效日期；mcore 暂以"最新属性值 + source_ids 证据链"满足需求。
- 多 user_id 支持：表已就绪，默认 default；Hermes 单用户场景无差别。