package org.mcore.mcp.protocol;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.JsonNode;

import java.io.Serializable;

@JsonIgnoreProperties(ignoreUnknown = true)
public class JsonRpcRequest implements Serializable {
    private static final long serialVersionUID = 1L;

    private String jsonrpc = "2.0";
    private Object id;
    private String method;
    private JsonNode params;

    public JsonRpcRequest() {}

    public String getJsonrpc() { return jsonrpc; }
    public void setJsonrpc(String jsonrpc) { this.jsonrpc = jsonrpc; }

    public Object getId() { return id; }
    public void setId(Object id) { this.id = id; }

    public String getMethod() { return method; }
    public void setMethod(String method) { this.method = method; }

    public JsonNode getParams() { return params; }
    public void setParams(JsonNode params) { this.params = params; }
}
