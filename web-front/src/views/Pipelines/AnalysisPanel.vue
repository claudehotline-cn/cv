<template>
  <div class="page">
    <el-page-header content="Pipeline 预览 / 分析" @back="goBack" />
    <el-card shadow="hover" class="panel">
      <template #header>
        <div class="toolbar">
          <el-select
            v-model="selectedPipeline"
            filterable
            placeholder="选择 Pipeline"
            style="width:220px"
            :loading="store.loading"
          >
            <el-option
              v-for="p in pipelines"
              :key="p.name"
              :label="pipelineLabel(p)"
              :value="p.name"
            />
          </el-select>
          <el-select
            v-model="selectedSource"
            filterable
            placeholder="选择视频源"
            style="width:260px"
            :loading="store.loading"
          >
            <el-option
              v-for="s in sources"
              :key="s.id"
              :label="sourceLabel(s)"
              :value="s.id"
            />
          </el-select>
          <el-divider direction="vertical" />
          <el-switch v-model="analyzing" active-text="实时分析" inactive-text="暂停" />
          <el-select
            v-model="selectedModel"
            placeholder="选择分析模型"
            style="width:240px"
            :disabled="!store.analyzing || !models.length"
          >
            <el-option
              v-for="m in models"
              :key="m.id"
              :label="modelLabel(m)"
              :value="m.id"
            />
          </el-select>
          <el-switch v-model="autoPlay" active-text="自动播放" style="margin-left:8px" />
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

      <div class="player-wrapper">
        <WhepPlayer ref="playerRef" :whep-url="store.whepUrl" />
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
          <div v-if="currentPipeline" class="meta-item">
            <strong>名称:</strong><span>{{ currentPipeline.name }}</span>
          </div>
          <div v-if="currentPipeline?.status" class="meta-item">
            <strong>状态:</strong><span>{{ currentPipeline.status }}</span>
          </div>
          <div v-if="currentPipeline?.fps" class="meta-item">
            <strong>FPS:</strong><span>{{ currentPipeline.fps }}</span>
          </div>
          <div v-if="currentPipeline?.input_fps" class="meta-item">
            <strong>输入 FPS:</strong><span>{{ currentPipeline.input_fps }}</span>
          </div>
          <div v-if="currentPipeline?.alerts != null" class="meta-item">
            <strong>今日告警:</strong><span>{{ currentPipeline.alerts }}</span>
          </div>
          <div v-if="!currentPipeline">暂无 Pipeline 信息</div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="never" header="当前数据源">
          <div v-if="store.currentSource" class="meta-item"><strong>ID:</strong><span>{{ store.currentSource.id }}</span></div>
          <div v-if="store.currentSource?.name" class="meta-item"><strong>名称:</strong><span>{{ store.currentSource.name }}</span></div>
          <div v-if="store.currentSource?.uri" class="meta-item"><strong>URI:</strong><span>{{ store.currentSource.uri }}</span></div>
          <div v-if="store.currentSource?.phase" class="meta-item"><strong>状态:</strong><span>{{ store.currentSource.phase }}</span></div>
          <div v-if="!store.currentSource">未选择数据源</div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="never" header="分析模型">
          <div v-if="store.currentModel" class="meta-item"><strong>ID:</strong><span>{{ store.currentModel.id }}</span></div>
          <div v-if="store.currentModel?.task" class="meta-item"><strong>任务:</strong><span>{{ store.currentModel.task }}</span></div>
          <div v-if="store.currentModel?.variant" class="meta-item"><strong>版本:</strong><span>{{ store.currentModel.variant }}</span></div>
          <div v-if="store.currentModel?.path" class="meta-item"><strong>路径:</strong><span>{{ store.currentModel.path }}</span></div>
          <div v-if="!store.currentModel">无可用模型或未选择</div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { RefreshRight } from '@element-plus/icons-vue'
import WhepPlayer from '@/widgets/WhepPlayer/WhepPlayer.vue'
import { useAnalysisStore } from '@/stores/analysis'

const route = useRoute()
const router = useRouter()
const store = useAnalysisStore()
const playerRef = ref<InstanceType<typeof WhepPlayer> | null>(null)

const sources = computed(() => store.sources)
const models = computed(() => store.models)
const pipelines = computed(() => store.pipelines)
const currentPipeline = computed(() => store.pipelines.find(p => p.name === store.currentPipeline) || null)

const selectedPipeline = computed({
  get: () => store.currentPipeline,
  set: (val: string) => {
    store.setPipeline(val)
    writeQuery()
  }
})

const selectedSource = computed({
  get: () => store.currentSourceId,
  set: (val: string) => {
    store.setSource(val)
    writeQuery()
  }
})

const selectedModel = computed({
  get: () => store.currentModelUri,
  set: (val: string) => {
    store.hotswapModel(val)
  }
})

const analyzing = computed({
  get: () => store.analyzing,
  set: (val: boolean) => {
    val ? store.startAnalysis() : store.stopAnalysis()
  }
})

const autoPlay = computed({ get:()=>store.autoPlay, set:(v:boolean)=>store.setAutoPlay(v) })

function sourceLabel(s: any) {
  return `${s.name || s.id} (${s.phase || 'Unknown'})`
}

function pipelineLabel(p: any) {
  return `${p.name} · ${p.status || 'Unknown'}`
}

function modelLabel(m: any) {
  const parts = [m.id]
  if (m.task) parts.push(m.task)
  if (m.variant) parts.push(m.variant)
  return parts.join(' · ')
}

function writeQuery() {
  const next = { ...route.query }
  if (store.currentSourceId) next.source = store.currentSourceId
  else delete next.source
  if (store.currentPipeline) next.pipeline = store.currentPipeline
  else delete next.pipeline
  router.replace({ path: route.path, query: next })
}

function syncFromRoute() {
  const qs = typeof route.query.source === 'string' ? route.query.source : ''
  if (qs && qs !== store.currentSourceId && sources.value.some(s => s.id === qs)) {
    store.setSource(qs)
  }
  const qp = typeof route.query.pipeline === 'string' ? route.query.pipeline : ''
  if (qp && qp !== store.currentPipeline && pipelines.value.some(p => p.name === qp)) {
    store.setPipeline(qp)
  }
}

function refresh() {
  store.refreshStats()
  playerRef.value?.refresh()
}

function goBack() {
  router.back()
}

onMounted(async () => {
  await store.bootstrap()
  syncFromRoute()
  if (!route.query.source && store.currentSourceId) {
    writeQuery()
  }
})

watch(() => route.query.source, () => syncFromRoute())
watch(() => route.query.pipeline, () => syncFromRoute())
</script>

<style scoped>
.page{ padding:12px 4px; display:flex; flex-direction:column; gap:12px; }
.panel{ border-radius:10px; }
.toolbar{ display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
.status{ margin-left:auto; }
.player-wrapper{ position:relative; }
.overlay{ position:absolute; left:16px; top:16px; display:flex; gap:8px; }
.meta{ margin-top:4px; }
.meta-item{ display:flex; gap:8px; font-size:13px; line-height:1.8; color: var(--va-text-2); }
.meta-item strong{ color: var(--va-text-1); font-weight:600; }
</style>




