package org.mcore.common.model;

import java.io.Serializable;
import java.time.Instant;

public class FeedbackEventDO implements Serializable {
    private static final long serialVersionUID = 1L;

    private String id;
    private String memoryId;
    private Double score;
    private String note;
    private String sourceAgent;
    private Instant createdAt;

    public FeedbackEventDO() {}

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }

    public String getMemoryId() { return memoryId; }
    public void setMemoryId(String memoryId) { this.memoryId = memoryId; }

    public Double getScore() { return score; }
    public void setScore(Double score) { this.score = score; }

    public String getNote() { return note; }
    public void setNote(String note) { this.note = note; }

    public String getSourceAgent() { return sourceAgent; }
    public void setSourceAgent(String sourceAgent) { this.sourceAgent = sourceAgent; }

    public Instant getCreatedAt() { return createdAt; }
    public void setCreatedAt(Instant createdAt) { this.createdAt = createdAt; }
}
