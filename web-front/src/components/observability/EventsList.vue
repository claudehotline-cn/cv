<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { dataProvider } from '@/api/dataProvider'
import { ElButton, ElSelect, ElOption } from 'element-plus'
import { InfoFilled, WarningFilled, CloseBold, CircleCheckFilled } from '@element-plus/icons-vue'

const props = withDefaults(defineProps<{ limit?: number; compact?: boolean; useSSE?: boolean; autoRefreshMs?: number; pipeline?: string }>(), { limit: 30, compact: false, useSSE: false, autoRefreshMs: 10000 })

const loading = ref(false)
const events = ref<any[]>([])
const level = ref('')
const detailVisible = ref(false)
const detail = ref<any>(null)
let timer: any = null
let es: EventSource | null = null

function timeAgo(ts: number | string) {
  const d = typeof ts === 'number' ? ts : Date.parse(ts)
  const diff = Date.now() - d
  if (diff < 30_000) return '刚刚'
  const m = Math.floor(diff/60000)
  if (m < 60) return `${m} 分钟前`
  const h = Math.floor(m/60)
  if (h < 24) return `${h} 小时前`
  const day = Math.floor(h/24)
  return `${day} 天前`
}

function typeColor(e: any): 'success'|'warning'|'danger'|'info' {
  const t = (e.level || e.type || '').toLowerCase()
  if (t.includes('error') || t.includes('fail')) return 'danger'
  if (t.includes('warn')) return 'warning'
  if (t.includes('ok') || t.includes('normal') || t.includes('success')) return 'success'
  return 'info'
}
function typeIconComp(e:any) {
  const t = typeColor(e)
  return t==='danger' ? CloseBold : t==='warning' ? WarningFilled : t==='success' ? CircleCheckFilled : InfoFilled
}

async function refresh() {
  loading.value = true
  try {
    const data = await dataProvider.eventsRecent({ limit: props.limit })
    events.value = (data as any).items ?? []
  } finally { loading.value = false }
}

function startPolling() { stopPolling(); timer = setInterval(refresh, props.autoRefreshMs) }
function stopPolling() { if (timer) clearInterval(timer); timer = null }
function startSSE() {
  stopSSE()
  const unsub = dataProvider.eventsSubscribe((obj) => {
    events.value.unshift(obj)
    if (events.value.length > (props.limit ?? 30)) events.value.pop()
  })
  // @ts-ignore
  es = { close: unsub } as any
}
function stopSSE() { if (es) { es.close(); es = null } }

const filtered = computed(() => {
  let list = events.value
  if (props.pipeline) list = list.filter(e => (e.pipeline||'') === props.pipeline)
  if (!level.value) return list
  return list.filter(e => (e.level || e.type || '').toLowerCase().includes(level.value.toLowerCase()))
})

watch(() => props.useSSE, (v) => { if (v) { stopPolling(); startSSE() } else { stopSSE(); startPolling() } })

onMounted(async () => { await refresh(); props.useSSE ? startSSE() : startPolling() })
onBeforeUnmount(() => { stopPolling(); stopSSE() })

function openDetail(e:any){ detail.value = e; detailVisible.value = true }
function pretty(obj:any){ try{ return JSON.stringify(obj, null, 2) } catch { return String(obj) } }
async function copyJson(){ try{ await navigator.clipboard.writeText(pretty(detail.value)); } catch{} }
</script>

<template>
  <div class="events" :class="{ compact }">
    <div class="toolbar">
      <div class="left"></div>
      <div class="right">
        <el-select v-model="level" placeholder="等级" size="small" style="width:120px">
          <el-option label="All" value=""/>
          <el-option label="Info" value="info"/>
          <el-option label="Warning" value="warn"/>
          <el-option label="Error" value="error"/>
          <el-option label="Success" value="success"/>
        </el-select>
        <el-button size="small" text @click="refresh">刷新</el-button>
      </div>
    </div>

    <div v-for="e in filtered" :key="e.id || e.ts" class="row" @click="openDetail(e)">
      <component :is="typeIconComp(e)" :class="['icon', typeColor(e)]"/>
      <div class="main">
        <div class="msg">{{ e.msg || e.message || e.type || '事件' }}</div>
        <div class="meta">
          <el-tag size="small" :type="typeColor(e)">{{ e.level || e.type || 'info' }}</el-tag>
          <span v-if="e.pipeline">Pipeline: {{ e.pipeline }}</span>
          <span v-if="e.node">Node: {{ e.node }}</span>
          <span>{{ timeAgo(e.ts || e.time || Date.now()) }}</span>
        </div>
      </div>
    </div>

    <el-dialog v-model="detailVisible" title="Event Detail" width="560px">
      <div class="kv">
        <div><b>level</b>: {{ detail?.level || detail?.type }}</div>
        <div v-if="detail?.pipeline"><b>pipeline</b>: {{ detail.pipeline }}</div>
        <div v-if="detail?.node"><b>node</b>: {{ detail.node }}</div>
        <div v-if="detail?.ts"><b>time</b>: {{ new Date(detail.ts).toLocaleString() }}</div>
      </div>
      <el-divider/>
      <pre class="json">{{ pretty(detail) }}</pre>
      <template #footer>
        <el-button @click="copyJson">Copy JSON</el-button>
        <el-button type="primary" @click="detailVisible=false">Close</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.events{ width:100%; }
.toolbar{ display:flex; align-items:center; margin-bottom:8px; }
.toolbar .right{ margin-left:auto; display:flex; gap:8px; align-items:center; }
.row{ display:flex; align-items:flex-start; gap:10px; padding:8px 0; border-bottom:1px solid rgba(255,255,255,.06) }
.row:last-child{ border-bottom: none }
.icon{ width:18px; height:18px }
.icon.success{ color:#16c28a } .icon.warning{ color:#ffb020 } .icon.danger{ color:#ff5d6c } .icon.info{ color:#7cc9ff }
.msg{ color: var(--va-text-1); }
.meta{ margin-top:4px; color: var(--va-text-2); display:flex; gap:8px; align-items:center; flex-wrap: wrap }
.compact .row{ padding:6px 0 }
.json{ background:#0b0e14; color:#e5edf6; padding:8px; border-radius:6px; max-height:300px; overflow:auto }
.kv{ font-size:12px; color:var(--va-text-2); display:flex; gap:14px; flex-wrap:wrap }
</style>
