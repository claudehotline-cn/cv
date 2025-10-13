<template>
  <el-row :gutter="12">
    <el-col :span="6">
      <el-card shadow="hover"><StatCard title="Pipeline 总数" :value="pipelineCount" :sub="`运行中 ${runningCount}`" trend="flat"/></el-card>
      <el-card shadow="hover" style="margin-top:12px"><StatCard title="运行中" :value="runningCount" :sub="`异常 ${errorCount}`" :trend="errorCount>0?'down':'up'"/></el-card>
      <el-card shadow="hover" style="margin-top:12px"><StatCard title="平均 FPS" :value="avgFps" sub="最近 30min" trend="flat"/></el-card>
      <el-card shadow="hover" style="margin-top:12px"><StatCard title="告警条目" :value="alertCount" sub="今日累计" :trend="alertCount>0?'down':'flat'"/></el-card>
    </el-col>
    <el-col :span="18">
      <div class="filter-bar">
        <el-select v-model="chosenPipeline" filterable clearable placeholder="按 Pipeline 筛选" size="small" style="width: 220px">
          <el-option v-for="p in pipelineNames" :key="p" :label="p" :value="p" />
        </el-select>
      </div>
      <el-card shadow="never" class="chart-card">
        <MetricsTimeseries metric="pipeline_fps" title="Pipeline FPS" :range-minutes="30" :pipeline="chosenPipeline || undefined"/>
      </el-card>
      <el-card shadow="never" class="chart-card" style="margin-top:12px">
        <MetricsTimeseries metric="latency_ms_p95" title="Inference P95 Latency" :range-minutes="30" :pipeline="chosenPipeline || undefined"/>
      </el-card>
    </el-col>
  </el-row>

  <el-card shadow="hover" style="margin-top:12px" header="Pipeline 状态概览">
    <el-row :gutter="8">
      <el-col v-for="item in pipelineCards" :key="item.name" :span="8">
        <el-card shadow="never" class="pipeline-card" @click="openPipeline(item.name)">
          <div class="pipeline-head">
            <span class="name">{{ item.name }}</span>
            <el-tag :type="item.statusTag" size="small" effect="dark">{{ item.statusText }}</el-tag>
          </div>
          <div class="pipeline-body">
            <div>FPS: {{ item.fps }}</div>
            <div>输入: {{ item.input }}</div>
            <div>告警: {{ item.alerts }}</div>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </el-card>

  <el-row :gutter="12" style="margin-top:12px">
    <el-col :span="12">
      <el-card shadow="hover" header="热点 Top Pipelines">
        <HotPipelines metric="pipeline_fps" :limit="10"/>
      </el-card>
    </el-col>
    <el-col :span="12">
      <el-card shadow="hover" header="时延 Top Pipelines">
        <HotPipelines metric="latency_ms_p95" :limit="10"/>
      </el-card>
    </el-col>
  </el-row>

  <el-card shadow="hover" style="margin-top:12px" header="最近事件">
    <EventsList compact :limit="12"/>
  </el-card>

  <el-card shadow="hover" style="margin-top:12px" header="视频墙（占位）">
    <VideoWall />
  </el-card>
</template>

<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import StatCard from '@/components/analytics/StatCard.vue'
import MetricsTimeseries from '@/components/analytics/MetricsTimeseries.vue'
import HotPipelines from '@/components/analytics/HotPipelines.vue'
import EventsList from '@/components/observability/EventsList.vue'
import VideoWall from '@/widgets/VideoWall/VideoWall.vue'
import { dataProvider } from '@/api/dataProvider'

type PipelineItem = { name: string; status: 'Running'|'Stopped'|'Error'; fps: number; alerts: number; input: string }

const pipelines = ref<PipelineItem[]>([])
const chosenPipeline = ref<string>('')
const router = useRouter()

function decorate(items: any[]): PipelineItem[] {
  const statuses: PipelineItem['status'][] = ['Running','Running','Running','Stopped','Error']
  return (items || []).map((it, idx) => {
    const status = statuses[idx % statuses.length]
    return {
      name: it.name || `pipeline_${idx+1}`,
      status,
      fps: Math.round(22 + Math.random() * 6),
      alerts: status === 'Error' ? Math.floor(Math.random()*3)+1 : Math.random() > 0.7 ? 1 : 0,
      input: it.input || `${Math.floor(300 + Math.random()*80)} fps`,
    }
  })
}

onMounted(async ()=>{
  try {
    const data = await dataProvider.listPipelines()
    pipelines.value = decorate((data as any).items ?? [])
  } catch {
    pipelines.value = []
  }
})

const pipelineNames = computed(() => pipelines.value.map(p => p.name))
const pipelineCount = computed(() => pipelines.value.length)
const runningCount = computed(() => pipelines.value.filter(p => p.status === 'Running').length)
const errorCount = computed(() => pipelines.value.filter(p => p.status === 'Error').length)
const alertCount = computed(() => pipelines.value.reduce((sum, p) => sum + p.alerts, 0))
const avgFps = computed(() => {
  if (!pipelines.value.length) return '0'
  const mean = pipelines.value.reduce((sum, p) => sum + p.fps, 0) / pipelines.value.length
  return mean.toFixed(1)
})

const pipelineCards = computed(() => pipelines.value.map(p => ({
  ...p,
  statusTag: p.status === 'Running' ? 'success' : p.status === 'Error' ? 'danger' : 'info',
  statusText: p.status === 'Running' ? '运行中' : p.status === 'Error' ? '异常' : '已停止'
})))

function openPipeline(name: string){
  router.push(`/pipelines/detail/${encodeURIComponent(name)}`)
}
</script>

<style scoped>
.chart-card{ min-height: 300px; }
.filter-bar{ display:flex; justify-content:flex-end; margin-bottom:8px }
.pipeline-card{ cursor:pointer; border-radius:8px; transition: all .2s ease; }
.pipeline-card:hover{ box-shadow: 0 8px 24px rgba(0,0,0,.35); transform: translateY(-2px); }
.pipeline-head{ display:flex; align-items:center; justify-content:space-between; margin-bottom:8px; }
.pipeline-head .name{ font-weight:600; color: var(--va-text-1); }
.pipeline-body{ font-size:12px; color: var(--va-text-2); display:flex; flex-direction:column; gap:4px; }
</style>

