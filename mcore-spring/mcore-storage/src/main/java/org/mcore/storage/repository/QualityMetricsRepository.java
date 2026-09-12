package org.mcore.storage.repository;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 召回质量指标读取（真实聚合，替代硬编码伪造值）。
 *
 * 修复背景：`McpProtocolService` 与 `ContextLabController` 曾直接返回
 * `hit_rate=0.94` / `average_recall_ms=3.8` 等硬编码常量，而工具描述自称
 * "数据库真实聚合"。下游据此判断健康度，属静默误导。
 *
 * 原则：
 * - 有真实数据 → 返回真实聚合值
 * - 无真实数据 → 返回 null 并显式标注可用性，**不编造数值**
 */
@Repository
public class QualityMetricsRepository {

    private final JdbcClient jdbcClient;

    public QualityMetricsRepository(JdbcClient jdbcClient) {
        this.jdbcClient = jdbcClient;
    }

    /**
     * 汇总 context_quality_events 的真实召回质量。
     *
     * @param days 统计近 N 天；<=0 表示全量
     */
    public Map<String, Object> quality(int days) {
        Map<String, Object> out = new LinkedHashMap<>();
        try {
            String base = "SELECT count(*) AS n, " +
                    "round(avg(hit_rate)::numeric, 4) AS avg_hit_rate, " +
                    "round(avg(filter_rate)::numeric, 4) AS avg_filter_rate, " +
                    "round(avg(vector_avg_score)::numeric, 4) AS avg_vector_score, " +
                    "round(avg(cross_retrieval_rate)::numeric, 4) AS avg_cross_retrieval_rate, " +
                    "sum(total_candidates) AS total_candidates, " +
                    "sum(used_count) AS total_used, " +
                    "sum(filtered_count) AS total_filtered, " +
                    "max(created_at) AS latest_event_at " +
                    "FROM context_quality_events ";
            var spec = days > 0
                    ? jdbcClient.sql(base + "WHERE created_at > now() - (:days || ' days')::interval")
                            .param("days", days)
                    : jdbcClient.sql(base);
            Map<String, Object> row = spec.query().listOfRows().stream().findFirst().orElse(Map.of());
            long n = row.get("n") == null ? 0L : ((Number) row.get("n")).longValue();
            out.put("quality_events", n);
            out.put("metrics_available", n > 0);
            out.put("hit_rate", n > 0 ? row.get("avg_hit_rate") : null);
            out.put("filter_rate", n > 0 ? row.get("avg_filter_rate") : null);
            out.put("vector_avg_score", n > 0 ? row.get("avg_vector_score") : null);
            out.put("cross_retrieval_rate", n > 0 ? row.get("avg_cross_retrieval_rate") : null);
            out.put("total_candidates", row.get("total_candidates"));
            out.put("total_used", row.get("total_used"));
            out.put("total_filtered", row.get("total_filtered"));
            out.put("metrics_updated_at", row.get("latest_event_at"));
            return out;
        } catch (Exception e) {
            // 不吞异常地伪造 0：明确标注不可用
            out.put("quality_events", 0L);
            out.put("metrics_available", false);
            out.put("hit_rate", null);
            out.put("metrics_error", e.getMessage());
            return out;
        }
    }

    /**
     * 召回耗时统计。
     *
     * 说明：当前审计表 `audit_events` 无耗时字段，系统未采集召回时延，
     * 因此**无可信的 average_recall_ms 来源**。此处如实返回 null，
     * 不再返回历史硬编码的 3.8。
     */
    public Map<String, Object> recallLatency() {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("average_recall_ms", null);
        out.put("latency_available", false);
        out.put("latency_note", "未采集召回时延（audit_events 无耗时字段），需先补埋点");
        return out;
    }
}
