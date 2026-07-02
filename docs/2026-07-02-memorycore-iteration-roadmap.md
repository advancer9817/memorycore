# MemoryCore 迭代路线图（基于深度审计）

> **制定日期**: 2026-07-02  
> **基于文档**: 2026-07-02-memorycore-deep-audit-report-v2.md  
> **目标**: 解决审计发现的核心问题，优化系统架构，提升记忆召回率  
> **执行周期**: 8 周（2026-07-02 至 2026-08-27）

---

## 执行摘要

基于深度审计发现的 3 个核心问题：
1. **69% active 记忆从未被召回** — 价值泄漏
2. **2,221 条治理决策积压** — 人工审核失效
3. **原子化拆分产出 46%** — 可能制造噪声

本路线图将问题分解为 **5 个迭代 Phase**，每个 Phase 1-2 周，按优先级从高到低执行。

**成功指标**（8 周后）:
- Active 记忆未召回率: 69% → **< 40%**
- 治理积压: 2,221 条 → **< 200 条**
- Context Pack hit_rate: 0.813 → **> 0.90**
- 系统代码量: 31,100 行 → **< 28,000 行**（删除死代码）

---

## Phase 0: 准备工作（Week 1, Day 1-2）

### 目标
建立基线指标和监控面板，为后续优化提供数据支撑。

### 任务清单

#### 0.1 建立基线指标数据库

**操作**:
```bash
# 创建基线快照
cd /home/advancer/project/memorycore
python3 << 'PYEOF'
import sqlite3
import json
from datetime import datetime

conn = sqlite3.connect('memory.sqlite3')
conn.row_factory = sqlite3.Row

baseline = {
    'timestamp': datetime.now().isoformat(),
    'memories': {
        'total': conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0],
        'active': conn.execute("SELECT COUNT(*) FROM memories WHERE status='active'").fetchone()[0],
        'never_injected': conn.execute("SELECT COUNT(*) FROM memories WHERE status='active' AND injected_count=0").fetchone()[0],
    },
    'governance': {
        'total': conn.execute("SELECT COUNT(*) FROM governance_decisions").fetchone()[0],
        'needs_review': conn.execute("SELECT COUNT(*) FROM governance_decisions WHERE review_status='needs_review'").fetchone()[0],
    },
    'context_quality': {
        'avg_hit_rate': conn.execute("SELECT AVG(hit_rate) FROM context_quality_events").fetchone()[0],
        'avg_used_count': conn.execute("SELECT AVG(used_count) FROM context_quality_events").fetchone()[0],
    }
}

with open('docs/baseline-2026-07-02.json', 'w') as f:
    json.dump(baseline, f, indent=2)

print("Baseline saved:", json.dumps(baseline, indent=2))
conn.close()
PYEOF
```

**验收标准**: 生成 `docs/baseline-2026-07-02.json` 文件

**预期时间**: 30 分钟

---

#### 0.2 添加前端监控面板

**目标**: 在 Dashboard 展示关键指标，实时监控优化效果

**新增指标卡片**:
1. **召回效率卡片**:
   - Active 记忆总数
   - 未召回记忆数
   - 未召回率（百分比 + 趋势图）
2. **治理健康卡片**:
   - needs_review 积压数
   - 积压率
   - 最近 7 天 applied 速度
3. **LLM Curator 卡片**:
   - 最近运行时间
   - 处理记忆数
   - 成功率（如果可获取）

**实现路径**:
```typescript
// ui/app/page.tsx 添加新组件
<RecallEfficiencyCard />
<GovernanceHealthCard />
<LLMCuratorStatusCard />
```

**API 端点**:
```python
# memorycore/frontend.py
@app.get("/api/v1/metrics/recall")
async def get_recall_metrics():
    # 返回召回效率指标

@app.get("/api/v1/metrics/governance")
async def get_governance_metrics():
    # 返回治理健康指标
```

**验收标准**: 
- Dashboard 显示 3 个新卡片
- 数据实时更新（30s 刷新）

**预期时间**: 4 小时

---

#### 0.3 修复 Silent Failure（Quick Win）

**目标**: 让写入队列错误可见，提高系统可观测性

**修改文件**: `memorycore/storage/search.py`

**变更**:
```python
# 第 78 行附近
# 修改前:
except Exception:
    pass

# 修改后:
except Exception as e:
    logger.warning(
        "Context pack injection count update failed",
        exc_info=True,
        extra={"memory_ids": [r.get("id") for r in results[:5]]}  # 记录前 5 个 ID
    )
```

**验收标准**: 
- 修改后运行 1 次 context pack 调用
- 检查 `mcore.log` 中是否有相关日志输出
- 无报错即为成功

**预期时间**: 15 分钟

---

### Phase 0 总结

**完成时间**: 2 天  
**交付物**:
- ✅ 基线指标 JSON 文件
- ✅ Dashboard 监控面板（3 个新卡片）
- ✅ Silent Failure 修复

**验证方法**: 访问 `http://localhost:8318/` 查看新卡片显示

---

## Phase 1: 召回失败根因分析与修复（Week 1-2）

### 目标
解决 **69% active 记忆从未被召回** 的核心问题，将未召回率降到 < 50%。

### 假设验证流程

```
假设 1: 原子化拆分制造噪声 
  → 按来源统计未召回率 
  → 如果 atomizer/governance_split 显著高于 extraction 
  → 提高拆分阈值或暂停拆分

假设 2: 召回算法问题
  → 如果所有来源未召回率均高
  → 降低向量阈值、调整融合权重

假设 3: 记忆内容质量问题
  → 抽样分析未召回记忆的内容
  → 识别共同特征（过短、过长、缺乏关键词等）
```

