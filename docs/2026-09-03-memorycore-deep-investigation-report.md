# MemoryCore (mcore) 深度探查与架构体检报告

> **报告日期**: 2026-09-03  
> **审计范围**: 检索召回管线（Context Pack / FTS5 / Qdrant）、去重与主体裁决引擎、LLM Curator 治理管线、测试套件覆盖率、SQLite/Qdrant 运行态数据  
> **审计目标**: 穿透表象深挖代码与架构中隐藏的致命缺陷（P0/P1）、梳理核心业务运转逻辑，并提供高价值功能演进路线。

---

## Executive Summary（执行摘要）

MemoryCore (mcore) 在经历多轮迭代（如迭代 213 主体上下文全域防御加固、迭代 214 检索质量观测工具落地）后，基础架构已相当健全（全量测试 607 passed）。但在本次细致代码走查与实时运行态探查中，发现了**若干隐藏极深、直接影响生产环境语义召回质量的核心缺陷**：

1. **【P0 致命缺陷】`get_vector_store()` 无参调用导致单例配置被空字典冲刷，Qdrant 向量检索频发静默断联**：
   - 生产环境监控中近 24 小时和 7 天内的双路重合度指标 `cross_retrieval_rate` 均为 `0.0000`。
   - 根因在于部分核心模块无参调用 `get_vector_store()`，由于缺少默认配置兜底，导致指纹突变强制销毁远程 Qdrant Server 连接，回退本地文件锁冲突失败，使向量检索直接降级瘫痪。
2. **【P1 测试盲区】`test_curator_llm_jobs.py` 单测假绿**：
   - 3 个核心用例因旧版内存变量被跳过（Skipped），导致已迁移到 SQLite 的冷却期机制未被单测有效覆盖。
3. **【P1 存储膨胀】运行审计与质量事件表无生命周期与滚卷清理机制**：
   - 数据库已累积 8,236 条审计日志与 1,244 条上下文质量记录，缺乏定时清理与归档。
4. **【功能断点】后端已完备的 Context Lab 评测接口未在前端 UI 落地**：
   - 后端已具备检索测试接口，但前端缺少可视化实验页面，排障仍需依赖脚本。

---

## 一、 系统运行态与数据全景

### 1.1 核心数据规模 (2026-09-03 实测)

| 统计项 | 统计值 | 状态与占比说明 |
|:---|:---|:---|
| **总记忆数 (Memories)** | **4,161 条** | 活跃 (Active) 1,864 条 (44.8%)；已归档 (Archived) 2,246 条 (54.0%)；矛盾/替代 51 条 |
| **按 Scope 作用域分布** | Global: 3,504 条 | Project: 656 条；User: 1 条 |
| **Top 记忆类型** | Project Memory | 活跃 712 条 / 归档 701 条 |
| | Environment Fact | 活跃 478 条 / 归档 384 条 |
| | Decision | 活跃 411 条 / 归档 313 条 |
| | User Profile | 活跃 120 条 / 归档 127 条 |
| **记忆链接网络 (Links)** | **2,103 条** | supports: 1,002 条；part_of: 999 条；supersedes: 90 条；related_to: 11 条；contradicts: 1 条 |
| **用户画像属性 (Profile)**| **13 个维度** | 姓名、职业、雇主、工作领域、技术栈、沟通偏好、模型偏好等核心画像全面生效 |
| **运维监控与审计事件** | Audit Events: 8,236 条 | Context Quality Events: 1,244 条；LLM Curator Batches: 136 条 |

### 1.2 检索召回质量实测基准 (eval_context_quality)

```text
时间窗口       | 事件数      | Hit Rate   | Cross Rate | Used Count
-----------------------------------------------------------------
过去 24 小时   | 133      | 0.8709     | 0.0000     | 8.98      
过去 7 天     | 281      | 0.8436     | 0.0000     | 9.26      
过去 30 天    | 553      | 0.8310     | 0.0130     | 10.53     
```
> **问题聚焦**：命中率（Hit Rate）稳定在 83%~87%，但交叉召回率（Cross Rate）近 7 天归零，暴露出向量召回与全文检索的协同断裂。

---

## 二、 隐藏缺陷与重大问题点深度分析

### 2.1 【P0 缺陷】`get_vector_store()` 单例冲刷引发 Qdrant 检索静默失效

