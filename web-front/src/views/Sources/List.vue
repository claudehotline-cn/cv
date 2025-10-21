<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Link, Grid, List } from '@element-plus/icons-vue'
import SourcesAttachDrawer from './SourcesAttachDrawer.vue'
import { dataProvider } from '@/api/dataProvider'
import { useAnalysisStore } from '@/stores/analysis'

type SourceItem = {
  id: string
  name?: string
  uri?: string
  status?: string
  fps?: number
  loss?: number
  jitter?: number
  group?: string
  caps?: { codec?: string; resolution?: [number, number]; fps?: number; pix_fmt?: string; color_space?: string }
}

const rows = ref<SourceItem[]>([])
const keyword = ref('')
const statusFilter = ref<'All'|'Running'|'Starting'|'Stopping'|'Stopped'|'Degraded'|'Error'>('All')
const groupFilter = ref<string>('All')
const viewMode = ref<'table'|'card'>('table')
const attachVisible = ref(false)
const pipelines = ref<{ name: string }[]>([])

const router = useRouter()
const route = useRoute()
let timer: any = null
let unwatch: any = null
const store = useAnalysisStore()

async function fetchList() {
  try {
    const resp = await dataProvider.listSources()
    const items = (resp as any)?.data?.items ?? (resp as any)?.items ?? (Array.isArray(resp) ? (resp as any) : [])
    const mapStatus = (s?: string) => (s === 'Ready' ? 'Unknown' : (s || ''))
    rows.value = (items || []).map((it: any) => ({
      ...it,
      status: mapStatus(it.status || it.phase),
      group: it.group || (it.id?.split('_')[0] ?? 'default')
    }))
  } catch (e:any) {
    ElMessage.error(e?.message || '加载失败')
  }
}

async function fetchPipelines() {
  const resp = await dataProvider.listPipelines()
  const items = (resp as any)?.data ?? (resp as any)?.items ?? []
  pipelines.value = (items as any[]).map((i:any) => ({ name: i.name }))
}

async function attach() {
  await fetchPipelines()
  attachVisible.value = true
}

async function detach(row: SourceItem) {
  await ElMessageBox.confirm(`确认要 Detach ${row.id}?`, '确认', { type: 'warning' })
  await dataProvider.detachSource(row.id)
  ElMessage.success('已 Detach')
  rows.value = rows.value.filter(r => r.id !== row.id)
}

function preview(row: SourceItem) {
  router.push({ path: '/analysis', query: { source: row.id } })
}

async function start(row: SourceItem) {
  try {
    // 统一走异步订阅路径：设置当前源与默认 profile，并触发 startAnalysis
    store.setSource(row.id)
    if (!store.currentPipeline) store.setPipeline('det_720p')
    const res = await store.startAnalysis()
    if (!res.ok) ElMessage.error((res as any).reasons?.join('；') || '订阅失败')
    else {
      ElMessage.success(`已开始分析 ${row.name || row.id}`)
      router.push({ path: '/analysis', query: { source: row.id, pipeline: store.currentPipeline } })
    }
  } catch (e:any) {
    ElMessage.error(e?.message || '启动失败')
  }
}

async function stop(row: SourceItem) {
  try {
    if (store.currentSubId && row.id === store.currentSourceId) {
      await store.stopAnalysis()
      ElMessage.info(`已停止分析 ${row.name || row.id}`)
    } else {
      ElMessage.info('仅支持停止当前页面发起的异步订阅')
    }
  } catch (e:any) {
    ElMessage.error(e?.message || '停止失败')
  }
}

onMounted(() => {
  if (typeof route.query.q === 'string') keyword.value = route.query.q
  if (typeof route.query.view === 'string' && (route.query.view === 'card' || route.query.view === 'table')) viewMode.value = route.query.view
  fetchList()
  // 长轮询 /api/sources/watch，降级：用定时刷新兜底
  try {
    unwatch = (dataProvider as any).watchSources?.(({ items }: any) => {
      if (!Array.isArray(items)) return
      rows.value = items.map((it: any) => ({ ...it, group: it.group || (it.id?.split('_')[0] ?? 'default') }))
    }, { intervalMs: 350, timeoutMs: 12000 })
  } catch {}
  if (!unwatch) timer = setInterval(fetchList, 3000)
})

