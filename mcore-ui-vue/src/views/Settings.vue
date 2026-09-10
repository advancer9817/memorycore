<template>
  <div class="space-y-6 pb-16 max-w-4xl mx-auto">
    <div>
      <h1 class="text-xl font-bold text-white tracking-tight">系统与底层引擎配置</h1>
      <p class="text-xs text-zinc-400 mt-1">MemoryCore 企业级多租户架构底座状态、数据库连接池与服务元数据。</p>
    </div>

    <!-- 引擎信息卡片 -->
    <div class="bg-[#18181b] border border-zinc-800/80 rounded-xl p-6 space-y-4">
      <h2 class="text-sm font-semibold text-white">架构技术矩阵 (Architecture Matrix)</h2>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
        <div class="bg-zinc-900/60 p-4 rounded-lg border border-zinc-800 space-y-1">
          <div class="text-zinc-500 text-[10px]">后端核心引擎</div>
          <div class="text-sm font-bold text-white">Java 17 (LTS) / Spring Boot 3.3.3</div>
          <div class="text-zinc-400 text-[11px]">Spring AI 官方 FastMCP 协议驱动</div>
        </div>

        <div class="bg-zinc-900/60 p-4 rounded-lg border border-zinc-800 space-y-1">
          <div class="text-zinc-500 text-[10px]">单一存储底座</div>
          <div class="text-sm font-bold text-emerald-400">PostgreSQL 16 + pgvector</div>
          <div class="text-zinc-400 text-[11px]">HNSW 768 维向量索引 + pg_trgm 混合打分</div>
        </div>

        <div class="bg-zinc-900/60 p-4 rounded-lg border border-zinc-800 space-y-1">
          <div class="text-zinc-500 text-[10px]">多租户隔离架构</div>
          <div class="text-sm font-bold text-indigo-400">Database-per-Tenant 物理库硬隔离</div>
          <div class="text-zinc-400 text-[11px]">template_mcore COW 写时复制 37ms 开辟</div>
        </div>

        <div class="bg-zinc-900/60 p-4 rounded-lg border border-zinc-800 space-y-1">
          <div class="text-zinc-500 text-[10px]">前端工程形态</div>
          <div class="text-sm font-bold text-indigo-300">Vue 3.5 + Vite 5 纯静态 SPA</div>
          <div class="text-zinc-400 text-[11px]">动静彻底分离，常驻内存仅 ~15MB</div>
        </div>
      </div>
    </div>

    <!-- 连接池与配额治理 -->
    <div class="bg-[#18181b] border border-zinc-800/80 rounded-xl p-6 space-y-4">
      <h2 class="text-sm font-semibold text-white">动态连接池治理 (Dynamic Connection Pool)</h2>
      <div class="space-y-2 text-xs text-zinc-300">
        <div class="flex justify-between py-2 border-b border-zinc-800/60">
          <span class="text-zinc-400">整机 PostgreSQL 连接预算</span>
          <span class="font-mono font-medium text-white">150 max_connections</span>
        </div>
        <div class="flex justify-between py-2 border-b border-zinc-800/60">
          <span class="text-zinc-400">单租户微型连接池配置</span>
          <span class="font-mono font-medium text-indigo-400">min=1, max=3</span>
        </div>
        <div class="flex justify-between py-2 border-b border-zinc-800/60">
          <span class="text-zinc-400">Caffeine LRU 活跃池上限</span>
          <span class="font-mono font-medium text-emerald-400">40 活跃池 (峰值 120 守护安全线)</span>
        </div>
        <div class="flex justify-between py-2 border-b border-zinc-800/60">
          <span class="text-zinc-400">空闲池自动回收时间</span>
          <span class="font-mono font-medium text-white">15 分钟无请求自动释放物理连接</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
// 静态配置与运行时展示
</script>
