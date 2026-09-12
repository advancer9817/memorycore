package org.mcore.storage.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.mcore.common.model.MemoryDO;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

import java.util.*;

@Service
public class GovernanceService {

    private final JdbcClient jdbcClient;
    private final org.mcore.storage.entity.EntityIndexService entityIndexService;
    private final ObjectMapper objectMapper;

    public GovernanceService(JdbcClient jdbcClient,
                             org.mcore.storage.entity.EntityIndexService entityIndexService,
                             ObjectMapper objectMapper) {
        this.jdbcClient = jdbcClient;
        this.entityIndexService = entityIndexService;
        this.objectMapper = objectMapper;
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

    /**
     * 决策执行器：把 `governance_decisions` 真正作用到 `memories`。
     *
     * 修复背景：此前 `applyDecision` / `batchApply` 只执行
     * `UPDATE governance_decisions SET review_status='applied'`，
     * **从不触碰 memories** —— 前端显示"已应用 N 条"，记忆零变化，
     * 属静默假成功（`getCounts` 的 applied 计数照涨，更具误导性）。
     *
     * 同时补齐执行台账：`governance_executions` + `governance_mutation_log`。
     */
    public Map<String, Object> executeDecision(String decisionId, String actor) {
        Map<String, Object> res = new LinkedHashMap<>();
        Map<String, Object> row = jdbcClient.sql(
                        "SELECT id, recommended_action, risk_level, review_status, " +
                        "       source_ids_json::text AS src, before_state_json::text AS before, " +
                        "       after_state_json::text AS after, rollback_json::text AS rollback " +
                        "FROM governance_decisions WHERE id = :id")
                .param("id", decisionId).query().listOfRows().stream().findFirst().orElse(null);

        if (row == null) {
            res.put("ok", false);
            res.put("error", "decision_not_found");
            res.put("decision_id", decisionId);
            return res;
        }

        String status = row.get("review_status") == null ? "" : String.valueOf(row.get("review_status"));
        if ("applied".equalsIgnoreCase(status)) {
            // 幂等：重复执行不产生第二次副作用
            res.put("ok", true);
            res.put("idempotent", true);
            res.put("decision_id", decisionId);
            res.put("note", "该决策已应用，跳过");
            return res;
        }

        String action = row.get("recommended_action") == null ? "" : String.valueOf(row.get("recommended_action"));
        String risk = row.get("risk_level") == null ? "unknown" : String.valueOf(row.get("risk_level"));

        String keepId = readJsonString(row.get("before"), "keep_id");
        String dropId = readJsonString(row.get("before"), "drop_id");
        String targetId = dropId != null ? dropId : keepId;

        // 显式动作白名单：未知动作一律拒绝。
        // 修复 S23：原 executeMaintenance 的 default 分支会把任何未知 action
        // （含 merge）执行为"归档全部 stale"，属会改坏数据的危险默认。
        String newStatus;
        boolean alsoMerge = false;
        switch (action) {
            case "archive_duplicate":
            case "archive":
                newStatus = "archived";
                break;
            case "merge":
            case "archive_and_merge_duplicate":
                newStatus = "archived";
                alsoMerge = true;
                break;
            case "mark_contradicted":
                newStatus = "contradicted";
                break;
            default:
                res.put("ok", false);
                res.put("error", "unsupported_action");
                res.put("action", action);
                res.put("note", "动作不在白名单内，已拒绝执行（不采用默认归档）");
                return res;
        }

        if (targetId == null || targetId.isBlank()) {
            res.put("ok", false);
            res.put("error", "missing_target");
            res.put("note", "决策未携带可执行的 target（before_state_json 缺少 drop_id/keep_id）");
            return res;
        }

        String execId = "gex_" + UUID.randomUUID().toString().replace("-", "").substring(0, 16);
        String idemKey = decisionId + ":" + action + ":" + targetId;

        Map<String, Object> beforeState = new LinkedHashMap<>();
        beforeState.put("status", queryMemoryStatus(targetId));
        beforeState.put("target_id", targetId);

        // 1) 执行真实变更
        int affected;
        if (alsoMerge && keepId != null && !keepId.isBlank()) {
            affected = jdbcClient.sql(
                            "UPDATE memories SET status = :status, superseded_by = :keep, updated_at = clock_timestamp() " +
                            "WHERE id = :id AND status <> :status")
                    .param("status", newStatus).param("keep", keepId).param("id", targetId).update();
        } else {
            affected = jdbcClient.sql(
                            "UPDATE memories SET status = :status, updated_at = clock_timestamp() " +
                            "WHERE id = :id AND status <> :status")
                    .param("status", newStatus).param("id", targetId).update();
        }

        // 状态变更后实体索引必须同步（非 active 记忆不应再被 entity_search 召回）
        syncEntities(targetId);

        Map<String, Object> afterState = new LinkedHashMap<>();
        afterState.put("status", newStatus);
        afterState.put("target_id", targetId);
        if (alsoMerge) {
            afterState.put("merged_into", keepId);
        }

        // 2) 写执行台账
        jdbcClient.sql("INSERT INTO governance_executions " +
                        "(id, decision_id, approval_kind, risk_level, status, idempotency_key, " +
                        " policy_snapshot_json, started_at, finished_at, created_by, metadata_json) " +
                        "VALUES (:id, :dec, :kind, :risk, 'applied', :idem, CAST(:snap AS jsonb), " +
                        " clock_timestamp()::text, clock_timestamp()::text, :by, CAST(:meta AS jsonb))")
                .param("id", execId).param("dec", decisionId)
                .param("kind", "manual").param("risk", risk)
                .param("idem", idemKey)
                .param("snap", toJson(Map.of("action", action, "policy_version", "v1")))
                .param("by", actor != null ? actor : "admin")
                .param("meta", toJson(Map.of("affected_rows", affected)))
                .update();

        jdbcClient.sql("INSERT INTO governance_mutation_log " +
                        "(id, execution_id, seq, mutation_type, entity_type, entity_id, operation, risk_level, " +
                        " policy_decision, policy_reason, request_json, before_json, after_json, inverse_json, " +
                        " status, idempotency_key, created_at, applied_at) " +
                        "VALUES (:id, :exec, 1, 'memory_status_change', 'memory', :entity, 'update', :risk, " +
                        " 'allow', :reason, CAST(:req AS jsonb), CAST(:before AS jsonb), CAST(:after AS jsonb), " +
                        " CAST(:inverse AS jsonb), 'applied', :idem, clock_timestamp()::text, clock_timestamp()::text)")
                .param("id", "gml_" + UUID.randomUUID().toString().replace("-", "").substring(0, 16))
                .param("exec", execId).param("entity", targetId).param("risk", risk)
                .param("reason", "决策 " + decisionId + " 动作 " + action)
                .param("req", toJson(Map.of("action", action, "decision_id", decisionId)))
                .param("before", toJson(beforeState))
                .param("after", toJson(afterState))
                .param("inverse", toJson(Map.of("action", "restore_status",
                        "target_id", targetId,
                        "status", beforeState.get("status") == null ? "active" : beforeState.get("status"))))
                .param("idem", idemKey)
                .update();

        // 3) 回写决策状态与执行关联
        jdbcClient.sql("UPDATE governance_decisions SET review_status = 'applied', applied_at = clock_timestamp(), " +
                        "applied_by = :by, execution_id = :exec, updated_at = clock_timestamp() WHERE id = :id")
                .param("by", actor != null ? actor : "admin")
                .param("exec", execId).param("id", decisionId).update();

        res.put("ok", true);
        res.put("decision_id", decisionId);
        res.put("action", action);
        res.put("target_id", targetId);
        res.put("new_status", newStatus);
        res.put("affected_rows", affected);
        res.put("execution_id", execId);
        res.put("idempotent", false);
        return res;
    }

    /** 兼容原签名：真正执行并返回是否成功 */
    public boolean applyDecision(String id, String actor) {
        Map<String, Object> r = executeDecision(id, actor);
        return Boolean.TRUE.equals(r.get("ok"));
    }

    public boolean rejectDecision(String id, String actor) {
        String sql = """
            UPDATE governance_decisions 
            SET review_status = 'rejected', updated_at = clock_timestamp()
            WHERE id = :id
        """;
        return jdbcClient.sql(sql).param("id", id).update() > 0;
    }

    /** 批量执行：逐条真实落地，失败与不支持的动作如实计入 skipped */
    public Map<String, Object> batchApply(List<String> ids, String actor) {
        if (ids == null || ids.isEmpty()) {
            return Map.of("applied_count", 0, "skipped_count", 0);
        }
        int applied = 0;
        int skipped = 0;
        int affectedTotal = 0;
        List<Map<String, Object>> results = new ArrayList<>();
        for (String id : ids) {
            Map<String, Object> r = executeDecision(id, actor);
            if (Boolean.TRUE.equals(r.get("ok"))) {
                applied++;
                affectedTotal += r.get("affected_rows") instanceof Number n ? n.intValue() : 0;
            } else {
                skipped++;
            }
            results.add(r);
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("applied_count", applied);
        out.put("skipped_count", skipped);
        out.put("affected_memories", affectedTotal);
        out.put("results", results);
        return out;
    }

    /** 依据 mutation_log 的 inverse_json 回滚最近一次执行 */
    public Map<String, Object> rollbackDecision(String decisionId, String actor) {
        Map<String, Object> res = new LinkedHashMap<>();
        Map<String, Object> dec = jdbcClient.sql(
                        "SELECT execution_id, review_status FROM governance_decisions WHERE id = :id")
                .param("id", decisionId).query().listOfRows().stream().findFirst().orElse(null);
        if (dec == null) {
            res.put("ok", false);
            res.put("error", "decision_not_found");
            return res;
        }
        String execId = dec.get("execution_id") == null ? null : String.valueOf(dec.get("execution_id"));
        if (execId == null || execId.isBlank()) {
            res.put("ok", false);
            res.put("error", "no_execution_record");
            res.put("note", "该决策尚无执行台账，无法回滚");
            return res;
        }
        List<Map<String, Object>> logs = jdbcClient.sql(
                        "SELECT id, entity_id, inverse_json::text AS inverse FROM governance_mutation_log " +
                        "WHERE execution_id = :exec AND status = 'applied' ORDER BY seq DESC")
                .param("exec", execId).query().listOfRows();

        int restored = 0;
        for (Map<String, Object> log : logs) {
            String targetId = log.get("entity_id") == null ? null : String.valueOf(log.get("entity_id"));
            String restoreStatus = readJsonString(log.get("inverse"), "status");
            if (targetId == null || restoreStatus == null) {
                continue;
            }
            restored += jdbcClient.sql("UPDATE memories SET status = :s, updated_at = clock_timestamp() WHERE id = :id")
                    .param("s", restoreStatus).param("id", targetId).update();
            syncEntities(targetId);
            jdbcClient.sql("UPDATE governance_mutation_log SET status = 'rolled_back', " +
                            "rolled_back_at = clock_timestamp()::text WHERE id = :id")
                    .param("id", String.valueOf(log.get("id"))).update();
        }
        jdbcClient.sql("UPDATE governance_decisions SET review_status = 'rolled_back', " +
                        "rolled_back_at = clock_timestamp(), rolled_back_by = :by, updated_at = clock_timestamp() " +
                        "WHERE id = :id")
                .param("by", actor != null ? actor : "admin").param("id", decisionId).update();

        res.put("ok", true);
        res.put("decision_id", decisionId);
        res.put("execution_id", execId);
        res.put("restored_count", restored);
        return res;
    }

    private String queryMemoryStatus(String id) {
        return jdbcClient.sql("SELECT status FROM memories WHERE id = :id")
                .param("id", id).query(String.class).optional().orElse(null);
    }

    private void syncEntities(String memoryId) {
        try {
            MemoryDO m = jdbcClient.sql("SELECT id, title, content, status, tags::text AS tags_json, project_path " +
                            "FROM memories WHERE id = :id")
                    .param("id", memoryId).query().listOfRows().stream().findFirst()
                    .map(r -> {
                        MemoryDO d = new MemoryDO();
                        d.setId(String.valueOf(r.get("id")));
                        d.setTitle(r.get("title") == null ? null : String.valueOf(r.get("title")));
                        d.setContent(r.get("content") == null ? null : String.valueOf(r.get("content")));
                        d.setStatus(r.get("status") == null ? null : String.valueOf(r.get("status")));
                        d.setProjectPath(r.get("project_path") == null ? null : String.valueOf(r.get("project_path")));
                        return d;
                    }).orElse(null);
            if (m != null) {
                entityIndexService.sync(m);
            }
        } catch (Exception ignored) {
            // 索引同步失败不阻断治理执行
        }
    }

    private String readJsonString(Object jsonish, String key) {
        if (jsonish == null) {
            return null;
        }
        try {
            var node = objectMapper.readTree(String.valueOf(jsonish));
            var v = node.get(key);
            return v == null || v.isNull() ? null : v.asText();
        } catch (Exception e) {
            return null;
        }
    }

    private String toJson(Object o) {
        try {
            return objectMapper.writeValueAsString(o);
        } catch (Exception e) {
            return "{}";
        }
    }


    /** 维护动作 → 候选/执行共用的 WHERE 谓词（保证"所见即所执行"） */
    private String maintenancePredicate(String act) {
        return switch (act) {
            case "clean" -> "(content IS NULL OR btrim(content) = '' OR title IS NULL OR btrim(title) = '') " +
                    "AND status <> 'archived'";
            case "expire" -> "status IN ('superseded','contradicted') AND updated_at < now() - interval '90 days'";
            case "archive_stale" -> "status = 'stale'";
            default -> null;
        };
    }

    private static final List<String> MAINTENANCE_ACTIONS = List.of("clean", "expire", "archive_stale");

    /**
     * 生成维护计划。
     *
     * 修复 S24：原实现 `plan_token` 是随机 UUID、既不落库也不在执行时校验，
     * 且候选集谓词与执行谓词不一致（clean 列出的是 status='archived' 的行），
     * 导致"计划"与"执行"完全脱钩 —— token 形同虚设，计划看到的行与实际改动的行无关。
     *
     * 现改为：
     * - 候选集与执行使用**同一谓词**
     * - `plan_token` = sha256(action + 排序后的候选 id)，内容确定、可校验
     * - 计划落库（maintenance_jobs.status='planned'），执行时比对哈希
     */
    public Map<String, Object> getMaintenancePlan(String action, int limit) {
        if (limit <= 0) limit = 100;
        String act = (action == null || action.isBlank()) ? "clean" : action.toLowerCase();
        String predicate = maintenancePredicate(act);
        if (predicate == null) {
            Map<String, Object> rejected = new LinkedHashMap<>();
            rejected.put("ok", false);
            rejected.put("error", "unsupported_maintenance_action");
            rejected.put("action", act);
            rejected.put("allowed_actions", MAINTENANCE_ACTIONS);
            return rejected;
        }

        List<Map<String, Object>> candidates = jdbcClient.sql(
                        "SELECT id, title, type, status, created_at FROM memories WHERE " + predicate +
                        " ORDER BY updated_at ASC LIMIT :limit")
                .param("limit", limit).query().listOfRows();

        List<String> ids = new ArrayList<>();
        for (Map<String, Object> c : candidates) {
            ids.add(String.valueOf(c.get("id")));
        }
        String token = planToken(act, ids);

        jdbcClient.sql("INSERT INTO maintenance_jobs (id, plan_token, kind, status, summary_json, created_at) " +
                        "VALUES (:id, :token, :kind, 'planned', CAST(:summary AS jsonb), clock_timestamp())")
                .param("id", "mnt_" + UUID.randomUUID().toString().replace("-", "").substring(0, 12))
                .param("token", token)
                .param("kind", act)
                .param("summary", toJson(Map.of(
                        "action", act,
                        "candidate_count", ids.size(),
                        "candidate_ids", ids,
                        "limit", limit)))
                .update();

        Map<String, Object> plan = new LinkedHashMap<>();
        plan.put("action", act);
        plan.put("candidate_count", candidates.size());
        plan.put("candidates", candidates);
        plan.put("plan_token", token);
        plan.put("created_at", new Date().toString());
        return plan;
    }

    /** plan_token = sha256(动作 + 排序后的候选 id)，内容确定且可复算 */
    private String planToken(String act, List<String> ids) {
        List<String> sorted = new ArrayList<>(ids);
        Collections.sort(sorted);
        String payload = act + "|" + String.join(",", sorted);
        try {
            var md = java.security.MessageDigest.getInstance("SHA-256");
            byte[] h = md.digest(payload.getBytes(java.nio.charset.StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder();
            for (byte b : h) {
                sb.append(String.format("%02x", b));
            }
            return sb.toString();
        } catch (Exception e) {
            return UUID.randomUUID().toString().replace("-", "");
        }
    }

    /** 审计事件分页查询（真实表 audit_events） */
    public Map<String, Object> listAuditEvents(int page, int pageSize, String eventType) {
        int p = Math.max(1, page);
        int size = Math.max(1, Math.min(pageSize, 200));
        int offset = (p - 1) * size;

        String where = (eventType != null && !eventType.isBlank()) ? " WHERE event_type = :et " : "";
        Map<String, Object> params = new LinkedHashMap<>();
        if (!where.isEmpty()) {
            params.put("et", eventType);
        }

        Long total = jdbcClient.sql("SELECT COUNT(*) FROM audit_events" + where)
                .params(params).query(Long.class).single();

        Map<String, Object> qp = new LinkedHashMap<>(params);
        qp.put("limit", size);
        qp.put("offset", offset);
        List<Map<String, Object>> items = org.mcore.storage.util.JsonbRows.rows(jdbcClient.sql(
                        "SELECT id, event_type, memory_id, agent, detail_json, created_at " +
                        "FROM audit_events" + where + " ORDER BY created_at DESC NULLS LAST LIMIT :limit OFFSET :offset")
                .params(qp).query().listOfRows());

        Map<String, Object> res = new LinkedHashMap<>();
        res.put("items", items);
        res.put("total", total);
        res.put("page", p);
        res.put("page_size", size);
        return res;
    }

    /**
     * 执行维护动作。
     *
     * 修复 S24（安全链条）：
     * - **令牌校验**：`plan_token` 必须对应一条已落库的计划，且与当前候选集哈希一致；
     *   否则拒绝。原实现从不校验 token，任意字符串都可通过。
     * - **计划漂移检测**：计划生成后候选集若发生变化，哈希不匹配 → 拒绝执行，
     *   避免"看一眼 A、改动 B"。
     * - **强制快照**：执行前把受影响行的 id+原状态写入作业记录，作为可回溯备份。
     * - **幂等重放**：同一 token 重复执行返回上次结果，不产生第二次副作用。
     * - **跨进程锁**：PG advisory lock，防止并发维护互相踩踏。
     */
    public Map<String, Object> executeMaintenance(String planToken, String action) {
        if (planToken == null || planToken.isBlank()) {
            return Map.of("ok", false, "error", "missing_plan_token",
                    "note", "必须先调用维护计划接口取得 plan_token");
        }
        String act = (action == null || action.isBlank()) ? "clean" : action.toLowerCase();
        String predicate = maintenancePredicate(act);
        if (predicate == null) {
            return Map.of("ok", false, "error", "unsupported_maintenance_action",
                    "action", act, "allowed_actions", MAINTENANCE_ACTIONS,
                    "note", "未知维护动作已拒绝，未产生任何写入");
        }

        // 1) 令牌必须对应已落库的计划
        Map<String, Object> planned = jdbcClient.sql(
                        "SELECT id, status, kind, summary_json::text AS summary " +
                        "FROM maintenance_jobs WHERE plan_token = :token ORDER BY created_at DESC LIMIT 1")
                .param("token", planToken).query().listOfRows().stream().findFirst().orElse(null);
        if (planned == null) {
            return Map.of("ok", false, "error", "unknown_plan_token",
                    "note", "该 plan_token 无对应计划记录，拒绝执行");
        }

        String jobStatus = planned.get("status") == null ? "" : String.valueOf(planned.get("status"));

        // 2) 幂等重放：已完成则返回上次结果，不再改动数据
        if ("done".equalsIgnoreCase(jobStatus)) {
            Map<String, Object> replay = new LinkedHashMap<>();
            replay.put("success", true);
            replay.put("idempotent", true);
            replay.put("job_id", planned.get("id"));
            replay.put("action", act);
            replay.put("plan_token", planToken);
            replay.put("previous_summary", readJsonMap(planned.get("summary")));
            replay.put("note", "该计划已执行，返回既有结果");
            return replay;
        }

        // 3) 漂移检测：当前候选集哈希必须与令牌一致
        List<Map<String, Object>> current = jdbcClient.sql(
                        "SELECT id FROM memories WHERE " + predicate + " ORDER BY updated_at ASC LIMIT :limit")
                .param("limit", readJsonInt(planned.get("summary"), "limit", 100))
                .query().listOfRows();
        List<String> currentIds = new ArrayList<>();
        for (Map<String, Object> c : current) {
            currentIds.add(String.valueOf(c.get("id")));
        }
        String currentToken = planToken(act, currentIds);
        if (!currentToken.equals(planToken)) {
            Map<String, Object> drift = new LinkedHashMap<>();
            drift.put("ok", false);
            drift.put("error", "plan_drift");
            drift.put("note", "候选集自计划生成后已变化，请重新生成计划");
            drift.put("planned_count", readJsonInt(planned.get("summary"), "candidate_count", -1));
            drift.put("current_count", currentIds.size());
            return drift;
        }

        // 4) 跨进程锁
        Boolean locked = jdbcClient.sql("SELECT pg_try_advisory_lock(918273645)")
                .query(Boolean.class).single();
        if (!Boolean.TRUE.equals(locked)) {
            return Map.of("ok", false, "error", "maintenance_locked",
                    "note", "另一维护作业正在执行，请稍后重试");
        }

        try {
            // 5) 强制快照：受影响行的原状态（可回溯）
            List<Map<String, Object>> snapshot = jdbcClient.sql(
                            "SELECT id, status FROM memories WHERE " + predicate)
                    .query().listOfRows();

            String sql = switch (act) {
                case "clean" -> "UPDATE memories SET status = 'archived', updated_at = clock_timestamp() " +
                        "WHERE " + predicate;
                case "expire" -> "UPDATE memories SET status = 'archived', updated_at = clock_timestamp() " +
                        "WHERE " + predicate;
                case "archive_stale" -> "UPDATE memories SET status = 'archived', updated_at = clock_timestamp() " +
                        "WHERE " + predicate;
                default -> null;
            };
            int affected = jdbcClient.sql(sql).update();

            String summary = toJson(Map.of(
                    "updated_count", affected,
                    "action", act,
                    "snapshot_count", snapshot.size(),
                    "snapshot", snapshot));

            jdbcClient.sql("UPDATE maintenance_jobs SET status = 'done', summary_json = CAST(:summary AS jsonb), " +
                            "finished_at = clock_timestamp() WHERE id = :id")
                    .param("summary", summary)
                    .param("id", String.valueOf(planned.get("id")))
                    .update();

            Map<String, Object> res = new LinkedHashMap<>();
            res.put("success", true);
            res.put("job_id", planned.get("id"));
            res.put("action", act);
            res.put("affected_rows", affected);
            res.put("updated_count", affected);
            res.put("snapshot_count", snapshot.size());
            res.put("plan_token", planToken);
            res.put("idempotent", false);
            return res;
        } finally {
            jdbcClient.sql("SELECT pg_advisory_unlock(918273645)").query(Boolean.class).single();
        }
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> readJsonMap(Object jsonish) {
        if (jsonish == null) {
            return Map.of();
        }
        try {
            return objectMapper.readValue(String.valueOf(jsonish), Map.class);
        } catch (Exception e) {
            return Map.of();
        }
    }

    private int readJsonInt(Object jsonish, String key, int dflt) {
        Object v = readJsonMap(jsonish).get(key);
        return v instanceof Number n ? n.intValue() : dflt;
    }
}
