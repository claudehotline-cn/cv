<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import ChartBase from './ChartBase.vue'
import type { EChartsOption } from 'echarts'
import { dataProvider } from '@/api/dataProvider'
import { useRouter } from 'vue-router'
import { ElSkeleton, ElEmpty, ElButton } from 'element-plus'

const props = defineProps<{ metric?: 'pipeline_fps' | 'latency_ms_p95'; limit?: number }>()

const router = useRouter()
const loading = ref(false)
const items = ref<{ name: string, value: number }[]>([])

async function fetchTop() {
  loading.value = true
  try { const data = await dataProvider.metricsTop({ metric: props.metric ?? 'pipeline_fps', limit: props.limit ?? 10 }); items.value = (data as any).items ?? [] } finally { loading.value = false }
}

const option = computed<EChartsOption>(() => {
  const names = items.value.map(i => i.name).reverse()
  const values = items.value.map(i => i.value).reverse()
  const color = props.metric === 'latency_ms_p95' ? '#ffb020' : '#22b2ff'
  return {
    backgroundColor: 'transparent',
    grid: { left: 90, right: 30, top: 10, bottom: 10 },
    xAxis: { type: 'value', axisLabel: { color: 'var(--va-text-2)' }, splitLine:{ lineStyle:{ color:'rgba(255,255,255,.08)' } } },
    yAxis: { type: 'category', data: names, axisLabel: { color: 'var(--va-text-2)' } },
    series: [{ type: 'bar', data: values, barWidth: 14, itemStyle: { color }, emphasis: { itemStyle: { opacity: 0.9 } } }],
    tooltip: { trigger: 'axis' }
  }
})

function openPipeline(name: string) { router.push(`/pipelines/detail/${encodeURIComponent(name)}`) }
onMounted(fetchTop)
</script>

<template>
  <div class="hot">
    <div class="toolbar">
      <strong>热点 Top Pipelines</strong>
      <el-button text size="small" @click="fetchTop">刷新</el-button>
    </div>
    <el-skeleton v-if="loading && !items.length" :rows="6" animated/>
    <el-empty v-else-if="!loading && !items.length" description="暂无数据"/>
    <div v-else class="wrap" @click.self>
      <ChartBase :option="option" :loading="loading"/>
      <ul class="overlay">
        <li v-for="i in items" :key="i.name"><a @click="openPipeline(i.name)">{{ i.name }}</a></li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.hot { width: 100%; }
.toolbar { display:flex; align-items:center; margin-bottom:8px; }
.toolbar strong { color: var(--va-text-1); font-weight:600; }
.wrap { position: relative; }
.overlay { position:absolute; right: 8px; top: 8px; list-style:none; margin:0; padding:0; text-align:right; }
.overlay a { color: var(--va-text-2); text-decoration: underline dotted; cursor: pointer; }
.overlay a:hover { color: var(--va-text-1); }
</style>
