package org.mcore.storage.pack;

import org.mcore.common.dto.ContextPackResponse;
import org.mcore.common.model.MemoryDO;
import org.mcore.storage.search.HybridSearchService.SearchHit;
import org.springframework.stereotype.Component;

import java.util.List;

/**
 * Slim 紧凑上下文信封组装器
 * 对齐迭代 220 极简契约，按 Token 预算熔断截断
 */
@Component
public class ContextPackBuilder {

    public ContextPackResponse buildContextPack(List<SearchHit> hits, int maxTokens) {
        if (hits == null || hits.isEmpty()) {
            return new ContextPackResponse(true, "# mcore context\n(暂无高度相关记忆)", 0, 0);
        }

        int budget = maxTokens > 0 ? maxTokens : 1200;
        StringBuilder sb = new StringBuilder();
        sb.append("# mcore context (slim)\n");

        int accumulatedTokens = 0;
        int includedCount = 0;

        for (SearchHit hit : hits) {
            MemoryDO mem = hit.record();
            String line = String.format("- [%s] (%s) %s\n",
                    mem.getType() != null ? mem.getType() : "fact",
                    mem.getScope() != null ? mem.getScope() : "global",
                    mem.getContent().trim()
            );

            // 中英混合 Token 估算: 字符数 / 2.5
            int lineTokens = (int) Math.ceil(line.length() / 2.5);
            if (accumulatedTokens + lineTokens > budget) {
                break; // 触及预算上限，直接截断
            }

            sb.append(line);
            accumulatedTokens += lineTokens;
            includedCount++;
        }

        return new ContextPackResponse(true, sb.toString(), includedCount, accumulatedTokens);
    }
}