---

### 任务清单

#### 1.1 数据分析：按来源统计未召回率

**目标**: 确认哪些来源的记忆召回率最低

**执行脚本**:
```bash
cd /home/advancer/project/memorycore
python3 << 'PYEOF'
import sqlite3
import json

conn = sqlite3.connect('memory.sqlite3')
conn.row_factory = sqlite3.Row

# 按来源统计
rows = conn.execute("""
    SELECT 
        source,
        COUNT(*) as total,
        SUM(CASE WHEN injected_count = 0 THEN 1 ELSE 0 END) as never_injected,
        SUM(CASE WHEN injected_count > 0 THEN 1 ELSE 0 END) as injected,
        SUM(CASE WHEN injected_count = 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as pct_never,
        AVG(LENGTH(content)) as avg_content_len
    FROM memories 
    WHERE status = 'active'
    GROUP BY source
    ORDER BY pct_never DESC;
""").fetchall()

result = [dict(row) for row in rows]
print(json.dumps(result, indent=2))

# 保存结果
with open('docs/recall-analysis-by-source.json', 'w') as f:
    json.dump(result, f, indent=2)

conn.close()
PYEOF
```

**验收标准**: 生成 `docs/recall-analysis-by-source.json`

**决策树**:
- 如果 `atomizer` 或 `governance_split` 的 `pct_never` > 80% → 执行 1.2（暂停拆分）
- 如果所有来源的 `pct_never` 都 > 60% → 执行 1.3（调整召回算法）
- 如果差异不明显 → 执行 1.4（内容质量分析）

**预期时间**: 30 分钟

---

#### 1.2 实验 A：暂停原子化拆分（条件触发）

**触发条件**: 1.1 分析显示 atomizer/governance_split 未召回率 > 80%

**目标**: 验证拆分是否在制造噪声

**操作**:
```python
# memorycore/storage/governance.py
# 在 judge_candidate() 函数中添加临时开关

def judge_candidate(candidate: dict, config: dict) -> dict:
    # 临时禁用拆分决策（实验期 2 周）
    if candidate.get('decision_type') == 'split_candidate':
        return {
            'review_status': 'rejected',
            'reason': 'Split temporarily disabled for experiment (Phase 1.2)',
            'confidence': 0.0
        }
    
    # 原有逻辑...
```

**同时提高规则拆分阈值**:
```yaml
# config.yaml
extraction_strategy:
  # 从 600 → 1000
  min_split_length: 1000
  
llm_curator:
  # 从 400 → 1000
  split_content_threshold: 1000
```

**验收标准**: 
- 观察 2 周后新增记忆的来源分布
- atomizer + governance_split 来源的新记忆数应显著减少

**回滚方案**: 如果 2 周后召回率无改善，恢复原配置

**预期时间**: 1 小时

---

#### 1.3 实验 B：调整召回算法（条件触发）

**触发条件**: 1.1 分析显示所有来源未召回率均 > 60%

**目标**: 提升 Context Pack 召回能力

**A. 降低向量搜索阈值**:
```yaml
# config.yaml
# 修改前: score_threshold: 0.35
# 修改后: score_threshold: 0.28
```

**B. 调整融合权重**:
```python
# memorycore/storage/search.py
# 在 build_context_pack() 函数中

# 修改前: FTS5 权重 0.6, Qdrant 权重 0.4
# 修改后: FTS5 权重 0.4, Qdrant 权重 0.6

def _merge_results(fts_results, vector_results):
    # 调整权重计算
    for r in fts_results:
        r['score'] = r.get('rank', 1.0) * 0.4  # 降低 FTS5 权重
    for r in vector_results:
        r['score'] = r.get('similarity', 0.5) * 0.6  # 提高向量权重
```

**C. 扩大候选池**:
```yaml
# config.yaml
context_pack:
  max_records_per_group: 10  # 从 6 增加到 10
  default_token_budget: 2500  # 从 2000 增加到 2500
```

**验收标准**: 
- 运行 1 周后统计 context_quality_events
- 如果 hit_rate 下降 > 5% → 回滚
- 如果 hit_rate 保持或提升 且 used_count 增加 → 成功

**A/B 测试方案**: 
- 前 3 天使用新配置记录结果
- 对比基线数据的 hit_rate 和 used_count
- 根据数据决定是否保留

**预期时间**: 2 小时（配置） + 1 周观察

---

#### 1.4 内容质量分析：抽样未召回记忆

**目标**: 识别未召回记忆的共同特征

**执行脚本**:
```bash
python3 << 'PYEOF'
import sqlite3
import json
from collections import Counter

conn = sqlite3.connect('memory.sqlite3')
conn.row_factory = sqlite3.Row

# 抽样 100 条未召回记忆
rows = conn.execute("""
    SELECT id, title, content, source, type, LENGTH(content) as len
    FROM memories 
    WHERE status = 'active' AND injected_count = 0
    ORDER BY RANDOM()
    LIMIT 100;
""").fetchall()

samples = [dict(row) for row in rows]

# 分析特征
analysis = {
    'total_samples': len(samples),
    'avg_length': sum(s['len'] for s in samples) / len(samples),
    'length_distribution': {
        'very_short (<50)': len([s for s in samples if s['len'] < 50]),
        'short (50-150)': len([s for s in samples if 50 <= s['len'] < 150]),
        'medium (150-500)': len([s for s in samples if 150 <= s['len'] < 500]),
        'long (>500)': len([s for s in samples if s['len'] >= 500]),
    },
    'type_distribution': dict(Counter(s['type'] for s in samples)),
    'source_distribution': dict(Counter(s['source'] for s in samples)),
}

print(json.dumps(analysis, indent=2))

# 保存样本
with open('docs/never-injected-samples.json', 'w') as f:
    json.dump({'analysis': analysis, 'samples': samples[:20]}, f, indent=2)

conn.close()
PYEOF
```

