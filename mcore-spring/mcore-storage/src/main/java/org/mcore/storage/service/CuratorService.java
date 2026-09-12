package org.mcore.storage.service;

import org.mcore.storage.config.ConfigFileStore;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.*;

/**
 * 策展与维护服务（真实数据版）。
 *
 * 背景：此前 CuratorController 的全部端点均为硬编码桩——status 用 Instant.now() 伪造"刚运行过"、
 * last-digest 是写死的中文文案、maintenance/candidates 恒返回空列表，导致前端「维护/策展」面板
 * 要么显示虚假成功，要么永远没有数据。
 *
 * 本服务把上述端点接到真实表：
 * - llm_curator_jobs    : LLM 策展作业
 * - governance_runs     : 治理运行记录与摘要
 * - maintenance_jobs    : 维护作业（计划令牌、备份路径）
 * - memories            : 候选集来源
 */
@Service
public class CuratorService {

    private final JdbcClient jdbcClient;
    private final ConfigFileStore configStore;
    private final GovernanceService governanceService;

    public CuratorService(JdbcClient jdbcClient, ConfigFileStore configStore, GovernanceService governanceService) {
        this.jdbcClient = jdbcClient;
        this.configStore = configStore;
        this.governanceService = governanceService;
    }

    // ==================== 状态 ====================

    /** 策展运行状态：取最近一次 LLM 策展作业与治理运行，不再伪造时间戳 */
    public Map<String, Object> getStatus() {
        Map<String, Object> res = new LinkedHashMap<>();

        Map<String, Object> latestJob = jdbcClient.sql(
                        "SELECT id, status, started_at, updated_at, finished_at, summary_json, error_json " +
                        "FROM llm_curator_jobs ORDER BY COALESCE(started_at, updated_at) DESC NULLS LAST LIMIT 1")
                .query().listOfRows().stream().findFirst().map(org.mcore.storage.util.JsonbRows::row).orElse(null);

        Map<String, Object> latestRun = jdbcClient.sql(
                        "SELECT id, status, mode, source, started_at, finished_at, summary_json " +
                        "FROM governance_runs ORDER BY COALESCE(finished_at, started_at) DESC NULLS LAST LIMIT 1")
                .query().listOfRows().stream().findFirst().map(org.mcore.storage.util.JsonbRows::row).orElse(null);

        boolean running = latestJob != null && "running".equalsIgnoreCase(String.valueOf(latestJob.get("status")));

        res.put("status", running ? "running" : "idle");
        res.put("running", running);
        res.put("curator_mode", "rule_and_llm");

        // 最近运行时间：来自真实作业记录，无记录则为 null（诚实反映"从未运行"）
        Object lastRunAt = null;
        if (latestJob != null) {
            lastRunAt = latestJob.get("finished_at") != null ? latestJob.get("finished_at") : latestJob.get("started_at");
        } else if (latestRun != null) {
            lastRunAt = latestRun.get("finished_at") != null ? latestRun.get("finished_at") : latestRun.get("started_at");
        }
        res.put("last_run_at", lastRunAt);

        Map<String, Object> statsPayload = new LinkedHashMap<>();
        statsPayload.put("total", countMemories(null));
        statsPayload.put("by_status", statusDistribution());
        res.put("stats", statsPayload);

        Map<String, Object> llmCurator = new LinkedHashMap<>();
        if (latestJob != null) {
            llmCurator.put("status", latestJob.get("status"));
            llmCurator.put("last_result", latestJob.get("error_json") != null ? "failed" : "succeeded");
            Map<String, Object> jobView = new LinkedHashMap<>();
            jobView.put("id", latestJob.get("id"));
            jobView.put("status", latestJob.get("status"));
            jobView.put("started_at", latestJob.get("started_at"));
            jobView.put("finished_at", latestJob.get("finished_at"));
            llmCurator.put("latest_job", jobView);
        } else {
            llmCurator.put("status", "idle");
            llmCurator.put("last_result", null);
            llmCurator.put("latest_job", null);
            llmCurator.put("note", "尚无 LLM 策展作业记录");
        }
        res.put("llm_curator", llmCurator);

        Map<String, Object> ruleCurator = new LinkedHashMap<>();
        ruleCurator.put("last_run_at", latestRun != null
                ? (latestRun.get("finished_at") != null ? latestRun.get("finished_at") : latestRun.get("started_at"))
                : null);
        ruleCurator.put("last_status", latestRun != null ? latestRun.get("status") : null);
        res.put("rule_curator", ruleCurator);

        return res;
    }

