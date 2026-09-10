<template>
  <div class="grid grid-cols-1 md:grid-cols-4 gap-4">
    <!-- 卡片 1: 待清理积压 -->
    <div class="bg-[#18181b] border border-zinc-800/80 rounded-xl p-5 hover:border-zinc-700 transition">
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-medium text-zinc-400">待清理积压</span>
        <span class="text-xs px-2 py-0.5 rounded bg-zinc-800 text-zinc-400">可用池</span>
      </div>
      <div class="text-3xl font-bold text-white tracking-tight">
        {{ metrics.pending_cleanup || 0 }}
      </div>
      <div class="text-[11px] text-zinc-400 mt-2 flex items-center gap-2">
        <span>过时: {{ metrics.stale || 0 }}</span>
        <span>·</span>
        <span>替代: {{ metrics.superseded || 0 }}</span>
        <span>·</span>
        <span class="text-amber-400">矛盾: {{ metrics.contradicted || 0 }}</span>
      </div>
    </div>

    <!-- 卡片 2: 矛盾待裁决 -->
    <div class="bg-[#18181b] border border-zinc-800/80 rounded-xl p-5 hover:border-zinc-700 transition relative overflow-hidden">
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-medium text-zinc-400">矛盾待裁决</span>
        <span
          class="text-xs px-2 py-0.5 rounded font-medium border"
          :class="signals.contradiction_actionable > 0 ? 'bg-amber-500/10 text-amber-400 border-amber-500/20' : 'bg-zinc-800 text-zinc-400 border-zinc-700/50'"
        >
          {{ signals.contradiction_actionable > 0 ? '待处理' : '无积压' }}
        </span>
      </div>
      <div class="text-3xl font-bold text-white tracking-tight flex items-baseline gap-2">
        <span :class="signals.contradiction_actionable > 0 ? 'text-amber-400' : 'text-white'">
          {{ signals.contradiction_actionable || 0 }}
        </span>
        <span class="text-xs font-normal text-zinc-400">项决策需复核</span>
      </div>
      <div class="mt-2 flex items-center justify-between">
        <span class="text-[11px] text-zinc-400">LLM 自动巡检研判</span>
        <router-link to="/governance" class="text-xs text-indigo-400 hover:text-indigo-300 font-medium">
          前往治理 →
        </router-link>
      </div>
    </div>

    <!-- 卡片 3: 活跃记忆与未触碰 -->
    <div class="bg-[#18181b] border border-zinc-800/80 rounded-xl p-5 hover:border-zinc-700 transition">
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-medium text-zinc-400">活跃高频记忆</span>
        <span class="text-xs px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">Active</span>
      </div>
      <div class="text-3xl font-bold text-white tracking-tight">
        {{ metrics.active || 0 }}
      </div>
      <div class="text-[11px] text-zinc-400 mt-2 flex items-center gap-1.5">
        <span>从未使用:</span>
        <b class="text-zinc-300 font-medium">{{ metrics.active_never_accessed || 0 }} 条</b>
        <span>({{ 100 - (metrics.active_reuse_coverage || 0) }}%)</span>
      </div>
    </div>

    <!-- 卡片 4: 协同 Agent 与调用 -->
    <div class="bg-[#18181b] border border-zinc-800/80 rounded-xl p-5 hover:border-zinc-700 transition">
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-medium text-zinc-400">协同 Agent 矩阵</span>
        <span class="text-xs px-2 py-0.5 rounded bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">Multi-Agent</span>
      </div>
      <div class="text-3xl font-bold text-white tracking-tight flex items-baseline gap-2">
        <span>{{ totalApps }}</span>
        <span class="text-xs font-normal text-zinc-400">个智能体在线</span>
      </div>
      <div class="mt-2 flex items-center justify-between">
        <span class="text-[11px] text-zinc-400">Claude / Hermes / Codex</span>
        <router-link to="/apps" class="text-xs text-indigo-400 hover:text-indigo-300 font-medium">
          查看详情 →
        </router-link>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';

const props = defineProps<{
  healthData: any;
  totalApps: number;
}>();

const metrics = computed(() => props.healthData?.metrics || {});
const signals = computed(() => props.healthData?.signals || {});
</script>