**人工审查**: 阅读 `never-injected-samples.json` 中的前 20 个样本，识别问题:
- 内容过于简短（< 50 字符）
- 内容过于泛化（如"完成了任务"）
- 内容是纯代码片段（无自然语言）
- 内容是调试日志（临时性信息）

**根据发现调整策略**:
- 如果大量是过短内容 → 在提取阶段添加最小长度限制
- 如果大量是代码片段 → 调整提取 prompt，减少代码提取
- 如果大量是临时信息 → 调整 episodic 记忆的晋升策略

**预期时间**: 1 小时分析 + 2 小时调整

---

#### 1.5 中文分词优化（可选）

**目标**: 提升 FTS5 中文搜索准确性

**问题**: SQLite FTS5 默认按 Unicode 字符边界分词，对中文不友好

**方案 A — 使用 jieba 预分词**:
```python
# memorycore/storage/search.py
import jieba

def _preprocess_chinese(text: str) -> str:
    """中文分词预处理"""
    if not text:
        return text
    # 简单启发式：如果包含 > 30% 中文字符，进行分词
    chinese_chars = sum(1 for c in text if '一' <= c <= '鿿')
    if chinese_chars / len(text) > 0.3:
        return ' '.join(jieba.cut(text))
    return text

# 在写入 FTS5 前调用
fts_content = _preprocess_chinese(content)
```

**方案 B — 使用 Simple Tokenizer**:
```sql
-- 在初始化 FTS5 表时
CREATE VIRTUAL TABLE memories_fts USING fts5(
    content,
    tokenize='unicode61 remove_diacritics 2'  -- 改进分词
);
```

**验收标准**: 
- 搜索常见中文词汇（"配置"、"修复"、"优化"）
- 召回率应提升

**预期时间**: 3 小时（如果选择实施）

---

### Phase 1 总结

**完成时间**: 2 周  
**交付物**:
- ✅ 召回分析报告（按来源）
- ✅ 未召回记忆样本分析
- ✅ 实验 A（暂停拆分）或 实验 B（调整召回）
- ✅ 中文分词优化（可选）

**成功指标**:
- Active 记忆未召回率: 69% → **< 55%**
- Context Pack hit_rate: 0.813 → **> 0.85**

**验证方法**: 
```bash
# 2 周后执行
python3 << 'PYEOF'
import sqlite3
conn = sqlite3.connect('memory.sqlite3')
never_rate = conn.execute("""
    SELECT 
        COUNT(CASE WHEN injected_count = 0 THEN 1 END) * 100.0 / COUNT(*) 
    FROM memories WHERE status='active'
""").fetchone()[0]
print(f"Current never-injected rate: {never_rate:.1f}%")
conn.close()
PYEOF
```

---

## Phase 2: 治理系统修复（Week 3-4）

### 目标
解决 **2,221 条 needs_review 积压**，让治理系统恢复流畅运作。

### 策略
采用 **三管齐下** 策略：降阈值 + 批量重分类 + 精简保护类型

---

### 任务清单

#### 2.1 降低 auto_approve 阈值

**目标**: 让更多低风险决策自动通过

**操作**:
```yaml
# config.yaml
governance:
  auto_approve_confidence: 0.65  # 从 0.8 降到 0.65
  auto_approve_low_risk_confidence: 0.60  # 从 0.7 降到 0.60
  review_confidence_threshold: 0.50  # 从 0.55 降到 0.50
```

**影响分析**:
- 预计 40-50% 的 needs_review 决策将改为 auto_approved
- 低风险动作（archive_duplicate, downgrade）更容易自动通过
- 高风险动作（delete, merge, split）仍需审核

**验收标准**: 
- 观察 3 天后新增决策的分布
- needs_review 新增速度应 < applied 新增速度

**回滚方案**: 如果出现大量错误决策（通过 rollback 次数判断），恢复原阈值

**预期时间**: 15 分钟

---

#### 2.2 批量重新分类积压决策

**目标**: 清理历史积压，给治理系统"重启"

