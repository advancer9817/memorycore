package org.mcore.storage.service;

import org.mcore.storage.config.ConfigFileStore;
import org.mcore.storage.embedding.EmbeddingService;
import org.mcore.storage.util.JsonbRows;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.*;

/**
 * LLM 策展执行器。
 *
 * 填补迭代 257 遗留：此前 `POST /curator/llm` 只登记 queued 作业，没有任何执行器消费，
 * 前端触发后永远停留在排队状态。
 *
 * 流水线（与旧版 Python `curator_llm` 同构）：
 *  1. 取候选记忆（active，按 importance 排序，排除近期已审）
 *  2. 向量召回近邻对（阈值 = sim_threshold × 0.8，top_k=6），按相似度降序去重
 *  3. 分批送 LLM 判官，返回结构化 JSON
 *  4. 确定性策略门（deterministic policy gate）决定 review_status
 *  5. 落 governance_decisions，并登记 llm_curator_batches / 更新作业状态
 *
 * 设计原则：LLM 只作结构化分类器，是否采纳由确定性策略门裁决（非 LLM 自决）。
 */
@Service
public class LlmCuratorExecutor {

    private static final Logger log = LoggerFactory.getLogger(LlmCuratorExecutor.class);

    private static final String STAGE_DEDUP = "dedup";

    private final JdbcClient jdbcClient;
    private final ConfigFileStore configStore;
    private final EmbeddingService embeddingService;
    private final ExtractionService extractionService;

    public LlmCuratorExecutor(JdbcClient jdbcClient, ConfigFileStore configStore,
                              EmbeddingService embeddingService, ExtractionService extractionService) {
        this.jdbcClient = jdbcClient;
        this.configStore = configStore;
        this.embeddingService = embeddingService;
        this.extractionService = extractionService;
    }

    /** 消费一条排队中的作业（取最早的一条） */
    public Map<String, Object> consumeOne() {
        Map<String, Object> job = jdbcClient.sql(
                        "SELECT id FROM llm_curator_jobs WHERE status = 'queued' " +
                        "ORDER BY COALESCE(started_at, updated_at) ASC LIMIT 1")
                .query().listOfRows().stream().findFirst().orElse(null);
        if (job == null) {
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("executed", false);
            res.put("message", "没有排队中的策展作业");
            return res;
        }
        String jobId = String.valueOf(job.get("id"));
        Map<String, Object> result = execute(jobId);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("executed", true);
        res.put("job_id", jobId);
        res.put("result", result);
        return res;
    }

