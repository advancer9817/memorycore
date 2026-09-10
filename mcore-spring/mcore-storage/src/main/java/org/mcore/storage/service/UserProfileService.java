package org.mcore.storage.service;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

import java.util.*;

@Service
public class UserProfileService {

    private final JdbcClient jdbcClient;

    public UserProfileService(JdbcClient jdbcClient) {
        this.jdbcClient = jdbcClient;
    }

    public Map<String, Object> getProfile() {
        String sql = """
            SELECT attribute, value, confidence, immutable, updated_at
            FROM user_profile_attrs
            ORDER BY attribute ASC
        """;
        List<Map<String, Object>> rows = jdbcClient.sql(sql).query().listOfRows();
        List<Map<String, Object>> attrs = new ArrayList<>();
        for (Map<String, Object> r : rows) {
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("key", r.get("attribute"));
            item.put("name", r.get("attribute"));
            item.put("value", r.get("value"));
            item.put("confidence", r.get("confidence"));
            item.put("immutable", ((Number) r.get("immutable")).intValue() == 1);
            item.put("updated_at", String.valueOf(r.get("updated_at")));
            attrs.add(item);
        }

        // 同时抓取 user_profile 类型的记忆作为核心事实
        String factSql = """
            SELECT id, title, content, type, confidence, importance, created_at
            FROM memories
            WHERE type IN ('user_profile', 'preference', 'persona') AND status = 'active'
            ORDER BY importance DESC LIMIT 30
        """;
        List<Map<String, Object>> facts = jdbcClient.sql(factSql).query().listOfRows();

        Map<String, Object> res = new LinkedHashMap<>();
        res.put("attributes", attrs);
        res.put("facts", facts);
        res.put("total_attributes", attrs.size());
        res.put("total_facts", facts.size());
        return res;
    }

    public boolean upsertAttribute(String attribute, String value, double confidence, boolean immutable) {
        String sql = """
            INSERT INTO user_profile_attrs (user_id, attribute, value, confidence, immutable, source_ids_json, updated_at)
            VALUES ('default', :attr, :val, :conf, :imm, '[]'::jsonb, clock_timestamp())
            ON CONFLICT (user_id, attribute)
            DO UPDATE SET value = EXCLUDED.value, confidence = EXCLUDED.confidence,
                          immutable = EXCLUDED.immutable, updated_at = clock_timestamp()
        """;
        return jdbcClient.sql(sql)
                .param("attr", attribute)
                .param("val", value)
                .param("conf", confidence)
                .param("imm", immutable ? 1 : 0)
                .update() > 0;
    }
}
