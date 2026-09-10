package org.mcore.storage.repository;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

import java.util.UUID;

@Repository
public class FeedbackRepository {

    private final JdbcClient jdbcClient;

    public FeedbackRepository(JdbcClient jdbcClient) {
        this.jdbcClient = jdbcClient;
    }

    public long count() {
        return jdbcClient.sql("SELECT count(*) FROM feedback_events").query(Long.class).single();
    }

    public void addFeedback(String memoryId, double score, String note, String agent) {
        String eventId = "fb_" + UUID.randomUUID().toString().replace("-", "").substring(0, 16);
        String ag = (agent != null && !agent.isBlank()) ? agent : "agent";
        String n = (note != null) ? note : "";

        // 1. 记录反馈明细事件
        String insertSql = """
            INSERT INTO feedback_events (id, memory_id, score, note, source_agent, created_at)
            VALUES (:id, :memoryId, :score, :note, :agent, clock_timestamp())
        """;
        jdbcClient.sql(insertSql)
                .param("id", eventId)
                .param("memoryId", memoryId)
                .param("score", score)
                .param("note", n)
                .param("agent", ag)
                .update();

        // 2. 真实同步更新记忆本体上的反馈与有效性得分
        String updateMemorySql = """
            UPDATE memories
            SET feedback_score = feedback_score + :score,
                ineffective_count = ineffective_count + (CASE WHEN :score < 0 THEN 1 ELSE 0 END),
                effectiveness_score = GREATEST(0.0, LEAST(1.0, effectiveness_score + (:score * 0.1))),
                updated_at = clock_timestamp()
            WHERE id = :memoryId
        """;
        jdbcClient.sql(updateMemorySql)
                .param("score", score)
                .param("memoryId", memoryId)
                .update();
    }
}
