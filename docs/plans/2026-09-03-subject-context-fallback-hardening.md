# 记忆主体上下文全域防御加固（迭代 213）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 彻底消除脱离 `~/project/*` 目录（如在 `/home/advancer/公共的`、桌面、家目录）对话时产生“无主体无标签记忆”的边缘漏洞，建立环境发现、常态 Prompt、标题反查、自动提权四层立体防御。

**Architecture:**
1. **环境发现层**：配置与 `subject_context.py` 扩展支持 `discovery_roots` 多根目录扫描。
2. **提取指令层**：将 `subject` / `entities` 正式纳入基础 JSON Schema，常态声明主体识别规则，解耦环境注入。
3. **落库裁决层**：`dedup.py` 实现四级 Fallback 链，新增 `infer_subject_from_title()` 标题前缀反查兜底，自动补全 `project_path`、`project:*` 标签与升级 `scope=project`。
4. **数据自愈**：修补当日在公共目录产生的无头漏网记录（如 `2b44f21d`）。

**Tech Stack:** Python 3.11, pytest, SQLite3, YAML, MCP

## Global Constraints

- 严禁重排 `ITERATION.md` 历史编号；新条目一律取最大编号 + 1（即 `[迭代 213]`）追加在底部。
- 所有数据操作前必须执行 SQLite 备份。
- 代码保持高内聚低耦合，函数不超过 50 行，模块不超过 700 行。
- 测试用例必须通过 TDD 流程（RED -> GREEN -> REFACTOR），全量测试保持 0 failed。

---

## 总体防御架构图

```
                        用户对话输入 (任意目录，如 /home/advancer/公共的)
                                     │
               ┌─────────────────────┴─────────────────────┐
               ▼                                           ▼
       【防线 1：多根目录探测】                     【防线 2：常态提取 Prompt】
       discovery_roots 多工作区支持                Schema 永久包含 subject / entities
       扫描 ~/project, 公共的 等                    无 Active Context 也能提取主体
               │                                           │
               └─────────────────────┬─────────────────────┘
                                     ▼
                          ExtractedFact (带有或未带有 subject)
                                     │
                                     ▼
                          【防线 3：四级裁决引擎 (dedup.py)】
              ┌─────────────────────────────────────────────────┐
              │ 1. 优先: LLM 显式提取的 fact.subject              │
              │ 2. 其次: 环境变量/路径推导出的 project_name        │
              │ 3. 兜底: infer_subject_from_title (标题前缀反查) │
              │          "mcore ..." 自动命中项目 mcore!         │
              │ 4. 保底: 保留为通用 global 记忆                   │
              └─────────────────────────────────────────────────┘
                                     │ (若命中 1~3 任意一级)
                                     ▼
                          【防线 4：元数据反向自动提权】
              - subject = project_info["name"]
              - resolved_path = resolved_path or project_info["path"]
              - mem_scope 升级: global -> project
              - fact_tags 必填: project:<name>
              - 触发 entities.py 强制注入项目实体索引
```

---

## File Structure

- Modify: `memorycore/models.py:456-478` — 校验与默认配置中支持 `discovery_roots`
- Modify: `config.yaml:110-125` — 生产配置追加 `discovery_roots`
- Modify: `memorycore/subject_context.py:40-165` — 实现多根扫描与 `infer_subject_from_title()`
- Modify: `memorycore/extraction.py:47-95, 290-310` — 常态化 `subject` JSON Schema 与提示词解耦
- Modify: `memorycore/dedup.py:400-440` — 实现四级主体裁决与元数据自动提权逻辑
- Modify: `tests/test_subject_context.py` — 新增多根目录探测、标题反查与 Fallback 单测
- Modify: `TODO.md` & `ITERATION.md` — 记录迭代 213 完成情况

---

### Task 1: 配置层支持多工作根目录 (`discovery_roots`)

**Files:**
- Modify: `memorycore/models.py`
- Modify: `config.yaml`
- Test: `tests/test_subject_context.py`

**Interfaces:**
- Consumes: `DEFAULT_CONFIG["subject_context"]`
- Produces: `sc.get("discovery_roots", [])`

