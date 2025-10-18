<template>
  <div class="page">
    <el-page-header content="Pipeline 预览 / 分析" @back="goBack" />
    <el-card shadow="hover" class="panel">
      <template #header>
        <div class="toolbar">
          <el-select v-model="selectedPipeline" filterable placeholder="选择 Pipeline" style="width:200px" :loading="store.loading">
            <el-option v-for="p in pipelines" :key="p.name" :label="pipelineLabel(p)" :value="p.name" />
          </el-select>
          <el-select v-model="selectedSource" filterable placeholder="选择视频源" style="width:240px" :loading="store.loading">
            <el-option v-for="opt in sourceOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
          </el-select>
          <el-select v-model="selectedGraph" filterable placeholder="选择分析图" style="width:240px" :loading="store.loading">
            <el-option v-for="g in graphs" :key="g.graph_id" :label="graphLabel(g)" :value="g.graph_id" />
          </el-select>
          <el-select v-model="selectedModel" placeholder="选择分析模型" style="width:220px" :disabled="!store.analyzing || !models.length">
            <el-option v-for="m in models" :key="m.id" :label="modelLabel(m)" :value="m.id" />
          </el-select>
          <el-switch v-model="autoPlay" active-text="自动播放" style="margin-left:8px" />
          <el-switch v-model="analyzing" :disabled="!preflight.ok && !store.analyzing" active-text="实时分析" inactive-text="暂停" style="margin-left:8px" />
          <el-button text size="small" @click="refresh">
            <el-icon><RefreshRight /></el-icon>
            刷新
          </el-button>
          <div class="status">
            <el-tag :type="store.analyzing ? 'success' : 'info'" effect="dark" round>
              {{ store.analyzing ? 'Analyzing' : 'Idle' }}
            </el-tag>
          </div>
        </div>
      </template>

      <el-alert
        v-if="!preflight.ok"
        type="warning"
        show-icon
        :closable="false"
        class="preflight"
        title="预检不通过，请检查视频源与分析图配置"
      >
        <ul>
          <li v-for="(reason, idx) in preflight.reasons" :key="idx">{{ reason }}</li>
        </ul>
      </el-alert>

      <el-alert
        v-if="store.errMsg"
        type="error"
        show-icon
        :closable="false"
        class="preflight"
        :title="store.errMsg"
      />

      <div class="player-wrapper">
        <WhepPlayer ref="playerRef" :whep-url="store.whepUrl" :autoplay="autoPlay" />
        <div class="overlay">
          <el-tag size="small" type="info">FPS {{ store.stats.fps }}</el-tag>
          <el-tag size="small" type="warning">P95 {{ store.stats.p95 }} ms</el-tag>
          <el-tag size="small" :type="store.stats.alerts ? 'danger' : 'success'">
            告警 {{ store.stats.alerts }}
          </el-tag>
        </div>
      </div>
    </el-card>

    <el-row :gutter="12" class="meta">
      <el-col :span="8">
        <el-card shadow="never" header="当前 Pipeline">
          <div v-if="currentPipeline" class="meta-item"><strong>名称:</strong><span>{{ currentPipeline.name }}</span></div>
          <div v-if="currentPipeline?.status" class="meta-item"><strong>状态:</strong><span>{{ currentPipeline.status }}</span></div>
          <div v-if="currentPipeline?.fps" class="meta-item"><strong>输出 FPS:</strong><span>{{ currentPipeline.fps }}</span></div>
          <div v-if="currentPipeline?.input_fps" class="meta-item"><strong>输入 FPS:</strong><span>{{ currentPipeline.input_fps }}</span></div>
          <div v-if="currentPipeline?.alerts != null" class="meta-item"><strong>今日告警:</strong><span>{{ currentPipeline.alerts }}</span></div>
          <div v-else-if="!currentPipeline">暂无 Pipeline 信息</div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="never" header="当前视频源">
          <div v-if="store.currentSource" class="meta-item"><strong>ID:</strong><span>{{ store.currentSource.id }}</span></div>
          <div v-if="store.currentSource?.name" class="meta-item"><strong>名称:</strong><span>{{ store.currentSource.name }}</span></div>
          <div v-if="store.currentSource?.status" class="meta-item"><strong>状态:</strong><span>{{ store.currentSource.status }}</span></div>
          <div v-if="store.currentSource?.caps" class="meta-item"><strong>能力:</strong><span>{{ capsText(store.currentSource) }}</span></div>
          <div v-else-if="!store.currentSource">未选择视频源</div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="never" header="分析图 / 模型">
          <div v-if="currentGraph" class="meta-item"><strong>分析图:</strong><span>{{ currentGraph.name }}</span></div>
          <div v-if="graphRequiresText" class="meta-item"><strong>要求:</strong><span>{{ graphRequiresText }}</span></div>
          <div v-if="store.currentModel" class="meta-item"><strong>模型:</strong><span>{{ store.currentModel.id }}</span></div>
          <div v-if="store.currentModel?.task" class="meta-item"><strong>任务:</strong><span>{{ store.currentModel.task }}</span></div>
          <div v-else-if="!store.currentModel">未选择模型</div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { RefreshRight } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import WhepPlayer from '@/widgets/WhepPlayer/WhepPlayer.vue'
import { useAnalysisStore } from '@/stores/analysis'

const route = useRoute()
const router = useRouter()
const store = useAnalysisStore()
const playerRef = ref<InstanceType<typeof WhepPlayer> | null>(null)

