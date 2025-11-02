<script setup lang="ts">
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart, BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, TitleComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { ECharts, EChartsOption } from 'echarts'

echarts.use([LineChart, BarChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, TitleComponent, CanvasRenderer])

const props = defineProps<{ option: EChartsOption; autoresize?: boolean; loading?: boolean }>()

const chartRef = ref<HTMLDivElement | null>(null)
let chart: ECharts | null = null
let ro: ResizeObserver | null = null

function init() {
  if (!chartRef.value) return
  chart = echarts.init(chartRef.value, undefined, { renderer: 'canvas' })
  props.option && chart.setOption(props.option as EChartsOption, { notMerge: true })
  if (props.loading) chart.showLoading('default')
  if (props.autoresize !== false) {
    ro = new ResizeObserver(() => chart?.resize())
    ro.observe(chartRef.value)
  }
}
function dispose() {
  ro?.disconnect(); ro = null
  if (chart) { chart.dispose(); chart = null }
}

watch(() => props.option, (opt) => {
  if (!chart) return
  chart.setOption(opt as EChartsOption, { notMerge: true })
})
watch(() => props.loading, (v) => {
  if (!chart) return
  v ? chart.showLoading('default') : chart.hideLoading()
})

onMounted(init)
onBeforeUnmount(dispose)
</script>

<template>
  <div class="chart-base"><div ref="chartRef" class="canvas"></div></div>
  
</template>

<style scoped>
.chart-base { width: 100%; height: 100%; }
.canvas { width: 100%; height: 100%; min-height: 260px; }
</style>

