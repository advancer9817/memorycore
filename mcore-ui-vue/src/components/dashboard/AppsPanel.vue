<template>
  <div class="mcore-card rounded-2xl overflow-hidden shadow-lg">
    <div class="flex items-center justify-between px-6 py-4 border-b border-zinc-800/80">
      <div class="flex items-center gap-2">
        <AppWindow class="h-4 w-4 text-sky-400" />
        <h2 class="text-sm font-semibold text-zinc-200">智能体接入与授权协同 (Apps & Agents)</h2>
        <span class="text-xs text-zinc-500 font-normal">(授权写入与接入通道)</span>
      </div>
      <span class="text-xs font-normal text-zinc-500">{{ apps.length }} 个接入方</span>
    </div>

    <div class="p-6">
      <div class="grid grid-cols-1 gap-3.5 sm:grid-cols-2 lg:grid-cols-4">
        <router-link
          v-for="app in apps"
          :key="app.id"
          to="/apps"
          class="group relative flex flex-col justify-between rounded-xl border border-zinc-800 bg-zinc-950/60 p-3.5 transition-all duration-200 hover:border-violet-500/50 hover:bg-zinc-900/90"
        >
          <div>
            <div class="flex items-center justify-between gap-2">
              <div class="flex items-center gap-2 min-w-0">
                <div class="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-zinc-800/80 text-zinc-300 group-hover:bg-violet-600/20 group-hover:text-violet-300 transition-colors">
                  <Server v-if="app.category === 'system' || app.id === 'mcore'" class="h-3.5 w-3.5 text-indigo-400" />
                  <Bot v-else class="h-3.5 w-3.5 text-sky-400" />
                </div>
                <span class="truncate text-xs font-semibold text-zinc-200 group-hover:text-violet-200">
                  {{ app.display_name || app.name }}
                </span>
              </div>

              <div class="flex items-center gap-1.5 shrink-0">
                <span
                  class="h-2 w-2 rounded-full"
                  :class="app.is_active ? 'bg-emerald-500 ring-2 ring-emerald-500/20 animate-pulse' : 'bg-zinc-600'"
                />
              </div>
            </div>

            <p class="mt-2 text-xs text-zinc-400 line-clamp-2 leading-relaxed min-h-[32px]">
              {{ app.description || '长期会话记忆协同与上下文自动注入' }}
            </p>
          </div>

          <div class="mt-3 flex items-center justify-between border-t border-zinc-800/60 pt-2.5 text-xs text-zinc-400">
            <div class="flex items-center gap-1">
              <span class="text-zinc-500">写入</span>
              <b class="text-zinc-200 font-mono">{{ app.total_memories_created || 0 }}</b>
            </div>
            <div class="flex items-center gap-1">
              <span class="text-zinc-500">召回</span>
              <b class="text-indigo-400 font-mono">{{ app.total_memories_accessed || 0 }}</b>
            </div>
          </div>
        </router-link>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { AppWindow, Server, Bot } from 'lucide-vue-next';
import apiClient from '@/api/client';

const apps = ref<any[]>([]);

async function fetchApps() {
  try {
    const res = await apiClient.get('/apps');
    apps.value = res.data.apps || [];
  } catch {}
}

onMounted(() => {
  fetchApps();
});
</script>
