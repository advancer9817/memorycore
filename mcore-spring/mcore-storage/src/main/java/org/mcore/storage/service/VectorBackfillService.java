package org.mcore.storage.service;

import org.mcore.storage.embedding.EmbeddingService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

import java.util.*;

/**
 * 向量回填服务。
 *
 * 背景：嵌入服务长期降级为 SHA-256 伪哈希（ollama 未运行），库中向量不含语义信息。
 * 恢复真实嵌入后，必须把存量哈希向量重新计算，否则新旧向量处于不同空间、检索结果错乱。
 *
 * 识别方法（判定性，非猜测）：
 *   对每条记忆按同一文本拼接规则重算哈希向量，与库中存储向量比对；
 *   余弦 > 0.999 即判定为哈希降级产物 —— 真实语义向量不可能与哈希向量高度吻合。
 *
 * 文本拼接规则与 EmbeddingService 保持一致：title + " " + content
 * （已实测：Python 与 Java 哈希实现对同一文本产出完全相同的向量，cos = 1.0）
 */
@Service
public class VectorBackfillService {

    private static final Logger log = LoggerFactory.getLogger(VectorBackfillService.class);

    /** 判定阈值：哈希向量与自身重算结果应近乎完全一致 */
    private static final double HASH_MATCH_THRESHOLD = 0.999;

    private final JdbcClient jdbcClient;
    private final EmbeddingService embeddingService;

    public VectorBackfillService(JdbcClient jdbcClient, EmbeddingService embeddingService) {
        this.jdbcClient = jdbcClient;
        this.embeddingService = embeddingService;
    }

    /** 统计待回填规模（抽样检测，避免全表遍历过慢） */
    public Map<String, Object> detect(int sampleSize) {
        int limit = Math.max(1, Math.min(sampleSize, 2000));
        List<Map<String, Object>> rows = jdbcClient.sql(
                        "SELECT id, title, content, embedding::text AS vec FROM memories " +
                        "WHERE content IS NOT NULL AND btrim(content) <> '' " +
                        "ORDER BY id LIMIT :limit")
                .param("limit", limit).query().listOfRows();

        int hashingDerived = 0;
        int semantic = 0;
        int nullEmbedding = 0;
        int unknown = 0;
        for (Map<String, Object> row : rows) {
            String text = buildText(row);
            if (text.isBlank()) {
                unknown++;
                continue;
            }
            float[] stored = row.get("vec") == null ? null : parseVector(String.valueOf(row.get("vec")));
            if (stored == null) {
                nullEmbedding++;   // 从未生成过向量（历史欠账），同样需要回填
                continue;
            }
            float[] hash = embeddingService.embedHashing(text, stored.length);
            double sim = cosine(hash, stored);
            if (sim > HASH_MATCH_THRESHOLD) {
                hashingDerived++;
            } else {
                semantic++;
            }
        }

        Long totalWith = jdbcClient.sql("SELECT COUNT(*) FROM memories WHERE embedding IS NOT NULL")
                .query(Long.class).single();
        Long totalNull = jdbcClient.sql("SELECT COUNT(*) FROM memories WHERE embedding IS NULL")
                .query(Long.class).single();

        Map<String, Object> res = new LinkedHashMap<>();
        res.put("sampled", rows.size());
        res.put("hashing_derived", hashingDerived);
        res.put("semantic", semantic);
        res.put("null_embedding", nullEmbedding);
        res.put("unknown", unknown);
        res.put("total_with_embedding", totalWith);
        res.put("total_null_embedding", totalNull);
        res.put("verdict", (hashingDerived + nullEmbedding) > semantic ? "degraded_hashing" : "semantic");
        return res;
    }

    /**
     * 分批回填。仅处理被判定为哈希降级产物的行；已是语义向量的行跳过（幂等）。
     *
     * @param batchSize 每批处理条数
     * @param maxRows   本次最多处理条数（防止单次请求过长）
     * @param dryRun    true 时只统计不写库
     */
    public Map<String, Object> backfill(int batchSize, int maxRows, boolean dryRun, int offset) {
        return backfill(batchSize, maxRows, dryRun, offset, null);
    }

