<template>
  <div v-if="!health" class="mcore-card rounded-2xl p-6 flex items-center gap-3 text-xs text-zinc-500">
    <HeartPulse class="h-5 w-5 animate-pulse text-zinc-400" />
    <span>正在实时评估系统健康水位与治理指标...</span>
  </div>

  <div
    v-else
    class="mcore-card rounded-2xl p-6 shadow-xl relative overflow-hidden transition-all duration-300"
  >
    <div class="flex flex-col lg:flex-row lg:items-center justify-between gap-6">
      <!-- 左侧：健康分总览与评级 -->
      <div class="flex items-center gap-6">
        <div
          class="flex flex-col items-center justify-center w-24 h-24 rounded-2xl border transition-all duration-300 shadow-inner"
          :class="[scoreTheme.bg, scoreTheme.border]"
        >
          <span class="text-3xl font-black tracking-tight" :class="scoreTheme.text">
            {{ health.quality }}
          </span>
          <span class="text-xs font-semibold mt-0.5" :class="scoreTheme.text">
            {{ scoreTheme.label }}
          </span>
        </div>

        <div class="space-y-1.5">
          <div class="flex items-center gap-2.5">
            <h2 class="text-base font-bold text-white tracking-tight flex items-center gap-2">
              <Sparkles class="h-4 w-4 text-indigo-400" />
              <span>系统综合健康指数</span>
            </h2>
            <span
              class="text-xs px-2.5 py-0.5 rounded-full font-medium border"
              :class="scoreTheme.badge"
            >
              评分体系 v1
            </span>
          </div>

          <p class="text-xs text-zinc-400 max-w-lg leading-relaxed">
            基于多维度动态加权矩阵：低风险治理（34%）、待清理低占比（16%）、记忆复用（24%）与知识关联覆盖率（8%）。
          </p>

          <div v-if="health.llmStatus === 'running'" class="flex items-center gap-2 text-xs text-indigo-400 pt-0.5">
            <span class="inline-block w-1.5 h-1.5 rounded-full bg-indigo-400 animate-ping"></span>
            <span>LLM 语义巡检运行中 (已耗时 {{ formattedLlmElapsed }})</span>
          </div>
        </div>
      </div>

      <!-- 右侧：四大核心维度指标卡片 -->
      <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 w-full lg:w-auto">
        <!-- 维度 1: 记忆复用率 -->
        <div class="bg-zinc-950/60 border border-zinc-800/80 rounded-xl p-3.5 flex flex-col justify-between min-w-[130px]">
          <div class="flex items-center justify-between text-xs text-zinc-400 mb-2">
            <span>记忆复用率</span>
            <Recycle class="h-3.5 w-3.5 text-emerald-400" />
          </div>
          <div>
            <div class="text-lg font-bold text-white tracking-tight">
              {{ metrics.active_reuse_coverage || 0 }}%
            </div>
            <div class="w-full h-1 bg-zinc-800 rounded-full mt-2 overflow-hidden">
              <div
                class="h-full bg-emerald-500 rounded-full transition-all duration-500"
                :style="{ width: `${metrics.active_reuse_coverage || 0}%` }"
              ></div>
            </div>
          </div>
        </div>

        <!-- 维度 2: 关联度覆盖 -->
        <div class="bg-zinc-950/60 border border-zinc-800/80 rounded-xl p-3.5 flex flex-col justify-between min-w-[130px]">
          <div class="flex items-center justify-between text-xs text-zinc-400 mb-2">
            <span>关联度覆盖</span>
            <Link2 class="h-3.5 w-3.5 text-indigo-400" />
          </div>
          <div>
            <div class="text-lg font-bold text-white tracking-tight">
              {{ metrics.linked_coverage || 0 }}%
            </div>
            <div class="w-full h-1 bg-zinc-800 rounded-full mt-2 overflow-hidden">
              <div
                class="h-full bg-indigo-500 rounded-full transition-all duration-500"
                :style="{ width: `${metrics.linked_coverage || 0}%` }"
              ></div>
            </div>
          </div>
        </div>

        <!-- 维度 3: 待清理占比 -->
        <div class="bg-zinc-950/60 border border-zinc-800/80 rounded-xl p-3.5 flex flex-col justify-between min-w-[130px]">
          <div class="flex items-center justify-between text-xs text-zinc-400 mb-2">
            <span>待清理占比</span>
            <Activity class="h-3.5 w-3.5 text-amber-400" />
          </div>
          <div>
            <div class="text-lg font-bold text-amber-400 tracking-tight">
              {{ metrics.pending_cleanup_share || 0 }}%
            </div>
            <div class="w-full h-1 bg-zinc-800 rounded-full mt-2 overflow-hidden">
              <div
                class="h-full bg-amber-500 rounded-full transition-all duration-500"
                :style="{ width: `${metrics.pending_cleanup_share || 0}%` }"
              ></div>
            </div>
          </div>
        </div>

        <!-- 维度 4: 治理风险抵御 -->
        <div class="bg-zinc-950/60 border border-zinc-800/80 rounded-xl p-3.5 flex flex-col justify-between min-w-[130px]">
          <div class="flex items-center justify-between text-xs text-zinc-400 mb-2">
            <span>风险抵御</span>
            <ShieldCheck class="h-3.5 w-3.5 text-sky-400" />
          </div>
          <div>
            <div class="text-lg font-bold text-sky-400 tracking-tight">
              {{ health.risk || 100 }}%
            </div>
            <div class="w-full h-1 bg-zinc-800 rounded-full mt-2 overflow-hidden">
              <div
                class="h-full bg-sky-500 rounded-full transition-all duration-500"
                :style="{ width: `${health.risk || 100}%` }"
              ></div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue';
import { Activity, HeartPulse, Link2, Recycle, ShieldCheck, Sparkles } from 'lucide-vue-next';
import apiClient from '@/api/client';

const health = ref<any>(null);
const llmElapsedMs = ref(0);
let pollTimer: any = null;
let elapsedTimer: any = null;

async function fetchHealth() {
  try {
    const res = await apiClient.get('/health-score');
    health.value = res.data;
  } catch {
    // 静默降级
  }
}

const metrics = computed(() => health.value?.metrics || {});

const scoreTheme = computed(() => {
  const score = health.value?.quality || 0;
  if (score >= 80) {
    return {
      text: 'text-emerald-400',
      bg: 'bg-emerald-500/10',
      border: 'border-emerald-500/30',
      badge: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
      label: '状态卓越',
    };
  }
  if (score >= 60) {
    return {
      text: 'text-amber-400',
      bg: 'bg-amber-500/10',
      border: 'border-amber-500/30',
      badge: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
      label: '状态良好',
    };
  }
  return {
    text: 'text-rose-400',
    bg: 'bg-rose-500/10',
    border: 'border-rose-500/30',
    badge: 'bg-rose-500/10 text-rose-400 border-rose-500/20',
    label: '需要关注',
  };
});

const formattedLlmElapsed = computed(() => {
  const sec = Math.floor(llmElapsedMs.value / 1000);
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
});

onMounted(() => {
  fetchHealth();
  pollTimer = setInterval(fetchHealth, 8000);
});

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer);
  if (elapsedTimer) clearInterval(elapsedTimer);
});
</script>
