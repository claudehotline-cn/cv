<script setup lang="ts">
import { ref, watch, onMounted, computed } from 'vue'
import ChartBase from './ChartBase.vue'
import type { EChartsOption } from 'echarts'
import { dataProvider } from '@/api/dataProvider'
import { ElSkeleton, ElEmpty, ElButton, ElSelect, ElOption } from 'element-plus'

const props = defineProps<{ metric: string; title?: string; rangeMinutes?: number; pipeline?: string }>()

const loading = ref(false)
const series = ref<{ t:number, v:number }[]>([])
const ranges = [ { label: '15 分钟', val: 15 }, { label: '30 分钟', val: 30 }, { label: '1 小时',  val: 60 }, { label: '6 小时',  val: 360 } ]
const chosen = ref(props.rangeMinutes ?? 30)

async function fetchData() {
  loading.value = true
  try {
    const now = Date.now()
    const from = now - chosen.value * 60 * 1000
    const data = await dataProvider.metricsQuery({ metric: props.metric, from, to: now, stepSec: Math.max(5, Math.floor(chosen.value * 60 / 200)), pipeline: props.pipeline })
    series.value = (data as any).points ?? []
  } finally { loading.value = false }
}

const option = computed<EChartsOption>(() => ({
  backgroundColor: 'transparent',
  title: { text: props.title ?? props.metric, left: '2%', textStyle: { color: 'var(--va-text-1)', fontSize: 13, fontWeight: 600 }},
  grid: { left: 50, right: 20, top: 40, bottom: 40 },
  tooltip: { trigger: 'axis' },
  legend: { data: [props.metric], right: 10, textStyle: { color: 'var(--va-text-2)' }},
  xAxis: { type: 'time', boundaryGap: false, axisLabel: { color: 'var(--va-text-2)' }, axisLine: { lineStyle: { color: 'var(--va-border)' } }, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } } },
  yAxis: { type: 'value', axisLabel: { color: 'var(--va-text-2)' }, axisLine: { lineStyle: { color: 'var(--va-border)' } }, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.08)' } } },
  dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 8 }],
  series: [{ name: props.metric, type: 'line', showSymbol: false, smooth: true, areaStyle: { opacity: 0.08 }, lineStyle: { width: 2 }, data: series.value.map(p => [p.t, p.v]) }]
}))

watch(chosen, fetchData)
watch(() => props.metric, fetchData)
onMounted(fetchData)
</script>

<template>
  <div class="ts">
    <div class="toolbar">
      <div class="left"></div>
      <div class="right">
        <el-select v-model="chosen" size="small" style="width:120px">
          <el-option v-for="r in ranges" :key="r.val" :label="r.label" :value="r.val" />
        </el-select>
        <el-button size="small" text @click="fetchData">刷新</el-button>
      </div>
    </div>
    <el-skeleton v-if="loading && !series.length" :rows="6" animated/>
    <el-empty v-else-if="!loading && !series.length" description="暂无数据"/>
    <ChartBase v-else :option="option" :loading="loading"/>
  </div>
</template>

<style scoped>
.ts { width: 100%; }
.toolbar { display:flex; align-items:center; margin-bottom:8px; }
.right { margin-left:auto; display:flex; align-items:center; gap:8px; }
</style>