    /** 最近一次治理摘要：来自 governance_runs.summary_json，无记录则如实说明 */
    public Map<String, Object> getLastDigest() {
        Map<String, Object> row = jdbcClient.sql(
                        "SELECT id, status, mode, finished_at, started_at, summary_json " +
                        "FROM governance_runs ORDER BY COALESCE(finished_at, started_at) DESC NULLS LAST LIMIT 1")
                .query().listOfRows().stream().findFirst().map(org.mcore.storage.util.JsonbRows::row).orElse(null);

        Map<String, Object> res = new LinkedHashMap<>();
        if (row == null) {
            res.put("status", "empty");
            res.put("timestamp", null);
            res.put("summary", "尚无治理运行记录。");
            res.put("run_id", null);
            return res;
        }
        res.put("status", row.get("status"));
        res.put("timestamp", row.get("finished_at") != null ? row.get("finished_at") : row.get("started_at"));
        res.put("run_id", row.get("id"));
        res.put("mode", row.get("mode"));
        res.put("summary", row.get("summary_json"));
        return res;
    }

    // ==================== 维护候选（真实查询，不再恒为空） ====================

    /**
     * 按动作类型返回真实候选集。
     * action: clean | archive | expire | dedup
     */
    public Map<String, Object> listCandidates(String action, int offset, int limit) {
        String act = action == null || action.isBlank() ? "clean" : action.toLowerCase();
        int lim = Math.max(1, Math.min(limit, 500));
        int off = Math.max(0, offset);

        Map<String, Object> cfg = configStore.raw();
        Map<String, Object> rule = asMap(cfg.get("rule_curator"));

        String where;
        Map<String, Object> params = new LinkedHashMap<>();
        switch (act) {
            case "archive" -> {
                int staleDays = num(rule.get("stale_days_default"), 180);
                double impTh = dbl(rule.get("stale_importance_threshold"), 0.45);
                where = "status = 'active' AND updated_at < now() - (:days || ' days')::interval AND COALESCE(importance, 0) < :impTh";
                params.put("days", staleDays);
                params.put("impTh", impTh);
            }
            case "expire" -> {
                int contradictedDays = num(rule.get("contradicted_archive_days"), 90);
                where = "status IN ('superseded','contradicted') AND updated_at < now() - (:days || ' days')::interval";
                params.put("days", contradictedDays);
            }
            case "dedup" -> {
                where = "status = 'active' AND title IS NOT NULL AND btrim(title) <> '' AND lower(btrim(title)) IN (" +
                        "SELECT lower(btrim(title)) FROM memories WHERE status='active' AND title IS NOT NULL " +
                        "GROUP BY lower(btrim(title)) HAVING COUNT(*) > 1)";
            }
            default -> { // clean
                where = "(content IS NULL OR btrim(content) = '' OR title IS NULL OR btrim(title) = '')";
            }
        }

        long total = jdbcClient.sql("SELECT COUNT(*) FROM memories WHERE " + where)
                .params(params).query(Long.class).single();

        Map<String, Object> qp = new LinkedHashMap<>(params);
        qp.put("limit", lim);
        qp.put("offset", off);
        List<Map<String, Object>> items = jdbcClient.sql(
                        "SELECT id, title, status, importance, updated_at, created_at, " +
                        "       left(COALESCE(content,''), 160) AS excerpt " +
                        "FROM memories WHERE " + where + " ORDER BY updated_at ASC NULLS FIRST LIMIT :limit OFFSET :offset")
                .params(qp).query().listOfRows();

        Map<String, Object> res = new LinkedHashMap<>();
        res.put("action", act);
        res.put("total", total);
        res.put("items", items);
        res.put("offset", off);
        res.put("limit", lim);
        return res;
    }

    // ==================== LLM 策展作业查询 ====================

