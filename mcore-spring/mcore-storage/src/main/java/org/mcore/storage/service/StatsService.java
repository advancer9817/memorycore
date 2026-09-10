package org.mcore.storage.service;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

import java.util.*;

@Service
public class StatsService {

    private final JdbcClient jdbcClient;

    public StatsService(JdbcClient jdbcClient) {
        this.jdbcClient = jdbcClient;
    }

    public Map<String, Object> getMemoryStats() {
        // 1. 各状态分布统计
        String statusSql = "SELECT status, COUNT(*) as cnt FROM memories GROUP BY status";
        Map<String, Long> byStatus = new LinkedHashMap<>();
        byStatus.put("active", 0L);
        byStatus.put("archived", 0L);
        byStatus.put("stale", 0L);
        byStatus.put("superseded", 0L);
        byStatus.put("contradicted", 0L);
        long total = 0;

        List<Map<String, Object>> statusRows = jdbcClient.sql(statusSql).query().listOfRows();
        for (Map<String, Object> row : statusRows) {
            String status = String.valueOf(row.get("status"));
            long cnt = ((Number) row.get("cnt")).longValue();
            byStatus.put(status, cnt);
            total += cnt;
        }

        // 2. 活跃且从未访问
        long activeNever = 0;
        try {
            Long val = jdbcClient.sql("SELECT COUNT(*) FROM memories WHERE status = 'active' AND (injected_count IS NULL OR injected_count = 0)")
                    .query(Long.class).single();
            if (val != null) activeNever = val;
        } catch (Exception ignored) {}

        // 3. 关联关系统计
        long linkTotal = 0;
        long uniqueLinked = 0;
        try {
            Long lt = jdbcClient.sql("SELECT COUNT(*) FROM memory_links").query(Long.class).single();
            if (lt != null) linkTotal = lt;
            Long ul = jdbcClient.sql("SELECT COUNT(DISTINCT source_id) FROM memory_links").query(Long.class).single();
            if (ul != null) uniqueLinked = ul;
        } catch (Exception ignored) {}

        // 4. Apps 协同列表统计
        List<Map<String, Object>> apps = getAppsList();

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("total_memories", total);
        result.put("total_apps", apps.size());
        result.put("apps", apps);
        result.put("by_status", byStatus);
        result.put("active_never_accessed_count", activeNever);
        result.put("link_count", linkTotal);
        result.put("unique_linked_memories", uniqueLinked);
        return result;
    }

    public List<Map<String, Object>> getAppsList() {
        String sql = """
            SELECT 
                source_agent,
                COUNT(*) as created_count,
                COALESCE(SUM(injected_count), 0) as access_count,
                MAX(COALESCE(updated_at, created_at)) as last_activity
            FROM memories
            WHERE source_agent IS NOT NULL AND source_agent != ''
            GROUP BY source_agent
            ORDER BY created_count DESC
        """;
        List<Map<String, Object>> rows = jdbcClient.sql(sql).query().listOfRows();
        List<Map<String, Object>> apps = new ArrayList<>();

        for (Map<String, Object> row : rows) {
            String agent = String.valueOf(row.get("source_agent"));
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("id", agent);
            item.put("name", agent);
            item.put("display_name", formatAppDisplayName(agent));
            item.put("description", formatAppDescription(agent));
            item.put("category", "agent");
            item.put("total_memories_created", ((Number) row.get("created_count")).longValue());
            item.put("total_memories_accessed", ((Number) row.get("access_count")).longValue());
            item.put("is_active", true);
            item.put("status", "idle");
            item.put("last_activity_at", String.valueOf(row.get("last_activity")));
            apps.add(item);
        }
        return apps;
    }