- [ ] **Step 1: 编写多根目录配置校验的失败测试**

在 `tests/test_subject_context.py` 中追加测试类 `TestSubjectConfig`：

```python
def test_validate_config_discovery_roots_valid():
    from memorycore.models import validate_config
    cfg = {
        "subject_context": {
            "enabled": True,
            "discovery_roots": ["~/project", "/home/advancer/公共的"],
            "projects": [],
        }
    }
    warnings = validate_config(cfg)
    assert not any("discovery_roots" in w for w in warnings)

def test_validate_config_discovery_roots_invalid():
    from memorycore.models import validate_config
    cfg = {
        "subject_context": {
            "enabled": True,
            "discovery_roots": "not-a-list",
            "projects": [],
        }
    }
    warnings = validate_config(cfg)
    assert any("discovery_roots must be a list" in w for w in warnings)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_subject_context.py -k "test_validate_config_discovery_roots" -v`
Expected: FAIL (因为目前还没有校验 discovery_roots)

- [ ] **Step 3: 实现配置模型校验与默认项**

在 `memorycore/models.py` 的 `DEFAULT_CONFIG` 中：
```python
        "subject_context": {
            "enabled": False,
            "default_scope": "global",
            "auto_discover": False,
            "discovery_roots": ["~/project"],
            "projects": [],
        },
```
在 `validate_config()` 中：
```python
    roots = sc.get("discovery_roots", [])
    if roots is not None and not isinstance(roots, list):
        _warn("subject_context.discovery_roots must be a list")
```

并在 `config.yaml` 中配置：
```yaml
subject_context:
  enabled: true
  default_scope: global
  auto_discover: true
  discovery_roots:
    - ~/project
    - /home/advancer/公共的
  projects:
    - name: mcore
      paths:
        - ~/project/memorycore
      aliases:
        - memorycore
        - MemoryCore
      scope: project
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/test_subject_context.py -k "test_validate_config_discovery_roots" -v`
Expected: PASS

- [ ] **Step 5: 提交代码**

```bash
git add memorycore/models.py config.yaml tests/test_subject_context.py
git commit -m "feat(subject): support discovery_roots in subject_context config"
```

---

### Task 2: 服务端环境探测支持多根目录扫描与非 git 别名注册

**Files:**
- Modify: `memorycore/subject_context.py`
- Test: `tests/test_subject_context.py`

**Interfaces:**
- Consumes: `sc.get("discovery_roots")`
- Produces: `discover_projects(sc) -> dict[str, dict[str, Any]]`

- [ ] **Step 1: 编写多根目录扫描的失败测试**

在 `tests/test_subject_context.py` 中追加：

```python
def test_discover_projects_multi_roots(tmp_path):
    import subprocess
    from memorycore.subject_context import discover_projects

    root1 = tmp_path / "root1"
    root2 = tmp_path / "root2"
    root1.mkdir()
    root2.mkdir()

    repo1 = root1 / "proj-a"
    repo1.mkdir()
    subprocess.run(["git", "init", "-q", str(repo1)], check=True)

    repo2 = root2 / "proj-b"
    repo2.mkdir()
    subprocess.run(["git", "init", "-q", str(repo2)], check=True)

    sc = {
        "enabled": True,
        "auto_discover": True,
        "discovery_roots": [str(root1), str(root2)],
    }
    discovered = discover_projects(sc)
    assert "proj-a" in discovered
    assert "proj-b" in discovered
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_subject_context.py -k "test_discover_projects_multi_roots" -v`
Expected: FAIL

- [ ] **Step 3: 改造 `discover_projects` 支持 `discovery_roots`**