    /** id 为 null/"latest" 时取最近一次作业 */
    public Map<String, Object> getLlmCuratorJob(String id) {
        Map<String, Object> row;
        if (id == null || id.isBlank() || "latest".equalsIgnoreCase(id)) {
            row = jdbcClient.sql("SELECT id, status, params_json, progress_json, summary_json, error_json, " +
                            "governance_run_id, created_by, started_at, updated_at, finished_at " +
                            "FROM llm_curator_jobs ORDER BY COALESCE(started_at, updated_at) DESC NULLS LAST LIMIT 1")
                    .query().listOfRows().stream().findFirst().map(org.mcore.storage.util.JsonbRows::row).orElse(null);
        } else {
            row = jdbcClient.sql("SELECT id, status, params_json, progress_json, summary_json, error_json, " +
                            "governance_run_id, created_by, started_at, updated_at, finished_at " +
                            "FROM llm_curator_jobs WHERE id = :id")
                    .param("id", id).query().listOfRows().stream().findFirst().map(org.mcore.storage.util.JsonbRows::row).orElse(null);
        }
        if (row == null) {
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("job_id", id == null ? "latest" : id);
            res.put("status", "none");
            res.put("found", false);
            res.put("note", "尚无 LLM 策展作业记录");
            return res;
        }
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("job_id", row.get("id"));
        res.put("status", row.get("status"));
        res.put("found", true);
        res.put("params", row.get("params_json"));
        res.put("progress", row.get("progress_json"));
        res.put("summary", row.get("summary_json"));
        res.put("error", row.get("error_json"));
        res.put("governance_run_id", row.get("governance_run_id"));
        res.put("created_by", row.get("created_by"));
        res.put("started_at", row.get("started_at"));
        res.put("updated_at", row.get("updated_at"));
        res.put("finished_at", row.get("finished_at"));
        return res;
    }

    // ==================== 维护作业 ====================

    public Map<String, Object> getLatestMaintenanceJob() {
        Map<String, Object> row = jdbcClient.sql(
                        "SELECT id, plan_token, kind, status, summary_json, backup_path, error, created_at, finished_at " +
                        "FROM maintenance_jobs ORDER BY created_at DESC NULLS LAST LIMIT 1")
                .query().listOfRows().stream().findFirst().map(org.mcore.storage.util.JsonbRows::row).orElse(null);
        if (row == null) {
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("job_id", null);
            res.put("status", "none");
            res.put("action", null);
            res.put("updated_count", 0);
            res.put("items", List.of());
            res.put("note", "尚无维护作业记录");
            return res;
        }
        return maintenanceJobView(row);
    }

    /** 维护作业历史列表 */
    public java.util.List<Map<String, Object>> listMaintenanceJobs(int limit) {
        int lim = Math.max(1, Math.min(limit, 200));
        return org.mcore.storage.util.JsonbRows.rows(jdbcClient.sql("SELECT id, plan_token, kind, status, summary_json, backup_path, error, created_at, finished_at " +
                        "FROM maintenance_jobs ORDER BY created_at DESC NULLS LAST LIMIT :limit")
                .param("limit", lim).query().listOfRows());
    }

    public Map<String, Object> getMaintenanceJob(String id) {
        Map<String, Object> row = jdbcClient.sql(
                        "SELECT id, plan_token, kind, status, summary_json, backup_path, error, created_at, finished_at " +
                        "FROM maintenance_jobs WHERE id = :id")
                .param("id", id).query().listOfRows().stream().findFirst().map(org.mcore.storage.util.JsonbRows::row).orElse(null);
        if (row == null) {
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("job_id", id);
            res.put("status", "not_found");
            res.put("found", false);
            return res;
        }
        Map<String, Object> view = maintenanceJobView(row);
        view.put("found", true);
        return view;
    }

    private Map<String, Object> maintenanceJobView(Map<String, Object> row) {
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("job_id", row.get("id"));
        res.put("plan_token", row.get("plan_token"));
        res.put("action", row.get("kind"));
        res.put("status", row.get("status"));
        res.put("summary", row.get("summary_json"));
        res.put("backup_path", row.get("backup_path"));
        res.put("error", row.get("error"));
        res.put("created_at", row.get("created_at"));
        res.put("finished_at", row.get("finished_at"));
        Object summary = row.get("summary_json");
        Object updatedCount = 0;
        if (summary instanceof Map<?, ?> m && m.get("updated_count") != null) {
            updatedCount = m.get("updated_count");
        }
        res.put("updated_count", updatedCount);
        res.put("items", List.of());
        return res;
    }

