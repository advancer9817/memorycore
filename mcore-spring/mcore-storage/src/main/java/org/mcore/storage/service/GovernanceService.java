package org.mcore.storage.service;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

import java.util.*;

@Service
public class GovernanceService {

    private final JdbcClient jdbcClient;

    public GovernanceService(JdbcClient jdbcClient) {
        this.jdbcClient = jdbcClient;
    }

    public Map<String, Object> getCounts() {
        String sql = """
            SELECT review_status, COUNT(*) as cnt
            FROM governance_decisions
            GROUP BY review_status
        """;
        List<Map<String, Object>> rows = jdbcClient.sql(sql).query().listOfRows();
        long total = 0;
        long applied = 0;
        long rejected = 0;
        long rolledBack = 0;
        long autoApproved = 0;
        for (Map<String, Object> r : rows) {
            String status = String.valueOf(r.get("review_status")).toLowerCase();
            long cnt = ((Number) r.get("cnt")).longValue();
            total += cnt;
            if ("applied".equals(status)) applied += cnt;
            else if ("rejected".equals(status)) rejected += cnt;
            else if ("rolled_back".equals(status)) rolledBack += cnt;
            else if ("auto_approved".equals(status)) autoApproved += cnt;
        }
        Map<String, Object> counts = new LinkedHashMap<>();
        counts.put("total", total);
        counts.put("applied", applied);
        counts.put("rejected", rejected);
        counts.put("rolled_back", rolledBack);
        counts.put("auto_approved", autoApproved);
        counts.put("data", new HashMap<>(counts));
        return counts;
    }

    public Map<String, Object> getMetrics() {
        String sql = """
            SELECT review_status, decision_type, COUNT(*) as cnt
            FROM governance_decisions
            GROUP BY review_status, decision_type
        """;
        List<Map<String, Object>> rows = jdbcClient.sql(sql).query().listOfRows();

        long pendingCount = 0;
        long appliedCount = 0;
        long contradictionCount = 0;
        long duplicateCount = 0;
        long totalDecisions = 0;

        for (Map<String, Object> r : rows) {
            String status = String.valueOf(r.get("review_status"));
            String type = String.valueOf(r.get("decision_type"));
            long cnt = ((Number) r.get("cnt")).longValue();
            totalDecisions += cnt;

            if ("pending".equalsIgnoreCase(status) || "needs_review".equalsIgnoreCase(status)) {
                pendingCount += cnt;
            }
            if ("applied".equalsIgnoreCase(status) || "auto_approved".equalsIgnoreCase(status)) {
                appliedCount += cnt;
            }
            if ("contradiction".equalsIgnoreCase(type)) {
                contradictionCount += cnt;
            }
            if ("semantic_duplicate".equalsIgnoreCase(type)) {
                duplicateCount += cnt;
            }
        }

        Map<String, Object> metrics = new LinkedHashMap<>();
        metrics.put("total_decisions", totalDecisions);
        metrics.put("pending_reviews", pendingCount);
        metrics.put("applied_decisions", appliedCount);
        metrics.put("contradictions", contradictionCount);
        metrics.put("semantic_duplicates", duplicateCount);
        metrics.put("auto_approval_rate", totalDecisions > 0 ? Math.round(((double) appliedCount / totalDecisions) * 100) : 0);
        return metrics;
    }