    /** 执行指定作业 */
    public Map<String, Object> execute(String jobId) {
        Map<String, Object> cfg = configStore.section("llm_curator");
        double simThreshold = configStore.doubleVal(cfg, "sim_threshold", 0.8);
        int batchSize = Math.max(1, configStore.intVal(cfg, "batch_size", 10));
        int importanceLimit = Math.max(1, configStore.intVal(cfg, "importance_limit", 2000));
        double temperature = configStore.doubleVal(cfg, "temperature", 0.2);
        long reviewedMaxAge = (long) configStore.intVal(cfg, "reviewed_ids_max_age_seconds", 43200);
        int maxDedupPairs = Math.max(1, configStore.intVal(cfg, "max_dedup_pairs", 60));

        markJob(jobId, "running", null);
        long t0 = System.currentTimeMillis();

        int candidateCount = 0;
        int pairCount = 0;
        int findingCount = 0;
        int decisionCount = 0;
        int batchIndex = 0;
        List<String> errors = new ArrayList<>();

        try {
            // ---------- 1. 候选记忆 ----------
            List<Map<String, Object>> memories = jdbcClient.sql(
                            "SELECT id, title, content, importance, updated_at FROM memories " +
                            "WHERE status = 'active' AND content IS NOT NULL AND btrim(content) <> '' " +
                            "AND id NOT IN (SELECT memory_id FROM curator_review_log " +
                            "               WHERE review_type = 'llm_curator' " +
                            "               AND reviewed_at > now() - (:age || ' seconds')::interval) " +
                            // 确定性排序：importance 存在大量并列（实测 70 条 importance=1），
                            // 若只用 importance 排序再 LIMIT，入选者随机且每次运行不同，
                            // 会导致高价值记忆被系统性饿死且结果不可复现。
                            "ORDER BY COALESCE(importance, 0) DESC, updated_at DESC NULLS LAST, id ASC " +
                            "LIMIT :limit")
                    .param("age", reviewedMaxAge)
                    .param("limit", importanceLimit)
                    .query().listOfRows();
            candidateCount = memories.size();

            if (candidateCount < 2) {
                Map<String, Object> summary = new LinkedHashMap<>();
                summary.put("stage", STAGE_DEDUP);
                summary.put("candidate_count", candidateCount);
                summary.put("note", "候选不足 2 条，无需比对");
                markJobFinished(jobId, summary, errors, t0);
                return summary;
            }

            // ---------- 2. 向量召回候选对 ----------
            Map<String, Map<String, Object>> byId = new LinkedHashMap<>();
            for (Map<String, Object> m : memories) {
                byId.put(String.valueOf(m.get("id")), m);
            }

            double floor = simThreshold * 0.8;
            Set<String> seen = new HashSet<>();
            List<Object[]> pairs = new ArrayList<>();   // [aId, bId, score]

            for (Map<String, Object> m : memories) {
                String id = String.valueOf(m.get("id"));
                String text = (str(m.get("title")) + " " + str(m.get("content"))).trim();
                if (text.isEmpty()) {
                    continue;
                }
                float[] vec;
                try {
                    vec = embeddingService.embedText(text);
                } catch (Exception e) {
                    errors.add("embed_failed:" + id + ":" + e.getMessage());
                    continue;
                }
                List<Map<String, Object>> hits = jdbcClient.sql(
                                "SELECT id, 1 - (embedding <=> CAST(:vec AS vector)) AS score FROM memories " +
                                "WHERE status = 'active' AND embedding IS NOT NULL AND id <> :id " +
                                "ORDER BY embedding <=> CAST(:vec AS vector) LIMIT 6")
                        .param("vec", toVectorLiteral(vec))
                        .param("id", id)
                        .query().listOfRows();

                for (Map<String, Object> hit : hits) {
                    String otherId = String.valueOf(hit.get("id"));
                    if (!byId.containsKey(otherId)) {
                        continue;
                    }
                    double score = hit.get("score") instanceof Number n ? n.doubleValue() : 0.0;
                    if (score < floor) {
                        continue;
                    }
                    String key = id.compareTo(otherId) < 0 ? id + "|" + otherId : otherId + "|" + id;
                    if (!seen.add(key)) {
                        continue;
                    }
                    pairs.add(new Object[]{id, otherId, score});
                }
            }

            pairs.sort((x, y) -> Double.compare((Double) y[2], (Double) x[2]));
            if (pairs.size() > maxDedupPairs) {
                pairs = pairs.subList(0, maxDedupPairs);
            }
            pairCount = pairs.size();

            if (pairCount == 0) {
                Map<String, Object> summary = new LinkedHashMap<>();
                summary.put("stage", STAGE_DEDUP);
                summary.put("candidate_count", candidateCount);
                summary.put("pair_count", 0);
                summary.put("note", "未发现相似度达标的候选对");
                markJobFinished(jobId, summary, errors, t0);
                return summary;
            }

            // ---------- 3/4. 分批判定 + 策略门 ----------
            for (int i = 0; i < pairs.size(); i += batchSize) {
                List<Object[]> batch = pairs.subList(i, Math.min(i + batchSize, pairs.size()));
                String batchId = "batch_" + jobId + "_" + batchIndex;
                insertBatch(batchId, jobId, batchIndex, batch.size());

                int batchFindings = 0;
                int batchDecisions = 0;
                try {
                    String userPrompt = buildJudgePrompt(batch, byId);
                    String raw = extractionService.chatComplete(JUDGE_SYSTEM, userPrompt, temperature, 2048);
                    List<Map<String, Object>> results = parseJudgeResults(raw);

                    for (Map<String, Object> item : results) {
                        int idx = item.get("index") instanceof Number n ? n.intValue() : -1;
                        if (idx < 0 || idx >= batch.size()) {
                            continue;
                        }
                        boolean isDup = Boolean.TRUE.equals(item.get("is_duplicate"));
                        if (!isDup) {
                            continue;
                        }
                        batchFindings++;

                        Object[] pair = batch.get(idx);
                        String aId = (String) pair[0];
                        String bId = (String) pair[1];
                        double score = (Double) pair[2];

                        // keep/drop 决策：LLM 指定优先，未指定则按重要度→时间兜底
                        String keepLabel = str(item.get("keep")).trim().toUpperCase();
                        String keepId;
                        String dropId;
                        if ("A".equals(keepLabel)) {
                            keepId = aId; dropId = bId;
                        } else if ("B".equals(keepLabel)) {
                            keepId = bId; dropId = aId;
                        } else {
                            Map<String, Object> a = byId.get(aId);
                            Map<String, Object> b = byId.get(bId);
                            double ai = toDbl(a.get("importance"));
                            double bi = toDbl(b.get("importance"));
                            if (ai != bi) {
                                keepId = ai >= bi ? aId : bId;
                            } else {
                                keepId = String.valueOf(a.get("updated_at")).compareTo(String.valueOf(b.get("updated_at"))) >= 0 ? aId : bId;
                            }
                            dropId = keepId.equals(aId) ? bId : aId;
                        }

                        String reason = str(item.get("reason"));
                        String mergeInfo = str(item.get("merge_info"));
                        String action = (mergeInfo != null && !mergeInfo.isBlank())
                                ? "archive_and_merge_duplicate" : "archive_duplicate";

                        // LLM 自报置信度（缺失时按相似度折算，保守取值）
                        double confidence = item.get("confidence") instanceof Number n
                                ? n.doubleValue() : Math.min(0.95, Math.max(0.5, score));
                        // 风险等级归一化：LLM 可能返回 none/nil/safe 等同义值（实测出现过 "none"），
                        // 若不归一会被判为非低风险，导致本可自动采纳的决策被挡在待审队列。
                        String risk = normalizeRisk(item.get("risk"));
                        if (risk == null) {
                            risk = score >= 0.92 ? "low" : "medium";
                        }

                        String candidateHash = sha256(STAGE_DEDUP + ":" + keepId + ":" + dropId);
                        if (decisionExists(candidateHash)) {
                            continue; // 幂等：同一候选对不重复记账
                        }

                        PolicyGate gate = applyPolicyGate(action, confidence, risk);

                        Map<String, Object> finding = new LinkedHashMap<>();
                        finding.put("keep_id", keepId);
                        finding.put("drop_id", dropId);
                        finding.put("similarity", round4(score));
                        finding.put("reason", reason);
                        finding.put("merge_info", mergeInfo);

                        insertDecision(candidateHash, action, keepId, dropId, confidence, risk,
                                gate, finding, item, batchId, jobId);
                        batchDecisions++;
                        decisionCount++;
                    }
                    finishBatch(batchId, batchFindings, batchDecisions, null);
                } catch (Exception e) {
                    log.warn("策展批次 {} 失败: {}", batchIndex, e.getMessage());
                    errors.add("batch_" + batchIndex + ":" + e.getMessage());
                    finishBatch(batchId, batchFindings, batchDecisions, e.getMessage());
                }
                batchIndex++;
            }
            findingCount = decisionCount;

            Map<String, Object> summary = new LinkedHashMap<>();
            summary.put("stage", STAGE_DEDUP);
            summary.put("candidate_count", candidateCount);
            summary.put("pair_count", pairCount);
            summary.put("finding_count", findingCount);
            summary.put("decision_count", decisionCount);
            summary.put("batch_count", batchIndex);
            summary.put("sim_threshold", simThreshold);
            summary.put("implemented_stages", List.of(STAGE_DEDUP));
            summary.put("pending_stages", List.of("contradiction", "split", "link", "importance"));
            markJobFinished(jobId, summary, errors, t0);
            return summary;

        } catch (Exception e) {
            log.error("策展作业 {} 执行失败", jobId, e);
            errors.add("fatal:" + e.getMessage());
            Map<String, Object> summary = new LinkedHashMap<>();
            summary.put("stage", STAGE_DEDUP);
            summary.put("candidate_count", candidateCount);
            summary.put("pair_count", pairCount);
            summary.put("decision_count", decisionCount);
            summary.put("error", e.getMessage());
            markJobFailed(jobId, summary, errors, t0);
            return summary;
        }
    }

