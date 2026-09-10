<template>
  <div class="mcore-card rounded-2xl overflow-hidden shadow-lg">
    <div class="flex items-center justify-between px-6 py-4 border-b border-zinc-800/80">
      <div class="flex items-center gap-2">
        <SlidersHorizontal class="h-4 w-4 text-emerald-400" />
        <h2 class="text-sm font-semibold text-zinc-200">巡检与 LLM 治理调优 (Curator Tuning)</h2>
        <span class="text-xs text-zinc-500 font-normal">动态调节提示词风格、相似度去重门槛与批处理上限</span>
      </div>

      <div class="flex items-center gap-2">
        <button
          @click="saveTuning"
          :disabled="saving"
          class="px-3.5 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-xs font-semibold text-white transition flex items-center gap-1.5 shadow-md shadow-emerald-600/20 disabled:opacity-50"
        >
          <SaveIcon class="h-3.5 w-3.5" />
          <span>{{ saving ? '保存中...' : '保存配置' }}</span>
        </button>
      </div>
    </div>

    <div class="p-6 space-y-5">
      <!-- 预设选择器 -->
      <div class="flex items-center gap-2">
        <span class="text-xs text-zinc-400 font-medium">快捷治理预设:</span>
        <div class="flex items-center bg-zinc-900 border border-zinc-800 rounded-lg p-0.5">
          <button
            v-for="p in ['economy', 'balanced', 'precision']"
            :key="p"
            @click="applyPreset(p)"
            class="px-3 py-1 rounded-md text-xs font-medium capitalize transition"
            :class="selectedPreset === p ? 'bg-zinc-800 text-emerald-400 shadow-sm' : 'text-zinc-400 hover:text-zinc-200'"
          >
            {{ p }}
          </button>
        </div>
      </div>

      <!-- 四大核心参数滑块网格 -->
      <div class="grid grid-cols-1 md:grid-cols-2 gap-5 pt-2">
        <!-- 温度 -->
        <div class="bg-zinc-950/50 p-4 rounded-xl border border-zinc-800/80 space-y-2">
          <div class="flex items-center justify-between text-xs">
            <span class="text-zinc-300 font-medium">模型采样温度 (Temperature)</span>
            <span class="font-mono text-emerald-400 font-bold">{{ config.temperature }}</span>
          </div>
          <input
            type="range"
            min="0"
            max="1"
            step="0.05"
            v-model.number="config.temperature"
            class="w-full accent-emerald-500 cursor-pointer"
          />
          <div class="text-[11px] text-zinc-500">更低值提升决策严谨度，更高值提升语义联想能力。</div>
        </div>

        <!-- 相似度阈值 -->
        <div class="bg-zinc-950/50 p-4 rounded-xl border border-zinc-800/80 space-y-2">
          <div class="flex items-center justify-between text-xs">
            <span class="text-zinc-300 font-medium">去重相似度门槛 (Sim Threshold)</span>
            <span class="font-mono text-indigo-400 font-bold">{{ config.sim_threshold }}</span>
          </div>
          <input
            type="range"
            min="0.4"
            max="0.95"
            step="0.02"
            v-model.number="config.sim_threshold"
            class="w-full accent-indigo-500 cursor-pointer"
          />
          <div class="text-[11px] text-zinc-500">判定为语义重复候选的最小余弦相似度。</div>
        </div>

        <!-- 批处理大小 -->
        <div class="bg-zinc-950/50 p-4 rounded-xl border border-zinc-800/80 space-y-2">
          <div class="flex items-center justify-between text-xs">
            <span class="text-zinc-300 font-medium">单批次治理容量 (Batch Size)</span>
            <span class="font-mono text-sky-400 font-bold">{{ config.batch_size }}</span>
          </div>
          <input
            type="range"
            min="5"
            max="50"
            step="5"
            v-model.number="config.batch_size"
            class="w-full accent-sky-500 cursor-pointer"
          />
          <div class="text-[11px] text-zinc-500">每次 LLM 巡检推理并发输入的最大记忆条数。</div>
        </div>

        <!-- 自动保留门槛 -->
        <div class="bg-zinc-950/50 p-4 rounded-xl border border-zinc-800/80 space-y-2">
          <div class="flex items-center justify-between text-xs">
            <span class="text-zinc-300 font-medium">保留置信度门槛 (Keep Threshold)</span>
            <span class="font-mono text-amber-400 font-bold">{{ config.keep_threshold }}</span>
          </div>
          <input
            type="range"
            min="0"
            max="0.3"
            step="0.01"
            v-model.number="config.keep_threshold"
            class="w-full accent-amber-500 cursor-pointer"
          />
          <div class="text-[11px] text-zinc-500">低于此阈值的模糊条目将优先被纳入淘汰或归档。</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { SlidersHorizontal, SaveIcon } from 'lucide-vue-next';
import apiClient from '@/api/client';

const selectedPreset = ref('balanced');
const saving = ref(false);

const config = ref<any>({
  temperature: 0.4,
  sim_threshold: 0.60,
  batch_size: 10,
  keep_threshold: 0.05,
});

const PRESETS: Record<string, any> = {
  economy: { temperature: 0.2, sim_threshold: 0.75, batch_size: 20, keep_threshold: 0.1 },
  balanced: { temperature: 0.4, sim_threshold: 0.60, batch_size: 10, keep_threshold: 0.05 },
  precision: { temperature: 0.3, sim_threshold: 0.82, batch_size: 10, keep_threshold: 0.02 },
};

function applyPreset(p: string) {
  selectedPreset.value = p;
  Object.assign(config.value, PRESETS[p]);
}

async function fetchConfig() {
  try {
    const res = await apiClient.get('/config');
    if (res.data) {
      config.value.temperature = res.data.temperature ?? 0.4;
      config.value.sim_threshold = res.data.sim_threshold ?? 0.6;
      config.value.batch_size = res.data.batch_size ?? 10;
      config.value.keep_threshold = res.data.keep_threshold ?? 0.05;
    }
  } catch {}
}

async function saveTuning() {
  saving.value = true;
  try {
    await apiClient.put('/config', config.value);
    alert('治理调优参数已成功同步至后端！');
  } catch (e) {
    console.error('保存配置失败', e);
  } finally {
    saving.value = false;
  }
}

onMounted(() => {
  fetchConfig();
});
</script>
