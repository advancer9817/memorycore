<template>
  <div class="space-y-6">
    <div class="bg-[#18181b] border border-zinc-800/80 rounded-xl p-6">
      <div class="flex items-center justify-between mb-6">
        <div>
          <h2 class="text-lg font-semibold text-white">租户私有记忆列表</h2>
          <p class="text-xs text-zinc-400 mt-1">按时间倒序展示当前租户物理库中的核心事实、规则与环境变量</p>
        </div>
        <button
          @click="loadMemories"
          class="bg-zinc-800 hover:bg-zinc-700 text-xs text-zinc-200 px-3 py-1.5 rounded-lg border border-zinc-700 transition"
        >
          刷新
        </button>
      </div>

      <div v-if="memories.length > 0" class="space-y-3">
        <div
          v-for="m in memories"
          :key="m.id"
          class="bg-zinc-900/50 border border-zinc-800/70 rounded-lg p-4 hover:border-zinc-700 transition"
        >
          <div class="flex items-center justify-between mb-2">
            <div class="flex items-center gap-2">
              <span class="text-xs px-2 py-0.5 rounded bg-zinc-800 text-zinc-300 font-mono">
                {{ m.id.substring(0, 8) }}...
              </span>
              <span class="text-xs px-2 py-0.5 rounded bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
                {{ m.type }}
              </span>
              <span class="text-xs text-zinc-400">[{{ m.scope }}]</span>
              <span class="text-sm font-medium text-white">{{ m.title || '无标题记录' }}</span>
            </div>
            <div class="text-xs text-zinc-400 flex items-center gap-3">
              <span>重要度: <b class="text-indigo-400">{{ m.importance }}</b></span>
              <span>来源: {{ m.sourceAgent }}</span>
              <span>{{ formatDate(m.createdAt) }}</span>
            </div>
          </div>
          <p class="text-xs text-zinc-300 leading-relaxed font-sans">{{ m.content }}</p>
        </div>
      </div>
      <div v-else class="text-center py-12 text-zinc-500 text-sm">
        当前租户物理库为空，尚未写入任何记忆
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import apiClient from '@/api/client';

const memories = ref<any[]>([]);

async function loadMemories() {
  try {
    const res = await apiClient.get('/memories/recent?limit=25');
    if (res.data && res.data.data) {
      memories.value = res.data.data;
    }
  } catch (e) {
    console.error('加载记忆列表失败', e);
  }
}

function formatDate(isoStr: string) {
  if (!isoStr) return '';
  try {
    return new Date(isoStr).toLocaleString('zh-CN', { hour12: false });
  } catch {
    return isoStr;
  }
}

onMounted(() => {
  loadMemories();
  window.addEventListener('mcore-tenant-changed', () => {
    loadMemories();
  });
});
</script>
