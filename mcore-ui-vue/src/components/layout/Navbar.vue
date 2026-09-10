<template>
  <header class="h-16 border-b border-zinc-800 bg-[#18181b]/90 backdrop-blur px-6 flex items-center justify-between sticky top-0 z-50">
    <div class="flex items-center gap-6">
      <div class="flex items-center gap-2.5">
        <div class="w-8 h-8 rounded-lg bg-gradient-to-tr from-indigo-500 to-rose-500 flex items-center justify-center font-bold text-white text-sm shadow-md shadow-indigo-500/20">
          M
        </div>
        <span class="font-semibold text-lg tracking-tight text-white">MemoryCore</span>
        <span class="text-xs px-2 py-0.5 rounded-full bg-zinc-800 text-zinc-400 border border-zinc-700/50">v0.26 (Vue3)</span>
      </div>

      <nav class="flex items-center gap-1 ml-4">
        <router-link to="/" class="px-3 py-1.5 rounded-md text-xs font-medium transition" :class="$route.path === '/' ? 'bg-zinc-800 text-white' : 'text-zinc-400 hover:text-zinc-200'">仪表盘</router-link>
        <router-link to="/memories" class="px-3 py-1.5 rounded-md text-xs font-medium transition" :class="$route.path.startsWith('/memories') || $route.path.startsWith('/memory') ? 'bg-zinc-800 text-white' : 'text-zinc-400 hover:text-zinc-200'">记忆管理</router-link>
        <router-link to="/governance" class="px-3 py-1.5 rounded-md text-xs font-medium transition relative flex items-center gap-1.5" :class="$route.path === '/governance' ? 'bg-zinc-800 text-white' : 'text-zinc-400 hover:text-zinc-200'">
          <span>治理中心</span>
          <span v-if="pendingDecisions > 0" class="w-2 h-2 rounded-full bg-amber-400 animate-pulse"></span>
        </router-link>
        <router-link to="/graph" class="px-3 py-1.5 rounded-md text-xs font-medium transition" :class="$route.path === '/graph' ? 'bg-zinc-800 text-white' : 'text-zinc-400 hover:text-zinc-200'">知识图谱</router-link>
        <router-link to="/profile" class="px-3 py-1.5 rounded-md text-xs font-medium transition" :class="$route.path === '/profile' ? 'bg-zinc-800 text-white' : 'text-zinc-400 hover:text-zinc-200'">用户画像</router-link>
        <router-link to="/apps" class="px-3 py-1.5 rounded-md text-xs font-medium transition" :class="$route.path === '/apps' ? 'bg-zinc-800 text-white' : 'text-zinc-400 hover:text-zinc-200'">协同应用</router-link>
        <router-link to="/settings" class="px-3 py-1.5 rounded-md text-xs font-medium transition" :class="$route.path === '/settings' ? 'bg-zinc-800 text-white' : 'text-zinc-400 hover:text-zinc-200'">系统设置</router-link>
      </nav>
    </div>

    <div class="flex items-center gap-4">
      <!-- 私有租户快速切换器 -->
      <div class="flex items-center gap-2 bg-zinc-900 border border-zinc-800 rounded-lg px-3 py-1.5 text-xs">
        <span class="text-zinc-400 font-medium">租户物理库:</span>
        <select
          v-model="tenantStore.currentTenantId"
          @change="onTenantChange"
          class="bg-transparent text-white font-medium text-xs focus:outline-none cursor-pointer"
        >
          <option v-for="t in tenantStore.availableTenants" :key="t.tenantId" :value="t.tenantId" class="bg-zinc-900 text-white">
            {{ t.tenantId }} ({{ t.dbName }})
          </option>
          <option value="tenant_agent_alpha" class="bg-zinc-900 text-white">tenant_agent_alpha</option>
        </select>
      </div>

      <div class="flex items-center gap-2 text-xs text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 px-2.5 py-1 rounded-full">
        <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
        FastMCP :8318 联通
      </div>
    </div>
  </header>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { useTenantStore } from '@/stores/tenant';
import apiClient from '@/api/client';

const tenantStore = useTenantStore();
const pendingDecisions = ref(0);

function onTenantChange(e: Event) {
  const select = e.target as HTMLSelectElement;
  tenantStore.switchTenant(select.value);
}

onMounted(async () => {
  try {
    const res = await apiClient.get('/governance/metrics');
    if (res.data && res.data.pending_reviews) {
      pendingDecisions.value = Number(res.data.pending_reviews);
    }
  } catch {
    // 静默降级
  }
});
</script>
