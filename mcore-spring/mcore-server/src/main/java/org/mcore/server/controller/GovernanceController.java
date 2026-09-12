package org.mcore.server.controller;

import org.mcore.storage.service.GovernanceService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.*;

@RestController
public class GovernanceController {

    private final GovernanceService governanceService;
    private final org.mcore.storage.service.VectorBackfillService vectorBackfillService;

    public GovernanceController(GovernanceService governanceService,
                                org.mcore.storage.service.VectorBackfillService vectorBackfillService) {
        this.governanceService = governanceService;
        this.vectorBackfillService = vectorBackfillService;
    }

    @GetMapping({"/api/governance/counts", "/api/v1/governance/counts"})
    public Map<String, Object> getCounts() {
        return governanceService.getCounts();
    }

    @GetMapping({"/api/governance/metrics", "/api/v1/governance/metrics"})
    public Map<String, Object> getMetrics() {
        return governanceService.getMetrics();
    }

    @GetMapping({"/api/governance/decisions", "/api/v1/governance/decisions"})
    public Map<String, Object> listDecisions(
            @RequestParam(value = "page", defaultValue = "1") int page,
            @RequestParam(value = "page_size", defaultValue = "20") int pageSize,
            @RequestParam(value = "status", required = false) String status,
            @RequestParam(value = "type", required = false) String type) {
        return governanceService.listDecisions(page, pageSize, status, type);
    }

    @PostMapping({"/api/governance/{id}/apply", "/api/v1/governance/{id}/apply"})
    public ResponseEntity<Map<String, Object>> applyDecision(
            @PathVariable("id") String id,
            @RequestParam(value = "actor", defaultValue = "admin") String actor) {
        boolean ok = governanceService.applyDecision(id, actor);
        return ResponseEntity.ok(Map.of("success", ok, "id", id, "status", "applied"));
    }

    @PostMapping({"/api/governance/{id}/reject", "/api/v1/governance/{id}/reject"})
    public ResponseEntity<Map<String, Object>> rejectDecision(
            @PathVariable("id") String id,
            @RequestParam(value = "actor", defaultValue = "admin") String actor) {
        boolean ok = governanceService.rejectDecision(id, actor);
        return ResponseEntity.ok(Map.of("success", ok, "id", id, "status", "rejected"));
    }

    @SuppressWarnings("unchecked")
    @PostMapping({"/api/governance/batch/apply", "/api/v1/governance/batch/apply"})
    public Map<String, Object> batchApply(@RequestBody Map<String, Object> body) {
        List<String> ids = body != null && body.get("decision_ids") != null ? (List<String>) body.get("decision_ids") : Collections.emptyList();
        String actor = body != null ? (String) body.getOrDefault("actor", "admin") : "admin";
        return governanceService.batchApply(ids, actor);
    }

    /** 向量健康检测：判定存量向量是否仍为哈希降级产物 */
    @GetMapping({"/api/v1/maintenance/vector-status"})
    public Map<String, Object> vectorStatus(@RequestParam(value = "sample", defaultValue = "200") int sample) {
        return vectorBackfillService.detect(sample);
    }

    /** 向量回填：将哈希降级向量重算为真实语义向量（幂等，已语义化的行自动跳过） */
    @PostMapping({"/api/v1/maintenance/reembed"})
    public Map<String, Object> reembed(@RequestBody(required = false) Map<String, Object> body) {
        boolean dryRun = body != null && Boolean.TRUE.equals(body.get("dry_run"));
        int batchSize = body != null && body.get("batch_size") instanceof Number n ? n.intValue() : 50;
        int maxRows = body != null && body.get("max_rows") instanceof Number n ? n.intValue() : 500;
        int offset = body != null && body.get("offset") instanceof Number n ? n.intValue() : 0;
        return vectorBackfillService.backfill(batchSize, maxRows, dryRun, offset);
    }

    @GetMapping({"/api/audit", "/api/v1/audit"})
    public Map<String, Object> getAudit(@RequestParam(value = "page", defaultValue = "1") int page,
                                        @RequestParam(value = "page_size", defaultValue = "20") int pageSize,
                                        @RequestParam(value = "event_type", required = false) String eventType) {
        // 此前硬编码返回空列表，导致审计页永远空白；现接真实 audit_events 表
        return governanceService.listAuditEvents(page, pageSize, eventType);
    }

    @GetMapping({"/api/v1/maintenance/plan", "/api/v1/maintenance/plan/"})
    public Map<String, Object> getMaintenancePlan(
            @RequestParam(value = "action", defaultValue = "archive") String action,
            @RequestParam(value = "limit", defaultValue = "100") int limit) {
        return governanceService.getMaintenancePlan(action, limit);
    }

    @PostMapping({"/api/v1/maintenance/execute", "/api/v1/maintenance/execute/"})
    public Map<String, Object> executeMaintenance(@RequestBody(required = false) Map<String, Object> body) {
        String token = body != null ? (String) body.get("plan_token") : null;
        String action = body != null ? (String) body.getOrDefault("action", "archive") : "archive";
        return governanceService.executeMaintenance(token, action);
    }
}
