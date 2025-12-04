<script setup lang="ts">
import type { AgentChartResult } from '@/api/agent'
import ChartBase from './ChartBase.vue'

const props = defineProps<{
  chart: AgentChartResult
}>()
</script>

<template>
  <el-card shadow="never" class="agent-chart-card">
    <template #header>
      <div class="chart-header">
        <div class="left">
          <span class="title">{{ chart.title }}</span>
          <span v-if="chart.id" class="id">#{{ chart.id }}</span>
        </div>
        <div v-if="chart.description" class="desc">
          {{ chart.description }}
        </div>
      </div>
    </template>
    <div class="chart-body">
      <ChartBase :option="chart.option" />
    </div>
  </el-card>
</template>

<style scoped>
.agent-chart-card {
  margin-bottom: 16px;
}
.chart-header {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.chart-header .left {
  display: flex;
  align-items: center;
  gap: 8px;
}
.chart-header .title {
  font-weight: 600;
}
.chart-header .id {
  font-size: 12px;
  color: #94a3b8;
}
.chart-header .desc {
  font-size: 12px;
  color: #64748b;
}
.chart-body {
  width: 100%;
  height: 320px;
}
</style>