**操作脚本**:
```bash
cd /home/advancer/project/memorycore
python3 << 'PYEOF'
import sqlite3

conn = sqlite3.connect('memory.sqlite3')
cursor = conn.cursor()

# 重新分类积压决策的安全规则
# 1. confidence > 0.7 且 非删除/合并 → auto_approved
# 2. confidence ∈ [0.6, 0.7] 且 低风险动作 → auto_approved
# 3. 其余保持 needs_review

# 规则 1: 高置信度 + 非高风险
cursor.execute("""
    UPDATE governance_decisions
    SET review_status = 'auto_approved',
        updated_at = datetime('now')
    WHERE review_status = 'needs_review'
      AND confidence > 0.7
      AND action NOT IN ('delete', 'hard_delete', 'merge', 'split')
      AND decision_type NOT IN ('split_candidate');
""")
rule1_count = cursor.rowcount

# 规则 2: 中等置信度 + 低风险动作
cursor.execute("""
    UPDATE governance_decisions
    SET review_status = 'auto_approved',
        updated_at = datetime('now')
    WHERE review_status = 'needs_review'
      AND confidence BETWEEN 0.6 AND 0.7
      AND action IN ('archive_duplicate', 'downgrade', 'archive', 'mark_stale');
""")
rule2_count = cursor.rowcount

# 规则 3: 超低置信度直接拒绝（< 0.45）
cursor.execute("""
    UPDATE governance_decisions
    SET review_status = 'rejected',
        updated_at = datetime('now')
    WHERE review_status = 'needs_review'
      AND confidence < 0.45;
""")
rule3_count = cursor.rowcount

conn.commit()

print(f"Recalibration completed:")
print(f"  Rule 1 (high confidence, low risk): {rule1_count} auto-approved")
print(f"  Rule 2 (medium confidence, safe actions): {rule2_count} auto-approved")
print(f"  Rule 3 (very low confidence): {rule3_count} rejected")
print(f"  Total processed: {rule1_count + rule2_count + rule3_count}")

# 查询剩余 needs_review
remaining = cursor.execute("""
    SELECT COUNT(*) FROM governance_decisions WHERE review_status = 'needs_review'
""").fetchone()[0]
print(f"  Remaining needs_review: {remaining}")

conn.close()
PYEOF
```

**验收标准**: 
- needs_review 从 2,221 降到 < 500
- 生成报告记录重分类规则和数量

**风险**: 可能自动批准少量不当决策

**缓解**: 
- 通过审计日志可追溯
- 监控 rollback 次数，如果突增则暂停自动批准

**预期时间**: 30 分钟执行 + 1 天观察

---

#### 2.3 精简 Precious Type 保护范围

**目标**: 减少不必要的"高价值记忆"保护，加快治理流程

**当前配置**:
```yaml
governance:
  precious_types:
    - user_profile
    - decision
    - project_memory
```

**问题**: decision 和 project_memory 占比 35.5%，导致大量决策被送审

**调整**:
```yaml
governance:
  precious_types:
    - user_profile  # 只保留这一个
```

**影响**:
- decision 和 project_memory 不再自动进入 needs_review
- 仍受置信度阈值约束（0.65）
- 只有 user_profile（3.2%）受特殊保护

**验收标准**: 
- 观察 3 天后 needs_review 新增速度
- 应显著低于调整前

**预期时间**: 5 分钟

---

#### 2.4 删除 Agent 通信工具（Quick Win）

**目标**: 减少 MCP 工具列表噪声

**操作**:
```python
# memorycore/server.py
# 注释掉以下 5 个工具的 @mcp.tool() 装饰器

# @mcp.tool()  # ← 注释掉
# def agent_send_message(...):
#     ...

# @mcp.tool()  # ← 注释掉
# def agent_get_inbox(...):
#     ...

# @mcp.tool()  # ← 注释掉
# def agent_presence_update(...):
#     ...

# @mcp.tool()  # ← 注释掉
# def agent_presence_list(...):
#     ...

# @mcp.tool()  # ← 注释掉
# def agent_messages_cleanup(...):
#     ...
```

**验收标准**: 
- 重启服务后，MCP 工具列表从 25 个降到 20 个
- 功能不受影响（这些工具从未被使用）

**预期时间**: 10 分钟

---

#### 2.5 LLM Curator 报告清理

**目标**: 释放磁盘空间，保持报告目录清晰

**操作**:
```bash
# 保留最近 7 天，删除旧报告
find /home/advancer/project/memorycore/reports/llm-curator-*.json -mtime +7 -delete
find /home/advancer/project/memorycore/reports/curator-*.json -mtime +7 -delete
```

**自动化脚本**:
```python
# memorycore/storage/curator_llm.py
# 在 llm_curator_report() 函数末尾添加清理逻辑

def _cleanup_old_reports(keep_days=7):
    """清理超过 keep_days 天的报告"""
    from pathlib import Path
    from datetime import datetime, timedelta
    
    cutoff = datetime.now() - timedelta(days=keep_days)
    reports_dir = Path("reports")
    
    if not reports_dir.exists():
        return
    
    deleted_count = 0
    for pattern in ["llm-curator-*.json", "curator-*.json"]:
        for f in reports_dir.glob(pattern):
            if f.stat().st_mtime < cutoff.timestamp():
                f.unlink()
                deleted_count += 1
    
    if deleted_count > 0:
        logger.info(f"Cleaned up {deleted_count} old curator reports")

# 在每次 curator 运行后调用
_cleanup_old_reports(keep_days=7)
```

**验收标准**: 
- 报告目录从 185 MB 降到 < 30 MB
- 保留最近 7 天报告供调试

**预期时间**: 30 分钟

---

### Phase 2 总结

**完成时间**: 2 周  
**交付物**:
- ✅ auto_approve 阈值降低
- ✅ 历史积压批量重分类（2,221 → < 500）
- ✅ Precious Type 精简（3 → 1）
- ✅ Agent 通信工具移除（MCP 工具 25 → 20）
- ✅ LLM Curator 报告清理（185 MB → < 30 MB）

**成功指标**:
- needs_review 积压: 2,221 → **< 200**
- needs_review 新增速度 < applied 新增速度
- rollback 次数不显著增加（< 5 次/周）

