<template>
  <div class="space-y-6 pb-16">
    <!-- 顶部标题与快速统计 -->
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
      <div>
        <h1 class="text-xl font-bold text-white tracking-tight">私有记忆管理与探索</h1>
        <p class="text-xs text-zinc-400 mt-1">按租户物理隔离检索全量事实、决策、工作流习惯与跨会话状态。</p>
      </div>

      <div class="flex items-center gap-3">
        <span class="text-xs px-3 py-1.5 rounded-lg bg-zinc-900 border border-zinc-800 text-zinc-300">
          共检索出 <b class="text-indigo-400">{{ total }}</b> 条记忆
        </span>
      </div>
    </div>

    <!-- 筛选控制栏 -->
    <div class="bg-[#18181b] border border-zinc-800/80 rounded-xl p-5 space-y-4">
      <!-- 搜索输入 + 分类与排序 -->
      <div class="flex flex-col md:flex-row gap-3">
        <div class="flex-1 relative">
          <input
            v-model="searchQuery"
            @keydown.enter="applyFilters"
            placeholder="搜索记忆标题、关键词、正文上下文..."
            class="w-full bg-zinc-900 border border-zinc-700/80 rounded-lg px-4 py-2 text-xs text-white placeholder-zinc-500 focus:outline-none focus:border-indigo-500 transition"
          />
        </div>

        <div class="flex items-center gap-2">
          <!-- 分类筛选 -->
          <select
            v-model="selectedCategory"
            @change="applyFilters"
            class="bg-zinc-900 border border-zinc-700/80 rounded-lg px-3 py-2 text-xs text-zinc-300 focus:outline-none focus:border-indigo-500 cursor-pointer"
          >
            <option value="">全部分类类型</option>
            <option v-for="cat in categories" :key="cat.category_id" :value="cat.category_id">
              {{ cat.name }} ({{ cat.count }})
            </option>
          </select>

          <!-- 排序依据 -->
          <select
            v-model="sortColumn"
            @change="applyFilters"
            class="bg-zinc-900 border border-zinc-700/80 rounded-lg px-3 py-2 text-xs text-zinc-300 focus:outline-none focus:border-indigo-500 cursor-pointer"
          >
            <option value="created_at">按创建时间排序</option>
            <option value="importance">按重要度排序</option>
            <option value="updated_at">按更新时间排序</option>
          </select>

          <button
            @click="applyFilters"
            class="bg-zinc-800 hover:bg-zinc-700 text-white font-medium px-4 py-2 rounded-lg text-xs transition border border-zinc-700"
          >
            筛选
          </button>
        </div>
      </div>

      <!-- 状态多选 Tab -->
      <div class="flex items-center justify-between border-t border-zinc-800/60 pt-3">
        <div class="flex items-center gap-1">
          <button
            v-for="st in statusTabs"
            :key="st.key"
            @click="switchStatus(st.key)"
            class="px-3 py-1.5 rounded-lg text-xs font-medium transition"
            :class="selectedStatus === st.key ? 'bg-indigo-600 text-white shadow-sm' : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900'"
          >
            {{ st.label }}
          </button>
        </div>

        <!-- 批量操作触发器 -->
        <div v-if="selectedIds.length > 0" class="flex items-center gap-2 bg-indigo-950/40 border border-indigo-500/30 px-3 py-1 rounded-lg text-xs">
          <span class="text-indigo-300">已选中 {{ selectedIds.length }} 项</span>
          <button @click="batchArchive" class="text-amber-400 hover:text-amber-300 font-medium ml-2">
            批量归档
          </button>
          <button @click="batchActivate" class="text-emerald-400 hover:text-emerald-300 font-medium ml-1">
            设为活跃
          </button>
          <button @click="selectedIds = []" class="text-zinc-400 hover:text-zinc-300 ml-1">
            取消
          </button>
        </div>
      </div>
    </div>

    <!-- 记忆列表主体 -->
    <div v-if="loading" class="text-center py-16 text-zinc-500 text-sm">
      正在加载租户物理库记忆...
    </div>
    <div v-else-if="memories.length === 0" class="text-center py-16 text-zinc-500 text-sm bg-[#18181b] border border-zinc-800 rounded-xl">
      未检索到符合条件的记忆记录
    </div>
    <div v-else class="space-y-3">
      <div
        v-for="mem in memories"
        :key="mem.id"
        class="bg-[#18181b] border border-zinc-800/80 rounded-xl p-5 hover:border-zinc-700 transition relative group"
      >
        <div class="flex items-start justify-between gap-4 mb-2">
          <div class="flex items-center gap-3">
            <input
              type="checkbox"
              :value="mem.id"
              v-model="selectedIds"
              class="w-4 h-4 rounded bg-zinc-900 border-zinc-700 text-indigo-600 focus:ring-indigo-500 cursor-pointer"
            />
            <span
              class="text-xs px-2 py-0.5 rounded font-medium border"
              :class="getStatusBadgeClass(mem.status)"
            >
              {{ mem.status }}
            </span>
            <span class="text-xs px-2 py-0.5 rounded bg-zinc-800/90 text-zinc-400 border border-zinc-700/50">
              {{ mem.type }}
            </span>
            <router-link
              :to="`/memory/${mem.id}`"
              class="text-sm font-semibold text-white hover:text-indigo-400 transition"
            >
              {{ mem.title || '无标题记忆' }}
            </router-link>
          </div>

          <div class="flex items-center gap-3 text-xs text-zinc-400">
            <span>重要度: <b class="text-zinc-200">{{ mem.importance }}</b></span>
            <span>置信度: <b class="text-zinc-200">{{ mem.confidence }}</b></span>
            <router-link
              :to="`/memory/${mem.id}`"
              class="text-indigo-400 hover:text-indigo-300 font-medium px-2 py-1 rounded hover:bg-zinc-800 transition"
            >
              详情 →
            </router-link>
          </div>
        </div>

        <p class="text-xs text-zinc-300 leading-relaxed line-clamp-3 ml-7">
          {{ mem.content }}
        </p>

        <div class="mt-3 ml-7 flex items-center justify-between text-[11px] text-zinc-500 border-t border-zinc-800/40 pt-2">
          <div class="flex items-center gap-3">
            <span>来源 Agent: <b class="text-zinc-400">{{ mem.source_agent || 'system' }}</b></span>
            <span>作用域: {{ mem.scope }}</span>
          </div>
          <span>创建于: {{ formatDate(mem.created_at) }}</span>
        </div>
      </div>
    </div>

    <!-- 分页器 -->
    <div v-if="totalPages > 1" class="flex items-center justify-between bg-[#18181b] border border-zinc-800 rounded-xl px-5 py-3 text-xs text-zinc-400">
      <div>
        显示第 {{ (page - 1) * pageSize + 1 }} 至 {{ Math.min(page * pageSize, total) }} 条，共 {{ total }} 条
      </div>
      <div class="flex items-center gap-2">
        <button
          @click="changePage(page - 1)"
          :disabled="page <= 1"
          class="px-3 py-1.5 rounded-lg border border-zinc-800 bg-zinc-900 hover:bg-zinc-800 disabled:opacity-40 transition"
        >
          上一页
        </button>
        <span class="text-zinc-200 font-medium px-2">{{ page }} / {{ totalPages }}</span>
        <button
          @click="changePage(page + 1)"
          :disabled="page >= totalPages"
          class="px-3 py-1.5 rounded-lg border border-zinc-800 bg-zinc-900 hover:bg-zinc-800 disabled:opacity-40 transition"
        >
          下一页
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import apiClient from '@/api/client';

