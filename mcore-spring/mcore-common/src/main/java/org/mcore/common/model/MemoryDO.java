package org.mcore.common.model;

import java.io.Serializable;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 记忆核心实体领域模型 (对齐 PostgreSQL 16 memories 表 31 个字段)
 */
public class MemoryDO implements Serializable {
    private static final long serialVersionUID = 1L;

    private String id;
    private String type;
    private String scope;
    private String title;
    private String content;
    private List<String> tags = new ArrayList<>();
    private Map<String, Object> metadata = new HashMap<>();
    private String source;
    private String sourceAgent;
    private String projectPath;
    private Double confidence;
    private Double importance;
    private String status;
    private String decayPolicy;
    private Double feedbackScore;
    private Integer injectedCount;
    private Integer ineffectiveCount;
    private Double effectivenessScore;
    private Instant createdAt;
    private Instant updatedAt;
    private Instant lastAccessedAt;
    private Instant lastInjectedAt;
    private String validFrom;
    private String validUntil;
    private String supersededBy;
    private String factLineageRoot;
    private List<String> relatedIds = new ArrayList<>();
    private float[] embedding;

    public MemoryDO() {}

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }

    public String getType() { return type; }
    public void setType(String type) { this.type = type; }

    public String getScope() { return scope; }
    public void setScope(String scope) { this.scope = scope; }

    public String getTitle() { return title; }
    public void setTitle(String title) { this.title = title; }

    public String getContent() { return content; }
    public void setContent(String content) { this.content = content; }

    public List<String> getTags() { return tags; }
    public void setTags(List<String> tags) { this.tags = tags != null ? tags : new ArrayList<>(); }

    public Map<String, Object> getMetadata() { return metadata; }
    public void setMetadata(Map<String, Object> metadata) { this.metadata = metadata != null ? metadata : new HashMap<>(); }

    public String getSource() { return source; }
    public void setSource(String source) { this.source = source; }

    public String getSourceAgent() { return sourceAgent; }
    public void setSourceAgent(String sourceAgent) { this.sourceAgent = sourceAgent; }

    public String getProjectPath() { return projectPath; }
    public void setProjectPath(String projectPath) { this.projectPath = projectPath; }

    public Double getConfidence() { return confidence; }
    public void setConfidence(Double confidence) { this.confidence = confidence; }

    public Double getImportance() { return importance; }
    public void setImportance(Double importance) { this.importance = importance; }

    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }

    public String getDecayPolicy() { return decayPolicy; }
    public void setDecayPolicy(String decayPolicy) { this.decayPolicy = decayPolicy; }

    public Double getFeedbackScore() { return feedbackScore; }
    public void setFeedbackScore(Double feedbackScore) { this.feedbackScore = feedbackScore; }

    public Integer getInjectedCount() { return injectedCount; }
    public void setInjectedCount(Integer injectedCount) { this.injectedCount = injectedCount; }

    public Integer getIneffectiveCount() { return ineffectiveCount; }
    public void setIneffectiveCount(Integer ineffectiveCount) { this.ineffectiveCount = ineffectiveCount; }

    public Double getEffectivenessScore() { return effectivenessScore; }
    public void setEffectivenessScore(Double effectivenessScore) { this.effectivenessScore = effectivenessScore; }

    public Instant getCreatedAt() { return createdAt; }
    public void setCreatedAt(Instant createdAt) { this.createdAt = createdAt; }

    public Instant getUpdatedAt() { return updatedAt; }
    public void setUpdatedAt(Instant updatedAt) { this.updatedAt = updatedAt; }

    public Instant getLastAccessedAt() { return lastAccessedAt; }
    public void setLastAccessedAt(Instant lastAccessedAt) { this.lastAccessedAt = lastAccessedAt; }

    public Instant getLastInjectedAt() { return lastInjectedAt; }
    public void setLastInjectedAt(Instant lastInjectedAt) { this.lastInjectedAt = lastInjectedAt; }

    public String getValidFrom() { return validFrom; }
    public void setValidFrom(String validFrom) { this.validFrom = validFrom; }

    public String getValidUntil() { return validUntil; }
    public void setValidUntil(String validUntil) { this.validUntil = validUntil; }

    public String getSupersededBy() { return supersededBy; }
    public void setSupersededBy(String supersededBy) { this.supersededBy = supersededBy; }

    public String getFactLineageRoot() { return factLineageRoot; }
    public void setFactLineageRoot(String factLineageRoot) { this.factLineageRoot = factLineageRoot; }

    public List<String> getRelatedIds() { return relatedIds; }
    public void setRelatedIds(List<String> relatedIds) { this.relatedIds = relatedIds != null ? relatedIds : new ArrayList<>(); }

    public float[] getEmbedding() { return embedding; }
    public void setEmbedding(float[] embedding) { this.embedding = embedding; }

    // ------------------------------------------------------------------
    // JSON 投影字段：供 MyBatis 写入 PostgreSQL 原生 _json 列使用
    // 表内触发器 sync_memories_json_columns 会据此自动同步 tags[] / metadata / related_ids[]
    // ------------------------------------------------------------------
    private static final com.fasterxml.jackson.databind.ObjectMapper JSON_MAPPER =
            new com.fasterxml.jackson.databind.ObjectMapper();

    private String toJson(Object value, String fallback) {
        try {
            return JSON_MAPPER.writeValueAsString(value);
        } catch (Exception e) {
            return fallback;
        }
    }

    public String getTagsJson() {
        return toJson(tags != null ? tags : new ArrayList<>(), "[]");
    }

    public String getMetadataJson() {
        return toJson(metadata != null ? metadata : new HashMap<>(), "{}");
    }

    public String getRelatedIdsJson() {
        return toJson(relatedIds != null ? relatedIds : new ArrayList<>(), "[]");
    }
}