**验证方法**: 
```bash
python3 << 'PYEOF'
import sqlite3
conn = sqlite3.connect('memory.sqlite3')
stats = conn.execute("""
    SELECT review_status, COUNT(*) as cnt
    FROM governance_decisions
    GROUP BY review_status
    ORDER BY cnt DESC;
""").fetchall()
for row in stats:
    print(f"{row[0]}: {row[1]}")
conn.close()
PYEOF
```

---

## Phase 3: LLM Curator 验证与优化（Week 5）

### 目标
确认 LLM Curator 的执行状态，修复问题或降级为手动触发模式。

---

### 任务清单

#### 3.1 检查最新 LLM Curator 报告

**目标**: 确认 LLM Curator 是否真正在工作

**操作**:
```bash
cd /home/advancer/project/memorycore

# 查看最新报告
cat reports/llm-curator-20260702T070240Z.json | python3 -m json.tool | head -100

# 检查报告结构
python3 << 'PYEOF'
import json
from pathlib import Path

latest_report = sorted(Path("reports").glob("llm-curator-*.json"))[-1]
with open(latest_report) as f:
    data = json.load(f)

print(f"Report: {latest_report.name}")
print(f"Keys: {list(data.keys())}")

if 'summary' in data:
    print(f"\nSummary: {json.dumps(data['summary'], indent=2)}")

# 统计各类分析结果数量
for key in ['semantic_duplicates', 'contradictions', 'importance_reassessments', 'split_candidates']:
    if key in data:
        print(f"{key}: {len(data[key])} findings")
PYEOF
```

**判断标准**:
- 如果报告包含有效分析结果 → LLM Curator 正常工作 → 执行 3.2（优化）
- 如果报告为空或格式错误 → LLM Curator 失效 → 执行 3.3（降级）

**预期时间**: 30 分钟

---

#### 3.2 LLM Curator 优化（条件：正常工作）

**A. 添加监控面板**（已在 Phase 0.2 完成，此处完善）:
```python
# memorycore/frontend.py
@app.get("/api/v1/llm-curator/status")
async def get_llm_curator_status():
    """返回 LLM Curator 运行状态"""
    # 从 llm_curator_batches 表读取
    # 或从最新报告解析
    pass
```

**B. 调整批处理大小**（如果执行缓慢）:
```yaml
# config.yaml
llm_curator:
  batch_size: 3  # 从 5 降到 3，减少单次 LLM 调用压力
  max_dedup_pairs: 100  # 从 200 降到 100
  max_contradiction_pairs: 100  # 从 200 降到 100
```

**C. 添加超时保护**:
```python
# memorycore/storage/curator_llm.py
# 在 LLM 调用处添加超时
import asyncio

async def _call_llm_with_timeout(prompt, timeout=300):
    try:
        return await asyncio.wait_for(
            _call_llm(prompt),
            timeout=timeout
        )
    except asyncio.TimeoutError:
        logger.error(f"LLM call timeout after {timeout}s")
        return None
```

**预期时间**: 3 小时

---

#### 3.3 LLM Curator 降级（条件：失效或不可靠）

**目标**: 改为手动触发模式，保留功能但不依赖后台运行

**操作**:
```python
# memorycore/server.py
# 添加手动触发的 MCP 工具

@mcp.tool()
def llm_curator_run_manual(
    analysis_type: str = "all",  # all | duplicates | contradictions | importance
    limit: int = 50
) -> dict:
    """手动触发 LLM Curator 分析（小批量）"""
    from memorycore.storage.curator_llm import llm_curator_report
    
    # 只分析 limit 条记忆
    config = load_config()
    config['llm_curator']['batch_size'] = min(limit, 10)
    
    if analysis_type == "duplicates":
        config['llm_curator']['max_contradiction_pairs'] = 0
        config['llm_curator']['max_split_candidates'] = 0
    # ... 其他类型类似
    
    report = llm_curator_report(config, limit=limit, similarity_threshold=0.4)
    return report
```

**前端界面**:
```typescript
// ui/app/page.tsx
// 在 Dashboard 添加 "Run LLM Curator" 按钮
<Button onClick={() => runLLMCurator('duplicates', 50)}>
  分析重复记忆（50条）
</Button>
```

**关闭后台自动运行**:
```bash
# 停用 systemd timer（如果存在）
systemctl --user disable mcore-curator.timer
systemctl --user stop mcore-curator.timer
```

**预期时间**: 2 小时

---

### Phase 3 总结

**完成时间**: 1 周  
**交付物**:
- ✅ LLM Curator 状态验证报告
- ✅ 优化方案（如果正常）或 降级方案（如果失效）
- ✅ 前端监控面板（如果正常）或 手动触发工具（如果降级）

**成功指标**:
- LLM Curator 执行成功率 > 80%（如果保留后台运行）
- 或 手动触发可用（如果降级）

---

## Phase 4: 代码重构与架构优化（Week 6-7）

### 目标
拆分巨型文件，提升代码可维护性，删除死代码。

---

### 任务清单

#### 4.1 拆分 curator_llm.py（1,654 行 → 6 个文件）

**目标**: 按分析能力拆分为独立模块

**新文件结构**:
```
memorycore/storage/
├── curator_llm/
│   ├── __init__.py           # 导出主函数
│   ├── core.py               # 共享基础设施（LLM 调用、JSON 解析）
│   ├── dedup_judge.py        # 语义去重判断
│   ├── contradiction.py      # 矛盾检测
│   ├── importance.py         # 重要性评估
│   ├── split_detector.py    # 拆分检测
│   └── link_discovery.py    # 链接发现
```

