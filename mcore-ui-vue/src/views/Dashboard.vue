<template>
  <div class="space-y-6 pb-16 max-w-7xl mx-auto">
    <!-- 1. 健康度 Banner -->
    <div class="animate-fade-slide-down">
      <HealthBanner />
    </div>

    <!-- 2. 一键维护面板 -->
    <div class="animate-fade-slide-down delay-1">
      <MemoryOperationsPanel />
    </div>

    <!-- 3. 记忆治理裁决中心看板 -->
    <div class="animate-fade-slide-down delay-2">
      <GovernancePanel />
    </div>

    <!-- 4. 智能体接入与授权协同面板 -->
    <div class="animate-fade-slide-down delay-3">
      <AppsPanel />
    </div>

    <!-- 5. 上下文召回实验台 (Context Lab) -->
    <div class="animate-fade-slide-down delay-4">
      <ContextLab />
    </div>

    <!-- 6. 巡检与 LLM 治理调优 (Curator Tuning) -->
    <div class="animate-fade-slide-down delay-5">
      <CuratorTuningPanel />
    </div>
  </div>
</template>

<script setup lang="ts">
import HealthBanner from '@/components/dashboard/HealthBanner.vue';
import MemoryOperationsPanel from '@/components/dashboard/MemoryOperationsPanel.vue';
import GovernancePanel from '@/components/dashboard/GovernancePanel.vue';
import AppsPanel from '@/components/dashboard/AppsPanel.vue';
import ContextLab from '@/components/dashboard/ContextLab.vue';
import CuratorTuningPanel from '@/components/dashboard/CuratorTuningPanel.vue';
</script>
