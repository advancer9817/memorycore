package org.mcore.server.controller;

import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.Map;

@RestController
@RequestMapping("/api/v1")
public class ConfigController {

    private final Map<String, Object> currentConfig = new HashMap<>();

    public ConfigController() {
        currentConfig.put("engine", "Java 17 (LTS) + Spring Boot 3.3.3 + Spring AI");
        currentConfig.put("database", "PostgreSQL 16 + pgvector");
        currentConfig.put("multi_tenancy", "Database-per-Tenant (COW 毫秒克隆)");
        currentConfig.put("temperature", 0.4);
        currentConfig.put("sim_threshold", 0.60);
        currentConfig.put("split_content_threshold", 500);
        currentConfig.put("importance_limit", 500);
        currentConfig.put("content_max_chars", 1500);
        currentConfig.put("batch_size", 10);
        currentConfig.put("review_cooldown_seconds", 3600);
        currentConfig.put("keep_threshold", 0.05);
        currentConfig.put("auto_approve_confidence", 0.85);
        currentConfig.put("prompt_style", "balanced");
        currentConfig.put("reviewed_ids_max_age_seconds", 86400);
    }

    @GetMapping("/config")
    public Map<String, Object> getConfig() {
        return currentConfig;
    }

    @PutMapping("/config")
    public Map<String, Object> updateConfig(@RequestBody Map<String, Object> newConfig) {
        if (newConfig != null) {
            currentConfig.putAll(newConfig);
        }
        return currentConfig;
    }
}
