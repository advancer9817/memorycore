package org.mcore.common.result;

/**
 * 阿里规约五位标准错误码枚举
 */
public enum ErrorCode {
    SUCCESS("00000", "操作成功"),
    
    // 客户端错误 (Axxxx)
    CLIENT_PARAM_ERROR("A0400", "请求参数非法"),
    CLIENT_UNAUTHORIZED("A0401", "未提供有效鉴权凭证"),
    CLIENT_FORBIDDEN("A0403", "无权访问指定租户资源"),
    CLIENT_TENANT_NOT_FOUND("A0404", "指定租户数据库不存在"),
    CLIENT_QUOTA_EXCEEDED("A0429", "租户配额超限"),

    // 系统错误 (Bxxxx)
    SYSTEM_ERROR("B0001", "系统内部异常"),
    SYSTEM_POOL_EXHAUSTED("B0002", "全局数据库连接池耗尽"),
    SYSTEM_SEARCH_TIMEOUT("B0003", "混合检索查询超时"),
    SYSTEM_DATABASE_PROVISION_FAILED("B0004", "租户物理数据库开辟失败"),

    // 第三方错误 (Cxxxx)
    THIRD_PARTY_EMBEDDING_FAILED("C0001", "外部 Embedding 服务异常");

    private final String code;
    private final String message;

    ErrorCode(String code, String message) {
        this.code = code;
        this.message = message;
    }

    public String getCode() {
        return code;
    }

    public String getMessage() {
        return message;
    }
}