onBeforeUnmount(() => { if (timer) { clearInterval(timer); timer = null } if (unwatch) { try { unwatch() } catch {} unwatch = null } })

watch(keyword, updateRoute)
watch(viewMode, updateRoute)
watch(() => route.query.q, (val) => {
  if (typeof val === 'string') keyword.value = val
})
watch(() => route.query.view, (val) => {
  if (typeof val === 'string' && (val === 'card' || val === 'table')) viewMode.value = val
})

function updateRoute() {
  const query: Record<string, any> = { ...route.query }
  if (keyword.value) query.q = keyword.value
  else delete query.q
  if (viewMode.value !== 'table') query.view = viewMode.value
  else delete query.view
  router.replace({ path: route.path, query })
}

const groups = computed(() => {
  const set = new Set<string>()
  rows.value.forEach(r => set.add(r.group || 'default'))
  return ['All', ...Array.from(set)]
})

const filtered = computed(() => rows.value.filter(r => {
  if (keyword.value) {
    const k = keyword.value.toLowerCase()
    const matches = [`${r.id}`, r.name || '', r.uri || ''].some(v => v.toLowerCase().includes(k))
    if (!matches) return false
  }
  if (statusFilter.value !== 'All' && (r.status || 'Unknown') !== statusFilter.value) return false
  if (groupFilter.value !== 'All' && (r.group || 'default') !== groupFilter.value) return false
  return true
}))

function statusType(status?: string) {
  if (status === 'Running') return 'success'
  if (status === 'Stopped') return 'info'
  if (status === 'Starting' || status === 'Stopping') return 'warning'
  if (status === 'Degraded' || status === 'Error') return 'danger'
  return 'info'
}

function statusText(status?: string) {
  switch (status) {
    case 'Running': return '运行中'
    case 'Starting': return '启动中'
    case 'Stopping': return '停止中'
    case 'Stopped': return '已停止'
    case 'Degraded': return '性能退化'
    case 'Error': return '异常'
    default: return status || '未知'
  }
}

function setStatus(val: typeof statusFilter.value) {
  statusFilter.value = val
}

function setGroup(val: string) {
  groupFilter.value = val
}

function capsText(item: SourceItem) {
  const caps = item.caps || {}
  const res = caps.resolution ? `${caps.resolution[0]}x${caps.resolution[1]}` : ''
  const codec = caps.codec || ''
  const fps = caps.fps ? `${caps.fps}fps` : ''
  const pix = caps.pix_fmt || ''
  return [codec, res, fps, pix].filter(Boolean).join(' · ')
}
</script>