在 `memorycore/subject_context.py` 中：
```python
def discover_projects(sc: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    if sc is None:
        sc = subject_config()
    if not sc or not sc.get("auto_discover", False):
        return {}
    from pathlib import Path
    
    roots = sc.get("discovery_roots") or []
    if not roots:
        env_root = os.environ.get("MCORE_PROJECTS_ROOT")
        roots = [env_root] if env_root else [str(Path.home() / "project")]

    discovered: dict[str, dict[str, Any]] = {}
    for r in roots:
        base = Path(os.path.expandvars(os.path.expanduser(str(r).strip()))).resolve()
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if not child.is_dir():
                continue
            # 支持 git 仓库或直接目录
            if (child / ".git").exists():
                name = child.name
                discovered[name.lower()] = {
                    "name": name,
                    "aliases": [name.lower()],
                    "scope": "project",
                    "path": str(child),
                }
    return discovered
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/test_subject_context.py -k "test_discover_projects_multi_roots" -v`
Expected: PASS

- [ ] **Step 5: 提交代码**

```bash
git add memorycore/subject_context.py tests/test_subject_context.py
git commit -m "feat(subject): support multi-root discovery in discover_projects"
```

---

### Task 3: 标题前缀/别名反查兜底引擎 (`infer_subject_from_title`)

**Files:**
- Modify: `memorycore/subject_context.py`
- Test: `tests/test_subject_context.py`

**Interfaces:**
- Produces: `infer_subject_from_title(title: str, cfg: dict | None = None) -> dict | None`

- [ ] **Step 1: 编写标题前缀反查的失败测试**

在 `tests/test_subject_context.py` 中追加：

```python
class TestInferSubjectFromTitle:
    def test_infer_from_exact_name(self):
        from memorycore.subject_context import infer_subject_from_title
        p = infer_subject_from_title("mcore 记忆主体治理完成落地", cfg=SUBJECT_CFG)
        assert p is not None
        assert p["name"] == "mcore"
        assert p["scope"] == "project"

    def test_infer_from_alias_name(self):
        from memorycore.subject_context import infer_subject_from_title
        p = infer_subject_from_title("MemoryCore 当前进展汇总", cfg=SUBJECT_CFG)
        assert p is not None
        assert p["name"] == "mcore"

    def test_infer_with_colons_or_brackets(self):
        from memorycore.subject_context import infer_subject_from_title
        p = infer_subject_from_title("[mcore]: 修复断点问题", cfg=SUBJECT_CFG)
        assert p is not None
        assert p["name"] == "mcore"

    def test_infer_no_match(self):
        from memorycore.subject_context import infer_subject_from_title
        p = infer_subject_from_title("今日天气不错", cfg=SUBJECT_CFG)
        assert p is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_subject_context.py -k "TestInferSubjectFromTitle" -v`
Expected: FAIL (`infer_subject_from_title` 未定义)

- [ ] **Step 3: 实现 `infer_subject_from_title`**

在 `memorycore/subject_context.py` 中实现：

```python
def infer_subject_from_title(
    title: str,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """从标题前缀提取项目名/别名并反查为已知项目。"""
    if not title or not title.strip():
        return None
    import re
    # 过滤开头的特殊括号符号，提取可能的前缀词元
    cleaned = re.sub(r"^[\[\(\<【〔（]+", "", title.strip())
    tokens = [t for t in re.split(r"[\s:：_\-—/\]\)\>】〕）]+", cleaned) if t]
    if not tokens:
        return None

    # 1. 尝试单个词匹配 (e.g. "mcore", "MemoryCore")
    first = tokens[0].strip()
    proj = resolve_project(project_name=first, cfg=cfg)
    if proj:
        return proj

    # 2. 尝试前两个词组合 (e.g. "cpa", "manager" -> "cpa-manager")
    if len(tokens) >= 2:
        combo = f"{tokens[0]}-{tokens[1]}".strip()
        proj = resolve_project(project_name=combo, cfg=cfg)
        if proj:
            return proj

    return None
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/test_subject_context.py -k "TestInferSubjectFromTitle" -v`
Expected: PASS

- [ ] **Step 5: 提交代码**

```bash
git add memorycore/subject_context.py tests/test_subject_context.py
git commit -m "feat(subject): implement infer_subject_from_title for fallback matching"
```

---

### Task 4: 提取 Prompt 常态化与解耦

**Files:**
- Modify: `memorycore/extraction.py`
- Test: `tests/test_subject_context.py`

