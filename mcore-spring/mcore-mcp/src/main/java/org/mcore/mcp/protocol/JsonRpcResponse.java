package org.mcore.mcp.protocol;

import com.fasterxml.jackson.annotation.JsonInclude;

import java.io.Serializable;

@JsonInclude(JsonInclude.Include.NON_NULL)
public class JsonRpcResponse implements Serializable {
    private static final long serialVersionUID = 1L;

    private String jsonrpc = "2.0";
    private Object id;
    private Object result;
    private JsonRpcError error;

    public JsonRpcResponse() {}

    public JsonRpcResponse(Object id, Object result) {
        this.id = id;
        this.result = result;
    }

    public JsonRpcResponse(Object id, JsonRpcError error) {
        this.id = id;
        this.error = error;
    }

    public static record JsonRpcError(int code, String message, Object data) {}

    public String getJsonrpc() { return jsonrpc; }
    public void setJsonrpc(String jsonrpc) { this.jsonrpc = jsonrpc; }

    public Object getId() { return id; }
    public void setId(Object id) { this.id = id; }

    public Object getResult() { return result; }
    public void setResult(Object result) { this.result = result; }

    public JsonRpcError getError() { return error; }
    public void setError(JsonRpcError error) { this.error = error; }
}
