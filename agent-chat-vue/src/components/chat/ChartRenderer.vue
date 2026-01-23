<template>
  <div class="chart-wrapper glass-panel">
    <div class="chart-header">
      <div v-if="chartData.title" class="chart-title">{{ chartData.title }}</div>
      <div v-if="chartData.description" class="chart-desc">{{ chartData.description }}</div>
    </div>
    <div ref="chartRef" class="chart-canvas"></div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts'
import type { ChartData } from '@/types'

const props = defineProps<{
  chartData: ChartData
}>()

const chartRef = ref<HTMLElement>()
let chartInstance: echarts.ECharts | null = null

// Observe class changes on html element to detect theme switch
const observer = new MutationObserver((mutations) => {
  mutations.forEach((mutation) => {
    if (mutation.type === 'attributes' && mutation.attributeName === 'class') {
      updateChartTheme()
    }
  })
})

onMounted(() => {
  if (chartRef.value) {
    initChart()
    window.addEventListener('resize', handleResize)
    observer.observe(document.documentElement, { attributes: true })
  }
})

onUnmounted(() => {
  if (chartInstance) {
    chartInstance.dispose()
    chartInstance = null
  }
  window.removeEventListener('resize', handleResize)
  observer.disconnect()
})

watch(
  () => props.chartData,
  () => updateChart(),
  { deep: true }
)

function isDarkMode() {
  return document.documentElement.classList.contains('dark')
}

function initChart() {
  if (!chartRef.value) return
  const theme = isDarkMode() ? 'dark' : undefined
  chartInstance = echarts.init(chartRef.value, theme, {
    renderer: 'canvas',
    useDirtyRect: true
  })
  updateChart()
}

function updateChartTheme() {
  if (!chartInstance) return
  chartInstance.getOption()
  chartInstance.dispose()
  initChart()
}

function updateChart() {
  if (chartInstance && props.chartData?.option) {
    const isDark = isDarkMode()
    
    // Force background transparent to blend with glass panel
    const option = {
      ...props.chartData.option,
      backgroundColor: 'transparent',
      textStyle: {
        fontFamily: 'Inter, sans-serif',
        color: isDark ? '#f8fafc' : '#0f172a'
      }
    }
    chartInstance.setOption(option as echarts.EChartsOption, true)
  }
}

function handleResize() {
  chartInstance?.resize()
}
</script>

<style scoped>
.chart-wrapper {
  margin: 24px 0;
  padding: 24px;
  border-radius: 12px;
  background: var(--glass-bg); /* Use var for theme support */
}

.chart-header {
  margin-bottom: 20px;
}

.chart-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 4px;
}

.chart-desc {
  font-size: 13px;
  color: var(--text-secondary);
}

.chart-canvas {
  width: 100%;
  height: 400px;
}
</style>
