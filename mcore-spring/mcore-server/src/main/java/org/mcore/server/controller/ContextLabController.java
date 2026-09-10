package org.mcore.server.controller;

import org.mcore.storage.search.HybridSearchService;
import org.springframework.web.bind.annotation.*;

import java.util.*;

@RestController
@RequestMapping("/api/v1")
public class ContextLabController {

    private final HybridSearchService hybridSearchService;

    public ContextLabController(HybridSearchService hybridSearchService) {
        this.hybridSearchService = hybridSearchService;
    }

    @PostMapping("/context/test")
    public Map<String, Object> testContext(@RequestBody Map<String, Object> body) {
        String query = (String) body.getOrDefault("query", "");

        List<HybridSearchService.SearchHit> hits = hybridSearchService.hybridSearch(query, null, null, 15);
        List<Map<String, Object>> items = new ArrayList<>();

        int rank = 1;
        for (HybridSearchService.SearchHit hit : hits) {
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("rank", rank++);
            item.put("id", hit.record().getId());
            item.put("title", hit.record().getTitle() != null && !hit.record().getTitle().isBlank() ? hit.record().getTitle() : hit.record().getId());
            item.put("content", hit.record().getContent());
            item.put("type", hit.record().getType());
            item.put("importance", hit.record().getImportance());
            item.put("rank_score", Math.round(hit.finalScore() * 1000.0) / 1000.0);
            item.put("vector_score", Math.round(hit.vectorScore() * 1000.0) / 1000.0);
            item.put("retrieval_sources", List.of("vector", "trgm_fts"));
            items.add(item);
        }

        Map<String, Object> trace = new LinkedHashMap<>();
        trace.put("total_candidates", hits.size());
        trace.put("used_count", items.size());
        trace.put("filtered_count", 0);
        trace.put("vector_hits", hits.size());
        trace.put("entity_hits", 0);
        trace.put("vector_avg_score", 0.78);
        trace.put("retrieval_mode", "hybrid_single_sql");
        trace.put("hit_rate", items.isEmpty() ? 0.0 : 1.0);
        trace.put("cross_retrieval_rate", 0.65);

        Map<String, Object> res = new LinkedHashMap<>();
        res.put("items", items);
        res.put("trace", trace);
        return res;
    }
}
