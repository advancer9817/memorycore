package org.mcore.common.model;

import java.io.Serializable;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;

public class MemoryEntityDO implements Serializable {
    private static final long serialVersionUID = 1L;

    private String id;
    private String memoryId;
    private String entity;
    private String normalizedEntity;
    private List<String> aliases = new ArrayList<>();
    private String entityType;
    private Double weight;
    private Instant createdAt;

    public MemoryEntityDO() {
        this.weight = 1.0;
        this.entityType = "concept";
    }

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }

    public String getMemoryId() { return memoryId; }
    public void setMemoryId(String memoryId) { this.memoryId = memoryId; }

    public String getEntity() { return entity; }
    public void setEntity(String entity) { this.entity = entity; }

    public String getNormalizedEntity() { return normalizedEntity; }
    public void setNormalizedEntity(String normalizedEntity) { this.normalizedEntity = normalizedEntity; }

    public List<String> getAliases() { return aliases; }
    public void setAliases(List<String> aliases) { this.aliases = aliases != null ? aliases : new ArrayList<>(); }

    public String getEntityType() { return entityType; }
    public void setEntityType(String entityType) { this.entityType = entityType; }

    public Double getWeight() { return weight; }
    public void setWeight(Double weight) { this.weight = weight; }

    public Instant getCreatedAt() { return createdAt; }
    public void setCreatedAt(Instant createdAt) { this.createdAt = createdAt; }
}