**Interfaces:**
- `ADDITIVE_EXTRACTION_PROMPT`: Schema 常态包含 `subject` 字段
- `extract_facts()`: 即使 `project_name=""`，也注入基础主体规范指令

- [ ] **Step 1: 编写提取 Prompt 常态声明的测试**

在 `tests/test_subject_context.py` 的 `TestExtractionSubject` 中增加：

```python
    def test_extract_facts_prompt_always_contains_subject_schema(self):
        from memorycore.extraction import ADDITIVE_EXTRACTION_PROMPT
        assert '"subject":' in ADDITIVE_EXTRACTION_PROMPT
        assert '"entities":' in ADDITIVE_EXTRACTION_PROMPT

    def test_extract_facts_system_prompt_has_general_subject_rule_without_project(self):
        captured = {}

        def fake_call(system_prompt, user_prompt, config):
            captured["system"] = system_prompt
            return json.dumps({"memory": []})

        with patch("memorycore.extraction._call_llm", side_effect=fake_call):
            extract_facts(
                [{"role": "user", "content": "讨论关于 mcore 的优化"}],
                config=__import__("memorycore.extraction", fromlist=["ExtractionConfig"]).ExtractionConfig(api_key="k"),
                project_name="",
            )
        assert "Subject Context" in captured["system"]
        assert "每条 fact 必须附 \"subject\"" in captured["system"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_subject_context.py -k "test_extract_facts_system_prompt_has_general_subject_rule_without_project" -v`
Expected: FAIL

- [ ] **Step 3: 修改 `extraction.py` 常态化 Schema 与指令**

在 `memorycore/extraction.py` 中更新 `ADDITIVE_EXTRACTION_PROMPT`：
```json
{{
  "memory": [
    {{
      "id": "0",
      "title": "...",
      "content": "...",
      "type": "decision",
      "importance": 0.8,
      "subject": "mcore",
      "entities": ["mcore"],
      "linked_memory_ids": ["<existing-uuid>"]
    }}
  ]
}}
```

并在 `extract_facts()` 中解除 `if project_name:` 对指令的封锁：
```python
    # Subject context (P1): 基础的主体提取规范永久生效
    from memorycore.subject_context import SUBJECT_PROMPT_INSTRUCTION, active_context_block
    system_prompt += SUBJECT_PROMPT_INSTRUCTION

    # 仅当具体项目已知时，注入 Active Context 说明
    active_context = ""
    if project_name:
        active_context = active_context_block(project_name, project_path, scope)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/test_subject_context.py -k "TestExtractionSubject" -v`
Expected: PASS

- [ ] **Step 5: 提交代码**

```bash
git add memorycore/extraction.py tests/test_subject_context.py
git commit -m "refactor(extraction): make subject and entities schema permanent in prompt"
```

---

### Task 5: `dedup.py` 四级裁决引擎与元数据自动提权

**Files:**
- Modify: `memorycore/dedup.py`
- Test: `tests/test_subject_context.py`

**Interfaces:**
- Consumes: `fact.subject`, `project_name`, `infer_subject_from_title()`
- Produces: 强化后的 `subject`, `fact_tags`, `mem_scope`, `project_path`, `metadata.subject`

- [ ] **Step 1: 编写脱离项目目录（但标题含项目名）时的自动识别测试**

在 `tests/test_subject_context.py` 的 `TestIngestSubject` 中增加：

```python
    def test_ingest_in_non_project_dir_auto_recovers_subject_from_title(self):
        captured = {}

        def add_memory_fn(**kwargs):
            captured.update(kwargs)
            return {"id": kwargs.get("memory_id")}

        # 模拟在 /home/advancer/公共的 产生的记忆：
        # project_path 为外部路径，LLM 漏了 subject，但标题明确以 mcore 开头
        fact = ExtractedFact(
            text="mcore 记忆主体上下文治理完成落地实施",
            title="mcore 记忆主体上下文治理完成落地实施",
            importance=0.8,
            memory_type="project_memory",
            subject="",  # LLM 漏填
        )
        self._run(fact, "/home/advancer/公共的", add_memory_fn, expect_resolve=False)

        # 断言兜底引擎生效：自动补齐 project 标签、升级 scope 并反查补齐路径
        assert captured["metadata"].get("subject") == "mcore"
        assert "project:mcore" in captured["tags"]
        assert captured["scope"] == "project"
        assert captured["project_path"] == "/home/advancer/project/memorycore"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_subject_context.py -k "test_ingest_in_non_project_dir_auto_recovers_subject_from_title" -v`