<template>
  <el-card shadow="never">
    <div class="toolbar">
      <el-input v-model="keyword" placeholder="名称 / URI 过滤" clearable class="w300">
        <template #prefix><el-icon><Search/></el-icon></template>
      </el-input>
      <el-segmented v-model="viewMode" :options="[
        { label: '表格', value: 'table', icon: List },
        { label: '卡片', value: 'card', icon: Grid }
      ]" size="small" />
      <el-divider direction="vertical" class="divider" />
      <el-check-tag :checked="statusFilter==='All'" @change="() => setStatus('All')">全部</el-check-tag>
      <el-check-tag :checked="statusFilter==='Running'" type="success" @change="() => setStatus('Running')">运行中</el-check-tag>
      <el-check-tag :checked="statusFilter==='Starting'" type="warning" @change="() => setStatus('Starting')">启动中</el-check-tag>
      <el-check-tag :checked="statusFilter==='Stopping'" type="warning" @change="() => setStatus('Stopping')">停止中</el-check-tag>
      <el-check-tag :checked="statusFilter==='Stopped'" type="info" @change="() => setStatus('Stopped')">已停止</el-check-tag>
      <el-check-tag :checked="statusFilter==='Degraded'" type="warning" @change="() => setStatus('Degraded')">性能退化</el-check-tag>
      <el-check-tag :checked="statusFilter==='Error'" type="danger" @change="() => setStatus('Error')">异常</el-check-tag>
      <el-select v-model="groupFilter" size="small" class="group-select">
        <el-option v-for="g in groups" :key="g" :label="g === 'All' ? '全部分组' : g" :value="g" />
      </el-select>
      <el-button type="primary" @click="attach"><el-icon><Link/></el-icon>Attach</el-button>
    </div>

    <template v-if="viewMode==='table'">
      <el-table :data="filtered" height="520" stripe border size="small">
        <el-table-column prop="id" label="ID" width="160" fixed />
        <el-table-column prop="name" label="名称" min-width="160" />
        <el-table-column prop="uri" label="URI" min-width="240" show-overflow-tooltip />
        <el-table-column label="状态" width="120">
          <template #default="{ row }"><el-tag :type="statusType(row.status)" effect="dark">{{ statusText(row.status) }}</el-tag></template>
        </el-table-column>
        <el-table-column label="性能" min-width="220">
          <template #default="{ row }"><span>{{ row.fps }} / {{ row.loss }}% / {{ row.jitter }}ms</span></template>
        </el-table-column>
        <el-table-column label="能力" min-width="200">
          <template #default="{ row }"><span>{{ capsText(row) }}</span></template>
        </el-table-column>
        <el-table-column fixed="right" label="操作" width="240">
          <template #default="{ row }">
            <el-button link type="primary" @click="preview(row)">分析</el-button>
            <el-button link type="success" v-if="row.status!=='Running'" @click="start(row)">Start</el-button>
            <el-button link type="warning" v-else @click="stop(row)">Stop</el-button>
            <el-button link type="danger" @click="detach(row)">Detach</el-button>
          </template>
        </el-table-column>
      </el-table>
    </template>

    <template v-else>
      <el-empty v-if="!filtered.length" description="暂无数据" />
      <el-row v-else :gutter="12" class="card-grid">
        <el-col v-for="item in filtered" :key="item.id" :span="8">
          <el-card shadow="hover" class="source-card">
            <div class="card-head">
              <div class="title">{{ item.name || item.id }}</div>
              <el-tag :type="statusType(item.status)" size="small" effect="dark">{{ statusText(item.status) }}</el-tag>
            </div>
            <div class="card-body">
              <div class="line">ID: {{ item.id }}</div>
              <div class="line" :title="item.uri">URI: {{ item.uri }}</div>
              <div class="line">性能: {{ item.fps }}fps / {{ item.loss }}% / {{ item.jitter }}ms</div>
              <div class="line" v-if="capsText(item)">能力: {{ capsText(item) }}</div>
              <div class="line">分组: {{ item.group }}</div>
            </div>
            <div class="card-actions">
              <el-button size="small" text type="primary" @click="preview(item)">分析</el-button>
              <el-button size="small" text type="success" v-if="item.status!=='Running'" @click="start(item)">Start</el-button>
              <el-button size="small" text type="warning" v-else @click="stop(item)">Stop</el-button>
              <el-button size="small" text type="danger" @click="detach(item)">Detach</el-button>
            </div>
          </el-card>
        </el-col>
      </el-row>
    </template>
  </el-card>

  <SourcesAttachDrawer v-model="attachVisible" :pipelines="pipelines" @success="fetchList" />
</template>

<style scoped>
.toolbar{ display:flex; align-items:center; gap:12px; margin-bottom:12px; flex-wrap:wrap; }
.w300{ width:280px; }
.group-select{ width:140px; }
.divider{ height:24px; margin:0 4px; }
.card-grid{ margin-top:4px; }
.source-card{ border-radius:8px; min-height:200px; display:flex; flex-direction:column; justify-content:space-between; }
.card-head{ display:flex; align-items:center; justify-content:space-between; margin-bottom:8px; }
.card-body{ font-size:12px; color:var(--va-text-2); display:flex; flex-direction:column; gap:4px; }
.title{ font-weight:600; color:var(--va-text-1); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.line{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.card-actions{ display:flex; justify-content:flex-end; gap:6px; margin-top:12px; }
</style>