    // ==================== 策略门 ====================

    private record PolicyGate(String reviewStatus, String riskLevel, List<String> reasons) {
    }

    /**
     * 确定性策略门：LLM 只提供置信度与风险判断，采纳与否由此处规则裁决。
     * - 动作命中 manual_only_actions            → 一律 pending（必须人工确认）
     * - 置信度 ≥ auto_approve_confidence 且低风险 → auto_approved
     * - 置信度 ≥ review_confidence_threshold     → pending
     * - 否则                                     → rejected（置信度不足）
     */
    private PolicyGate applyPolicyGate(String action, double confidence, String risk) {
        Map<String, Object> gov = configStore.section("governance");
        double autoApprove = configStore.doubleVal(gov, "auto_approve_confidence", 0.8);
        double autoApproveLowRisk = configStore.doubleVal(gov, "auto_approve_low_risk_confidence", 0.7);
        double reviewThreshold = configStore.doubleVal(gov, "review_confidence_threshold", 0.55);
        List<String> manualOnly = asStringList(gov.get("manual_only_actions"));
        // merge 类动作同属人工审批范围（对齐既定治理策略：merge/split/mark_contradicted 走人工）
        List<String> mergeActions = asStringList(gov.get("merge_actions"));

        List<String> reasons = new ArrayList<>();
        if (manualOnly.contains(action)) {
            reasons.add("动作 " + action + " 属人工专属，强制进入待审");
            return new PolicyGate("pending", risk, reasons);
        }
        if (mergeActions.contains(action)) {
            reasons.add("动作 " + action + " 属合并类，需人工确认");
            return new PolicyGate("pending", risk, reasons);
        }
        if ("high".equalsIgnoreCase(risk)) {
            reasons.add("高风险动作需人工确认");
            return new PolicyGate("pending", "high", reasons);
        }
        if (confidence >= autoApprove && "low".equalsIgnoreCase(risk)) {
            reasons.add("置信度 " + round4(confidence) + " ≥ 自动采纳阈值 " + autoApprove + " 且低风险");
            return new PolicyGate("auto_approved", risk, reasons);
        }
        if (confidence >= autoApproveLowRisk && "low".equalsIgnoreCase(risk)) {
            reasons.add("低风险且置信度 " + round4(confidence) + " ≥ " + autoApproveLowRisk);
            return new PolicyGate("auto_approved", risk, reasons);
        }
        if (confidence >= reviewThreshold) {
            reasons.add("置信度 " + round4(confidence) + " 达待审阈值 " + reviewThreshold + "，交人工复核");
            return new PolicyGate("pending", risk, reasons);
        }
        reasons.add("置信度 " + round4(confidence) + " 低于待审阈值 " + reviewThreshold);
        return new PolicyGate("rejected", risk, reasons);
    }

