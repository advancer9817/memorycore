package org.mcore.storage.service;

import org.mcore.common.model.MemoryDO;
import org.mcore.storage.config.ConfigFileStore;
import org.mcore.storage.entity.EntityIndexService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.temporal.ChronoUnit;
import java.util.*;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 规则策展引擎（对标 Python `memorycore/storage/curator.py`，427 行）。
 *
 * 记忆保留策略（v3 — 证据驱动的生命周期）：
 * - 高价值类型（user_profile / environment_fact / decision / project_memory /
 *   skill_candidate）**永不自动 stale**，除非 feedback < -2.0 且 importance < 0.3
 * - candidate 窗口按类型分层：episodic 7 天 / precious 30 天 / 其他 7 天
 * - candidate → active 晋升：importance ≥ 0.75 且 feedback ≥ 0，或 injected_count ≥ 3
 * - stale → active 复活：近 7 天内被注入且有效且无负反馈
 * - contradicted 自动归档：90 天未访问
 * - decay_policy：review 慢衰减 / stable 不衰减 / freeze 完全跳过
 *
 * Java 迁移后该能力**整体缺失** —— `rule_curator` 的 25 个配置参数中有 22 个
 * 从未被任何代码消费，属"配置文件看起来在工作、实际不起作用"的静默失效。
 */
@Service
public class RuleCuratorService {

    private static final Logger log = LoggerFactory.getLogger(RuleCuratorService.class);

    private static final int UNUSED_STALE_DAYS = 30;
    private static final int UNUSED_FRAGMENT_STALE_DAYS = 7;
    private static final Set<String> FRAGMENT_SOURCES = Set.of("atomizer", "governance_split");
    private static final Pattern TITLE_TOKENS = Pattern.compile("[\\w\\u4e00-\\u9fff]+");

    private final JdbcClient jdbcClient;
    private final ConfigFileStore configStore;
    private final EntityIndexService entityIndexService;

    public RuleCuratorService(JdbcClient jdbcClient, ConfigFileStore configStore,
                              EntityIndexService entityIndexService) {
        this.jdbcClient = jdbcClient;
        this.configStore = configStore;
        this.entityIndexService = entityIndexService;
    }

    /** 标题归一（对标 Python `normalize_title_key`） */
    static String normalizeTitleKey(String title) {
        if (title == null || title.isEmpty()) {
            return "";
        }
        Matcher m = TITLE_TOKENS.matcher(title.toLowerCase(Locale.ROOT));
        List<String> toks = new ArrayList<>();
        while (m.find()) {
            toks.add(m.group());
        }
        String joined = String.join(" ", toks);
        return joined.length() > 120 ? joined.substring(0, 120) : joined;
    }

