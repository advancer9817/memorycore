<template>
  <div class="space-y-6 pb-16">
    <div>
      <h1 class="text-xl font-bold text-white tracking-tight">协同智能体与应用监控</h1>
      <p class="text-xs text-zinc-400 mt-1">接入 MemoryCore 记忆中枢的多 Agent 协同状态、写入量与召回命中全景。</p>
    </div>

    <!-- Agent 列表卡片 -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-5">
      <div
        v-for="app in apps"
        :key="app.id"
        class="bg-[#18181b] border border-zinc-800/80 rounded-xl p-6 hover:border-zinc-700 transition space-y-4"
      >
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-3">
            <div class="w-10 h-10 rounded-xl bg-zinc-900 border border-zinc-700/80 flex items-center justify-center font-bold text-sm text-indigo-400 shadow">
              {{ app.name.slice(0, 2).toUpperCase() }}
            </div>
            <div>
              <h3 class="text-sm font-bold text-white">{{ app.display_name }}</h3>
              <span class="text-[11px] text-zinc-500 font-mono">{{ app.id }}</span>
            </div>
          </div>

          <span
            class="text-xs px-2.5 py-0.5 rounded-full font-medium border"
            :class="app.is_active ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : 'bg-zinc-800 text-zinc-400 border-zinc-700'"
          >
            {{ app.is_active ? '活跃' : '空闲' }}
          </span>
        </div>

        <p class="text-xs text-zinc-400 leading-relaxed min-h-[36px]">
          {{ app.description || '长期会话记忆协同与上下文自动注入' }}
        </p>

        <div class="grid grid-cols-2 gap-2 pt-3 border-t border-zinc-800/60 text-xs">
          <div class="bg-zinc-900/50 p-2.5 rounded-lg border border-zinc-800/60">
            <div class="text-[10px] text-zinc-500">累计写入记忆</div>
            <div class="text-base font-bold text-white mt-0.5">{{ app.total_memories_created || 0 }}</div>
          </div>
          <div class="bg-zinc-900/50 p-2.5 rounded-lg border border-zinc-800/60">
            <div class="text-[10px] text-zinc-500">上下文召回命中</div>
            <div class="text-base font-bold text-indigo-400 mt-0.5">{{ app.total_memories_accessed || 0 }}</div>
          </div>
        </div>

        <div class="text-[10px] text-zinc-500 pt-1">
          最近活动: {{ formatDate(app.last_activity_at) }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import apiClient from '@/api/client';

const apps = ref<any[]>([]);

async function fetchApps() {
  try {
    const res = await apiClient.get('/apps');
    apps.value = res.data.apps || [];
  } catch (e) {
    console.error('获取应用列表失败', e);
  }
}

function formatDate(d: string) {
  if (!d) return '暂无记录';
  return d.replace('T', ' ').replace('Z', '').slice(0, 19);
}

onMounted(() => {
  fetchApps();
});
</script>
