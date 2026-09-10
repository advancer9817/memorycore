<template>
  <div class="space-y-6 pb-16">
    <!-- 顶栏概览 -->
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
      <div>
        <h1 class="text-xl font-bold text-white tracking-tight">记忆治理与矛盾裁决中心</h1>
        <p class="text-xs text-zinc-400 mt-1">LLM 巡检与规则引擎驱动的自动矛盾发现、语义去重与知识演化审批流。</p>
      </div>

      <div class="flex items-center gap-3">
        <button
          v-if="pendingCount > 0"
          @click="batchApplyAll"
          :disabled="batchApplying"
          class="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-xs font-semibold text-white transition disabled:opacity-50 shadow-md shadow-indigo-600/20"
        >
          {{ batchApplying ? '审批中...' : `一键全量应用 (${pendingCount} 项)` }}
        </button>
      </div>
    </div>

    <!-- 治理核心指标行 -->
    <div class="grid grid-cols-1 md:grid-cols-4 gap-4">
      <div class="bg-[#18181b] border border-zinc-800/80 rounded-xl p-5">
        <div class="text-xs text-zinc-400 mb-1">待复核审查</div>
        <div class="text-2xl font-bold text-amber-400 tracking-tight">{{ metrics.pending_reviews || 0 }}</div>
        <div class="text-[11px] text-zinc-500 mt-1">需人工复核或一键应用</div>
      </div>
      <div class="bg-[#18181b] border border-zinc-800/80 rounded-xl p-5">
        <div class="text-xs text-zinc-400 mb-1">已裁决解决矛盾</div>
        <div class="text-2xl font-bold text-emerald-400 tracking-tight">{{ metrics.applied_decisions || 0 }}</div>
        <div class="text-[11px] text-zinc-500 mt-1">历史自动与手动累计</div>
      </div>
      <div class="bg-[#18181b] border border-zinc-800/80 rounded-xl p-5">
        <div class="text-xs text-zinc-400 mb-1">已检测矛盾总数</div>
        <div class="text-2xl font-bold text-white tracking-tight">{{ metrics.contradictions || 0 }}</div>
        <div class="text-[11px] text-zinc-500 mt-1">跨会话事实碰撞拦截</div>
      </div>
      <div class="bg-[#18181b] border border-zinc-800/80 rounded-xl p-5">
        <div class="text-xs text-zinc-400 mb-1">自动通过率</div>
        <div class="text-2xl font-bold text-indigo-400 tracking-tight">{{ metrics.auto_approval_rate || 0 }}%</div>
        <div class="text-[11px] text-zinc-500 mt-1">高置信度自愈闭环</div>
      </div>
    </div>

    <!-- 状态筛选 Tab -->
    <div class="flex items-center gap-1 bg-[#18181b] border border-zinc-800/80 rounded-xl p-2">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        @click="switchTab(tab.key)"
        class="px-4 py-1.5 rounded-lg text-xs font-medium transition"
        :class="currentTab === tab.key ? 'bg-indigo-600 text-white' : 'text-zinc-400 hover:text-white hover:bg-zinc-800'"
      >
        {{ tab.label }}
      </button>
    </div>

    <!-- 决策列表 -->
    <div v-if="loading" class="text-center py-16 text-zinc-500 text-sm">
      正在加载治理决策队列...
    </div>
    <div v-else-if="decisions.length === 0" class="text-center py-16 text-zinc-500 text-sm bg-[#18181b] border border-zinc-800 rounded-xl">
      当前队列无待处理决策项
    </div>
    <div v-else class="space-y-4">
      <div
        v-for="d in decisions"
        :key="d.id"
        class="bg-[#18181b] border border-zinc-800/80 rounded-xl p-6 hover:border-zinc-700 transition"
      >
        <div class="flex items-center justify-between mb-3">
          <div class="flex items-center gap-3">
            <span
              class="text-xs px-2.5 py-0.5 rounded-full font-medium border"
              :class="d.review_status === 'applied' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : 'bg-amber-500/10 text-amber-400 border-amber-500/20'"
            >
              {{ d.review_status }}
            </span>
            <span class="text-xs px-2.5 py-0.5 rounded-full bg-zinc-800 text-zinc-300 border border-zinc-700">
              {{ d.decision_type }}
            </span>
            <span class="text-xs text-zinc-400">建议动作: <b class="text-indigo-400">{{ d.recommended_action }}</b></span>
          </div>

          <div v-if="d.review_status === 'pending' || d.review_status === 'needs_review'" class="flex items-center gap-2">
            <button
              @click="applyOne(d.id)"
              class="px-3 py-1 rounded-md bg-emerald-600 hover:bg-emerald-500 text-xs font-medium text-white transition shadow-sm"
            >
              同意应用
            </button>
            <button
              @click="rejectOne(d.id)"
              class="px-3 py-1 rounded-md bg-zinc-800 hover:bg-zinc-700 text-xs font-medium text-zinc-300 transition border border-zinc-700"
            >
              驳回
            </button>
          </div>
        </div>

        <div class="bg-zinc-900/60 border border-zinc-800/60 rounded-lg p-3 text-xs text-zinc-300 leading-relaxed mb-3">
          <b class="text-zinc-400">研判依据: </b> {{ d.policy_reason || 'LLM 语义巡检研判产生' }}
        </div>

        <div class="flex items-center justify-between text-[11px] text-zinc-500">
          <span>决策 ID: {{ d.id }}</span>
          <span>生成于: {{ d.created_at }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import apiClient from '@/api/client';

const tabs = [
  { key: 'all', label: '全部决策' },
  { key: 'needs_review', label: '待复核审查' },
  { key: 'applied', label: '已生效应用' },
  { key: 'rejected', label: '已驳回' },
];

const currentTab = ref('needs_review');
const metrics = ref<any>({});
const decisions = ref<any[]>([]);
const loading = ref(false);
const batchApplying = ref(false);

const pendingCount = computed(() => metrics.value.pending_reviews || 0);

async function fetchMetrics() {
  try {
    const res = await apiClient.get('/governance/metrics');
    metrics.value = res.data;
  } catch (e) {
    console.error('获取治理指标失败', e);
  }
}

async function fetchDecisions() {
  loading.value = true;
  try {
    const statusParam = currentTab.value === 'all' ? '' : currentTab.value;
    const res = await apiClient.get(`/governance/decisions?status=${statusParam}&page_size=50`);
    decisions.value = res.data.items || res.data.decisions || [];
  } catch (e) {
    console.error('获取决策列表失败', e);
  } finally {
    loading.value = false;
  }
}

function switchTab(t: string) {
  currentTab.value = t;
  fetchDecisions();
}

async function applyOne(id: string) {
  try {
    await apiClient.post(`/governance/${id}/apply`);
    fetchMetrics();
    fetchDecisions();
  } catch (e) {
    console.error('应用决策失败', e);
  }
}

async function rejectOne(id: string) {
  try {
    await apiClient.post(`/governance/${id}/reject`);
    fetchMetrics();
    fetchDecisions();
  } catch (e) {
    console.error('驳回决策失败', e);
  }
}

async function batchApplyAll() {
  const pendingIds = decisions.value
    .filter((d) => d.review_status === 'pending' || d.review_status === 'needs_review')
    .map((d) => d.id);
  if (pendingIds.length === 0) return;

  batchApplying.value = true;
  try {
    await apiClient.post('/governance/batch/apply', { decision_ids: pendingIds });
    fetchMetrics();
    fetchDecisions();
  } catch (e) {
    console.error('批量审批失败', e);
  } finally {
    batchApplying.value = false;
  }
}

onMounted(() => {
  fetchMetrics();
  fetchDecisions();
});
</script>