    /**
     * 生成/执行策展报告。
     *
     * @param dryRun           true 只报告不改动（默认）
     * @param limit            扫描上限，<=0 表示不设上限
     * @param staleAfterDays   通用 stale 阈值天数
     * @param archiveAfterDays 通用 archive 阈值天数
     */
    public Map<String, Object> report(boolean dryRun, int limit, int staleAfterDays,
                                      int archiveAfterDays, List<String> allowActions,
                                      List<String> denyActions) {
        Instant now = Instant.now();
        long cap = limit > 0 ? limit : 1_000_000L;

        Map<String, Object> cfg = configStore.section("rule_curator");
        double decayStep = num(cfg, "decay_step", 0.05);
        int decayIntervalDays = (int) num(cfg, "decay_interval_days", 30);
        double decayMinConfidence = num(cfg, "decay_min_confidence", 0.15);
        int candTtlEpisodic = (int) num(cfg, "candidate_ttl_episodic_days", 7);
        int candTtlPrecious = (int) num(cfg, "candidate_ttl_precious_days", 30);
        int candTtlDefault = (int) num(cfg, "candidate_ttl_default_days", 7);
        int staleDaysEpisodic = (int) num(cfg, "stale_days_episodic", 14);
        int archiveDaysEpisodic = (int) num(cfg, "archive_days_episodic", 30);
        int contradictedArchiveDays = (int) num(cfg, "contradicted_archive_days", 90);
        int neverAccessedDays = (int) num(cfg, "never_accessed_candidate_days", 14);
        double promoteImportance = num(cfg, "promote_importance_threshold", 0.75);
        int promoteInjected = (int) num(cfg, "promote_injected_threshold", 3);
        Set<String> preciousTypes = new HashSet<>(strList(cfg.get("precious_types"),
                List.of("user_profile", "environment_fact", "decision", "project_memory", "skill_candidate")));
        double staleImportance = num(cfg, "stale_importance_threshold", 0.45);
        double staleFeedback = num(cfg, "stale_feedback_threshold", -0.5);
        double preciousStaleFb = num(cfg, "precious_stale_feedback", -2.0);
        double preciousStaleImp = num(cfg, "precious_stale_importance", 0.3);
        int revivalWindowDays = (int) num(cfg, "revival_window_days", 7);
        double revivalEffMin = num(cfg, "revival_effectiveness_min", 0.5);
        double revivalFbMin = num(cfg, "revival_feedback_min", 0.0);
        double skillImp = num(cfg, "skill_promote_importance", 0.65);
        double skillFbMin = num(cfg, "skill_promote_feedback_min", 0.0);

        // SELECT * 会带出 ARRAY / vector 等驱动对象：tags(text[]) 与 embedding(vector)
        // 若不经规范化直接序列化，Jackson 会 introspect 出连接内部结构
        // （resultSet→statement→connection），既泄漏信息又产出非法 JSON。
        // 此处统一走 JsonbRows 规范化，并剔除 embedding（1024 维向量对调用方无意义且体积巨大）。
        List<Map<String, Object>> allRows = new ArrayList<>();
        for (Map<String, Object> raw : jdbcClient.sql(
                        "SELECT * FROM memories ORDER BY updated_at DESC LIMIT :cap")
                .param("cap", cap).query().listOfRows()) {
            Map<String, Object> norm = org.mcore.storage.util.JsonbRows.row(raw);
            norm.remove("embedding");
            allRows.add(norm);
        }

        Instant decayCutoff = now.minus(decayIntervalDays, ChronoUnit.DAYS);
        Instant episodicStaleCutoff = now.minus(staleDaysEpisodic, ChronoUnit.DAYS);
        Instant episodicArchiveCutoff = now.minus(archiveDaysEpisodic, ChronoUnit.DAYS);
        Instant episodicCandCutoff = now.minus(candTtlEpisodic, ChronoUnit.DAYS);
        Instant preciousCandCutoff = now.minus(candTtlPrecious, ChronoUnit.DAYS);
        Instant defaultCandCutoff = now.minus(candTtlDefault, ChronoUnit.DAYS);
        Instant neverAccessedCutoff = now.minus(neverAccessedDays, ChronoUnit.DAYS);
        Instant staleCutoff = now.minus(Math.max(1, staleAfterDays), ChronoUnit.DAYS);
        Instant archiveCutoff = now.minus(Math.max(1, archiveAfterDays), ChronoUnit.DAYS);
        Instant contradictedCutoff = now.minus(contradictedArchiveDays, ChronoUnit.DAYS);
        Instant revivalCutoff = now.minus(revivalWindowDays, ChronoUnit.DAYS);
        Instant unusedCutoff = now.minus(UNUSED_STALE_DAYS, ChronoUnit.DAYS);
        Instant fragmentCutoff = now.minus(UNUSED_FRAGMENT_STALE_DAYS, ChronoUnit.DAYS);

        Map<String, List<Map<String, Object>>> byTitle = new LinkedHashMap<>();
        List<Map<String, Object>> lowFeedback = new ArrayList<>();
        List<Map<String, Object>> autoDecay = new ArrayList<>();
        List<Map<String, Object>> episodicStale = new ArrayList<>();
        List<Map<String, Object>> episodicArchive = new ArrayList<>();
        List<Map<String, Object>> deadEpisodic = new ArrayList<>();
        List<Map<String, Object>> deadPrecious = new ArrayList<>();
        List<Map<String, Object>> deadDefault = new ArrayList<>();
        List<Map<String, Object>> neverAccessed = new ArrayList<>();
        List<Map<String, Object>> staleCands = new ArrayList<>();
        List<Map<String, Object>> preciousStale = new ArrayList<>();
        List<Map<String, Object>> archiveCands = new ArrayList<>();
        List<Map<String, Object>> contradictedArchive = new ArrayList<>();
        List<Map<String, Object>> revivalCands = new ArrayList<>();
        List<Map<String, Object>> promoteCands = new ArrayList<>();
        List<Map<String, Object>> skillPromotions = new ArrayList<>();
        List<Map<String, Object>> unusedActive = new ArrayList<>();
        List<Map<String, Object>> unusedFragment = new ArrayList<>();

        for (Map<String, Object> r : allRows) {
            String typ = str(r.get("type"));
            String status = str(r.get("status"));
            double importance = dbl(r.get("importance"), 0.5);
            double feedback = dbl(r.get("feedback_score"), 0.0);
            double confidence = dbl(r.get("confidence"), 0.7);
            String decay = str(r.get("decay_policy"));
            if (decay.isEmpty()) {
                decay = "review";
            }
            Instant updated = ts(r.get("updated_at"));
            Instant lastAccessed = ts(r.get("last_accessed_at"));
            int injected = (int) dbl(r.get("injected_count"), 0);
            double effectiveness = dbl(r.get("effectiveness_score"), 0.5);
            String content = str(r.get("content"));
            Instant lastInjected = ts(r.get("last_injected_at"));
            Instant created = ts(r.get("created_at"));

            String key = normalizeTitleKey(str(r.get("title")));
            if (!key.isEmpty()) {
                byTitle.computeIfAbsent(key, k -> new ArrayList<>()).add(r);
            }

            if ("freeze".equals(decay)) {
                continue;
            }

            if (("active".equals(status) || "candidate".equals(status))
                    && feedback < -1.0 && !preciousTypes.contains(typ)) {
                lowFeedback.add(r);
            }

            if ("active".equals(status) && "review".equals(decay)
                    && (lastAccessed == null || lastAccessed.isBefore(decayCutoff))
                    && effectiveness < 0.3 && importance < 0.5
                    && injected > 0 && confidence > decayMinConfidence) {
                autoDecay.add(r);
            }

            if ("episodic_memory".equals(typ)) {
                if ("active".equals(status) && before(updated, episodicStaleCutoff) && importance < 0.65) {
                    episodicStale.add(r);
                }
                if ("stale".equals(status) && before(updated, episodicArchiveCutoff)) {
                    episodicArchive.add(r);
                }
                if ("candidate".equals(status) && before(updated, episodicCandCutoff) && importance < 0.65) {
                    deadEpisodic.add(r);
                }
            }

            if ("candidate".equals(status)) {
                if (preciousTypes.contains(typ)) {
                    if (before(updated, preciousCandCutoff) && importance < 0.4 && feedback < 0) {
                        deadPrecious.add(r);
                    }
                } else if (!"episodic_memory".equals(typ)) {
                    if (before(updated, defaultCandCutoff) && importance < 0.5) {
                        deadDefault.add(r);
                    }
                }
                if (lastAccessed == null && injected == 0
                        && before(updated, neverAccessedCutoff) && !preciousTypes.contains(typ)) {
                    neverAccessed.add(r);
                }
                if ((importance >= promoteImportance && feedback >= 0) || injected >= promoteInjected) {
                    promoteCands.add(r);
                }
            }

            if ("active".equals(status) && !preciousTypes.contains(typ) && !"episodic_memory".equals(typ)
                    && before(updated, staleCutoff) && importance < staleImportance
                    && feedback <= staleFeedback && !"freeze".equals(decay) && !"stable".equals(decay)) {
                staleCands.add(r);
            }

            if ("active".equals(status) && injected == 0 && !preciousTypes.contains(typ)
                    && importance < 0.9 && before(updated, unusedCutoff)
                    && !"freeze".equals(decay) && !"stable".equals(decay)) {
                unusedActive.add(r);
            }

            String source = str(r.get("source"));
            if ("active".equals(status) && injected == 0 && FRAGMENT_SOURCES.contains(source)
                    && before(created, fragmentCutoff)
                    && !"freeze".equals(decay) && !"stable".equals(decay)) {
                unusedFragment.add(r);
            }

            if ("active".equals(status) && preciousTypes.contains(typ)
                    && feedback < preciousStaleFb && importance < preciousStaleImp
                    && !"freeze".equals(decay) && !"stable".equals(decay)) {
                preciousStale.add(r);
            }

            if ("stale".equals(status) && !"episodic_memory".equals(typ) && before(updated, archiveCutoff)) {
                archiveCands.add(r);
            }

            if ("contradicted".equals(status) && (lastAccessed == null || lastAccessed.isBefore(contradictedCutoff))) {
                contradictedArchive.add(r);
            }

            if ("stale".equals(status) && !"episodic_memory".equals(typ)
                    && lastInjected != null && !lastInjected.isBefore(revivalCutoff)
                    && effectiveness >= revivalEffMin && feedback >= revivalFbMin) {
                revivalCands.add(r);
            }

            if ("skill_candidate".equals(typ) && ("active".equals(status) || "candidate".equals(status))
                    && importance >= skillImp && feedback >= skillFbMin) {
                skillPromotions.add(r);
            }
        }

        // 重复标题分组
        List<List<Map<String, Object>>> duplicateGroups = new ArrayList<>();
        for (Map.Entry<String, List<Map<String, Object>>> e : byTitle.entrySet()) {
            if (!e.getKey().isEmpty() && e.getValue().size() > 1) {
                duplicateGroups.add(e.getValue());
            }
        }

        List<Map<String, Object>> deadCandidates = new ArrayList<>();
        deadCandidates.addAll(deadEpisodic);
        deadCandidates.addAll(deadPrecious);
        deadCandidates.addAll(deadDefault);

        // 取代候选：同标题/类型/scope/项目下存在更新的 active 记录（仅报告，不自动执行）
        List<Map<String, Object>> supersession = new ArrayList<>();
        for (List<Map<String, Object>> group : duplicateGroups) {
            List<Map<String, Object>> activeGroup = new ArrayList<>();
            for (Map<String, Object> r : group) {
                if ("active".equals(str(r.get("status")))) {
                    activeGroup.add(r);
                }
            }
            if (activeGroup.size() < 2) {
                continue;
            }
            Map<String, List<Map<String, Object>>> buckets = new LinkedHashMap<>();
            for (Map<String, Object> row : activeGroup) {
                String bk = str(row.get("type")) + "\u0001" + defaultScope(row) + "\u0001" + str(row.get("project_path"));
                buckets.computeIfAbsent(bk, k -> new ArrayList<>()).add(row);
            }
            for (List<Map<String, Object>> bucket : buckets.values()) {
                if (bucket.size() < 2) {
                    continue;
                }
                bucket.sort((a, b) -> {
                    Instant ia = a.get("updated_at") != null ? ts(a.get("updated_at")) : ts(a.get("created_at"));
                    Instant ib = b.get("updated_at") != null ? ts(b.get("updated_at")) : ts(b.get("created_at"));
                    if (ia == null && ib == null) return 0;
                    if (ia == null) return 1;
                    if (ib == null) return -1;
                    return ib.compareTo(ia);
                });
                Map<String, Object> survivor = bucket.get(0);
                for (int i = 1; i < bucket.size(); i++) {
                    Map<String, Object> old = bucket.get(i);
                    boolean isPrecious = preciousTypes.contains(str(old.get("type")));
                    Map<String, Object> item = new LinkedHashMap<>();
                    item.put("old_id", old.get("id"));
                    item.put("new_id", survivor.get("id"));
                    item.put("title", old.get("title"));
                    item.put("type", old.get("type"));
                    item.put("scope", old.get("scope"));
                    item.put("project_path", old.get("project_path"));
                    item.put("reason", "same_title_type_scope_project_newer_active_record");
                    item.put("review_required", isPrecious || dbl(old.get("importance"), 0) >= 0.7);
                    item.put("action", "supersede_candidate");
                    supersession.add(item);
                }
            }
        }

        // 矛盾候选：同一标题键下同时存在 active 与 contradicted
        Map<String, List<Map<String, Object>>> activeByKey = new LinkedHashMap<>();
        Map<String, List<Map<String, Object>>> contradictedByKey = new LinkedHashMap<>();
        for (Map<String, Object> r : allRows) {
            String k = normalizeTitleKey(str(r.get("title")));
            if (k.isEmpty()) {
                continue;
            }
            if ("active".equals(str(r.get("status")))) {
                activeByKey.computeIfAbsent(k, x -> new ArrayList<>()).add(r);
            } else if ("contradicted".equals(str(r.get("status")))) {
                contradictedByKey.computeIfAbsent(k, x -> new ArrayList<>()).add(r);
            }
        }
        List<Map<String, Object>> contradictions = new ArrayList<>();
        for (Map.Entry<String, List<Map<String, Object>>> e : activeByKey.entrySet()) {
            if (contradictedByKey.containsKey(e.getKey())) {
                Map<String, Object> item = new LinkedHashMap<>();
                item.put("title_key", e.getKey());
                item.put("active", e.getValue());
                item.put("contradicted", contradictedByKey.get(e.getKey()));
                contradictions.add(item);
            }
        }

        // ── 动作计划（优先级顺序 + 首命中胜出）────────────────────────────
        Set<String> allowSet = new HashSet<>(allowActions == null ? List.of() : allowActions);
        Set<String> denySet = new HashSet<>(denyActions == null ? List.of() : denyActions);
        List<Map<String, Object>> actionPlan = new ArrayList<>();
        Set<String> plannedIds = new HashSet<>();

        planAll(actionPlan, plannedIds, revivalCands, "revive", "stale_revival", "active", allowSet, denySet);
        planAll(actionPlan, plannedIds, promoteCands, "promote", "high_importance_candidate", "active", allowSet, denySet);
        planAll(actionPlan, plannedIds, lowFeedback, "mark_stale", "low_feedback", "stale", allowSet, denySet);
        planAll(actionPlan, plannedIds, preciousStale, "mark_stale", "precious_negative_feedback", "stale", allowSet, denySet);
        planAll(actionPlan, plannedIds, episodicStale, "mark_stale", "episodic_aged", "stale", allowSet, denySet);
        planAll(actionPlan, plannedIds, staleCands, "mark_stale", "stale_candidate", "stale", allowSet, denySet);
        planAll(actionPlan, plannedIds, episodicArchive, "archive", "episodic_archive", "archived", allowSet, denySet);
        planAll(actionPlan, plannedIds, archiveCands, "archive", "archive_candidate", "archived", allowSet, denySet);
        planAll(actionPlan, plannedIds, deadCandidates, "archive", "dead_candidate", "archived", allowSet, denySet);
        planAll(actionPlan, plannedIds, neverAccessed, "archive", "never_accessed_candidate", "archived", allowSet, denySet);
        planAll(actionPlan, plannedIds, unusedActive, "mark_stale", "unused_30_days", "stale", allowSet, denySet);
        planAll(actionPlan, plannedIds, unusedFragment, "mark_stale", "unused_fragment_14_days", "stale", allowSet, denySet);
        planAll(actionPlan, plannedIds, contradictedArchive, "archive", "contradicted_expired", "archived", allowSet, denySet);

        List<Map<String, Object>> actions = new ArrayList<>();
        int decayApplied = 0;

        if (!dryRun) {
            // 1) 置信度衰减
            if (!autoDecay.isEmpty()) {
                Instant ts = Instant.now();
                for (Map<String, Object> r : autoDecay) {
                    double cur = dbl(r.get("confidence"), 0.7);
                    double next = Math.max(decayMinConfidence, round3(cur - decayStep));
                    jdbcClient.sql("UPDATE memories SET confidence = :c, updated_at = :ts WHERE id = :id")
                            .param("c", next).param("ts", java.sql.Timestamp.from(ts))
                            .param("id", String.valueOf(r.get("id"))).update();
                    decayApplied++;
                }
            }

            // 2) 历史事件清理
            jdbcClient.sql("DELETE FROM context_quality_events WHERE created_at < now() - interval '90 days'").update();
            jdbcClient.sql("DELETE FROM audit_events WHERE created_at < now() - interval '180 days'").update();

            // 3) 批量状态迁移
            Instant ts = Instant.now();
            int applied = 0;
            for (Map<String, Object> planned : actionPlan) {
                String id = String.valueOf(planned.get("id"));
                String target = "promote".equals(planned.get("action")) || "revive".equals(planned.get("action"))
                        ? "active" : String.valueOf(planned.get("target_status"));
                int n = jdbcClient.sql("UPDATE memories SET status = :s, updated_at = :ts WHERE id = :id AND status <> :s")
                        .param("s", target).param("ts", java.sql.Timestamp.from(ts)).param("id", id).update();
                if (n > 0) {
                    applied++;
                    resyncEntities(id);
                }
                Map<String, Object> a = new LinkedHashMap<>();
                a.put("id", id);
                a.put("action", planned.get("action"));
                a.put("title", planned.get("title"));
                actions.add(a);
            }

            // 4) 汇总审计
            Map<String, Object> detail = new LinkedHashMap<>();
            detail.put("stale", countAction(actions, "mark_stale"));
            detail.put("archived", countAction(actions, "archive"));
            detail.put("promoted", countAction(actions, "promote"));
            detail.put("revived", countAction(actions, "revive"));
            detail.put("auto_decay", decayApplied);
            detail.put("total_actions", actions.size());
            detail.put("applied", applied);
            try {
                jdbcClient.sql("INSERT INTO audit_events (id, event_type, memory_id, agent, detail_json, created_at) " +
                                "VALUES (:id, 'curator_apply', NULL, 'rule_curator', CAST(:d AS jsonb), clock_timestamp())")
                        .param("id", "a_" + UUID.randomUUID().toString().replace("-", "").substring(0, 16))
                        .param("d", toJson(detail)).update();
            } catch (Exception e) {
                log.warn("策展审计事件写入失败: {}", e.getMessage());
            }
        }

        List<Map<String, Object>> allStale = new ArrayList<>();
        allStale.addAll(staleCands);
        allStale.addAll(episodicStale);
        allStale.addAll(preciousStale);
        List<Map<String, Object>> allArchive = new ArrayList<>();
        allArchive.addAll(archiveCands);
        allArchive.addAll(episodicArchive);
        allArchive.addAll(contradictedArchive);

        Map<String, Object> summary = new LinkedHashMap<>();
        summary.put("scanned", allRows.size());
        summary.put("duplicates", duplicateGroups.size());
        summary.put("low_feedback", lowFeedback.size());
        summary.put("stale", allStale.size());
        summary.put("archive", allArchive.size() + deadCandidates.size() + neverAccessed.size());
        summary.put("contradictions", contradictions.size());
        summary.put("supersession_candidates", supersession.size());
        summary.put("skill_promotions", skillPromotions.size());
        summary.put("auto_decay_candidates", autoDecay.size());
        summary.put("auto_decay_applied", decayApplied);
        summary.put("promote_candidates", promoteCands.size());
        summary.put("revival_candidates", revivalCands.size());
        summary.put("unused_fragment_candidates", unusedFragment.size());
        summary.put("planned_actions", actionPlan.size());
        summary.put("actions", actions.size());

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("dry_run", dryRun);
        out.put("generated_at", Instant.now().toString());
        out.put("scanned", allRows.size());
        out.put("summary", summary);
        out.put("action_plan", actionPlan);
        out.put("actions", actions);
        out.put("stale_candidates", allStale);
        out.put("archive_candidates", allArchive);
        out.put("never_accessed_candidates", neverAccessed);
        out.put("unused_fragment_candidates", unusedFragment);
        out.put("contradiction_candidates", contradictions);
        out.put("supersession_candidates", supersession);
        out.put("skill_promotion_candidates", skillPromotions);
        out.put("auto_decay_candidates", autoDecay);
        out.put("promote_candidates", promoteCands);
        out.put("revival_candidates", revivalCands);
        out.put("low_feedback_candidates", lowFeedback);
        return out;
    }

