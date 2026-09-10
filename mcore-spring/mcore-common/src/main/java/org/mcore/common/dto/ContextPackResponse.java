package org.mcore.common.dto;

import java.io.Serializable;

/**
 * Slim 上下文信封响应 DTO (符合迭代 220 极简契约)
 */
public class ContextPackResponse implements Serializable {
    private static final long serialVersionUID = 1L;

    private Boolean ok;
    private String context;
    private Integer totalHits;
    private Integer estimatedTokens;

    public ContextPackResponse() {}

    public ContextPackResponse(Boolean ok, String context, Integer totalHits, Integer estimatedTokens) {
        this.ok = ok;
        this.context = context;
        this.totalHits = totalHits;
        this.estimatedTokens = estimatedTokens;
    }

    public Boolean getOk() { return ok; }
    public void setOk(Boolean ok) { this.ok = ok; }

    public String getContext() { return context; }
    public void setContext(String context) { this.context = context; }

    public Integer getTotalHits() { return totalHits; }
    public void setTotalHits(Integer totalHits) { this.totalHits = totalHits; }

    public Integer getEstimatedTokens() { return estimatedTokens; }
    public void setEstimatedTokens(Integer estimatedTokens) { this.estimatedTokens = estimatedTokens; }
}
