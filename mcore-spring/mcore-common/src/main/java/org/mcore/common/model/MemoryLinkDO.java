package org.mcore.common.model;

import java.io.Serializable;
import java.time.Instant;

public class MemoryLinkDO implements Serializable {
    private static final long serialVersionUID = 1L;

    private String id;
    private String sourceId;
    private String targetId;
    private String relationType;
    private Double weight;
    private String note;
    private String sourceAgent;
    private Instant createdAt;
    private Instant updatedAt;

    public MemoryLinkDO() {
        this.weight = 1.0;
        this.note = "";
        this.sourceAgent = "agent";
    }

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }

    public String getSourceId() { return sourceId; }
    public void setSourceId(String sourceId) { this.sourceId = sourceId; }

    public String getTargetId() { return targetId; }
    public void setTargetId(String targetId) { this.targetId = targetId; }

    public String getRelationType() { return relationType; }
    public void setRelationType(String relationType) { this.relationType = relationType; }

    public Double getWeight() { return weight; }
    public void setWeight(Double weight) { this.weight = weight; }

    public String getNote() { return note; }
    public void setNote(String note) { this.note = note; }

    public String getSourceAgent() { return sourceAgent; }
    public void setSourceAgent(String sourceAgent) { this.sourceAgent = sourceAgent; }

    public Instant getCreatedAt() { return createdAt; }
    public void setCreatedAt(Instant createdAt) { this.createdAt = createdAt; }

    public Instant getUpdatedAt() { return updatedAt; }
    public void setUpdatedAt(Instant updatedAt) { this.updatedAt = updatedAt; }
}
