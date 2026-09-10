<template>
  <div class="bg-[#18181b] border border-zinc-800/80 rounded-xl p-6">
    <div class="flex items-center justify-between mb-4">
      <div>
        <h2 class="text-base font-semibold text-white">一键维护与生命周期管理</h2>
        <p class="text-xs text-zinc-400 mt-0.5">对长周期未触碰、已替代或已失效的记忆执行批量安全归档或清理。</p>
      </div>

      <!-- Tab 切换 -->
      <div class="flex items-center bg-zinc-900 border border-zinc-800 rounded-lg p-0.5">
        <button
          @click="switchAction('archive')"
          class="px-3 py-1 rounded-md text-xs font-medium transition"
          :class="action === 'archive' ? 'bg-zinc-800 text-white shadow' : 'text-zinc-400 hover:text-zinc-200'"
        >
          推荐归档
        </button>
        <button
          @click="switchAction('clean')"
          class="px-3 py-1 rounded-md text-xs font-medium transition"
          :class="action === 'clean' ? 'bg-zinc-800 text-white shadow' : 'text-zinc-400 hover:text-zinc-200'"
        >
          清理归档
        </button>
      </div>
    </div>

    <!-- 扫描计划概览区 -->
    <div class="bg-zinc-900/50 border border-zinc-800/70 rounded-lg p-4 mb-4 flex items-center justify-between">
      <div class="flex items-center gap-4">
        <div class="w-10 h-10 rounded-lg bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center text-indigo-400 font-bold">
          ⚡
        </div>
        <div>
          <div class="text-sm font-medium text-white flex items-center gap-2">
            <span>{{ action === 'archive' ? '待归档候选队列' : '待清理归档队列' }}</span>
            <span class="text-xs px-2 py-0.2 rounded-full bg-zinc-800 text-indigo-300">
              {{ planData ? planData.candidate_count : '未扫描' }} 条
            </span>
          </div>
          <div class="text-xs text-zinc-400 mt-0.5">
            {{ action === 'archive' ? '扫描 30 天未触碰的过时 (stale) 与已替代记忆' : '扫描处于 archived 状态的沉淀历史' }}
          </div>
        </div>
      </div>

      <div class="flex items-center gap-3">
        <button
          @click="fetchPlan"
          :disabled="scanning"
          class="px-4 py-2 rounded-lg border border-zinc-700 bg-zinc-800 hover:bg-zinc-700 text-xs font-medium text-white transition disabled:opacity-50"
        >
          {{ scanning ? '扫描中...' : '重新扫描' }}
        </button>
        <button
          v-if="planData && planData.candidate_count > 0"
          @click="confirmExecute"
          :disabled="executing"
          class="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-xs font-medium text-white transition disabled:opacity-50"
        >
          {{ executing ? '处理中...' : (action === 'archive' ? `归档 ${planData.candidate_count} 条` : `删除 ${planData.candidate_count} 条记录`) }}
        </button>
      </div>
    </div>

    <!-- 候选预览列表 -->
    <div v-if="planData && planData.candidates && planData.candidates.length > 0" class="space-y-2">
      <div class="text-xs font-medium text-zinc-400 mb-1 flex items-center justify-between">
        <span>候选预览采样 (前 {{ Math.min(planData.candidates.length, 5) }} 条)</span>
        <span class="text-[11px] text-zinc-500">Plan Token: {{ planData.plan_token.slice(0, 10) }}...</span>
      </div>
      <div
        v-for="item in planData.candidates.slice(0, 5)"
        :key="item.id"
        class="bg-zinc-900/40 border border-zinc-800/60 rounded-lg p-3 text-xs flex items-center justify-between hover:border-zinc-700 transition"
      >
        <div class="flex items-center gap-2 max-w-[70%] truncate">
          <span class="text-[10px] px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400 border border-zinc-700">
            {{ item.type || 'fact' }}
          </span>
          <span class="text-zinc-200 font-medium truncate">{{ item.title || item.id }}</span>
        </div>
        <div class="text-[11px] text-zinc-500">
          状态: <span class="text-amber-400">{{ item.status }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import apiClient from '@/api/client';

const emit = defineEmits(['updated']);

const action = ref<'archive' | 'clean'>('archive');
const scanning = ref(false);
const executing = ref(false);
const planData = ref<any>(null);

function switchAction(a: 'archive' | 'clean') {
  action.value = a;
  fetchPlan();
}

async function fetchPlan() {
  scanning.value = true;
  try {
    const res = await apiClient.get(`/maintenance/plan?action=${action.value}&limit=50`);
    planData.value = res.data;
  } catch (e) {
    console.error('获取维护计划失败', e);
  } finally {
    scanning.value = false;
  }
}

async function confirmExecute() {
  if (!planData.value || !planData.value.plan_token) return;
  const msg = action.value === 'archive'
    ? `确定要对扫描出的 ${planData.value.candidate_count} 条记忆执行批量归档吗？`
    : `确定要永久物理清理 ${planData.value.candidate_count} 条已归档记忆吗？此操作不可逆！`;
  if (!window.confirm(msg)) return;

  executing.value = true;
  try {
    await apiClient.post('/maintenance/execute', {
      plan_token: planData.value.plan_token,
      action: action.value,
    });
    alert('维护执行完成！');
    fetchPlan();
    emit('updated');
  } catch (e) {
    console.error('执行维护失败', e);
    alert('维护操作异常，请重试');
  } finally {
    executing.value = false;
  }
}

onMounted(() => {
  fetchPlan();
});
</script>