**重构步骤**:
1. 创建 `curator_llm/` 目录
2. 提取共享代码到 `core.py`（LLM 调用、prompt 模板、JSON Schema）
3. 将 5 种分析能力分别移到对应文件
4. 在 `__init__.py` 中重新导出 `llm_curator_report()`
5. 更新所有 import 路径

**验收标准**: 
- 所有文件 < 400 行
- 功能完全兼容（运行测试套件）
- `from memorycore.storage.curator_llm import llm_curator_report` 仍可用

**预期时间**: 1 天

---

#### 4.2 拆分 frontend.py（1,457 行 → 6 个文件）

**目标**: 按 API 路由分组拆分

**新文件结构**:
```
memorycore/api/
├── __init__.py
├── memories.py       # /api/v1/memories/*
├── governance.py     # /api/v1/governance/*
├── curator.py        # /api/v1/curator/*
├── config.py         # /api/v1/config/*
├── dashboard.py      # /api/v1/dashboard/*
└── health.py         # /health, /metrics
```

**重构步骤**:
1. 创建 `memorycore/api/` 目录
2. 将路由按功能分组移到对应文件
3. 保留 `frontend.py` 作为入口，只负责组装路由
4. 更新 `server.py` 的导入

**验收标准**: 
- 所有文件 < 350 行
- API 端点完全兼容
- 前端无感知（接口不变）

**预期时间**: 1 天

---

#### 4.3 拆分 search.py（1,178 行 → 3 个文件）

**新文件结构**:
```
memorycore/storage/
├── search.py         # 保留主函数入口（200 行）
├── fts_search.py     # FTS5 全文搜索（400 行）
└── context_pack.py   # Context Pack 构建（500 行）
```

**预期时间**: 4 小时

---

#### 4.4 拆分 server.py（1,146 行 → 3 个文件）

**新文件结构**:
```
memorycore/
├── server.py         # FastMCP 实例 + 路由注册（300 行）
├── cli.py            # CLI 命令（400 行）
└── mcp_tools.py      # MCP 工具定义（400 行）
```

**预期时间**: 4 小时

---

#### 4.5 删除/归档无用代码

**目标**: 减少代码量，提升维护性

**待删除/归档**:

1. **Agent 通信代码**（已在 Phase 2.4 从 MCP 移除）:
   - 保留代码但移到 `memorycore/deprecated/agents.py`
   - 添加 deprecation 注释

2. **重复的原子化路径**（如果 Phase 1.2 实验成功）:
   - 如果验证拆分确实制造噪声，删除 governance_split 逻辑
   - 只保留规则拆分或只保留 LLM 拆分（二选一）

3. **未使用的配置项**:
   - 审查 `config.yaml`，移除从未被读取的配置

**预期时间**: 3 小时

---

### Phase 4 总结

**完成时间**: 2 周  
**交付物**:
- ✅ curator_llm 拆分（1,654 → 6 文件）
- ✅ frontend 拆分（1,457 → 6 文件）
- ✅ search 拆分（1,178 → 3 文件）
- ✅ server 拆分（1,146 → 3 文件）
- ✅ 死代码清理

**成功指标**:
- 所有文件 < 800 行
- 代码总量: 31,100 → **< 28,000 行**
- 测试套件全部通过

---

## Phase 5: 前端优化与最终验证（Week 8）

### 目标
优化前端状态管理，最终验证所有优化效果。

---

### 任务清单

#### 5.1 前端状态管理迁移到 React Query（可选）

**目标**: 简化服务端状态管理，删除手写缓存

**当前问题**:
- 6 个 Redux slice 管理服务端状态
- 手写 30s 缓存逻辑（~200 行代码）
- 缺少自动失效和重新获取

**迁移方案**:

**保留 Redux 的部分**（UI 状态）:
- `uiSlice.ts` — dialogs, modals, theme
- 其他 UI 临时状态

**迁移到 React Query 的部分**:
```typescript
// ui/hooks/useMemoriesQuery.ts
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

export function useMemoriesList(filters: MemoryFilters) {
  return useQuery({
    queryKey: ['memories', 'list', filters],
    queryFn: () => fetchMemories(filters),
    staleTime: 30000,  // 30s 自动失效
  });
}

export function useMemoryDetail(id: string) {
  return useQuery({
    queryKey: ['memories', 'detail', id],
    queryFn: () => fetchMemoryDetail(id),
  });
}

export function useUpdateMemory() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data) => updateMemory(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['memories'] });
    },
  });
}
```

**迁移的 slice**:
- `memoriesSlice.ts` → `useMemoriesQuery.ts`
- `appsSlice.ts` → `useAppsQuery.ts`
- `configSlice.ts` → `useConfigQuery.ts`
- `filtersSlice.ts` → 保留在 Redux（UI 状态）

**预期收益**:
- 删除 ~300 行手写缓存代码
- 自动缓存失效和重新获取
- 更好的加载状态管理

**预期时间**: 2 天（如果选择实施）

**优先级**: P2（可选），如果时间紧张可跳过

---

#### 5.2 3D 图谱优化：过滤自动边

**目标**: 提升图谱信息密度

**操作**:
```typescript
// ui/app/graph/page.tsx
// 默认只显示语义链接

const [edgeFilters, setEdgeFilters] = useState({
  supports: false,      // 默认隐藏
  part_of: false,       // 默认隐藏
  supersedes: true,     // 默认显示
  contradicts: true,    // 默认显示
  related_to: true,     // 默认显示
  causes: true,         // 默认显示
});

// 在过滤面板添加提示
<FilterPanel>
  <Checkbox label="supports (自动生成)" checked={false} />
  <Checkbox label="part_of (自动生成)" checked={false} />
  <div className="text-xs text-muted">
    💡 自动边已默认隐藏以提升信息密度
  </div>
</FilterPanel>
```

