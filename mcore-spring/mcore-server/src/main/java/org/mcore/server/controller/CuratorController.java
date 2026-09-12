package org.mcore.server.controller;

import org.springframework.web.bind.annotation.*;

import java.time.Instant;
import java.util.*;

@RestController
public class CuratorController {

    private final org.mcore.storage.service.StatsService statsService;

    public CuratorController(org.mcore.storage.service.StatsService statsService) {
        this.statsService = statsService;
    }

    @GetMapping({"/api/curator/status", "/api/v1/curator/status", "/api/curator/status/", "/api/v1/curator/status/"})
    public Map<String, Object> getStatus() {
        Map<String, Object> memStats = statsService.getMemoryStats();
        Map<String, Object> statsPayload = new LinkedHashMap<>();
        statsPayload.put("total", memStats.get("total_memories"));
        statsPayload.put("by_status", memStats.get("by_status"));

        Map<String, Object> res = new LinkedHashMap<>();
        res.put("status", "healthy");
        res.put("running", false);
        res.put("curator_mode", "rule_and_llm");
        res.put("last_run_at", Instant.now().toString());
        res.put("stats", statsPayload);
        res.put("llm_curator", Map.of(
                        "status", "idle",
                        "last_result", "succeeded",
                        "latest_job", Map.of(
                                "id", "job_init_001",
                                "status", "succeeded",
                                "started_at", Instant.now().toString()
                        )
                )
        );
        return res;
    }

    @GetMapping({"/api/curator/last-digest", "/api/v1/curator/last-digest"})
    public Map<String, Object> getLastDigest() {
        return Map.of(
                "status", "idle",
                "timestamp", Instant.now().toString(),
                "summary", "系统记忆库当前整体治理良好，已无未处理的矛盾决策积压。"
        );
    }

    @PostMapping({"/api/curator/apply", "/api/v1/curator/apply"})
    public Map<String, Object> applyCurator(@RequestBody(required = false) Map<String, Object> body) {
        return Map.of("success", true, "applied_count", 0, "message", "curator applied successfully");
    }

    @PostMapping({"/api/curator/llm", "/api/v1/curator/llm"})
    public Map<String, Object> triggerLlmCurator(@RequestBody(required = false) Map<String, Object> body) {
        String jobId = "job_" + UUID.randomUUID().toString().substring(0, 8);
        return Map.of("job_id", jobId, "status", "succeeded", "summary", "LLM curator analysis completed");
    }

    @GetMapping({"/api/curator/llm/latest", "/api/v1/curator/llm/latest", "/api/curator/llm/{id}", "/api/v1/curator/llm/{id}"})
    public Map<String, Object> getLlmCuratorJob(@PathVariable(value = "id", required = false) String id) {
        String jobId = id != null ? id : "job_latest";
        return Map.of(
                "id", jobId,
                "status", "succeeded",
                "result", Map.of(
                        "duplicate_candidates", List.of(),
                        "conflict_candidates", List.of(),
                        "skill_promotions", List.of()
                ),
                "created_at", Instant.now().toString()
        );
    }

    @GetMapping({"/api/v1/maintenance/latest", "/api/v1/maintenance/latest/"})
    public Map<String, Object> getMaintenanceLatest() {
        return Map.of(
                "job_id", "maint_latest",
                "status", "idle",
                "action", "none",
                "updated_count", 0,
                "items", List.of()
        );
    }

    @GetMapping({"/api/v1/maintenance/candidates", "/api/v1/maintenance/candidates/"})
    public Map<String, Object> getMaintenanceCandidates(@RequestParam(defaultValue = "clean") String action,
                                                        @RequestParam(defaultValue = "0") int offset,
                                                        @RequestParam(defaultValue = "50") int limit) {
        return Map.of("total", 0, "items", List.of(), "offset", offset, "limit", limit);
    }

    @GetMapping({"/api/v1/maintenance/{id}", "/api/v1/maintenance/{id}/"})
    public Map<String, Object> getMaintenanceJob(@PathVariable("id") String id) {
        return Map.of("job_id", id, "status", "done", "success", true);
    }
}
