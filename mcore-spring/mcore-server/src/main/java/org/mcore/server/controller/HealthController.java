package org.mcore.server.controller;

import org.mcore.storage.repository.MemoryRepository;
import org.mcore.tenancy.provisioner.TenantDatabaseProvisioner;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.Map;

@RestController
public class HealthController {

    private final MemoryRepository memoryRepository;
    private final TenantDatabaseProvisioner tenantDatabaseProvisioner;

    public HealthController(MemoryRepository memoryRepository,
                            TenantDatabaseProvisioner tenantDatabaseProvisioner) {
        this.memoryRepository = memoryRepository;
        this.tenantDatabaseProvisioner = tenantDatabaseProvisioner;
    }

    @GetMapping({"/health", "/api/v1/health"})
    public ResponseEntity<Map<String, Object>> health() {
        try {
            // 修复语义错配：此前把 countActiveMemories() 的结果标成 total_memories，
            // 导致监控探针读到的"总数"实际是活跃数（观测差异达 2700+ 条）。
            long total = memoryRepository.countTotalMemories();
            long active = memoryRepository.countActiveMemories();
            Map<String, Object> data = new LinkedHashMap<>();
            data.put("status", "ok");
            data.put("total_memories", total);
            data.put("active_memories", active);
            return ResponseEntity.ok(Map.of("ok", true, "data", data));
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
        // 此前 active_tenants 硬编码为 1，与注册表实际租户数不符；现读控制面真实数据。
        int tenantCount;
        try {
            tenantCount = tenantDatabaseProvisioner.listTenants().size();
        } catch (Exception e) {
            tenantCount = -1; // 控制面不可达时如实暴露，不伪造
        }
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("active_tenants", tenantCount);
        res.put("engine", "spring-boot-3");
        res.put("jvm_version", System.getProperty("java.version"));
        return ResponseEntity.ok(res);
    }
}
