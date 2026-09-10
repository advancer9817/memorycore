<template>
  <div class="space-y-6 pb-16 max-w-5xl mx-auto">
    <!-- 顶栏返回与快捷操作 -->
    <div class="flex items-center justify-between">
      <router-link to="/memories" class="text-xs text-zinc-400 hover:text-white flex items-center gap-1.5 transition">
        <span>←</span> 返回记忆列表
      </router-link>

      <div class="flex items-center gap-2">
        <button
          @click="toggleStatus"
          class="px-3 py-1.5 rounded-lg border text-xs font-medium transition"
          :class="memory?.status === 'active' ? 'border-zinc-700 bg-zinc-800 text-zinc-300 hover:bg-zinc-700' : 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20'"
        >
          {{ memory?.status === 'active' ? '归档此记忆' : '激活为 Active' }}
        </button>
        <button
          @click="saveMemory"
          :disabled="saving"
          class="px-4 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-xs font-medium text-white transition disabled:opacity-50 shadow-md shadow-indigo-600/20"
        >
          {{ saving ? '保存中...' : '保存更改' }}
        </button>
      </div>
    </div>

    <div v-if="loading" class="text-center py-16 text-zinc-500 text-sm">
      正在加载记忆详情...
    </div>
    <div v-else-if="!memory" class="text-center py-16 text-zinc-500 text-sm">
      未找到该记忆记录
    </div>
    <div v-else class="space-y-6">
      <!-- 基础元数据卡片 -->
      <div class="bg-[#18181b] border border-zinc-800/80 rounded-xl p-6 space-y-4">
        <div class="flex items-center gap-3">
          <span class="text-xs px-2.5 py-0.5 rounded-full font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
            {{ memory.status }}
          </span>
          <span class="text-xs px-2.5 py-0.5 rounded-full bg-zinc-800 text-zinc-400 border border-zinc-700">
            {{ memory.type }}
          </span>
          <span class="text-xs text-zinc-500">ID: {{ memory.id }}</span>
        </div>

        <div>
          <label class="block text-xs font-medium text-zinc-400 mb-1.5">记忆标题</label>
          <input
            v-model="memory.title"
            class="w-full bg-zinc-900 border border-zinc-700/80 rounded-lg px-4 py-2.5 text-sm font-semibold text-white focus:outline-none focus:border-indigo-500"
          />
        </div>

        <div>
          <label class="block text-xs font-medium text-zinc-400 mb-1.5">核心正文上下文</label>
          <textarea
            v-model="memory.content"
            rows="6"
            class="w-full bg-zinc-900 border border-zinc-700/80 rounded-lg p-4 text-xs text-zinc-200 leading-relaxed focus:outline-none focus:border-indigo-500"
          ></textarea>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-3 gap-4 pt-2 border-t border-zinc-800/60 text-xs">
          <div>
            <label class="text-zinc-400 block mb-1">重要度 (Importance): {{ memory.importance }}</label>
            <input
              type="range"
              min="0"
              max="1"
              step="0.05"
              v-model.number="memory.importance"
              class="w-full accent-indigo-500"
            />
          </div>
          <div>
            <span class="text-zinc-400 block mb-1">置信度 (Confidence): {{ memory.confidence }}</span>
            <div class="text-zinc-200 font-medium py-1">{{ (memory.confidence * 100).toFixed(0) }}%</div>
          </div>
          <div>
            <span class="text-zinc-400 block mb-1">来源智能体 (Source Agent)</span>
            <div class="text-zinc-200 font-medium py-1">{{ memory.source_agent || 'system' }}</div>
          </div>
        </div>
      </div>

      <!-- 关联实体与知识链接 -->
      <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
        <!-- 关联实体 -->
        <div class="bg-[#18181b] border border-zinc-800/80 rounded-xl p-6">
          <h3 class="text-sm font-semibold text-white mb-3 flex items-center justify-between">
            <span>关联知识实体 (Entities)</span>
            <span class="text-xs text-zinc-500">{{ memory.entities?.length || 0 }} 个</span>
          </h3>
          <div v-if="memory.entities && memory.entities.length > 0" class="flex flex-wrap gap-2">
            <span
              v-for="e in memory.entities"
              :key="e.entity"
              class="text-xs px-2.5 py-1 rounded-md bg-zinc-900 border border-zinc-700/60 text-zinc-300"
            >
              {{ e.entity }}
              <span class="text-[10px] text-zinc-500 ml-1">({{ e.entity_type || 'tag' }})</span>
            </span>
          </div>
          <div v-else class="text-xs text-zinc-500 py-4 text-center">
            暂无抽取的命名实体
          </div>
        </div>

        <!-- 语义关联 -->
        <div class="bg-[#18181b] border border-zinc-800/80 rounded-xl p-6">
          <h3 class="text-sm font-semibold text-white mb-3 flex items-center justify-between">
            <span>前驱与关联网络 (Links)</span>
            <span class="text-xs text-zinc-500">{{ memory.links?.length || 0 }} 条</span>
          </h3>
          <div v-if="memory.links && memory.links.length > 0" class="space-y-2">
            <div
              v-for="l in memory.links"
              :key="l.id"
              class="bg-zinc-900/60 border border-zinc-800 rounded-lg p-3 text-xs flex items-center justify-between"
            >
              <div class="max-w-[75%] truncate">
                <span class="text-[10px] px-1.5 py-0.5 rounded bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 mr-2">
                  {{ l.relation_type }}
                </span>
                <span class="text-zinc-200 font-medium truncate">{{ l.target_title || l.target_id }}</span>
              </div>
              <router-link :to="`/memory/${l.target_id}`" class="text-indigo-400 hover:text-indigo-300">
                查看 →
              </router-link>
            </div>
          </div>
          <div v-else class="text-xs text-zinc-500 py-4 text-center">
            暂无关联网络连线
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { useRoute } from 'vue-router';
import apiClient from '@/api/client';

const route = useRoute();
const memoryId = route.params.id as string;
const memory = ref<any>(null);
const loading = ref(false);
const saving = ref(false);

async function fetchDetail() {
  loading.value = true;
  try {
    const res = await apiClient.get(`/memories/${memoryId}`);
    memory.value = res.data;
  } catch (e) {
    console.error('获取记忆详情失败', e);
  } finally {
    loading.value = false;
  }
}

async function saveMemory() {
  if (!memory.value) return;
  saving.value = true;
  try {
    await apiClient.put(`/memories/${memoryId}`, {
      title: memory.value.title,
      content: memory.value.content,
      importance: memory.value.importance,
      status: memory.value.status,
    });
    alert('保存成功！');
  } catch (e) {
    console.error('保存失败', e);
    alert('保存失败，请检查网络');
  } finally {
    saving.value = false;
  }
}

async function toggleStatus() {
  if (!memory.value) return;
  const nextStatus = memory.value.status === 'active' ? 'archived' : 'active';
  try {
    await apiClient.put(`/memories/${memoryId}`, {
      status: nextStatus,
    });
    memory.value.status = nextStatus;
  } catch (e) {
    console.error('状态切换失败', e);
  }
}

onMounted(() => {
  fetchDetail();
});
</script>