    public Map<String, Object> listDecisions(int page, int pageSize, String status, String type) {
        page = Math.max(1, page);
        pageSize = Math.max(1, Math.min(200, pageSize));
        int offset = (page - 1) * pageSize;

        StringBuilder where = new StringBuilder(" WHERE 1=1");
        Map<String, Object> params = new HashMap<>();

        if (status != null && !status.isBlank() && !"all".equalsIgnoreCase(status)) {
            where.append(" AND review_status = :status");
            params.put("status", status);
        }
        if (type != null && !type.isBlank() && !"all".equalsIgnoreCase(type)) {
            where.append(" AND decision_type = :type");
            params.put("type", type);
        }

        String countSql = "SELECT COUNT(*) FROM governance_decisions" + where;
        var countSpec = jdbcClient.sql(countSql);
        params.forEach(countSpec::param);
        long total = Optional.ofNullable(countSpec.query(Long.class).single()).orElse(0L);

        String sql = "SELECT id, decision_type, recommended_action, llm_confidence, risk_level, review_status, " +
                     "policy_reason, finding_json, source_ids_json, created_at, updated_at " +
                     "FROM governance_decisions" + where + " ORDER BY created_at DESC LIMIT :limit OFFSET :offset";

        var querySpec = jdbcClient.sql(sql);
        params.forEach(querySpec::param);
        querySpec.param("limit", pageSize).param("offset", offset);

        List<Map<String, Object>> rows = querySpec.query().listOfRows();
        List<Map<String, Object>> items = new ArrayList<>();
        for (Map<String, Object> r : rows) {
            Map<String, Object> item = new LinkedHashMap<>(r);
            item.put("created_at", String.valueOf(r.get("created_at")));
            item.put("updated_at", String.valueOf(r.get("updated_at")));
            items.add(item);
        }

        Map<String, Object> res = new LinkedHashMap<>();
        res.put("items", items);
        res.put("decisions", items); // 兼容双字段
        res.put("total", total);
        res.put("page", page);
        res.put("page_size", pageSize);
        res.put("pages", (int) Math.max(1, (total + pageSize - 1) / pageSize));
        return res;
    }

    public boolean applyDecision(String id, String actor) {
        String sql = """
            UPDATE governance_decisions 
            SET review_status = 'applied', applied_at = clock_timestamp(), applied_by = :actor, updated_at = clock_timestamp()
            WHERE id = :id
        """;
        return jdbcClient.sql(sql)
                .param("id", id)
                .param("actor", actor != null ? actor : "admin")
                .update() > 0;
    }

    public boolean rejectDecision(String id, String actor) {
        String sql = """
            UPDATE governance_decisions 
            SET review_status = 'rejected', updated_at = clock_timestamp()
            WHERE id = :id
        """;
        return jdbcClient.sql(sql).param("id", id).update() > 0;
    }

    public Map<String, Object> batchApply(List<String> ids, String actor) {
        if (ids == null || ids.isEmpty()) {
            return Map.of("applied_count", 0, "skipped_count", 0);
        }
        String sql = """
            UPDATE governance_decisions 
            SET review_status = 'applied', applied_at = clock_timestamp(), applied_by = :actor, updated_at = clock_timestamp()
            WHERE id IN (:ids)
        """;
        int updated = jdbcClient.sql(sql)
                .param("ids", ids)
                .param("actor", actor != null ? actor : "admin")
                .update();
        return Map.of("applied_count", updated, "skipped_count", Math.max(0, ids.size() - updated));
    }

    public Map<String, Object> getMaintenancePlan(String action, int limit) {
        if (limit <= 0) limit = 100;
        String statusTarget = "clean".equalsIgnoreCase(action) ? "archived" : "stale";

        String sql = "SELECT id, title, type, status, created_at FROM memories WHERE status = :status ORDER BY updated_at ASC LIMIT :limit";
        List<Map<String, Object>> candidates = jdbcClient.sql(sql)
                .param("status", statusTarget)
                .param("limit", limit)
                .query().listOfRows();

        Map<String, Object> plan = new LinkedHashMap<>();
        plan.put("action", action != null ? action : "archive");
        plan.put("candidate_count", candidates.size());
        plan.put("candidates", candidates);
        plan.put("plan_token", UUID.randomUUID().toString().replace("-", ""));
        plan.put("created_at", new Date().toString());
        return plan;
    }

    public Map<String, Object> executeMaintenance(String planToken, String action) {
        String targetStatus = "clean".equalsIgnoreCase(action) ? "archived" : "stale";
        // 软更新至已归档或移除
        String sql = "UPDATE memories SET status = 'archived', updated_at = clock_timestamp() WHERE status = :status";
        int affected = jdbcClient.sql(sql).param("status", targetStatus).update();

        return Map.of("success", true, "action", action, "affected_rows", affected, "plan_token", planToken);
    }
}
