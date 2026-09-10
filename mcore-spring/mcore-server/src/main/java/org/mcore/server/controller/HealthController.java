package org.mcore.server.controller;

import org.mcore.storage.repository.MemoryRepository;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

@RestController
public class HealthController {

    private final MemoryRepository memoryRepository;

    public HealthController(MemoryRepository memoryRepository) {
        this.memoryRepository = memoryRepository;
    }

    @GetMapping("/health")
    public ResponseEntity<Map<String, Object>> health() {
        try {
            long count = memoryRepository.countActiveMemories();
            return ResponseEntity.ok(Map.of(
                    "ok", true,
                    "data", Map.of(
                            "status", "ok",
                            "total_memories", count
                    )
            ));
        } catch (Exception e) {
            return ResponseEntity.status(503).body(Map.of(
                    "ok", false,
                    "error", Map.of(
                            "code", "unavailable",
                            "message", e.getMessage()
                    )
            ));
        }
    }

    @GetMapping("/metrics")
    public ResponseEntity<Map<String, Object>> metrics() {
        return ResponseEntity.ok(Map.of(
                "active_tenants", 1,
                "engine", "spring-boot-3",
                "jvm_version", System.getProperty("java.version")
        ));
    }
}
