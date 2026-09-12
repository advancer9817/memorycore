package org.mcore.common.dto;

import java.io.Serializable;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * Slim 上下文信封响应 DTO (符合迭代 220 极简契约)
 */
public class ContextPackResponse implements Serializable {
    private static final long serialVersionUID = 1L;

    private Boolean ok;
    private String context;
    private Integer totalHits;
    private Integer estimatedTokens;

    /** 被注入防护拦截或以其他方式剔除的记忆告警（Python 侧 slim 信封的 warnings 字段） */
    private List<Map<String, Object>> warnings = new ArrayList<>();

    /** 因注入防护被剔除正文的记忆数 */
    private Integer filteredCount = 0;

    public ContextPackResponse() {}

    public ContextPackResponse(Boolean ok, String context, Integer totalHits, Integer estimatedTokens) {
        this.ok = ok;
        this.context = context;
        this.totalHits = totalHits;
        this.estimatedTokens = estimatedTokens;
    }

    public List<Map<String, Object>> getWarnings() { return warnings; }
    public void setWarnings(List<Map<String, Object>> warnings) {
        this.warnings = warnings == null ? new ArrayList<>() : warnings;
    }

    public Integer getFilteredCount() { return filteredCount; }
    public void setFilteredCount(Integer filteredCount) { this.filteredCount = filteredCount; }

    public Boolean getOk() { return ok; }
    public void setOk(Boolean ok) { this.ok = ok; }

    public String getContext() { return context; }
    public void setContext(String context) { this.context = context; }

    public Integer getTotalHits() { return totalHits; }
    public void setTotalHits(Integer totalHits) { this.totalHits = totalHits; }

    public Integer getEstimatedTokens() { return estimatedTokens; }
    public void setEstimatedTokens(Integer estimatedTokens) { this.estimatedTokens = estimatedTokens; }
}
