package org.mcore.common.enums;

/**
 * 租户数据库生命周期状态枚举
 */
public enum TenantStatusEnum {
    PROVISIONING("provisioning", "正在开辟"),
    READY("ready", "运行就绪"),
    MAINTENANCE("maintenance", "维护锁定"),
    ARCHIVING("archiving", "归档中"),
    SUSPENDED("suspended", "已冻结");

    private final String code;
    private final String desc;

    TenantStatusEnum(String code, String desc) {
        this.code = code;
        this.desc = desc;
    }

    public String getCode() { return code; }
    public String getDesc() { return desc; }
}
