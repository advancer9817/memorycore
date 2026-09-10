<template>
  <div class="space-y-6">
    <div class="bg-[#18181b] border border-zinc-800/80 rounded-xl p-6">
      <div class="flex items-center justify-between mb-4">
        <div>
          <h2 class="text-lg font-semibold text-white">向量聚类与知识拓扑图谱 (Apache ECharts 2D)</h2>
          <p class="text-xs text-zinc-400 mt-1">基于当前租户私有记忆资产的高性能拓扑渲染，支持缩放、拖拽与高亮</p>
        </div>
        <button
          @click="renderChart"
          class="bg-zinc-800 hover:bg-zinc-700 text-xs text-zinc-200 px-3 py-1.5 rounded-lg border border-zinc-700 transition"
        >
          重新聚类
        </button>
      </div>

      <div ref="chartContainer" class="w-full h-[600px] rounded-lg bg-zinc-900/60 border border-zinc-800"></div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue';
import * as echarts from 'echarts';
import apiClient from '@/api/client';

const chartContainer = ref<HTMLDivElement | null>(null);
let chartInstance: echarts.ECharts | null = null;

async function renderChart() {
  if (!chartContainer.value) return;
  if (!chartInstance) {
    chartInstance = echarts.init(chartContainer.value);
  }

  chartInstance.showLoading({ color: '#6366f1', textColor: '#a1a1aa' });

  try {
    const res = await apiClient.get('/graph?limit=60');
    const graphData = res.data || { nodes: [], links: [] };

    const nodes = (graphData.nodes || []).map((r: any) => ({
      name: r.name || r.id.substring(0, 8),
      id: r.id,
      category: r.type,
      value: r.importance,
      symbolSize: Math.max(16, (r.importance || 0.5) * 36),
      content: r.title || r.name
    }));

    const links = (graphData.links || []).map((l: any) => ({
      source: l.source,
      target: l.target,
      lineStyle: { opacity: 0.4, width: 1.5, curveness: 0.1 }
    }));

    const option: echarts.EChartsOption = {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'item',
        formatter: (params: any) => {
          if (params.dataType === 'node') {
            return `<div style="max-width:320px; font-size:12px;"><b>[${params.data.category}] ${params.data.name}</b><br/><span style="color:#a1a1aa;">${params.data.content}</span></div>`;
          }
          return '';
        }
      },
      legend: {
        textStyle: { color: '#a1a1aa' },
        top: '10'
      },
      series: [
        {
          type: 'graph',
          layout: 'force',
          data: nodes,
          links: links,
          roam: true,
          label: {
            show: true,
            position: 'right',
            color: '#e4e4e7',
            fontSize: 11
          },
          force: {
            repulsion: 180,
            edgeLength: 80,
            gravity: 0.1
          },
          itemStyle: {
            color: (params: any) => {
              const cat = params.data.category;
              if (cat === 'environment_fact') return '#10b981';
              if (cat === 'user_profile') return '#f59e0b';
              if (cat === 'rule') return '#ef4444';
              return '#6366f1';
            }
          }
        }
      ]
    };

    chartInstance.setOption(option);
  } finally {
    chartInstance.hideLoading();
  }
}

onMounted(() => {
  renderChart();
  window.addEventListener('resize', () => chartInstance?.resize());
  window.addEventListener('mcore-tenant-changed', () => renderChart());
});

onUnmounted(() => {
  chartInstance?.dispose();
});
</script>
