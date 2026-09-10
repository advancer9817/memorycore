<template>
  <div class="mcore-card rounded-2xl overflow-hidden shadow-lg">
    <div class="flex items-center justify-between px-6 py-4 border-b border-zinc-800/80">
      <div class="flex items-center gap-2">
        <FlaskConical class="h-4 w-4 text-violet-400" />
        <h2 class="text-sm font-semibold text-zinc-200">上下文召回实验台 (Context Lab)</h2>
        <span class="text-xs text-zinc-500 font-normal">单 SQL 混合余弦与三元词算子下推与 Token 预算熔断实测</span>
      </div>
      <span class="text-xs px-2.5 py-0.5 rounded-full bg-violet-500/10 text-violet-400 border border-violet-500/20 font-mono">
        Budget: {{ tokenBudget }} tok
      </span>
    </div>

    <div class="p-6 space-y-5">
      <!-- 搜索输入与参数调节 -->
      <div class="flex flex-col sm:flex-row gap-3">
        <div class="flex-1 relative">
          <Search class="absolute left-3.5 top-3 h-4 w-4 text-zinc-500" />
          <input
            v-model="query"
            @keydown.enter="handleTest"
            placeholder="输入测试提示词（如: COW 模板库、系统服务、开发环境、API超时）..."
            class="w-full bg-zinc-900/80 border border-zinc-700/80 rounded-xl pl-10 pr-4 py-2.5 text-xs text-white placeholder-zinc-500 focus:outline-none focus:border-violet-500 transition"
          />
        </div>

        <div class="flex items-center gap-3">
          <button
            @click="handleTest"
            :disabled="loading || !query.trim()"
            class="px-5 py-2.5 rounded-xl bg-violet-600 hover:bg-violet-500 disabled:opacity-50 text-xs font-semibold text-white transition flex items-center gap-2 shadow-lg shadow-violet-600/20"
          >
            <Loader2 v-if="loading" class="h-3.5 w-3.5 animate-spin" />
            <span>{{ loading ? '测验计算中...' : '开始实验' }}</span>
          </button>
        </div>
      </div>

      <!-- 实验追踪 Trace 雷达指标卡 -->
      <div v-if="result && result.trace" class="grid grid-cols-2 sm:grid-cols-5 gap-3">
        <div class="bg-zinc-950/50 p-3 rounded-xl border border-zinc-800/80">
          <div class="text-[11px] text-zinc-500">候选集数量</div>
          <div class="text-base font-bold text-white mt-1">{{ result.trace.total_candidates }}</div>
        </div>
        <div class="bg-zinc-950/50 p-3 rounded-xl border border-zinc-800/80">
          <div class="text-[11px] text-zinc-500">最终注入项</div>
          <div class="text-base font-bold text-emerald-400 mt-1">{{ result.trace.used_count }}</div>
        </div>
        <div class="bg-zinc-950/50 p-3 rounded-xl border border-zinc-800/80">
          <div class="text-[11px] text-zinc-500">向量平均分</div>
          <div class="text-base font-bold text-violet-400 mt-1">{{ (result.trace.vector_avg_score || 0).toFixed(2) }}</div>
        </div>
        <div class="bg-zinc-950/50 p-3 rounded-xl border border-zinc-800/80">
          <div class="text-[11px] text-zinc-500">检索模式</div>
          <div class="text-xs font-bold text-indigo-300 mt-1 truncate">{{ result.trace.retrieval_mode }}</div>
        </div>
        <div class="bg-zinc-950/50 p-3 rounded-xl border border-zinc-800/80">
          <div class="text-[11px] text-zinc-500">跨通道召回率</div>
          <div class="text-base font-bold text-sky-400 mt-1">{{ (result.trace.cross_retrieval_rate * 100).toFixed(0) }}%</div>
        </div>
      </div>

      <!-- 命中的上下文记忆卡片 -->
      <div v-if="result && result.items && result.items.length > 0" class="space-y-3">
        <div
          v-for="item in result.items"
          :key="item.id"
          class="bg-zinc-950/60 border border-zinc-800/80 rounded-xl p-4 hover:border-zinc-700 transition space-y-2"
        >
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <span class="w-5 h-5 rounded-full bg-violet-600/20 text-violet-400 text-xs font-bold flex items-center justify-center border border-violet-500/30">
                {{ item.rank }}
              </span>
              <span class="text-xs px-2 py-0.5 rounded bg-zinc-800 text-zinc-400 border border-zinc-700">
                {{ item.type }}
              </span>
              <span class="text-xs font-semibold text-zinc-200">{{ item.title }}</span>
            </div>

            <div class="flex items-center gap-3 text-xs">
              <span class="text-zinc-400">综合得分: <b class="text-emerald-400 font-mono">{{ item.rank_score }}</b></span>
              <div class="flex items-center gap-1">
                <span
                  v-for="s in item.retrieval_sources"
                  :key="s"
                  class="text-[11px] px-1.5 py-0.2 rounded bg-indigo-500/10 text-indigo-400 border border-indigo-500/20"
                >
                  {{ s }}
                </span>
              </div>
            </div>
          </div>

          <p class="text-xs text-zinc-300 leading-relaxed font-sans bg-zinc-900/40 p-3 rounded-lg border border-zinc-900">
            {{ item.content }}
          </p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { FlaskConical, Search, Loader2 } from 'lucide-vue-next';
import apiClient from '@/api/client';

const query = ref('COW 模板库');
const tokenBudget = ref(2000);
const loading = ref(false);
const result = ref<any>(null);

async function handleTest() {
  if (!query.value.trim()) return;
  loading.value = true;
  try {
    const res = await apiClient.post('/context/test', {
      query: query.value.trim(),
      token_budget: tokenBudget.value,
    });
    result.value = res.data;
  } catch (e) {
    console.error('ContextLab 测试失败', e);
  } finally {
    loading.value = false;
  }
}
</script>