**验收标准**: 
- 打开 Graph 页面，默认只显示语义链接
- 边数从 5,484 降到 ~45（0.8%）
- 图谱加载速度提升

**预期时间**: 1 小时

---

#### 5.3 i18n 精简（可选）

**目标**: 如果确认为个人项目，删除双语支持

**操作**:
```bash
# 删除 i18n 配置
rm -rf ui/lib/i18n
rm ui/hooks/useI18n.ts

# 硬编码中文文案
# 在所有使用 t('key') 的地方替换为直接中文字符串
```

**预期收益**: 
- 删除 ~150 行 i18n 配置
- 简化维护

**优先级**: P3（可选），如果有开源计划则跳过

**预期时间**: 3 小时（如果选择实施）

---

#### 5.4 最终验证：8 周成果检查

**目标**: 验证所有优化目标是否达成

**执行脚本**:
```bash
cd /home/advancer/project/memorycore
python3 << 'PYEOF'
import sqlite3
import json
from datetime import datetime

conn = sqlite3.connect('memory.sqlite3')
conn.row_factory = sqlite3.Row

# 加载基线
with open('docs/baseline-2026-07-02.json') as f:
    baseline = json.load(f)

# 当前指标
current = {
    'timestamp': datetime.now().isoformat(),
    'memories': {
        'total': conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0],
        'active': conn.execute("SELECT COUNT(*) FROM memories WHERE status='active'").fetchone()[0],
        'never_injected': conn.execute("SELECT COUNT(*) FROM memories WHERE status='active' AND injected_count=0").fetchone()[0],
    },
    'governance': {
        'total': conn.execute("SELECT COUNT(*) FROM governance_decisions").fetchone()[0],
        'needs_review': conn.execute("SELECT COUNT(*) FROM governance_decisions WHERE review_status='needs_review'").fetchone()[0],
    },
    'context_quality': {
        'avg_hit_rate': conn.execute("SELECT AVG(hit_rate) FROM context_quality_events WHERE created_at > datetime('now', '-7 days')").fetchone()[0],
        'avg_used_count': conn.execute("SELECT AVG(used_count) FROM context_quality_events WHERE created_at > datetime('now', '-7 days')").fetchone()[0],
    }
}

# 计算改善
def compare(metric_path, baseline_val, current_val, target_val, lower_is_better=True):
    if baseline_val == 0:
        return "N/A"
    change_pct = (current_val - baseline_val) / baseline_val * 100
    direction = "↓" if change_pct < 0 else "↑"
    
    if lower_is_better:
        status = "✅" if current_val <= target_val else "❌"
    else:
        status = "✅" if current_val >= target_val else "❌"
    
    return f"{status} {baseline_val} → {current_val} ({direction}{abs(change_pct):.1f}%), 目标: {target_val}"

print("=" * 80)
print("8 周优化成果验证报告")
print("=" * 80)
print()

print("1. Active 记忆未召回率")
baseline_rate = baseline['memories']['never_injected'] / baseline['memories']['active'] * 100
current_rate = current['memories']['never_injected'] / current['memories']['active'] * 100
print(compare('never_injected_rate', baseline_rate, current_rate, 40.0, lower_is_better=True))
print()

print("2. 治理积压")
print(compare('needs_review', baseline['governance']['needs_review'], current['governance']['needs_review'], 200, lower_is_better=True))
print()

print("3. Context Pack hit_rate")
print(compare('hit_rate', baseline['context_quality']['avg_hit_rate'], current['context_quality']['avg_hit_rate'], 0.90, lower_is_better=False))
print()

print("4. Context Pack used_count")
print(compare('used_count', baseline['context_quality']['avg_used_count'], current['context_quality']['avg_used_count'], 8.0, lower_is_better=False))
print()

# 保存最终报告
with open('docs/final-report-2026-08-27.json', 'w') as f:
    json.dump({
        'baseline': baseline,
        'current': current,
        'goals_achieved': {
            'recall_rate': current_rate <= 40.0,
            'governance_backlog': current['governance']['needs_review'] <= 200,
            'hit_rate': current['context_quality']['avg_hit_rate'] >= 0.90,
        }
    }, f, indent=2)

print("=" * 80)
print("详细报告已保存到: docs/final-report-2026-08-27.json")
print("=" * 80)

conn.close()
PYEOF
```

**验收标准**: 
- ✅ Active 记忆未召回率 < 40%
- ✅ 治理积压 < 200 条
- ✅ Context Pack hit_rate > 0.90
- ✅ 代码总量 < 28,000 行

**如果未达标**: 
- 分析差距原因
- 制定 Phase 6 补充优化计划

**预期时间**: 1 小时

---

#### 5.5 文档更新

**目标**: 更新项目文档，反映架构变化

**待更新文档**:
1. **README.md**: 
   - 更新数据规模
   - 更新成功指标
   - 添加架构改进说明

2. **CHANGELOG.md**:
   - 记录 Phase 1-5 的所有变更
   - 按版本号组织（如 v0.26.0）

3. **DESIGN.md**:
   - 更新架构图（如果有拆分）
   - 更新模块职责说明

