# MemoryCore 优化执行摘要（Quick Reference）

> 基于深度审计报告的 8 周优化计划精简版

---

## 🎯 核心目标

解决 3 个关键问题：
1. **69% 记忆未召回** → < 40%
2. **2,221 条治理积压** → < 200
3. **代码膨胀 31,100 行** → < 28,000

---

## 📅 执行时间表（8 周）

| 周 | Phase | 核心任务 | 预期成果 |
|----|-------|----------|----------|
| 1 | Phase 0 + 1 前半 | 建立监控 + 召回分析 | 找到未召回根因 |
| 2 | Phase 1 后半 | 实验 A/B（拆分或召回调整）| 召回率 69% → 55% |
| 3-4 | Phase 2 | 治理修复 + 积压清理 | 积压 2,221 → < 500 |
| 5 | Phase 3 | LLM Curator 验证/降级 | 确认可用或降级 |
| 6-7 | Phase 4 | 代码重构（拆分 4 个巨型文件）| 代码 < 28,000 行 |
| 8 | Phase 5 | 前端优化 + 最终验证 | 所有目标达成验证 |

---

## ⚡ Quick Wins（立即可做）

### Week 1, Day 1（2 小时内完成）

1. **修复 Silent Failure**（15 分钟）:
   ```python
   # memorycore/storage/search.py:78
   except Exception as e:
       logger.warning("Context pack injection count update failed", exc_info=True)
   ```

2. **删除 Agent 通信工具**（10 分钟）:
   ```python
   # memorycore/server.py
   # 注释掉 5 个 agent_* 工具的 @mcp.tool() 装饰器
   ```

3. **清理旧报告**（5 分钟）:
   ```bash
   find reports/llm-curator-*.json -mtime +7 -delete
   ```

---

## 📊 关键决策点

### 决策点 1：Phase 1.1 数据分析后

**如果** atomizer/governance_split 未召回率 > 80%  
**则** 执行 Phase 1.2（暂停拆分）  
**否则** 执行 Phase 1.3（调整召回算法）

### 决策点 2：Phase 3.1 LLM Curator 检查后

**如果** 报告有效且执行成功  
**则** 执行 Phase 3.2（优化）  
**否则** 执行 Phase 3.3（降级为手动触发）

---

## 🔧 配置速查表

### 降低治理阈值（Phase 2.1）
```yaml
# config.yaml
governance:
  auto_approve_confidence: 0.65  # 从 0.8 降低
  precious_types:
    - user_profile  # 只保留 1 个（删除 decision, project_memory）
```

### 调整召回参数（Phase 1.3）
```yaml
# config.yaml
# 向量搜索阈值
score_threshold: 0.28  # 从 0.35 降低

# Context Pack 容量
context_pack:
  max_records_per_group: 10  # 从 6 增加
  default_token_budget: 2500  # 从 2000 增加
```

### 提高拆分阈值（Phase 1.2）
```yaml
# config.yaml
extraction_strategy:
  min_split_length: 1000  # 从 600 提高
  
llm_curator:
  split_content_threshold: 1000  # 从 400 提高
```

---

## 📈 验证脚本

### 每周执行（监控进度）
```bash
cd /home/advancer/project/memorycore
python3 << 'PYEOF'
import sqlite3
conn = sqlite3.connect('memory.sqlite3')

# 未召回率
never_rate = conn.execute("""
    SELECT COUNT(CASE WHEN injected_count = 0 THEN 1 END) * 100.0 / COUNT(*) 
    FROM memories WHERE status='active'
""").fetchone()[0]

# 治理积压
needs_review = conn.execute("""
    SELECT COUNT(*) FROM governance_decisions WHERE review_status='needs_review'
""").fetchone()[0]

# Context Pack 质量
hit_rate = conn.execute("""
    SELECT AVG(hit_rate) FROM context_quality_events 
    WHERE created_at > datetime('now', '-7 days')
""").fetchone()[0]

print(f"未召回率: {never_rate:.1f}% (目标 < 40%)")
print(f"治理积压: {needs_review} (目标 < 200)")
print(f"Hit Rate: {hit_rate:.3f} (目标 > 0.90)")

conn.close()
PYEOF
```

---

## 🚨 风险与回滚

### 如果召回率反而下降
→ 回滚 Phase 1.3 的配置变更  
→ 保持 Phase 1.2 的拆分暂停

### 如果治理错误决策增多
→ 通过审计日志查询错误决策  
→ 恢复 auto_approve_confidence 为 0.75（折中值）

### 如果代码重构引入 bug
→ Git 分支回滚（每次重构前创建备份分支）  
→ 运行完整测试套件验证

---

## ✅ 阶段性检查点

### Week 2 末（Phase 1 完成）
- [ ] 未召回率 < 55%
- [ ] 召回分析报告生成
- [ ] 实验方案已执行

### Week 4 末（Phase 2 完成）
- [ ] 治理积压 < 500
- [ ] Agent 通信工具移除
- [ ] 报告清理完成

### Week 5 末（Phase 3 完成）
- [ ] LLM Curator 状态明确（优化或降级）
- [ ] 前端监控面板完善

### Week 7 末（Phase 4 完成）
- [ ] 4 个巨型文件拆分完成
- [ ] 所有文件 < 800 行
- [ ] 测试套件全部通过

### Week 8 末（Phase 5 完成）
- [ ] 最终验证报告生成
- [ ] 所有目标达成
- [ ] 文档更新完成

---

## 📞 问题升级

如果遇到以下情况，重新评估计划：
1. Phase 1 和 Phase 2 都完成，但主要指标仍未达标
2. 代码重构引入超过 5 个严重 bug
3. LLM Curator 完全无法修复且占用大量资源

---

**快速链接**:
- 完整路线图: `docs/2026-07-02-memorycore-iteration-roadmap.md`
- 审计报告: `docs/2026-07-02-memorycore-deep-audit-report-v2.md`
- 基线数据: `docs/baseline-2026-07-02.json`（执行 Phase 0.1 后生成）