    /**
     * 分批回填（可限定状态）。
     *
     * @param statusFilter 仅回填该状态的记忆；null/空表示全部。
     *                     用于优先补齐 active 行（检索正确性直接相关），
     *                     把 archived/superseded 等非检索行延后。
     */
    public Map<String, Object> backfill(int batchSize, int maxRows, boolean dryRun, int offset, String statusFilter) {
        int size = Math.max(1, Math.min(batchSize, 500));
        int cap = Math.max(1, Math.min(maxRows, 10000));
        int off = Math.max(0, offset);

        int scanned = 0;
        int reembedded = 0;
        int skippedSemantic = 0;
        int failed = 0;
        List<String> errors = new ArrayList<>();
        long t0 = System.currentTimeMillis();

        while (scanned < cap) {
            int take = Math.min(size, cap - scanned);
            boolean filterByStatus = statusFilter != null && !statusFilter.isBlank();
            String sqlText = "SELECT id, title, content, embedding::text AS vec FROM memories " +
                    "WHERE content IS NOT NULL AND btrim(content) <> '' " +
                    (filterByStatus ? "AND status = :status " : "") +
                    "ORDER BY id LIMIT :limit OFFSET :offset";
            var spec = jdbcClient.sql(sqlText);
            if (filterByStatus) {
                spec = spec.param("status", statusFilter);
            }
            List<Map<String, Object>> rows = spec
                    .param("limit", take).param("offset", off + scanned)
                    .query().listOfRows();
            if (rows.isEmpty()) {
                break;
            }

            // 第一遍：筛出需要重嵌入的行（哈希产物与 NULL 向量）
            List<String> ids = new ArrayList<>();
            List<String> texts = new ArrayList<>();
            for (Map<String, Object> row : rows) {
                scanned++;
                String text = buildText(row);
                if (text.isBlank()) {
                    continue;
                }
                try {
                    float[] stored = row.get("vec") == null ? null : parseVector(String.valueOf(row.get("vec")));
                    if (stored != null) {
                        // 已是语义向量则跳过（幂等）
                        float[] hash = embeddingService.embedHashing(text, stored.length);
                        if (cosine(hash, stored) <= HASH_MATCH_THRESHOLD) {
                            skippedSemantic++;
                            continue;
                        }
                    }
                    ids.add(String.valueOf(row.get("id")));
                    texts.add(text);
                } catch (Exception e) {
                    failed++;
                    if (errors.size() < 10) {
                        errors.add(String.valueOf(row.get("id")) + ":" + e.getMessage());
                    }
                }
            }

            if (dryRun) {
                reembedded += ids.size();
                continue;
            }
            if (ids.isEmpty()) {
                continue;
            }

            // 第二遍：批量嵌入后统一写回（单请求批量提交，避免逐条 HTTP 往返）
            List<float[]> vecs;
            try {
                vecs = embeddingService.embedBatch(texts);
            } catch (Exception e) {
                failed += ids.size();
                if (errors.size() < 10) {
                    errors.add("batch_embed:" + e.getMessage());
                }
                continue;
            }
            for (int i = 0; i < ids.size(); i++) {
                float[] vec = i < vecs.size() ? vecs.get(i) : null;
                if (vec == null || vec.length == 0) {
                    failed++;
                    if (errors.size() < 10) {
                        errors.add(ids.get(i) + ":empty_vector");
                    }
                    continue;
                }
                try {
                    jdbcClient.sql("UPDATE memories SET embedding = CAST(:vec AS vector) WHERE id = :id")
                            .param("vec", toVectorLiteral(vec))
                            .param("id", ids.get(i))
                            .update();
                    reembedded++;
                } catch (Exception e) {
                    failed++;
                    if (errors.size() < 10) {
                        errors.add(ids.get(i) + ":" + e.getMessage());
                    }
                }
            }

            if (rows.size() < take) {
                break;
            }
        }

        Map<String, Object> res = new LinkedHashMap<>();
        res.put("scanned", scanned);
        res.put("reembedded", reembedded);
        res.put("skipped_already_semantic", skippedSemantic);
        res.put("failed", failed);
        res.put("dry_run", dryRun);
        res.put("elapsed_s", Math.round((System.currentTimeMillis() - t0) / 100.0) / 10.0);
        res.put("real_model_online", embeddingService.isRealModelOnline());
        res.put("status_filter", statusFilter == null || statusFilter.isBlank() ? null : statusFilter);
        if (!errors.isEmpty()) {
            res.put("errors", errors);
        }
        log.info("向量回填: 扫描 {} 条, 重嵌入 {} 条, 跳过语义向量 {} 条, 失败 {} 条",
                scanned, reembedded, skippedSemantic, failed);
        return res;
    }

    // ==================== 工具 ====================

    private String buildText(Map<String, Object> row) {
        String title = row.get("title") == null ? "" : String.valueOf(row.get("title"));
        String content = row.get("content") == null ? "" : String.valueOf(row.get("content"));
        return (title + " " + content).trim();
    }

    private float[] parseVector(String text) {
        if (text == null || text.isBlank()) {
            return null;
        }
        String s = text.trim();
        if (s.startsWith("[")) {
            s = s.substring(1);
        }
        if (s.endsWith("]")) {
            s = s.substring(0, s.length() - 1);
        }
        if (s.isBlank()) {
            return null;
        }
        String[] parts = s.split(",");
        float[] vec = new float[parts.length];
        for (int i = 0; i < parts.length; i++) {
            vec[i] = Float.parseFloat(parts[i].trim());
        }
        return vec;
    }

    private String toVectorLiteral(float[] vec) {
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < vec.length; i++) {
            if (i > 0) sb.append(',');
            sb.append(vec[i]);
        }
        return sb.append(']').toString();
    }

    private double cosine(float[] a, float[] b) {
        if (a.length != b.length) {
            return -1;
        }
        double dot = 0, na = 0, nb = 0;
        for (int i = 0; i < a.length; i++) {
            dot += a[i] * b[i];
            na += a[i] * a[i];
            nb += b[i] * b[i];
        }
        if (na == 0 || nb == 0) {
            return -1;
        }
        return dot / (Math.sqrt(na) * Math.sqrt(nb));
    }
}