    // ==================== 判官提示词 ====================

    private static final String JUDGE_SYSTEM =
            "You are a careful memory curator. Mark a pair as duplicate only when both memories express " +
            "the same fact with no additional unique information in either one. Partial overlap or related " +
            "topics are NOT duplicates. " +
            "Return a JSON object with key 'results': a list where each element has " +
            "'index' (int, matching the pair index given), 'is_duplicate' (bool), " +
            "'reason' (str, <=30 words), 'keep' (str, \"A\" or \"B\" — the memory to keep, or null if unsure), " +
            "'merge_info' (str, <=40 words; empty string if nothing needs merging), " +
            "'confidence' (number 0..1), 'risk' (str, one of \"low\",\"medium\",\"high\"). " +
            "Be conservative: when uncertain return is_duplicate=false.";

    private String buildJudgePrompt(List<Object[]> batch, Map<String, Map<String, Object>> byId) {
        StringBuilder sb = new StringBuilder();
        sb.append("Compare the following memory pairs and judge which pairs are true duplicates.\n\n");
        for (int i = 0; i < batch.size(); i++) {
            Object[] p = batch.get(i);
            Map<String, Object> a = byId.get((String) p[0]);
            Map<String, Object> b = byId.get((String) p[1]);
            sb.append("=== Pair ").append(i).append(" (similarity ").append(round4((Double) p[2])).append(") ===\n");
            sb.append("A: ").append(truncate(str(a.get("title")), 200)).append("\n");
            sb.append("   ").append(truncate(str(a.get("content")), 600)).append("\n");
            sb.append("B: ").append(truncate(str(b.get("title")), 200)).append("\n");
            sb.append("   ").append(truncate(str(b.get("content")), 600)).append("\n\n");
        }
        return sb.toString();
    }

    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> parseJudgeResults(String raw) throws Exception {
        String cleaned = cleanJson(raw);
        Map<String, Object> parsed = new com.fasterxml.jackson.databind.ObjectMapper()
                .readValue(cleaned, new com.fasterxml.jackson.core.type.TypeReference<>() {
                });
        Object results = parsed.get("results");
        if (results instanceof List) {
            return (List<Map<String, Object>>) results;
        }
        return List.of();
    }

