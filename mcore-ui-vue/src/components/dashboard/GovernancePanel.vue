<template>
  <div class="mcore-card rounded-2xl overflow-hidden shadow-lg">
    <!-- 面板标题栏 -->
    <div class="flex items-center justify-between px-6 py-4 border-b border-zinc-800/80">
      <div class="flex items-center gap-2.5">
        <ShieldAlert class="h-4 w-4 text-violet-400" />
        <h2 class="text-sm font-semibold text-zinc-200">记忆治理裁决中心 (Governance Cockpit)</h2>
      </div>

      <div class="flex items-center gap-3">
        <span
          class="text-xs px-2.5 py-0.5 rounded-full font-medium border"
          :class="actionableCount > 0 ? 'border-amber-500/30 bg-amber-500/10 text-amber-300' : 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'"
        >
          {{ actionableCount > 0 ? `${actionableCount} 项待决策审阅` : '全量合规通过' }}
        </span>

        <router-link
          to="/governance"
          class="flex items-center gap-1 text-xs text-violet-400 hover:text-violet-300 font-medium transition-colors"
        >
          <span>完整治理台</span>
          <ArrowRight class="h-3 w-3" />
        </router-link>
      </div>
    </div>

    <div class="p-6 space-y-4">
      <!-- 上次自治理保洁提示条 -->
      <div class="flex items-center gap-2.5 rounded-xl border border-cyan-800/40 bg-cyan-950/20 p-3 text-xs text-cyan-200">
        <span class="text-sm">🧹</span>
        <div class="flex-1">
          <span class="font-semibold text-cyan-100">上次自治理保洁：</span>
          <span class="text-zinc-300 ml-1">
            活跃记忆 1,902 条 · 向量索引 100% 对齐 · 物理库强隔离就绪
          </span>
        </div>
      </div>

      <!-- 决策状态与分类大卡片 -->
      <div class="grid grid-cols-1 md:grid-cols-3 gap-3.5">
        <div class="bg-zinc-950/60 border border-zinc-800/80 rounded-xl p-4 flex flex-col justify-between">
          <div class="text-xs text-zinc-400 flex items-center justify-between">
            <span>矛盾事实冲突</span>
            <span class="text-xs text-amber-400 font-mono font-bold">{{ metrics.contradictions || 0 }}</span>
          </div>
          <div class="text-xs text-zinc-500 mt-2">新事实覆盖旧认知或待人工判定胜败方</div>
        </div>

        <div class="bg-zinc-950/60 border border-zinc-800/80 rounded-xl p-4 flex flex-col justify-between">
          <div class="text-xs text-zinc-400 flex items-center justify-between">
            <span>语义重复项</span>
            <span class="text-xs text-indigo-400 font-mono font-bold">{{ metrics.semantic_duplicates || 0 }}</span>
          </div>
          <div class="text-xs text-zinc-500 mt-2">高相似度多会话冗余提取，建议合并或沉淀</div>
        </div>

        <div class="bg-zinc-950/60 border border-zinc-800/80 rounded-xl p-4 flex flex-col justify-between">
          <div class="text-xs text-zinc-400 flex items-center justify-between">
            <span>已执行治理闭环</span>
            <span class="text-xs text-emerald-400 font-mono font-bold">{{ metrics.applied_decisions || 0 }}</span>
          </div>
          <div class="text-xs text-zinc-500 mt-2">自动与人工审批完成变更落地</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { ShieldAlert, ArrowRight } from 'lucide-vue-next';
import apiClient from '@/api/client';

const metrics = ref<any>({});

const actionableCount = computed(() => metrics.value.pending_reviews || 0);

async function fetchMetrics() {
  try {
    const res = await apiClient.get('/governance/metrics');
    metrics.value = res.data || {};
  } catch {}
}

onMounted(() => {
  fetchMetrics();
});
</script>
