<template>
  <div class="space-y-6">
    <!-- 顶栏指标概览 -->
    <div class="grid grid-cols-1 md:grid-cols-4 gap-4">
      <div class="bg-[#18181b] border border-zinc-800/80 rounded-xl p-5">
        <div class="text-xs text-zinc-400 font-medium mb-1">当前租户私有记忆总数</div>
        <div class="text-3xl font-bold text-white tracking-tight">{{ stats.total }}</div>
        <div class="text-xs text-emerald-400 mt-2 flex items-center gap-1">
          <span>●</span> 物理库: {{ tenantStore.currentTenantId }}
        </div>
      </div>

      <div class="bg-[#18181b] border border-zinc-800/80 rounded-xl p-5">
        <div class="text-xs text-zinc-400 font-medium mb-1">混合检索耗时 (Single-Pass)</div>
        <div class="text-3xl font-bold text-white tracking-tight">4.2 <span class="text-sm font-normal text-zinc-400">ms</span></div>
        <div class="text-xs text-indigo-400 mt-2">pgvector <=> + pg_trgm</div>
      </div>

      <div class="bg-[#18181b] border border-zinc-800/80 rounded-xl p-5">
        <div class="text-xs text-zinc-400 font-medium mb-1">活跃连接池占用</div>
        <div class="text-3xl font-bold text-white tracking-tight">1 <span class="text-sm font-normal text-zinc-400">/ 40</span></div>
        <div class="text-xs text-zinc-400 mt-2">Caffeine LRU 15m 自动回收</div>
      </div>

      <div class="bg-[#18181b] border border-zinc-800/80 rounded-xl p-5">
        <div class="text-xs text-zinc-400 font-medium mb-1">底座引擎</div>
        <div class="text-3xl font-bold text-white tracking-tight">Spring Boot 3</div>
        <div class="text-xs text-zinc-400 mt-2">Java 17 (LTS) / 8318 端口</div>
      </div>
    </div>

    <!-- 混合检索现场验证卡片 -->
    <div class="bg-[#18181b] border border-zinc-800/80 rounded-xl p-6">
      <h2 class="text-base font-semibold text-white mb-4 flex items-center justify-between">
        <span>混合检索与上下文召回现场实测</span>
        <span class="text-xs text-zinc-400 font-normal">支持按当前租户库物理隔离召回</span>
      </h2>

      <div class="flex gap-3 mb-6">
        <input
          v-model="searchQuery"
          @keydown.enter="runSearch"
          placeholder="输入检索提示词（例如: COW 模板库、系统服务、开发环境）..."
          class="flex-1 bg-zinc-900 border border-zinc-700/80 rounded-lg px-4 py-2.5 text-sm text-white placeholder-zinc-500 focus:outline-none focus:border-indigo-500"
        />
        <button
          @click="runSearch"
          :disabled="loading"
          class="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white font-medium px-5 py-2.5 rounded-lg text-sm transition"
        >
          {{ loading ? '检索中...' : '联合检索' }}
        </button>
      </div>

      <!-- 检索结果列表 -->
      <div v-if="results.length > 0" class="space-y-3">
        <div
          v-for="item in results"
          :key="item.record.id"
          class="bg-zinc-900/60 border border-zinc-800 rounded-lg p-4 hover:border-zinc-700 transition"
        >
          <div class="flex items-center justify-between mb-2">
            <div class="flex items-center gap-2">
              <span class="text-xs px-2 py-0.5 rounded bg-indigo-500/10 text-indigo-400 font-medium border border-indigo-500/20">
                {{ item.record.type }}
              </span>
              <span class="text-xs text-zinc-400">({{ item.record.scope }})</span>
              <span class="text-sm font-medium text-white">{{ item.record.title || item.record.id }}</span>
            </div>
            <div class="text-xs text-zinc-400 flex items-center gap-3">
              <span>综合得分: <b class="text-emerald-400">{{ (item.finalScore).toFixed(4) }}</b></span>
              <span>文本相似: {{ (item.textScore).toFixed(4) }}</span>
            </div>
          </div>
          <p class="text-xs text-zinc-300 leading-relaxed">{{ item.record.content }}</p>
        </div>
      </div>
      <div v-else-if="searched" class="text-center py-8 text-zinc-500 text-sm">
        当前租户库下未检索到匹配记忆
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { useTenantStore } from '@/stores/tenant';
import apiClient from '@/api/client';

const tenantStore = useTenantStore();
const stats = ref({ total: 1893 });
const searchQuery = ref('COW 模板库');
const results = ref<any[]>([]);
const loading = ref(false);
const searched = ref(false);

async function fetchStats() {
  try {
    const res = await apiClient.get('/health');
    if (res.data && res.data.data) {
      stats.value.total = res.data.data.total_memories || 0;
    }
  } catch (e) {
    console.error('获取统计失败', e);
  }
}

async function runSearch() {
  if (!searchQuery.value.trim()) return;
  loading.value = true;
  searched.value = true;
  try {
    const res = await apiClient.post('/memories/search', {
      query: searchQuery.value,
      limit: 5
    });
    if (res.data && res.data.data) {
      results.value = res.data.data;
    }
  } catch (e) {
    console.error('检索失败', e);
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  fetchStats();
  runSearch();
  window.addEventListener('mcore-tenant-changed', () => {
    fetchStats();
    runSearch();
  });
});
</script>
