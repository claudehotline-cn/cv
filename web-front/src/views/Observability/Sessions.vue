<template>
  <div>
    <div class="toolbar">
      <el-input v-model="streamId" placeholder="stream_id" style="max-width:220px" clearable />
      <el-input v-model="pipeline" placeholder="pipeline" style="max-width:220px;margin-left:8px" clearable />
      <el-date-picker v-model="dateRange" type="datetimerange" start-placeholder="开始时间" end-placeholder="结束时间" value-format="x" style="margin-left:8px" />
      <el-button type="primary" size="small" @click="load">刷新</el-button>
      <el-switch v-model="auto" active-text="自动刷新" style="margin-left:12px" @change="onAutoChange" />
      <el-button size="small" @click="exportCsv" style="margin-left:8px">导出 CSV</el-button>
    </div>
    <el-alert v-if="errorMsg" :title="errorMsg" type="error" show-icon style="margin:8px 0" />
    <div class="filter-actions"><el-button size="small" @click="resetFilters">清空筛选</el-button></div>
    <el-table :data="pagedRows" size="small" stripe>
      <el-table-column prop="id" label="ID" width="80" />
      <el-table-column prop="stream_id" label="Stream" />
      <el-table-column prop="pipeline" label="Pipeline" />
      <el-table-column prop="status" label="状态" width="110">
        <template #default="{row}">
          <el-tag :type="row.status==='Running' ? 'success' : (row.status==='Failed' ? 'danger' : 'info')">{{row.status}}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="started_at" label="开始时间" width="180">
        <template #default="{row}">{{ fmt(row.started_at) }}</template>
      </el-table-column>
      <el-table-column prop="stopped_at" label="结束时间" width="180">
        <template #default="{row}">{{ fmt(row.stopped_at) }}</template>
      </el-table-column>
      <el-table-column prop="error_msg" label="错误" />
    </el-table>
    <div class="pager">
      <el-pagination background layout="prev, pager, next, sizes, total" :total="total" :page-size="pageSize" :current-page="page" @current-change="onPageChange" @size-change="onSizeChange" :page-sizes="[10,20,50,100]" />
    </div>
  </div>
  
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { dataProvider } from '@/api/dataProvider'

const rows = ref<any[]>([])
const errorMsg = ref('')
const pagedRows = computed(()=>{
  const start = (page.value-1) * pageSize.value
  return rows.value.slice(start, start + pageSize.value)
})
const streamId = ref('')
const pipeline = ref('')
const auto = ref(true)
const dateRange = ref<any[]>([])
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
let stopWatch: any = null

function fmt(v: any){ if(!v) return ''; const d = new Date(Number(v)); if(!isFinite(d.getTime())) return ''; return d.toLocaleString() }
function last30Days(): [number, number] { const now = Date.now(); return [now - 30*24*3600*1000, now] }

async function load(){
  try {
    // 透传分页与时间窗
    const [from_ts, to_ts] = (Array.isArray(dateRange.value) && dateRange.value.length===2) ? [Number(dateRange.value[0]), Number(dateRange.value[1])] : [undefined, undefined] as any
    const j = await dataProvider.listSessions({ stream_id: streamId.value || undefined, pipeline: pipeline.value || undefined, page: page.value, page_size: pageSize.value, from_ts, to_ts, limit: pageSize.value })
    const d = (j?.data || j)?.items || []
    rows.value = Array.isArray(d) ? d : []
    total.value = Number((j?.data || j)?.total || rows.value.length || 0)
    errorMsg.value = ''
  } catch (e:any) { rows.value = []; total.value = 0; errorMsg.value = e?.message || '加载会话失败' }
}

function startWatch(){
  if (stopWatch) stopWatch()
  stopWatch = dataProvider.watchSessions((payload)=>{
    // full snapshot semantics：替换列表
    rows.value = payload.items || []
    total.value = rows.value.length
  }, { stream_id: streamId.value || undefined, pipeline: pipeline.value || undefined, intervalMs: 300, timeoutMs: 12000 })
}

function onAutoChange(v:boolean){ if (v) startWatch(); else if (stopWatch) stopWatch() }

function onPageChange(p:number){ page.value = p; load() }
function onSizeChange(ps:number){ pageSize.value = ps; page.value = 1; load() }

function exportCsv(){
  const header = ['id','stream_id','pipeline','status','started_at','stopped_at','error_msg']
  const lines = [header.join(',')].concat(rows.value.map(r => [r.id, r.stream_id, r.pipeline, r.status, fmt(r.started_at), fmt(r.stopped_at), (r.error_msg||'').replace(/\n/g,' ')].join(',')))
  const blob = new Blob(["\ufeff" + lines.join('\n')], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a'); a.href = url; a.download = 'sessions.csv'; a.click(); setTimeout(()=>URL.revokeObjectURL(url), 1000)
}

function resetFilters(){
  streamId.value = ''
  pipeline.value = ''
  dateRange.value = last30Days()
  page.value = 1
  load()
  if (auto.value) startWatch()
}

watch([streamId, pipeline, dateRange], ()=>{ page.value = 1; load(); if (auto.value) startWatch() })

onMounted(()=>{ if (!Array.isArray(dateRange.value) || dateRange.value.length!==2) { const now=Date.now(); dateRange.value = [now-30*24*3600*1000, now] as any } load(); if (auto.value) startWatch() })
onUnmounted(()=>{ if(stopWatch) stopWatch() })

function onSessionsError(ev:any){ try { errorMsg.value = ev?.detail || '加载会话失败' } catch { errorMsg.value = '加载会话失败' } }
if (typeof window !== 'undefined') {
  try { window.addEventListener('sessions-error', onSessionsError as any) } catch {}
}

</script>

<style scoped>
.toolbar{ display:flex; align-items:center; gap:8px; margin-bottom:8px }
.pager{ display:flex; justify-content:flex-end; margin-top:8px }
</style>