const sources = computed(() => store.sources)
const sourceOptions = computed(() => (sources.value || []).map((s:any) => ({
  value: s?.id || '',
  label: sourceLabel(s)
})).filter((o:any) => !!o.value))
const models = computed(() => store.models)
const pipelines = computed(() => store.pipelines)
const graphs = computed(() => store.graphs)
const currentPipeline = computed(() => store.pipelines.find(p => p.name === store.currentPipeline) || null)
const currentGraph = computed(() => store.currentGraph)

const selectedPipeline = computed({
  get: () => store.currentPipeline,
  set: (val: string) => { store.setPipeline(val); writeQuery(); updatePreflight() }
})

const selectedSource = computed({
  get: () => store.currentSourceId,
  set: (val: string) => { store.setSource(val); writeQuery(); updatePreflight() }
})

const selectedGraph = computed({
  get: () => store.currentGraphId,
  set: (val: string) => { store.setGraph(val); writeQuery(); updatePreflight() }
})

const selectedModel = computed({
  get: () => store.currentModelUri,
  set: (val: string) => { store.hotswapModel(val) }
})

const autoPlay = computed({ get: () => store.autoPlay, set: (v:boolean) => store.setAutoPlay(v) })

const preflight = ref<{ ok: boolean; reasons: string[] }>({ ok: true, reasons: [] })
const analyzing = computed({
  get: () => store.analyzing,
  set: async (val: boolean) => {
    if (val) {
      const pf = await updatePreflight()
      const res = await store.startAnalysis()
      preflight.value = res
      if (!res.ok) {
        if (pf.reasons?.length) preflight.value.reasons = pf.reasons
        ElMessage.warning(res.reasons?.join('；') || '预检失败')
        return
      }
      ElMessage.success('已开始分析')
    } else {
      await store.stopAnalysis()
      ElMessage.info('已停止分析')
    }
  }
})

function pipelineLabel(p: any) { return `${p.name} · ${p.status || '未知'}` }
function sourceLabel(s: any) {
  const o = (typeof s === 'string') ? { id: s, name: s, status: '' } : (s || {})
  const name = o.name || o.id || '未知源'
  const st = o.status || '未知'
  return `${name} · ${st}`
}
function graphLabel(g: any) { return g.name || g.graph_id }
function modelLabel(m: any) { const parts = [m.id]; if (m.task) parts.push(m.task); if (m.variant) parts.push(m.variant); return parts.join(' · ') }

function graphRequiresText() {
  const req = currentGraph.value?.requires
  if (!req) return ''
  const parts: string[] = []
  if (req.color_format) parts.push(`像素:${req.color_format.join('/')}`)
  if (req.fps_range) parts.push(`FPS:${req.fps_range[0]}-${req.fps_range[1]}`)
  if (req.min_resolution) parts.push(`分辨率≥${req.min_resolution[0]}x${req.min_resolution[1]}`)
  if (req.max_resolution) parts.push(`分辨率≤${req.max_resolution[0]}x${req.max_resolution[1]}`)
  return parts.join('，')
}

function capsText(source: any) {
  const caps = source?.caps || {}
  const res = caps.resolution ? `${caps.resolution[0]}x${caps.resolution[1]}` : ''
  const codec = caps.codec || ''
  const fps = caps.fps ? `${caps.fps}fps` : ''
  const pix = caps.pix_fmt || ''
  return [codec, res, fps, pix].filter(Boolean).join(' · ')
}

function writeQuery() {
  const next = { ...route.query }
  if (store.currentSourceId) next.source = store.currentSourceId
  else delete next.source
  if (store.currentPipeline) next.pipeline = store.currentPipeline
  else delete next.pipeline
  if (store.currentGraphId) next.graph = store.currentGraphId
  else delete next.graph
  router.replace({ path: route.path, query: next })
}

async function updatePreflight() {
  const result = await store.preflight()
  preflight.value = result
  return result
}

function refresh() {
  store.refreshStats()
  playerRef.value?.refresh()
}

function goBack() { router.back() }

onMounted(async () => {
  await store.bootstrap()
  if (typeof route.query.source === 'string') store.setSource(route.query.source)
  if (typeof route.query.pipeline === 'string') store.setPipeline(route.query.pipeline)
  if (typeof route.query.graph === 'string') store.setGraph(route.query.graph)
  const pf = await updatePreflight()
  if (store.autoPlay && !store.analyzing) {
    const res = await store.startAnalysis()
    preflight.value = res
    if (!res.ok && pf.reasons?.length) preflight.value.reasons = pf.reasons
  }
})

watch(() => route.query.source, async (val) => {
  if (typeof val === 'string') { store.setSource(val); await updatePreflight() }
})
watch(() => route.query.graph, async (val) => {
  if (typeof val === 'string') { store.setGraph(val); await updatePreflight() }
})
watch(() => route.query.pipeline, (val) => {
  if (typeof val === 'string') store.setPipeline(val)
})
</script>

<style scoped>
.page{ padding:12px 4px; display:flex; flex-direction:column; gap:12px; }
.panel{ border-radius:10px; }
.toolbar{ display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
.status{ margin-left:auto; }
.player-wrapper{ position:relative; }
.overlay{ position:absolute; left:16px; top:16px; display:flex; gap:8px; }
.preflight{ margin-bottom:12px; }
.meta{ margin-top:4px; }
.meta-item{ display:flex; gap:8px; font-size:13px; line-height:1.8; color: var(--va-text-2); }
.meta-item strong{ color: var(--va-text-1); font-weight:600; }
</style>

