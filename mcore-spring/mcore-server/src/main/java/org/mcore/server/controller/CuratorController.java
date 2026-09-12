package org.mcore.server.controller;

import org.mcore.storage.service.CuratorService;
import org.mcore.storage.service.LlmCuratorExecutor;
import org.springframework.web.bind.annotation.*;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 策展 / 维护 REST 接口。
 *
 * 此前全部端点为硬编码桩（伪造 last_run_at、写死 digest 文案、candidates 恒空），
 * 现全部接真实表：llm_curator_jobs / governance_runs / maintenance_jobs / memories。
 */
@RestController
public class CuratorController {

    private final CuratorService curatorService;
    private final LlmCuratorExecutor llmCuratorExecutor;

    private final org.mcore.storage.service.RuleCuratorService ruleCuratorService;

    public CuratorController(CuratorService curatorService, LlmCuratorExecutor llmCuratorExecutor,
                             org.mcore.storage.service.RuleCuratorService ruleCuratorService) {
        this.ruleCuratorService = ruleCuratorService;
        this.curatorService = curatorService;
        this.llmCuratorExecutor = llmCuratorExecutor;
    }

    // ==================== 状态 ====================

    @GetMapping({"/api/curator/status", "/api/v1/curator/status", "/api/curator/status/", "/api/v1/curator/status/"})
    public Map<String, Object> getStatus() {
        return curatorService.getStatus();
    }

    @GetMapping({"/api/curator/last-digest", "/api/v1/curator/last-digest",
            "/api/curator/last-digest/", "/api/v1/curator/last-digest/"})
    public Map<String, Object> getLastDigest() {
        return curatorService.getLastDigest();
    }

    // ==================== 触发 ====================

    @PostMapping({"/api/curator/apply", "/api/v1/curator/apply"})
    public Map<String, Object> applyCurator(@RequestBody(required = false) Map<String, Object> body) {
        return curatorService.applyCurator();
    }

    /**
     * 规则策展报告（默认 dry-run，只报告不改动）。
     * 对标 Python `curator_report`；`rule_curator` 的 25 个参数由此真实消费。
     */
    @GetMapping({"/api/v1/curator/rules", "/api/curator/rules"})
    public Map<String, Object> ruleCuratorReport(
            @RequestParam(value = "dry_run", defaultValue = "true") boolean dryRun,
            @RequestParam(value = "limit", defaultValue = "500") int limit,
            @RequestParam(value = "stale_after_days", defaultValue = "365") int staleAfterDays,
            @RequestParam(value = "archive_after_days", defaultValue = "730") int archiveAfterDays,
            @RequestParam(value = "allow_actions", required = false) String allowActions,
            @RequestParam(value = "deny_actions", required = false) String denyActions) {
        return ruleCuratorService.report(dryRun, limit, staleAfterDays, archiveAfterDays,
                splitCsv(allowActions), splitCsv(denyActions));
    }

    /** 规则策展执行（真实改库；默认传入 dry_run=false 才生效） */
    @PostMapping({"/api/v1/curator/rules/apply", "/api/curator/rules/apply"})
    public Map<String, Object> applyRuleCurator(@RequestBody(required = false) Map<String, Object> body) {
        boolean dryRun = body == null || !Boolean.FALSE.equals(body.get("dry_run"));
        int limit = body != null && body.get("limit") instanceof Number n ? n.intValue() : 500;
        int staleDays = body != null && body.get("stale_after_days") instanceof Number n ? n.intValue() : 365;
        int archiveDays = body != null && body.get("archive_after_days") instanceof Number n ? n.intValue() : 730;
        List<String> allow = body != null ? asList(body.get("allow_actions")) : List.of();
        List<String> deny = body != null ? asList(body.get("deny_actions")) : List.of();
        return ruleCuratorService.report(dryRun, limit, staleDays, archiveDays, allow, deny);
    }

