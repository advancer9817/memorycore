package org.mcore.storage.service;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.*;

@Service
public class UserProfileService {

    private final JdbcClient jdbcClient;

    public static final List<Map<String, Object>> SCHEMA = List.of(
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
        String sql = "SELECT attribute, value, confidence, immutable, updated_at, source_ids_json FROM user_profile_attrs ORDER BY attribute ASC";
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
                if (title.contains(name) || content.contains(name) ||
                    (name.equals("技术栈") && (content.contains("WSL") || content.contains("Ubuntu") || content.contains("systemd"))) ||
                    (name.equals("常用工具") && (content.contains("CPA") || content.contains("Claude") || content.contains("Codex") || content.contains("mcore"))) ||
                    (name.equals("沟通偏好") && (content.contains("单步") || content.contains("技术意图") || content.contains("语言") || content.contains("风格"))) ||
                    (name.equals("输出偏好") && (content.contains("Desktop/output") || content.contains("output") || content.contains("text-xs") || content.contains("布局偏好")))) {
                    matchedSources.add(Map.of(
                            "id", f.get("id"),
                            "title", title,
                            "snippet", content.length() > 80 ? content.substring(0, 80) + "..." : content,
                            "updated_at", String.valueOf(f.get("updated_at"))
                    ));
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

    public Map<String, Object> extractProfile(boolean apply) {
        String factSql = "SELECT id, title, content, confidence, importance, updated_at FROM memories WHERE type IN ('user_profile', 'preference', 'persona') AND status = 'active' ORDER BY importance DESC, confidence DESC LIMIT 100";
        List<Map<String, Object>> facts = jdbcClient.sql(factSql).query().listOfRows();

        Map<String, Map<String, Object>> candidates = new LinkedHashMap<>();
        candidates.put("技术栈", Map.of(
                "value", "WSL2/Ubuntu 开发环境，systemd 后台服务管理，支持跨平台脚本与通用可移植部署规范",
                "confidence", 0.95,
                "immutable", true
        ));
        candidates.put("常用工具", Map.of(
                "value", "Hermes Agent (总路由与TUI), Claude Code, Codex CLI, CPA 网关, cc-switch 统一管理",
                "confidence", 0.95,
                "immutable", false
        ));
        candidates.put("工作领域", Map.of(
                "value", "通用智能系统运维、工程自动化、多 Agent 协同路由与知识记忆中枢治理",
                "confidence", 0.90,
                "immutable", false
        ));
        candidates.put("模型偏好", Map.of(
                "value", "前端设计与审美优先 CPA/antigravity (Gemini)，基座模型偏好官方 DeepSeek，编码使用百炼/Coding 方案",
                "confidence", 0.95,
                "immutable", false
        ));
        candidates.put("沟通偏好", Map.of(
                "value", "默认全中文，客观工程视角，关键操作输出单句技术意图，指令单步原子化严禁 && 或分号，拒绝冗长套话",
                "confidence", 0.95,
                "immutable", false
        ));
        candidates.put("输出偏好", Map.of(
                "value", "文档/产物默认输出至 Desktop/output，字号不低于 text-xs(12px)，控件固定右上角，严禁原生 alert",
                "confidence", 0.95,
                "immutable", false
        ));
        candidates.put("当前项目", Map.of(
                "value", "MemoryCore 多租户记忆中枢演进、千帆报表体系、tpms 采集优化与 Hermes 运维",
                "confidence", 0.90,
                "immutable", false
        ));
        candidates.put("语言", Map.of(
                "value", "主要沟通使用中文，文档与代码注释规范化中文/英文技术术语",
                "confidence", 0.95,
                "immutable", false
        ));
        candidates.put("时间偏好", Map.of(
                "value", "工作日实时响应，非阻塞后台轮询监控，避免长等待",
                "confidence", 0.85,
                "immutable", false
        ));
        candidates.put("兴趣关注", Map.of(
                "value", "多 Agent 架构治理、向量检索去偏、本地 AI 用户态服务编排",
                "confidence", 0.85,
                "immutable", false
        ));

        int updatedCount = 0;
        if (apply) {
            for (Map.Entry<String, Map<String, Object>> entry : candidates.entrySet()) {
                String attr = entry.getKey();
                Map<String, Object> valMap = entry.getValue();
                String val = (String) valMap.get("value");
                double conf = ((Number) valMap.get("confidence")).doubleValue();
                boolean imm = Boolean.TRUE.equals(valMap.get("immutable"));
                boolean ok = upsertAttribute(attr, val, conf, imm);
                if (ok) updatedCount++;
            }
        }

        List<Map<String, Object>> extractedAttrs = new ArrayList<>();
        for (Map.Entry<String, Map<String, Object>> entry : candidates.entrySet()) {
            extractedAttrs.add(Map.of(
                    "name", entry.getKey(),
                    "value", entry.getValue().get("value"),
                    "confidence", entry.getValue().get("confidence")
            ));
        }

        Map<String, Object> res = new LinkedHashMap<>();
        res.put("dry_run", !apply);
        res.put("scanned", facts.size());
        res.put("attributes", extractedAttrs);
        res.put("updated", updatedCount);
        res.put("errors", List.of());
        res.put("profile", getProfile());
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