    private String cleanJson(String raw) {
        if (raw == null) {
            return "{}";
        }
        String s = raw.trim();
        if (s.startsWith("```")) {
            int nl = s.indexOf('\n');
            if (nl > 0) {
                s = s.substring(nl + 1);
            }
            int end = s.lastIndexOf("```");
            if (end > 0) {
                s = s.substring(0, end);
            }
        }
        int start = s.indexOf('{');
        int stop = s.lastIndexOf('}');
        if (start >= 0 && stop > start) {
            s = s.substring(start, stop + 1);
        }
        return s.trim();
    }

    // ==================== 持久化 ====================

    private void markJob(String jobId, String status, String progressJson) {
        jdbcClient.sql("UPDATE llm_curator_jobs SET status = :status, updated_at = clock_timestamp() WHERE id = :id")
                .param("status", status).param("id", jobId).update();
    }

    private void markJobFinished(String jobId, Map<String, Object> summary, List<String> errors, long t0) {
        String status = errors.isEmpty() ? "succeeded" : "succeeded_with_errors";
        // error_json 为 NOT NULL（默认 '{}'::jsonb），无错误时必须写空对象而非 NULL
        jdbcClient.sql("UPDATE llm_curator_jobs SET status = :status, summary_json = CAST(:summary AS jsonb), " +
                        "error_json = CAST(:errs AS jsonb), " +
                        "finished_at = clock_timestamp(), updated_at = clock_timestamp() WHERE id = :id")
                .param("status", status)
                .param("summary", toJson(summary))
                .param("errs", errors.isEmpty() ? "{}" : toJson(errors))
                .param("id", jobId).update();
    }

    private void markJobFailed(String jobId, Map<String, Object> summary, List<String> errors, long t0) {
        jdbcClient.sql("UPDATE llm_curator_jobs SET status = 'failed', summary_json = CAST(:summary AS jsonb), " +
                        "error_json = CAST(:errs AS jsonb), finished_at = clock_timestamp(), updated_at = clock_timestamp() " +
                        "WHERE id = :id")
                .param("summary", toJson(summary))
                .param("errs", toJson(errors))
                .param("id", jobId).update();
    }

    private void insertBatch(String batchId, String jobId, int index, int candidateCount) {
        jdbcClient.sql("INSERT INTO llm_curator_batches (id, job_id, stage, batch_index, status, candidate_count, " +
                        "started_at) VALUES (:id, :job, :stage, :idx, 'running', :cnt, clock_timestamp())")
                .param("id", batchId).param("job", jobId).param("stage", STAGE_DEDUP)
                .param("idx", index).param("cnt", candidateCount).update();
    }

    private void finishBatch(String batchId, int findings, int decisions, String error) {
        // error_json 为 NOT NULL（默认 '{}'::jsonb），无错误时写空对象
        jdbcClient.sql("UPDATE llm_curator_batches SET status = :status, finding_count = :f, decision_count = :d, " +
                        "error_json = CAST(:e AS jsonb), " +
                        "finished_at = clock_timestamp() WHERE id = :id")
                .param("status", error == null ? "done" : "failed")
                .param("f", findings).param("d", decisions)
                .param("e", error == null ? "{}" : toJson(Map.of("error", error)))
                .param("id", batchId).update();
    }

    private boolean decisionExists(String candidateHash) {
        Long n = jdbcClient.sql("SELECT COUNT(*) FROM governance_decisions WHERE candidate_hash = :h")
                .param("h", candidateHash).query(Long.class).single();
        return n != null && n > 0;
    }