    private java.util.List<String> splitCsv(String v) {
        if (v == null || v.isBlank()) {
            return java.util.List.of();
        }
        java.util.List<String> out = new java.util.ArrayList<>();
        for (String s : v.split(",")) {
            if (!s.isBlank()) {
                out.add(s.trim());
            }
        }
        return out;
    }

    @SuppressWarnings("unchecked")
    private java.util.List<String> asList(Object v) {
        java.util.List<String> out = new java.util.ArrayList<>();
        if (v instanceof java.util.List<?> list) {
            for (Object o : list) {
                if (o != null && !String.valueOf(o).isBlank()) {
                    out.add(String.valueOf(o).trim());
                }
            }
        }
        return out;
    }

    @PostMapping({"/api/curator/llm", "/api/v1/curator/llm"})
    public Map<String, Object> triggerLlmCurator(@RequestBody(required = false) Map<String, Object> body) {
        Map<String, Object> job = curatorService.triggerLlmCurator(body);
        // run=true 时同步执行（默认只登记，交由 /curator/execute 或调度器消费）
        boolean run = body != null && Boolean.TRUE.equals(body.get("run"));
        if (run && job.get("job_id") != null) {
            Map<String, Object> result = llmCuratorExecutor.execute(String.valueOf(job.get("job_id")));
            Map<String, Object> merged = new LinkedHashMap<>(job);
            merged.put("status", "executed");
            merged.put("execution", result);
            return merged;
        }
        return job;
    }

    /** 消费一条排队中的策展作业（真实执行） */
    @PostMapping({"/api/curator/execute", "/api/v1/curator/execute"})
    public Map<String, Object> executeQueued() {
        return llmCuratorExecutor.consumeOne();
    }

    /** 执行指定策展作业 */
    @PostMapping({"/api/curator/execute/{id}", "/api/v1/curator/execute/{id}"})
    public Map<String, Object> executeJob(@PathVariable("id") String id) {
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("job_id", id);
        res.put("result", llmCuratorExecutor.execute(id));
        return res;
    }

    // ==================== LLM 策展作业 ====================

    @GetMapping({"/api/curator/llm/latest", "/api/v1/curator/llm/latest"})
    public Map<String, Object> getLlmCuratorLatest() {
        return curatorService.getLlmCuratorJob("latest");
    }

    @GetMapping({"/api/curator/llm/{id}", "/api/v1/curator/llm/{id}"})
    public Map<String, Object> getLlmCuratorJob(@PathVariable("id") String id) {
        return curatorService.getLlmCuratorJob(id);
    }

    // ==================== 维护 ====================

    @GetMapping({"/api/v1/maintenance/latest", "/api/v1/maintenance/latest/"})
    public Map<String, Object> getMaintenanceLatest() {
        return curatorService.getLatestMaintenanceJob();
    }

    @GetMapping({"/api/v1/maintenance/candidates", "/api/v1/maintenance/candidates/"})
    public Map<String, Object> getMaintenanceCandidates(
            @RequestParam(value = "action", defaultValue = "clean") String action,
            @RequestParam(value = "offset", defaultValue = "0") int offset,
            @RequestParam(value = "limit", defaultValue = "50") int limit) {
        return curatorService.listCandidates(action, offset, limit);
    }

    @GetMapping({"/api/v1/maintenance/{id}", "/api/v1/maintenance/{id}/"})
    public Map<String, Object> getMaintenanceJob(@PathVariable("id") String id) {
        return curatorService.getMaintenanceJob(id);
    }

    // ==================== 作业列表（便于前端展示历史） ====================

    @GetMapping({"/api/v1/maintenance/jobs", "/api/v1/maintenance/jobs/"})
    public Map<String, Object> listMaintenanceJobs(
            @RequestParam(value = "limit", defaultValue = "20") int limit) {
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("items", curatorService.listMaintenanceJobs(limit));
        return res;
    }
}