    private void planAll(List<Map<String, Object>> plan, Set<String> plannedIds,
                         List<Map<String, Object>> rows, String action, String reason,
                         String targetStatus, Set<String> allowSet, Set<String> denySet) {
        for (Map<String, Object> row : rows) {
            String id = String.valueOf(row.get("id"));
            if (plannedIds.contains(id)) {
                continue;
            }
            if (!allowSet.isEmpty() && !allowSet.contains(action)) {
                continue;
            }
            if (denySet.contains(action)) {
                continue;
            }
            plannedIds.add(id);
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("id", id);
            item.put("action", action);
            item.put("title", row.get("title"));
            item.put("reason", reason);
            item.put("target_status", targetStatus);
            Map<String, Object> rb = new LinkedHashMap<>();
            rb.put("status", row.get("status"));
            item.put("rollback", rb);
            plan.add(item);
        }
    }

    /** 状态变更后重算实体索引（非 active 记忆不应再被 entity_search 召回） */
    private void resyncEntities(String memoryId) {
        try {
            MemoryDO m = jdbcClient.sql(
                            "SELECT id, title, content, status, tags::text AS tags_json, project_path " +
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
        } catch (Exception e) {
            log.warn("策展状态变更后实体索引同步失败: id={} err={}", memoryId, e.getMessage());
        }
    }

    private int countAction(List<Map<String, Object>> actions, String action) {
        int n = 0;
        for (Map<String, Object> a : actions) {
            if (action.equals(a.get("action"))) {
                n++;
            }
        }
        return n;
    }

    // ---------- 取值工具 ----------

    private String defaultScope(Map<String, Object> row) {
        String s = str(row.get("scope"));
        return s.isEmpty() ? "global" : s;
    }

    private static boolean before(Instant a, Instant b) {
        // 时间缺失时视为不满足"早于"（保守：不触发生命周期变更）
        return a != null && a.isBefore(b);
    }

    private static String str(Object v) {
        return v == null ? "" : String.valueOf(v);
    }

    private static double dbl(Object v, double dflt) {
        if (v instanceof Number n) {
            return n.doubleValue();
        }
        if (v == null) {
            return dflt;
        }
        try {
            return Double.parseDouble(String.valueOf(v));
        } catch (Exception e) {
            return dflt;
        }
    }

    private static double num(Map<String, Object> m, String k, double dflt) {
        return m == null ? dflt : dbl(m.get(k), dflt);
    }

    private static double round3(double v) {
        return Math.round(v * 1000.0) / 1000.0;
    }

    private static Instant ts(Object v) {
        if (v == null) {
            return null;
        }
        if (v instanceof OffsetDateTime odt) {
            return odt.toInstant();
        }
        if (v instanceof java.sql.Timestamp t) {
            return t.toInstant();
        }
        if (v instanceof java.util.Date d) {
            return d.toInstant();
        }
        String s = String.valueOf(v).trim();
        if (s.isEmpty()) {
            return null;
        }
        try {
            return OffsetDateTime.parse(s).toInstant();
        } catch (Exception ignored) {
            // 继续尝试其他格式
        }
        try {
            return Instant.parse(s);
        } catch (Exception ignored) {
            return null;
        }
    }

    private static List<String> strList(Object v, List<String> dflt) {
        if (v instanceof List<?> list) {
            List<String> out = new ArrayList<>();
            for (Object o : list) {
                if (o != null && !String.valueOf(o).isBlank()) {
                    out.add(String.valueOf(o).trim());
                }
            }
            return out.isEmpty() ? dflt : out;
        }
        return dflt;
    }

    private String toJson(Object o) {
        try {
            return new com.fasterxml.jackson.databind.ObjectMapper().writeValueAsString(o);
        } catch (Exception e) {
            return "{}";
        }
    }
}
