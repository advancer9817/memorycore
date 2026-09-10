<template>
  <div class="space-y-6 pb-16 max-w-5xl mx-auto">
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-xl font-bold text-white tracking-tight">用户长期画像与偏好中心</h1>
        <p class="text-xs text-zinc-400 mt-1">跨会话提炼的高置信度个人事实、编码风格与工程工作流习惯。</p>
      </div>

      <button
        @click="showAddModal = true"
        class="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-xs font-semibold text-white transition shadow-md shadow-indigo-600/20"
      >
        + 添加偏好属性
      </button>
    </div>

    <!-- 属性列表 -->
    <div class="bg-[#18181b] border border-zinc-800/80 rounded-xl p-6">
      <h2 class="text-sm font-semibold text-white mb-4 flex items-center justify-between">
        <span>提炼固化的用户画像属性 (Attributes)</span>
        <span class="text-xs text-zinc-400 font-normal">共 {{ attributes.length }} 项</span>
      </h2>

      <div v-if="attributes.length === 0" class="text-xs text-zinc-500 py-8 text-center">
        暂未提取到画像属性
      </div>
      <div v-else class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div
          v-for="attr in attributes"
          :key="attr.key"
          class="bg-zinc-900/60 border border-zinc-800/80 rounded-xl p-4 hover:border-zinc-700 transition"
        >
          <div class="flex items-center justify-between mb-2">
            <span class="text-xs font-bold text-indigo-400 uppercase tracking-wider">{{ attr.key }}</span>
            <span class="text-[10px] px-2 py-0.5 rounded-full bg-zinc-800 text-zinc-400">
              置信度: {{ (attr.confidence * 100).toFixed(0) }}%
            </span>
          </div>
          <div class="text-xs text-zinc-200 leading-relaxed font-mono bg-zinc-950/60 p-2.5 rounded-lg border border-zinc-900">
            {{ attr.value }}
          </div>
        </div>
      </div>
    </div>

    <!-- 关联核心身份记忆 -->
    <div class="bg-[#18181b] border border-zinc-800/80 rounded-xl p-6">
      <h2 class="text-sm font-semibold text-white mb-4">
        <span>身份与偏好事实记忆 (User Profile Memories)</span>
      </h2>

      <div v-if="facts.length === 0" class="text-xs text-zinc-500 py-8 text-center">
        暂无身份事实类记忆
      </div>
      <div v-else class="space-y-3">
        <div
          v-for="f in facts"
          :key="f.id"
          class="bg-zinc-900/40 border border-zinc-800/60 rounded-lg p-4 text-xs hover:border-zinc-700 transition"
        >
          <div class="flex items-center justify-between mb-1">
            <span class="text-zinc-200 font-medium">{{ f.title || f.id }}</span>
            <span class="text-indigo-400 font-mono text-[10px]">Score: {{ f.importance }}</span>
          </div>
          <p class="text-zinc-400 text-[11px] leading-relaxed">{{ f.content }}</p>
        </div>
      </div>
    </div>

    <!-- 新增弹窗 -->
    <div v-if="showAddModal" class="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div class="bg-[#18181b] border border-zinc-800 rounded-2xl max-w-md w-full p-6 space-y-4 shadow-2xl">
        <h3 class="text-base font-bold text-white">添加长期偏好属性</h3>
        <div>
          <label class="block text-xs font-medium text-zinc-400 mb-1">属性名 (Attribute Key)</label>
          <input
            v-model="newAttrKey"
            placeholder="例如: coding_style, shell_preference"
            class="w-full bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-indigo-500"
          />
        </div>
        <div>
          <label class="block text-xs font-medium text-zinc-400 mb-1">属性值 (Value)</label>
          <textarea
            v-model="newAttrVal"
            rows="3"
            placeholder="例如: 偏好单步终端执行，严禁使用 && 组合指令"
            class="w-full bg-zinc-900 border border-zinc-700 rounded-lg p-3 text-xs text-white focus:outline-none focus:border-indigo-500"
          ></textarea>
        </div>
        <div class="flex justify-end gap-2 pt-2">
          <button @click="showAddModal = false" class="px-4 py-2 rounded-lg text-xs text-zinc-400 hover:text-white">取消</button>
          <button @click="submitAddAttr" class="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-xs font-medium text-white">保存</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import apiClient from '@/api/client';

const attributes = ref<any[]>([]);
const facts = ref<any[]>([]);
const showAddModal = ref(false);
const newAttrKey = ref('');
const newAttrVal = ref('');

async function fetchProfile() {
  try {
    const res = await apiClient.get('/profile');
    attributes.value = res.data.attributes || [];
    facts.value = res.data.facts || [];
  } catch (e) {
    console.error('获取画像失败', e);
  }
}

async function submitAddAttr() {
  if (!newAttrKey.value.trim() || !newAttrVal.value.trim()) return;
  try {
    await apiClient.post('/profile/attrs', {
      key: newAttrKey.value.trim(),
      value: newAttrVal.value.trim(),
      confidence: 0.9,
    });
    showAddModal.value = false;
    newAttrKey.value = '';
    newAttrVal.value = '';
    fetchProfile();
  } catch (e) {
    console.error('添加属性失败', e);
  }
}

onMounted(() => {
  fetchProfile();
});
</script>