const statusTabs = [
  { key: 'all', label: '全部状态' },
  { key: 'active', label: '活跃 (Active)' },
  { key: 'archived', label: '已归档 (Archived)' },
  { key: 'superseded', label: '已替代 (Superseded)' },
  { key: 'contradicted', label: '矛盾 (Contradicted)' },
];

const searchQuery = ref('');
const selectedStatus = ref('active');
const selectedCategory = ref('');
const sortColumn = ref('created_at');
const categories = ref<any[]>([]);

const memories = ref<any[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(20);
const totalPages = ref(1);
const loading = ref(false);
const selectedIds = ref<string[]>([]);

async function fetchCategories() {
  try {
    const res = await apiClient.get('/memories/categories');
    categories.value = res.data || [];
  } catch {}
}

async function fetchMemories() {
  loading.value = true;
  try {
    const res = await apiClient.post('/memories/filter', {
      page: page.value,
      size: pageSize.value,
      search_query: searchQuery.value,
      status: selectedStatus.value,
      category_ids: selectedCategory.value ? [selectedCategory.value] : [],
      sort_column: sortColumn.value,
      sort_direction: 'desc',
    });
    memories.value = res.data.items || res.data.memories || [];
    total.value = res.data.total || 0;
    totalPages.value = res.data.pages || 1;
  } catch (e) {
    console.error('获取记忆失败', e);
  } finally {
    loading.value = false;
  }
}

function applyFilters() {
  page.value = 1;
  fetchMemories();
}

function switchStatus(st: string) {
  selectedStatus.value = st;
  page.value = 1;
  fetchMemories();
}

function changePage(p: number) {
  if (p < 1 || p > totalPages.value) return;
  page.value = p;
  fetchMemories();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

async function batchArchive() {
  if (selectedIds.value.length === 0) return;
  try {
    await apiClient.post('/memories/actions/pause', {
      memory_ids: selectedIds.value,
      state: 'archived',
    });
    selectedIds.value = [];
    fetchMemories();
  } catch (e) {
    console.error('批量归档失败', e);
  }
}

async function batchActivate() {
  if (selectedIds.value.length === 0) return;
  try {
    await apiClient.post('/memories/actions/pause', {
      memory_ids: selectedIds.value,
      state: 'active',
    });
    selectedIds.value = [];
    fetchMemories();
  } catch (e) {
    console.error('批量激活失败', e);
  }
}

function getStatusBadgeClass(status: string) {
  if (status === 'active') return 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20';
  if (status === 'archived') return 'bg-zinc-800 text-zinc-400 border-zinc-700/50';
  if (status === 'superseded') return 'bg-purple-500/10 text-purple-400 border-purple-500/20';
  if (status === 'contradicted') return 'bg-amber-500/10 text-amber-400 border-amber-500/20';
  return 'bg-zinc-800 text-zinc-400 border-zinc-700';
}

function formatDate(d: string) {
  if (!d) return '';
  return d.replace('T', ' ').replace('Z', '').slice(0, 19);
}

onMounted(() => {
  fetchCategories();
  fetchMemories();
});
</script>
