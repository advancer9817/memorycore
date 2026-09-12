package org.mcore.storage.service;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.*;

@Service
public class UserProfileService {

    private final JdbcClient jdbcClient;

    private static final List<Map<String, Object>> SCHEMA = List.of(
            Map.of("name", "姓名", "description", "用户的姓名", "immutable", false),
            Map.of("name", "职业", "description", "用户的职业/岗位", "immutable", false),
            Map.of("name", "雇主", "description", "用户所在公司或雇主名称", "immutable", false),
            Map.of("name", "工作领域", "description", "用户日常工作涉及的领域、平台、系统", "immutable", false),
            Map.of("name", "技术栈", "description", "用户的技术背景、技能与开发环境", "immutable", true),
            Map.of("name", "沟通偏好", "description", "用户偏好的回答语言、风格、格式、交互方式", "immutable", false),
            Map.of("name", "模型偏好", "description", "用户偏好的模型/供应商/路由", "immutable", false),
            Map.of("name", "学习方向", "description", "用户当前的学习重点与转型目标", "immutable", false),
            Map.of("name", "语言", "description", "用户主要使用的语言（沟通、文档、代码注释）", "immutable", false),
            Map.of("name", "常用工具", "description", "用户常用的开发/办公/流程工具链", "immutable", false),
            Map.of("name", "当前项目", "description", "用户正在推进的项目/产品/任务焦点", "immutable", false),
            Map.of("name", "兴趣关注", "description", "用户关注的技术方向、行业趋势与话题", "immutable", false),
            Map.of("name", "时间偏好", "description", "工作时区、作息节奏、会议/响应时间偏好", "immutable", false),
            Map.of("name", "输出偏好", "description", "用户偏好的产出物格式（报告/图表/代码/演示等）", "immutable", false)
    );

    public UserProfileService(JdbcClient jdbcClient) {
        this.jdbcClient = jdbcClient;
    }

    public Map<String, Object> getProfile() {
        String sql = "SELECT attribute, value, confidence, immutable, updated_at FROM user_profile_attrs ORDER BY attribute ASC";
        List<Map<String, Object>> rows = jdbcClient.sql(sql).query().listOfRows();
        Map<String, Map<String, Object>> attrMap = new HashMap<>();
        for (Map<String, Object> r : rows) {
            String attrName = String.valueOf(r.get("attribute"));
            attrMap.put(attrName, r);
        }

        String factSql = "SELECT id, title, content, confidence, importance, updated_at FROM memories WHERE type IN ('user_profile', 'preference', 'persona') AND status = 'active' ORDER BY importance DESC, confidence DESC LIMIT 50";
        List<Map<String, Object>> facts = jdbcClient.sql(factSql).query().listOfRows();

        List<Map<String, Object>> attributes = new ArrayList<>();
        int coveredCount = 0;
        int highCount = 0;
        int medCount = 0;
        int lowCount = 0;
        List<String> immutableLocked = new ArrayList<>();

        for (Map<String, Object> s : SCHEMA) {
            String name = (String) s.get("name");
            String desc = (String) s.get("description");
            boolean isImmutable = Boolean.TRUE.equals(s.get("immutable"));
            if (isImmutable) {
                immutableLocked.add(name);
            }

            Map<String, Object> stored = attrMap.get(name);
            String value = stored != null && stored.get("value") != null ? String.valueOf(stored.get("value")) : null;
            double confidence = stored != null && stored.get("confidence") != null ? ((Number) stored.get("confidence")).doubleValue() : 0.0;
            String updatedAt = stored != null && stored.get("updated_at") != null ? String.valueOf(stored.get("updated_at")) : null;

            List<Map<String, Object>> matchedSources = new ArrayList<>();
            for (Map<String, Object> f : facts) {
                String title = String.valueOf(f.get("title"));
                String content = String.valueOf(f.get("content"));
                if (title.contains(name) || content.contains(name) || (name.equals("沟通偏好") && (title.contains("语言") || title.contains("风格")))) {
                    matchedSources.add(Map.of(
                            "id", f.get("id"),
                            "title", title,
                            "snippet", content.length() > 80 ? content.substring(0, 80) + "..." : content,
                            "updated_at", String.valueOf(f.get("updated_at"))
                    ));
                    if (value == null || value.isBlank()) {
                        value = content.length() > 100 ? content.substring(0, 100) + "..." : content;
                        confidence = f.get("confidence") != null ? ((Number) f.get("confidence")).doubleValue() : 0.85;
                        updatedAt = String.valueOf(f.get("updated_at"));
                    }
                }
            }

            if (value != null && !value.isBlank()) {
                coveredCount++;
                if (confidence >= 0.8) highCount++;
                else if (confidence >= 0.6) medCount++;
                else lowCount++;
            }

            Map<String, Object> attrItem = new LinkedHashMap<>();
            attrItem.put("attribute", name);
            attrItem.put("value", value);
            attrItem.put("confidence", confidence);
            attrItem.put("immutable", isImmutable);
            attrItem.put("description", desc);
            attrItem.put("source_count", matchedSources.size());
            attrItem.put("updated_at", updatedAt != null ? updatedAt : Instant.now().toString());
            attrItem.put("sources", matchedSources);
            attributes.add(attrItem);
        }

        double coverage = (double) coveredCount / SCHEMA.size();

        Map<String, Object> res = new LinkedHashMap<>();
        res.put("enabled", true);
        res.put("user_id", "default");
        res.put("schema_count", SCHEMA.size());
        res.put("covered", coveredCount);
        res.put("coverage", coverage);
        res.put("confidence_groups", Map.of("high", highCount, "medium", medCount, "low", lowCount));
        res.put("immutable_locked", immutableLocked);
        res.put("latest_extract_at", Instant.now().toString());
        res.put("extract_limit", 200);
        res.put("min_confidence", 0.6);
        res.put("max_snapshot_chars", 800);
        res.put("attributes", attributes);
        res.put("facts", facts);
        return res;
    }

    public boolean upsertAttribute(String attribute, String value, double confidence, boolean immutable) {
        String sql = "INSERT INTO user_profile_attrs (user_id, attribute, value, confidence, immutable, source_ids_json, updated_at) " +
                "VALUES ('default', :attr, :val, :conf, :imm, '[]'::jsonb, clock_timestamp()) " +
                "ON CONFLICT (user_id, attribute) " +
                "DO UPDATE SET value = EXCLUDED.value, confidence = EXCLUDED.confidence, " +
                "immutable = EXCLUDED.immutable, updated_at = clock_timestamp()";
        return jdbcClient.sql(sql)
                .param("attr", attribute)
                .param("val", value)
                .param("conf", confidence)
                .param("imm", immutable ? 1 : 0)
                .update() > 0;
    }
}
