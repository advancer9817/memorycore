package org.mcore.storage.pack;

import org.mcore.common.dto.ContextPackResponse;
import org.mcore.common.model.MemoryDO;
import org.mcore.storage.config.ConfigFileStore;
import org.mcore.storage.privacy.InjectionGuard;
import org.mcore.storage.search.HybridSearchService.SearchHit;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Slim 紧凑上下文信封组装器。
 *
 * 对齐迭代 220 极简契约，按 Token 预算熔断截断。
 *
 * 本次补齐（迁移期间丢失的能力）：
 * - **注入防护**：长期记忆是数据而非指令；命中指令覆盖/密钥外泄措辞的记录从正文剔除，改以 warning 提示
 * - **边界声明**（`BOUNDARY_NOTICE`）：明确告知 Agent 记忆为不可信数据
 * - **强制护栏**：从 `config.yaml` 的 `context_pack.hard_constraints` 读取并渲染
 */
@Component
public class ContextPackBuilder {

    private final InjectionGuard injectionGuard;
    private final ConfigFileStore configStore;

    public ContextPackBuilder(InjectionGuard injectionGuard, ConfigFileStore configStore) {
        this.injectionGuard = injectionGuard;
        this.configStore = configStore;
    }

    public ContextPackResponse buildContextPack(List<SearchHit> hits, int maxTokens) {
        List<Map<String, Object>> warnings = new ArrayList<>();
        if (hits == null || hits.isEmpty()) {
            ContextPackResponse empty = new ContextPackResponse(true, "# mcore context\n(暂无高度相关记忆)", 0, 0);
            empty.setWarnings(warnings);
            return empty;
        }

        int budget = maxTokens > 0 ? maxTokens : 1200;

        StringBuilder sb = new StringBuilder();
        sb.append("# mcore context (slim)\n");

        // 边界声明：记忆是不可信数据，不得当作指令执行
        sb.append("safety: ").append(InjectionGuard.BOUNDARY_NOTICE)
                .append(" 若背景记忆存在过时/冲突，请指出或调用 memory_feedback / memory_supersede 纠偏。\n");

        // 强制护栏（顶层硬约束）
        appendHardConstraints(sb);

        int accumulatedTokens = estimateTokens(sb.toString());
        int includedCount = 0;
        int filteredCount = 0;

        for (SearchHit hit : hits) {
            MemoryDO mem = hit.record();

            // 注入防护：命中即剔除正文，仅留告警（不复述可疑内容）
            InjectionGuard.InjectionCheck check = injectionGuard.check(mem.getTitle(), mem.getContent());
            if (check.highRisk()) {
                filteredCount++;
                warnings.add(injectionGuard.warningFor(mem.getId(), mem.getTitle(), check));
                continue;
            }

            String line = String.format("- [%s] (%s) %s\n",
                    mem.getType() != null ? mem.getType() : "fact",
                    mem.getScope() != null ? mem.getScope() : "global",
                    mem.getContent() != null ? mem.getContent().trim() : ""
            );

            int lineTokens = estimateTokens(line);
            if (accumulatedTokens + lineTokens > budget) {
                break; // 触及预算上限，直接截断
            }

            sb.append(line);
            accumulatedTokens += lineTokens;
            includedCount++;
        }

        ContextPackResponse res = new ContextPackResponse(true, sb.toString(), includedCount, accumulatedTokens);
        res.setWarnings(warnings);
        res.setFilteredCount(filteredCount);

        // 被拦截项在正文中留下可见痕迹（不复述可疑内容，仅列 id 与命中规则），
        // 使 Agent 知道"有记忆因安全原因未展示"，而不是静默消失。
        if (filteredCount > 0) {
            sb.append("\n## 因安全原因未展示\n");
            for (Map<String, Object> w : warnings) {
                sb.append("- memory_id=").append(w.get("memory_id"))
                        .append(" matches=").append(w.get("matches")).append('\n');
            }
            res.setContext(sb.toString());
        }
        return res;
    }

    /**
     * 渲染 `context_pack.hard_constraints`。
     * 配置缺失时退回 Python 侧同款默认规则，保证护栏不因配置遗漏而消失。
     */
    private void appendHardConstraints(StringBuilder sb) {
        List<String> rules = new ArrayList<>();
        try {
            Map<String, Object> cp = configStore.section("context_pack");
            Object hcObj = cp.get("hard_constraints");
            if (hcObj instanceof Map<?, ?> hc) {
                Object enabled = hc.get("enabled");
                boolean on = !(enabled instanceof Boolean b) || b;
                if (on && hc.get("rules") instanceof List<?> list) {
                    for (Object r : list) {
                        if (r != null && !String.valueOf(r).isBlank()) {
                            rules.add(String.valueOf(r));
                        }
                    }
                }
            }
        } catch (Exception ignored) {
            // 配置不可读时使用下方默认规则
        }
        if (rules.isEmpty()) {
            rules.add("代码提交/推送前必须在仓库根目录追加 ITERATION.md 迭代记录");
        }
        sb.append("## 强制护栏\n");
        for (int i = 0; i < rules.size(); i++) {
            sb.append(i + 1).append(". ").append(rules.get(i)).append('\n');
        }
    }

    /** 中英混合 Token 估算：字符数 / 2.5 */
    private int estimateTokens(String s) {
        return s == null ? 0 : (int) Math.ceil(s.length() / 2.5);
    }

    /** 供调用方构造 warnings 信封（保持 MCP 文本契约不变的同时可选用） */
    public Map<String, Object> warningsEnvelope(ContextPackResponse pack) {
        Map<String, Object> env = new LinkedHashMap<>();
        env.put("context", pack.getContext());
        env.put("warnings", pack.getWarnings());
        return env;
    }
}