```
[调用时序与故障链]

1. Server / Ingest 启动
   └── get_vector_store(load_config())
       └── 连接 Qdrant Server (http://127.0.0.1:6333) [Fingerprint A] -> available=True

2. Context Pack 检索执行
   ├── context_pack.py:187: _vs_hint = _gvs_hint() (无参调用)
   └── search.py:604: vs = get_vector_store() (无参调用)
       └── vs_cfg = vector_store_config_from_dict({})
       └── [Fingerprint B: path=~/.agent-memory/qdrant, url=""]
       └── 指纹不匹配！触发单例销毁重构：
           ├── 关闭现有 Server 连接
           └── 尝试以文件锁模式打开 ~/.agent-memory/qdrant
           └── 报错: Storage folder already accessed by another instance!
           └── self._initialized = False, available = False ❌

3. 结果: 后续向量搜索全部返回空列表，系统降级为纯 FTS5 关键词召回！
```

#### 根因代码分析：
位于 `memorycore/vector_store.py:774`：
```python
def get_vector_store(config: dict[str, Any] | None = None) -> VectorStore:
    global _store, _store_fingerprint
    vs_cfg = vector_store_config_from_dict(config or {})  # ⚠️ 问题出在这里：若传 None 则默认为 {}
    fingerprint = _vector_store_fingerprint(vs_cfg)
    ...
```
当 `config` 为 `None` 时，没有从全局 `load_config()` 加载默认配置，而是传空字典 `{}`。导致 `vs_cfg.url` 为空字符串，指纹与传了 `config.yaml` 的实例完全不同，单例被强行重置成单机文件模式，引发锁冲突崩溃。

#### 修复方案：
当 `config is None` 时，必须强制兜底调用 `load_config()`：
```python
def get_vector_store(config: dict[str, Any] | None = None) -> VectorStore:
    global _store, _store_fingerprint
    if config is None:
        from memorycore.models import load_config
        config = load_config()
    vs_cfg = vector_store_config_from_dict(config)
    ...
```

---

### 2.2 【P1 缺陷】`test_curator_llm_jobs.py` 单测假绿，冷却期逻辑裸奔

#### 现象：
在 pytest 报告中：
```text
SKIPPED [1] tests/test_curator_llm_jobs.py:14: _cleanup_stale_llm_jobs not implemented yet
SKIPPED [1] tests/test_curator_llm_jobs.py:26: _reviewed_memory_ids not implemented yet
SKIPPED [1] tests/test_curator_llm_jobs.py:47: _reviewed_memory_ids not implemented yet
```
#### 根因：
在早期实现中，LLM Curator 使用了内存字典 `_reviewed_memory_ids` 进行记忆冷却控制。后来为了支持服务重启与跨进程持久化，重构为 SQLite 的 `curator_review_log` 表，并由 `_get_recently_reviewed_ids()` 和 `_cleanup_reviewed_ids()` 进行管理。
然而，单元测试文件 `tests/test_curator_llm_jobs.py` 从未重构，一直通过 `if not hasattr(clm, '_reviewed_memory_ids'): pytest.skip(...)` 绕过了测试，导致生产环境核心的防重复审核冷却逻辑长期没有单元测试守护。

---

### 2.3 【P1 隐患】事件表与日志表缺乏 TTL 归档清理机制

#### 现象：
* `audit_events`: 8,236 行
* `context_quality_events`: 1,244 行
* `llm_curator_batches`: 136 行

每次智能体发起任务，`build_context_pack` 都会异步写入一条 `context_quality_events`。系统后台虽然有 `_start_auto_curator` 定时器执行 `cleanup_expired_handoffs()`，但从未包含对事件表的保留策略清理。长期运行将导致本地 SQLite 数据库碎片化与查询性能劣化。

---

## 三、 核心业务逻辑与架构全景剖析

### 3.1 检索召回与重排序架构全景图

