package org.mcore.common.dto;

import java.io.Serializable;

public class MemorySearchDTO implements Serializable {
    private static final long serialVersionUID = 1L;

    private String query;
    private String type;
    private String scope;
    private Integer limit;
    private Integer maxTokens;

    public MemorySearchDTO() {
        this.limit = 10;
        this.maxTokens = 1200;
    }

    public String getQuery() { return query; }
    public void setQuery(String query) { this.query = query; }

    public String getType() { return type; }
    public void setType(String type) { this.type = type; }

    public String getScope() { return scope; }
    public void setScope(String scope) { this.scope = scope; }

    public Integer getLimit() { return limit; }
    public void setLimit(Integer limit) { this.limit = limit; }

    public Integer getMaxTokens() { return maxTokens; }
    public void setMaxTokens(Integer maxTokens) { this.maxTokens = maxTokens; }
}
