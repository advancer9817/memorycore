package org.mcore.tenancy.routing;

/**
 * 租户上下文持有器 (基于 InheritableThreadLocal)
 * 阿里规约强约束：所有请求终点必须强制调用 remove() 防止线程复用污染
 */
public final class TenantContextHolder {
    private static final ThreadLocal<String> CURRENT_TENANT = new InheritableThreadLocal<>();

    private TenantContextHolder() {}

    public static void setTenantId(String tenantId) {
        CURRENT_TENANT.set((tenantId != null && !tenantId.isBlank()) ? tenantId.trim() : "default");
    }

    public static String getTenantId() {
        String tenant = CURRENT_TENANT.get();
        return (tenant != null && !tenant.isBlank()) ? tenant : "default";
    }

    public static void remove() {
        CURRENT_TENANT.remove();
    }
}
