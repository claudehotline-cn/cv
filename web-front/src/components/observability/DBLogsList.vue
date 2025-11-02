<template>
  <el-card shadow="hover" class="logs-db-card">
    <template #header>
      <div class="toolbar">
        <el-tag size="small" effect="dark">DB</el-tag>
        <div style="margin-left:auto"></div>
      </div>
    </template>
    <el-alert v-if="errorMsg" :title="errorMsg" type="error" show-icon style="margin:8px 0" />
    <el-table :data="items" size="small" stripe>
      <el-table-column prop="ts" label="时间" width="180">
        <template #default="{row}">{{ fmt(row.ts) }}</template>
      </el-table-column>
      <el-table-column prop="level" label="级别" width="100" />
      <el-table-column prop="pipeline" label="Pipeline" width="160" />
      <el-table-column prop="node" label="Node" width="120" />
      <el-table-column prop="msg" label="消息" />
    </el-table>
    <div class="pager">
      <el-pagination background layout="prev, pager, next, sizes, total" :total="total" :page-size="pageSize" :current-page="page" @current-change="onPageChange" @size-change="onSizeChange" :page-sizes="[50,100,200,500]" />
      <div class="summary">{{ summary }}</div>
      <div class="actions">
        <el-button size="small" @click="exportTxt">导出</el-button>
      </div>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { dataProvider } from '@/api/dataProvider'

const props = defineProps<{ fromTs?: number; toTs?: number }>()

const items = ref<any[]>([])
const page = ref(1)
const pageSize = ref(100)
const total = ref(0)
const errorMsg = ref('')

const summary = computed(()=>{
  if (!total.value) return '0/共0'
  const start = (page.value - 1) * pageSize.value + 1
  const end = Math.min(page.value * pageSize.value, total.value)
  return `${start}-${end}/共${total.value}`
})

function fmt(ts:number|string){ const d = new Date(typeof ts==='number'?ts:Date.parse(String(ts))); return isFinite(d.getTime())? d.toLocaleString() : '' }

async function load(){
  try{
    const data = await dataProvider.logsRecent({ from_ts: props.fromTs, to_ts: props.toTs, page: page.value, page_size: pageSize.value })
    const d = (data as any)?.data ?? data as any
    const arr = d?.items ?? []
    items.value = Array.isArray(arr)? arr : []
    total.value = Number(d?.total ?? items.value.length)
    errorMsg.value = ''
  } catch(e:any){ items.value = []; total.value = 0; errorMsg.value = e?.message || '加载日志失败' }
}

function onPageChange(p:number){ page.value = p; load() }
function onSizeChange(ps:number){ pageSize.value = ps; page.value = 1; load() }

function exportTxt(){
  const rows = items.value
  const text = rows.map(r=>{
    const t = fmt(r.ts)
    const lvl = r.level || ''
    const p = r.pipeline ? `[${r.pipeline}]` : ''
    const n = r.node ? `(${r.node})` : ''
    return `${t} ${lvl} ${p}${n} ${r.msg??''}`.trim()
  }).join('\n')
  const blob = new Blob([text], { type:'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a'); a.href=url; a.download=`logs_db_${Date.now()}.txt`; a.click(); setTimeout(()=>URL.revokeObjectURL(url), 300)
}

onMounted(load)
watch(()=>[props.fromTs, props.toTs], ()=> { page.value = 1; load() })
</script>

<style scoped>
.logs-db-card { min-height: 300px; }
.toolbar{ display:flex; align-items:center; gap:10px }
.pager{ display:flex; justify-content:space-between; align-items:center; margin-top:8px }
.summary{ color: var(--va-text-2); font-size:12px }
.actions{ display:flex; gap:8px }
</style>