    // ==================== 触发类 ====================

    /** 应用所有待审治理决策（复用 GovernanceService，真实写库） */
    public Map<String, Object> applyCurator() {
        List<String> pendingIds = jdbcClient.sql(
                        "SELECT id FROM governance_decisions WHERE review_status = 'pending' ORDER BY created_at ASC LIMIT 500")
                .query(String.class).list();
        Map<String, Object> result = governanceService.batchApply(pendingIds, "curator");
        Map<String, Object> res = new LinkedHashMap<>(result);
        res.put("success", true);
        res.put("pending_found", pendingIds.size());
        res.put("message", pendingIds.isEmpty()
                ? "没有待审决策，无需应用"
                : "已应用 " + result.getOrDefault("applied", 0) + " 条决策");
        return res;
    }

    /**
     * 触发一次 LLM 策展作业。
     *
     * 诚实语义：本方法只负责**登记真实作业记录**并返回其 id，
     * 不会在没有执行的情况下谎报 succeeded。当前实现登记为 queued。
     */
    public Map<String, Object> triggerLlmCurator(Map<String, Object> params) {
        String jobId = "cur_" + UUID.randomUUID().toString().replace("-", "").substring(0, 12);
        Map<String, Object> p = params == null ? new LinkedHashMap<>() : new LinkedHashMap<>(params);
        jdbcClient.sql("INSERT INTO llm_curator_jobs (id, status, params_json, created_by, started_at, updated_at) " +
                        "VALUES (:id, 'queued', :params::jsonb, :by, clock_timestamp(), clock_timestamp())")
                .param("id", jobId)
                .param("params", toJson(p))
                .param("by", String.valueOf(p.getOrDefault("created_by", "curator")))
                .update();

        Map<String, Object> res = new LinkedHashMap<>();
        res.put("job_id", jobId);
        res.put("status", "queued");
        res.put("queued_at", Instant.now().toString());
        res.put("params", p);
        res.put("note", "作业已登记，等待执行器消费");
        return res;
    }

    // ==================== 内部 ====================

    private long countMemories(String status) {
        if (status == null) {
            return jdbcClient.sql("SELECT COUNT(*) FROM memories").query(Long.class).single();
        }
        return jdbcClient.sql("SELECT COUNT(*) FROM memories WHERE status = :s")
                .param("s", status).query(Long.class).single();
    }

    private Map<String, Object> statusDistribution() {
        Map<String, Object> byStatus = new LinkedHashMap<>();
        for (String s : new String[]{"active", "archived", "stale", "superseded", "contradicted"}) {
            byStatus.put(s, 0L);
        }
        for (Map<String, Object> row : jdbcClient.sql("SELECT status, COUNT(*) cnt FROM memories GROUP BY status")
                .query().listOfRows()) {
            byStatus.put(String.valueOf(row.get("status")), row.get("cnt"));
        }
        return byStatus;
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> asMap(Object o) {
        if (o instanceof Map) {
            return (Map<String, Object>) o;
        }
        return new LinkedHashMap<>();
    }

    private int num(Object o, int fallback) {
        if (o instanceof Number n) {
            return n.intValue();
        }
        try {
            return o == null ? fallback : (int) Double.parseDouble(String.valueOf(o));
        } catch (NumberFormatException e) {
            return fallback;
        }
    }

    private double dbl(Object o, double fallback) {
        if (o instanceof Number n) {
            return n.doubleValue();
        }
        try {
            return o == null ? fallback : Double.parseDouble(String.valueOf(o));
        } catch (NumberFormatException e) {
            return fallback;
        }
    }

    private String toJson(Object o) {
        try {
            return new com.fasterxml.jackson.databind.ObjectMapper().writeValueAsString(o);
        } catch (Exception e) {
            return "{}";
        }
    }
}