Expected: FAIL (`captured["metadata"].get("subject")` 为 None，`tags` 缺 `project:mcore`)

- [ ] **Step 3: 在 `memorycore/dedup.py` 中实现四级裁决引擎**

修改 `memorycore/dedup.py`：
```python
            from memorycore.subject_context import infer_subject_from_title

            # 四级主体裁决引擎
            raw_subject = (getattr(fact, "subject", "") or "").strip()
            resolved_proj = None

            # 1. 优先采用 LLM 提取的 subject 归一化
            if raw_subject:
                resolved_proj = resolve_project(project_name=raw_subject, cfg=cfg)

            # 2. 其次采用会话环境探测出的 project
            if not resolved_proj and project:
                resolved_proj = project

            # 3. 兜底防线：从标题前缀提取反查
            if not resolved_proj:
                resolved_proj = infer_subject_from_title(fact_title, cfg=cfg)

            # 元数据增强与自动提权
            fact_tags = ["extracted", f"agent:{agent_id}"]
            if resolved_proj:
                subject = resolved_proj["name"]
                resolved_path = resolved_path or resolved_proj.get("path", "")
                mem_scope = "project"  # 自动提权为 project 级 scope
                fact_tags.append(f"project:{subject}")
                subject_meta = {"subject": subject}
                if not fact_title.lower().startswith(subject.lower()):
                    fact_title = f"{subject} {fact_title}"[:title_max]
            else:
                subject = ""
                subject_meta = {}
```

并在调用 `_add_memory_fn` 处传入提升后的 `scope=mem_scope` 与 `project_path=resolved_path`。

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/test_subject_context.py -k "test_ingest_in_non_project_dir_auto_recovers_subject_from_title" -v`
Expected: PASS

- [ ] **Step 5: 提交代码**

```bash
git add memorycore/dedup.py tests/test_subject_context.py
git commit -m "feat(dedup): implement 4-level subject resolution and auto promotion"
```

---

### Task 6: 数据自愈与全量回归验证

**Files:**
- Modify: `scripts/backfill_subject.py`
- Test: 全量 pytest 594+ 用例

- [ ] **Step 1: 运行全量测试套件**

Run: `.venv/bin/pytest`
Expected: 597+ passed, 0 failed, 7 skipped

- [ ] **Step 2: 对 2026-09-03 产生的漏网数据执行自动修复**

执行带有严格备份的自愈修复：
```bash
python scripts/backfill_subject.py --apply
```
验证目标记录（如 `2b44f21d`）已成功被打上 `project:mcore` 标签、`project_path` 与 `scope=project`。

- [ ] **Step 3: 更新 `TODO.md` 与 `ITERATION.md`**

在 `ITERATION.md` 底部以 `[迭代 213]` 记录完整变更、设计与验证结果，严格遵守编号冻结规则。

- [ ] **Step 4: 最终提交并重启服务**

```bash
git add TODO.md ITERATION.md
git commit -m "docs(iteration): record iteration 213 subject context fallback hardening"
systemctl --user restart mcore.service
```

---

## 验收标准 (DoD)

1. **单测覆盖完整**：`tests/test_subject_context.py` 全部用例通过，全量 pytest 保持 0 failed。
2. **边缘场景实测通过**：在 `/home/advancer/公共的` 或任何非项目路径执行 ingest，只要文本或标题涉及已知项目（如 `mcore ...`），落库记录的 `tags` 必带 `project:<name>`、`scope` 必为 `project`、`metadata.subject` 必有规范项目名。
3. **实体搜索 100% 召回**：`entity_search("mcore")` 确定性命中新产生的所有相关记忆。
4. **服务运行平稳**：`mcore.service` 健康状态 200，前端智能中心可用池健康稳定保持在 98%+。