4. **docs/optimization-results.md**（新增）:
   - 记录优化前后对比
   - 附带数据图表
   - 经验总结

**预期时间**: 2 小时

---

### Phase 5 总结

**完成时间**: 1 周  
**交付物**:
- ✅ 前端状态管理优化（可选）
- ✅ 3D 图谱信息密度提升
- ✅ i18n 精简（可选）
- ✅ 最终验证报告
- ✅ 文档更新

**成功指标**: 所有 Phase 0-4 的优化目标均达成

---

## 总体时间表

| Phase | 周期 | 工作日 | 关键交付 |
|-------|------|--------|----------|
| Phase 0 | Week 1, Day 1-2 | 2 天 | 基线 + 监控面板 + Silent Failure 修复 |
| Phase 1 | Week 1-2 | 10 天 | 召回失败根因分析 + 实验 A/B |
| Phase 2 | Week 3-4 | 10 天 | 治理系统修复 + 积压清理 |
| Phase 3 | Week 5 | 5 天 | LLM Curator 验证/优化/降级 |
| Phase 4 | Week 6-7 | 10 天 | 代码重构（4 个巨型文件拆分）|
| Phase 5 | Week 8 | 5 天 | 前端优化 + 最终验证 |
| **总计** | **8 周** | **42 天** | **完整优化方案** |

---

## 风险管理

### 高风险项

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| Phase 1 实验无效（召回率仍低） | 中 | 高 | 准备 Plan C：重写召回算法 |
| 批量重分类导致错误决策增多 | 低 | 中 | 监控 rollback 次数，随时回滚 |
| 代码重构引入 bug | 中 | 高 | 每次重构后运行完整测试套件 |
| LLM Curator 无法修复 | 中 | 低 | 直接降级为手动触发模式 |

### 回滚计划

每个 Phase 都有独立的回滚方案：
- **Phase 1**: 恢复原配置（阈值、拆分开关）
- **Phase 2**: 通过审计日志回滚错误决策
- **Phase 3**: 恢复后台自动运行（如果降级）
- **Phase 4**: Git 分支回滚（每次重构前创建分支）
- **Phase 5**: 前端改动通过 Git 回滚

---

## 成功指标总览

### 主要指标（8 周后）

| 指标 | 基线 | 目标 | 权重 |
|------|------|------|------|
| **Active 记忆未召回率** | 69% | < 40% | 40% |
| **治理积压** | 2,221 条 | < 200 条 | 30% |
| **Context Pack hit_rate** | 0.813 | > 0.90 | 20% |
| **代码总量** | 31,100 行 | < 28,000 行 | 10% |

### 次要指标

| 指标 | 基线 | 目标 |
|------|------|------|
| Context Pack used_count | 7.1 | > 8.0 |
| needs_review 新增速度 | > applied | < applied |
| rollback 次数 | ~0 | < 5/周 |
| LLM Curator 成功率 | 未知 | > 80% 或 降级 |
| MCP 工具数量 | 25 个 | 20 个 |
| 报告目录大小 | 185 MB | < 30 MB |

---

## 验收标准

### Phase 完成标准

每个 Phase 必须满足：
1. ✅ 所有任务的验收标准通过
2. ✅ 测试套件全部通过（如涉及代码修改）
3. ✅ 数据验证脚本输出符合预期
4. ✅ 监控面板指标改善
5. ✅ 文档更新（ITERATION.md 追加条目）

### 项目完成标准

8 周后必须满足：
1. ✅ 4 个主要指标中至少 3 个达标
2. ✅ 无 P0 级别的遗留问题
3. ✅ 生成最终验证报告（`docs/final-report-2026-08-27.json`）
4. ✅ README.md 和 CHANGELOG.md 更新完成

---

## 后续计划（Phase 6+，可选）

如果 8 周后仍有优化空间，可考虑：

### Phase 6: 深度优化（Week 9-10）
- 重写召回算法（如果 Phase 1 效果不理想）
- 实现拆分后聚合（在 context pack 中自动附带父记忆）
- 治理系统完全改为"事后抽查"模式

### Phase 7: 新特性（Week 11-12）
- 记忆版本控制（Git-style branching）
- 多工作区支持
- API 限流和配额管理

---

## 附录

### A. 关键脚本汇总

所有验证脚本已内嵌在各 Phase 的任务中，包括：
- 基线指标采集
- 召回率按来源统计
- 未召回记忆抽样分析
- 批量重分类积压决策
- 最终验证报告生成

### B. 配置变更记录

| 配置项 | 原值 | 新值 | Phase |
|--------|------|------|-------|
| `auto_approve_confidence` | 0.8 | 0.65 | Phase 2.1 |
| `precious_types` | 3 个 | 1 个 | Phase 2.3 |
| `score_threshold` | 0.35 | 0.28 | Phase 1.3 |
| `split_content_threshold` | 400 | 1000 | Phase 1.2 |
| `max_records_per_group` | 6 | 10 | Phase 1.3 |
| `default_token_budget` | 2000 | 2500 | Phase 1.3 |

### C. 测试清单

每次代码修改后运行：
```bash
# 单元测试
.venv/bin/python -m pytest tests/ -v

# 集成测试（Context Pack）
.venv/bin/python -m pytest tests/test_context_pack_v2.py -v

# E2E 测试（前端）
cd ui && pnpm test:e2e
```

---

**文档版本**: v1.0  
**制定日期**: 2026-07-02  
**预计完成**: 2026-08-27  
**负责人**: advancer9817-crypto  
**审核状态**: 待审核