```
                       ┌───────────────────────────────────────────────┐
                       │           Agent Prompt / Task 输入             │
                       └───────────────────────┬───────────────────────┘
                                               │
               ┌───────────────────────────────┼───────────────────────────────┐
               ▼                               ▼                               ▼
       【FTS5 全文召回】              【Qdrant 向量召回】              【实体/别名召回】
   - 词元 AND 检索 (Limit 40)      - top_k=30, threshold=0.35      - 实体/别名权重匹配
   - 候选状态降级补齐               - 长文本自动切分检索 (>200字)    - weight: 0.0 ~ 1.0
   - F2 画像查询扩展 (最多3短语)    - ⚠️ 当前易因配置空置被误杀       │
               │                               │                               │
               └───────────────────────┬───────────────────────────────┘
                                       │
                                       ▼
                       【统一重排序与过滤引擎 _rank_score】
   ┌───────────────────────────────────────────────────────────────────────────┐
   │ 线性加权基础分：                                                           │
   │   vector_score × 0.30 + lexical × 0.26 + entity_boost + source_bonus      │
   │   + high_lexical_bonus(0.15) + importance(0.05) + usage_rate(0.08)       │
   │   + effectiveness(0.04) + feedback(0.03) + recency_score + profile_boost   │
   │                                                                           │
   │ 乘法修正因子：                                                             │
   │   × candidate_discount(0.85) × short_content_penalty(0.5~1.0)              │
   │   × cross_retrieval_multiplier(1.5, 双路重合加权)                          │
   │   × profile_conflict_penalty(0.6, 画像冲突惩罚)                            │
   └───────────────────────────────────┬───────────────────────────────────────┘
                                       │
                                       ▼
                  【分类截断约束】每类最多 6 条，原子事实优先
                                       │
                                       ▼
               【Context Pack 输出】+ 异步写回 quality 指标日志
```

### 3.2 召回权重机制的逻辑问题剖析
1. **纯向量命中的“字面分惩罚”过重**：
   * 代码在 `context_pack.py:317-319` 中规定：若未命中 FTS 或 Keyword，`lexical` 强制置为 0。
   * 即使向量相似度高达 0.85 的高度语义相关记录，因为字面分（权重 0.26）和 source_bonus（0.08）双失，最终总分可能落后于仅含弱关键词的记忆。
2. **双路加权乘数 (1.5x) 失效链**：
   * 必须在记录同时出现在 `fts_records` 且在 `vector_hits` 中时，`_retrieval_sources` 才会同时打上 `["fts", "vector"]`。一旦向量单例失效，乘数永远无法激活。

---

## 四、 功能优化与演进机会点 (Enhancement Roadmap)

### 4.1 落地 Context Lab (检索实验室) 可视化界面
* **现状**：后端已具备 `/api/v1/context-lab/test` 和 `_context_lab_test` 接口，但前端 `ui/app` 缺少对应界面。
* **规划**：
  * 在 UI 中新增 `/context-lab` 路由。
  * 提供输入框输入测试 Prompt，并展示：
    1. 三路召回的原始候选列表（FTS5 / Vector / Entity）。
    2. 每条记录的 `_rank_score` 详细分解（向量分、字面分、画像加成、乘法惩罚）。
    3. 最终被截断/过滤的原因（如超过分类上限、字数惩罚等）。

### 4.2 前端 Dashboard 接入 Retrieval Quality 观测卡片
* **现状**：UI Dashboard 仅展示记忆数量与 Curator 状态，用户无法直观了解当前 Agent 检索调用的健康度。
* **规划**：
  * 对接 `get_context_quality_stats()` 接口。
  * 在仪表盘展示近 24h / 7d 的 Hit Rate 环形进度条、Cross Rate 双路协同度指示灯以及召回平均 Token 消耗。

### 4.3 数据库自动化维护任务扩充
* **规划**：
  * 在 `_start_auto_curator` 后台循环中，新增历史日志滚卷清理：
    * `context_quality_events`: 保留最近 30 天，其余自动删除。
    * `audit_events`: 保留最近 90 天，其余自动删除。
    * `llm_curator_jobs` & `llm_curator_batches`: 清理 30 天前处于 failed 或 succeeded 状态的历史运行记录。

---

## 五、 优化执行排期表

| 阶段 | 优先级 | 任务项 | 涉及文件 | 预期收益 |
|:---|:---|:---|:---|:---|
| **Phase 1** | **P0** | 修复 `get_vector_store()` 默认加载配置，增加单例重置守护 | `memorycore/vector_store.py` | 根除 Qdrant 偶发失效，恢复双路交叉召回 |
| **Phase 1** | **P1** | 重构 `test_curator_llm_jobs.py`，覆盖真实 SQLite 冷却机制 | `tests/test_curator_llm_jobs.py` | 消除 3 个 skipped 测试，实现 100% 真实断言 |
| **Phase 2** | **P1** | 增加 `context_quality_events` 与审计日志 30d/90d 定期清理 | `memorycore/storage/maintenance.py` | 消除数据库膨胀与索引劣化隐患 |
| **Phase 2** | **P2** | 前端新增 `/context-lab` 调试页面与 Dashboard 质量卡片 | `ui/app/context-lab/page.tsx`, `ui/app/page.tsx` | 极大提升日常调试与质量监控直观度 |
