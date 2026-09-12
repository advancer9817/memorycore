package org.mcore.server.controller;

import org.mcore.storage.repository.EntityRepository;
import org.mcore.storage.search.HybridSearchService;
import org.springframework.web.bind.annotation.*;

import java.util.*;

/**
 * 上下文实验室：对给定查询执行混合检索并返回可解释的 trace。
 *
 * 修复：此前 trace 中的 `vector_avg_score=0.78`、`cross_retrieval_rate=0.65`、
 * `entity_hits=0` 均为硬编码常量，与真实检索结果无关；每个 item 的
 * `retrieval_sources` 也无条件写死为 ["vector","trgm_fts"]。
 * 现全部改为按实际命中分数推导。
 */
@RestController
@RequestMapping("/api/v1")
public class ContextLabController {

    private final HybridSearchService hybridSearchService;
    private final EntityRepository entityRepository;

    public ContextLabController(HybridSearchService hybridSearchService, EntityRepository entityRepository) {
        this.hybridSearchService = hybridSearchService;
        this.entityRepository = entityRepository;
    }

    @PostMapping("/context/test")
    public Map<String, Object> testContext(@RequestBody Map<String, Object> body) {
        String query = (String) body.getOrDefault("query", "");

        List<HybridSearchService.SearchHit> hits = hybridSearchService.hybridSearch(query, null, null, 15);
        List<Map<String, Object>> items = new ArrayList<>();

        double vectorSum = 0.0;
        int vectorCount = 0;
        int crossCount = 0;
        int rank = 1;

        for (HybridSearchService.SearchHit hit : hits) {
            double vs = hit.vectorScore();
            double ts = hit.textScore();

            // 真实召回来源：按分数是否有效判定，不再无条件写死
            List<String> sources = new ArrayList<>();
            if (vs > 0) {
                sources.add("vector");
            }
            if (ts > 0) {
                sources.add("trgm_fts");
            }
            if (vs > 0 && ts > 0) {
                crossCount++;
            }
            if (vs > 0) {
                vectorSum += vs;
                vectorCount++;
            }

            Map<String, Object> item = new LinkedHashMap<>();
            item.put("rank", rank++);
            item.put("id", hit.record().getId());
            item.put("title", hit.record().getTitle() != null && !hit.record().getTitle().isBlank()
                    ? hit.record().getTitle() : hit.record().getId());
            item.put("content", hit.record().getContent());
            item.put("type", hit.record().getType());
            item.put("importance", hit.record().getImportance());
            item.put("rank_score", Math.round(hit.finalScore() * 1000.0) / 1000.0);
            item.put("vector_score", Math.round(vs * 1000.0) / 1000.0);
            item.put("text_score", Math.round(ts * 1000.0) / 1000.0);
            item.put("retrieval_sources", sources);
            items.add(item);
        }

        // 实体召回：真实执行一次实体检索以获得真实命中数
        int entityHits = 0;
        try {
            entityHits = entityRepository.searchEntities(query, 15, "", "").size();
        } catch (Exception ignored) {
            // 实体检索失败不应影响主流程；entityHits 保持 0 并如实反映
        }

        Map<String, Object> trace = new LinkedHashMap<>();
        trace.put("total_candidates", hits.size());
        trace.put("used_count", items.size());
        trace.put("filtered_count", 0);
        trace.put("vector_hits", vectorCount);
        trace.put("entity_hits", entityHits);
        trace.put("vector_avg_score", vectorCount > 0
                ? Math.round((vectorSum / vectorCount) * 1000.0) / 1000.0 : null);
        trace.put("retrieval_mode", "hybrid_single_sql");
        trace.put("hit_rate", hits.isEmpty() ? 0.0
                : Math.round((double) items.size() / hits.size() * 1000.0) / 1000.0);
        trace.put("cross_retrieval_rate", hits.isEmpty() ? 0.0
                : Math.round((double) crossCount / hits.size() * 1000.0) / 1000.0);

        Map<String, Object> res = new LinkedHashMap<>();
        res.put("items", items);
        res.put("trace", trace);
        return res;
    }
}
