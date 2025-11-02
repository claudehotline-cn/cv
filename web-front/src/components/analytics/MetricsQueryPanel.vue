<template>
  <el-card shadow="hover">
    <template #header>
      <div class="toolbar">
        <el-select v-model="selMetrics" multiple filterable placeholder="选择指标(可多选)" class="w360" collapse-tags>
          <el-option v-for="m in metricOptions" :key="m" :label="m" :value="m"/>
        </el-select>
        <el-select v-model="pipeline" filterable clearable placeholder="Pipeline" class="w220">
          <el-option v-for="p in pipelines" :key="p" :label="p" :value="p"/>
        </el-select>
        <el-date-picker v-model="range" type="datetimerange" start-placeholder="开始" end-placeholder="结束" :default-time="['00:00:00','23:59:59']" class="w420"/>
        <el-button type="primary" @click="query"><el-icon><Search/></el-icon>查询</el-button>
        <el-button text @click="exportCSV"><el-icon><Download/></el-icon>导出 CSV</el-button>
      </div>
    </template>
    <ChartBase :option="option" :loading="loading" />
  </el-card>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import ChartBase from '@/components/analytics/ChartBase.vue'
import type { EChartsOption } from 'echarts'
import { dataProvider } from '@/api/dataProvider'
import { Search, Download } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

const metricOptions = ['pipeline_fps','latency_ms_p50','latency_ms_p95','drop_rate','gpu_mem_mb']
const selMetrics = ref<string[]>(['pipeline_fps','latency_ms_p95'])
const pipeline = ref<string>('')
const pipelines = ref<string[]>([])
const range = ref<[Date,Date] | null>(null)
const loading = ref(false)
const series = ref<{ metric: string, points: {t:number,v:number}[] }[]>([])

onMounted(async ()=>{
  try { const data = await dataProvider.listPipelines(); pipelines.value = (data as any).items?.map((i:any)=>i.name) ?? [] } catch {}
  const now = Date.now(); range.value = [new Date(now - 30*60*1000), new Date(now)]
  query()
})

async function query(){
  if (!selMetrics.value.length) { ElMessage.warning('请选择至少一个指标'); return }
  if (!range.value) { ElMessage.warning('请选择时间范围'); return }
  loading.value = true
  try{
    const [from,to] = [range.value[0].getTime(), range.value[1].getTime()]
    const step = Math.max(5, Math.floor((to-from)/1000/200))
    const data = await dataProvider.metricsMultiQuery({ metrics: selMetrics.value, from, to, stepSec: step, pipeline: pipeline.value || undefined })
    series.value = data.series || []
  } finally { loading.value=false }
}

const palette = ['#22b2ff','#7cc9ff','#ffd479','#ff8f6b','#16c28a','#c58af9']
const option = computed<EChartsOption>(() => ({
  backgroundColor:'transparent',
  tooltip: { trigger: 'axis' },
  legend: { top: 10, textStyle: { color: 'var(--va-text-2)' } },
  grid: { left:50, right:20, top:40, bottom:40 },
  xAxis: { type:'time', axisLabel:{ color:'var(--va-text-2)' }, splitLine:{ lineStyle:{ color:'rgba(255,255,255,.08)'} } },
  yAxis: { type:'value', axisLabel:{ color:'var(--va-text-2)' }, splitLine:{ lineStyle:{ color:'rgba(255,255,255,.08)'} } },
  series: series.value.map((s,idx)=>({
    name: s.metric,
    type:'line',
    showSymbol:false,
    smooth:true,
    areaStyle:{ opacity:0.06 },
    lineStyle:{ width:2, color: palette[idx % palette.length] },
    data: s.points.map(p=>[p.t,p.v])
  }))
}))

function exportCSV(){
  if (!series.value.length){ ElMessage.warning('暂无可导出的数据'); return }
  const times = Array.from(new Set(series.value.flatMap(s=>s.points.map(p=>p.t)))).sort()
  const header = ['time', ...series.value.map(s=>s.metric)]
  const rows = times.map(t=>{
    const cols = [new Date(t).toISOString()]
    for (const s of series.value){
      const found = s.points.find(p=>p.t===t)
      cols.push(found ? String(found.v) : '')
    }
    return cols.join(',')
  })
  const csv = [header.join(','), ...rows].join('\n')
  const blob = new Blob([csv], { type:'text/csv;charset=utf-8;' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `metrics_${Date.now()}.csv`
  a.click()
  URL.revokeObjectURL(a.href)
}
</script>

<style scoped>
.toolbar{ display:flex; gap:10px; align-items:center; flex-wrap: wrap; }
.w360{ width:360px } .w220{ width:220px } .w420{ width:420px }
</style>