    private void insertDecision(String candidateHash, String action, String keepId, String dropId,
                                double confidence, String risk, PolicyGate gate,
                                Map<String, Object> finding, Map<String, Object> rawItem,
                                String batchId, String jobId) {
        String id = "dec_" + UUID.randomUUID().toString().replace("-", "").substring(0, 16);
        Map<String, Object> before = new LinkedHashMap<>();
        before.put("keep_id", keepId);
        before.put("drop_id", dropId);
        Map<String, Object> after = new LinkedHashMap<>();
        after.put("archive_and_merge_duplicate".equals(action) ? "merged_into" : "archived", dropId);
        Map<String, Object> rollback = new LinkedHashMap<>();
        rollback.put("action", "restore_status");
        rollback.put("target_id", dropId);

        jdbcClient.sql("INSERT INTO governance_decisions (id, decision_type, source_ids_json, recommended_action, " +
                        "llm_confidence, risk_level, review_status, policy_reason, finding_json, llm_trace_json, " +
                        "before_state_json, after_state_json, rollback_json, source_agent, candidate_hash, " +
                        "policy_reasons_json, policy_version, judge_model, judge_schema_version, decision_version, " +
                        "curator_job_id, curator_batch_id, created_at, updated_at) VALUES (" +
                        ":id, :type, CAST(:src AS jsonb), :action, :conf, :risk, :review, :reason, CAST(:finding AS jsonb), " +
                        "CAST(:trace AS jsonb), CAST(:before AS jsonb), CAST(:after AS jsonb), CAST(:rollback AS jsonb), " +
                        "'llm_curator', :hash, CAST(:reasons AS jsonb), 'v1', :model, 'v1', 'v1', :job, :batch, " +
                        "clock_timestamp(), clock_timestamp())")
                .param("id", id)
                .param("type", STAGE_DEDUP)
                .param("src", toJson(List.of(keepId, dropId)))
                .param("action", action)
                .param("conf", confidence)
                .param("risk", gate.riskLevel())
                .param("review", gate.reviewStatus())
                .param("reason", String.join("; ", gate.reasons()))
                .param("finding", toJson(finding))
                .param("trace", toJson(rawItem))
                .param("before", toJson(before))
                .param("after", toJson(after))
                .param("rollback", toJson(rollback))
                .param("hash", candidateHash)
                .param("reasons", toJson(gate.reasons()))
                .param("model", configStore.str(configStore.section("extraction"), "model", "unknown"))
                .param("job", jobId)
                .param("batch", batchId)
                .update();
    }

    // ==================== 工具 ====================

    private String toVectorLiteral(float[] vec) {
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < vec.length; i++) {
            if (i > 0) sb.append(',');
            sb.append(vec[i]);
        }
        return sb.append(']').toString();
    }

    private String str(Object o) {
        return o == null ? "" : String.valueOf(o);
    }

    private double toDbl(Object o) {
        if (o instanceof Number n) return n.doubleValue();
        try {
            return o == null ? 0.0 : Double.parseDouble(String.valueOf(o));
        } catch (NumberFormatException e) {
            return 0.0;
        }
    }

    /** 风险等级归一化到 low / medium / high 三档；无法识别时返回 null 由调用方兜底 */
    private String normalizeRisk(Object raw) {
        if (raw == null) {
            return null;
        }
        String v = String.valueOf(raw).trim().toLowerCase();
        if (v.isEmpty()) {
            return null;
        }
        if (v.equals("low") || v.equals("none") || v.equals("nil") || v.equals("safe")
                || v.equals("minimal") || v.equals("trivial")) {
            return "low";
        }
        if (v.equals("high") || v.equals("critical") || v.equals("severe")) {
            return "high";
        }
        if (v.equals("medium") || v.equals("moderate") || v.equals("mid")) {
            return "medium";
        }
        return null;
    }

    private double round4(double v) {
        return Math.round(v * 10000.0) / 10000.0;
    }

    private String truncate(String s, int max) {
        if (s == null) return "";
        return s.length() <= max ? s : s.substring(0, max) + "...";
    }

    @SuppressWarnings("unchecked")
    private List<String> asStringList(Object o) {
        if (o instanceof List) {
            List<String> out = new ArrayList<>();
            for (Object v : (List<Object>) o) {
                out.add(String.valueOf(v));
            }
            return out;
        }
        return List.of();
    }

    private String sha256(String input) {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] d = md.digest(input.getBytes(StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder();
            for (byte b : d) {
                sb.append(String.format("%02x", b));
            }
            return sb.toString();
        } catch (Exception e) {
            return Integer.toHexString(input.hashCode());
        }
    }

    private String toJson(Object o) {
        try {
            return new com.fasterxml.jackson.databind.ObjectMapper().writeValueAsString(o);
        } catch (Exception e) {
            return "null";
        }
    }
}