    public Map<String, Object> getHealthScorePayload() {
        Map<String, Object> stats = getMemoryStats();
        @SuppressWarnings("unchecked")
        Map<String, Long> byStatus = (Map<String, Long>) stats.get("by_status");

        long active = byStatus.getOrDefault("active", 0L);
        long stale = byStatus.getOrDefault("stale", 0L);
        long superseded = byStatus.getOrDefault("superseded", 0L);
        long contradicted = byStatus.getOrDefault("contradicted", 0L);
        long activeNever = ((Number) stats.getOrDefault("active_never_accessed_count", 0L)).longValue();
        long uniqueLinked = ((Number) stats.getOrDefault("unique_linked_memories", 0L)).longValue();
        long linkTotal = ((Number) stats.getOrDefault("link_count", 0L)).longValue();

        long pendingCleanup = stale + superseded + contradicted;
        long usablePool = active + pendingCleanup;

        double activeReuse = active > 0 ? Math.min(100.0, Math.round(((double)(active - activeNever) / active) * 100.0)) : 0.0;
        double linkedCoverage = active > 0 ? Math.min(100.0, Math.round(((double)uniqueLinked / active) * 100.0)) : 0.0;
        double pendingShare = usablePool > 0 ? Math.min(100.0, Math.round(((double)pendingCleanup / usablePool) * 100.0)) : 0.0;

        // 治理风险项统计
        long contraActionable = 0;
        long dupActionable = 0;
        try {
            String govSql = """
                SELECT decision_type, COUNT(*) as cnt FROM governance_decisions 
                WHERE review_status IN ('needs_review', 'auto_approved') AND recommended_action != 'keep'
                GROUP BY decision_type
            """;
            List<Map<String, Object>> govRows = jdbcClient.sql(govSql).query().listOfRows();
            for (Map<String, Object> r : govRows) {
                String dt = String.valueOf(r.get("decision_type"));
                long cnt = ((Number) r.get("cnt")).longValue();
                if ("contradiction".equalsIgnoreCase(dt)) contraActionable = cnt;
                if ("semantic_duplicate".equalsIgnoreCase(dt)) dupActionable = cnt;
            }
        } catch (Exception ignored) {}

        long highRiskCount = contraActionable + dupActionable;
        double riskScore = clamp(100.0 - highRiskCount * 18.0 - Math.min(dupActionable, 100) * 0.28 - Math.min(contraActionable, 20) * 2.0);
        double llmScore = 80.0; // 默认稳健分

        // 权重融合: risk(0.34) + pending(0.16) + linked(0.08) + reuse(0.24) + llm(0.14)
        double quality = clamp(
            (riskScore * 0.34) +
            (clamp(100.0 - pendingShare) * 0.16) +
            (clamp(linkedCoverage) * 0.08) +
            (clamp(activeReuse) * 0.24) +
            (llmScore * 0.14)
        );

        Map<String, Object> metrics = new LinkedHashMap<>();
        metrics.put("active", active);
        metrics.put("stale", stale);
        metrics.put("superseded", superseded);
        metrics.put("contradicted", contradicted);
        metrics.put("active_never_accessed", activeNever);
        metrics.put("active_reuse_coverage", activeReuse);
        metrics.put("linked_coverage", linkedCoverage);
        metrics.put("link_count", linkTotal);
        metrics.put("unique_linked_memories", uniqueLinked);
        metrics.put("pending_cleanup_share", pendingShare);
        metrics.put("pending_cleanup", pendingCleanup);
        metrics.put("usable_pool", usablePool);

        Map<String, Object> signals = new LinkedHashMap<>();
        signals.put("high_risk_count", highRiskCount);
        signals.put("contradiction_actionable", contraActionable);
        signals.put("duplicate_actionable", dupActionable);

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("quality", Math.round(quality));
        payload.put("risk", Math.round(riskScore));
        payload.put("llmGovernance", llmScore);
        payload.put("llmStatus", "idle");
        payload.put("metrics", metrics);
        payload.put("signals", signals);
        return payload;
    }

    private double clamp(double v) {
        return Math.max(0.0, Math.min(100.0, v));
    }

    private String formatAppDisplayName(String agent) {
        if ("claude".equalsIgnoreCase(agent)) return "Claude Code";
        if ("hermes".equalsIgnoreCase(agent)) return "Hermes Agent";
        if ("codex".equalsIgnoreCase(agent)) return "Codex CLI";
        if ("opencode".equalsIgnoreCase(agent)) return "OpenCode";
        if ("mcore".equalsIgnoreCase(agent)) return "MemoryCore System";
        return agent;
    }

    private String formatAppDescription(String agent) {
        if ("claude".equalsIgnoreCase(agent)) return "Anthropic Claude Code 交互智能体";
        if ("hermes".equalsIgnoreCase(agent)) return "Hermes 个人全能工程助理";
        if ("codex".equalsIgnoreCase(agent)) return "OpenAI Codex 编码执行 Agent";
        if ("mcore".equalsIgnoreCase(agent)) return "mcore 核心记忆中枢";
        return "外部协同智能体与调用方";
    }
}
