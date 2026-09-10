import { defineStore } from 'pinia';
import { ref } from 'vue';

export interface TenantInfo {
  tenantId: string;
  dbName: string;
  status: string;
  totalMemories?: number;
}

export const useTenantStore = defineStore('tenant', () => {
  const currentTenantId = ref<string>(localStorage.getItem('mcore_tenant_id') || 'default');
  const availableTenants = ref<TenantInfo[]>([
    { tenantId: 'default', dbName: 'mcore', status: 'ready' }
  ]);

  function switchTenant(tenantId: string) {
    currentTenantId.value = tenantId;
    localStorage.setItem('mcore_tenant_id', tenantId);
    window.dispatchEvent(new CustomEvent('mcore-tenant-changed', { detail: { tenantId } }));
  }

  function registerTenant(tenant: TenantInfo) {
    if (!availableTenants.value.some(t => t.tenantId === tenant.tenantId)) {
      availableTenants.value.push(tenant);
    }
  }

  return {
    currentTenantId,
    availableTenants,
    switchTenant,
    registerTenant
  };
});
