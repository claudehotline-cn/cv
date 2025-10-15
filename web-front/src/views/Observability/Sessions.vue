<template>
  <div>
    <div class="toolbar">
      <el-input v-model="streamId" placeholder="stream_id" style="max-width:220px" clearable />
      <el-input v-model="pipeline" placeholder="pipeline" style="max-width:220px;margin-left:8px" clearable />
      <el-button type="primary" size="small" @click="load">刷新</el-button>
      <el-switch v-model="auto" active-text="自动刷新" style="margin-left:12px" />
    </div>
    <el-table :data="rows" size="small" stripe>
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
  </div>
  
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { dataProvider } from '@/api/dataProvider'

const rows = ref<any[]>([])
const streamId = ref('')
const pipeline = ref('')
const auto = ref(true)
let stopWatch: any = null

function fmt(v: any){ if(!v) return ''; const d = new Date(Number(v)); if(!isFinite(d.getTime())) return ''; return d.toLocaleString() }

async function load(){
  try {
    const j = await dataProvider.listSessions({ stream_id: streamId.value || undefined, pipeline: pipeline.value || undefined, limit: 200 })
    const d = (j?.data || j)?.items || []
    rows.value = Array.isArray(d) ? d : []
  } catch (e) { /* noop */ }
}

function startWatch(){
  if (stopWatch) stopWatch()
  stopWatch = dataProvider.watchSessions((payload)=>{
    // full snapshot semantics：替换列表
    rows.value = payload.items || []
  }, { stream_id: streamId.value || undefined, pipeline: pipeline.value || undefined, intervalMs: 300, timeoutMs: 12000 })
}

onMounted(()=>{ load(); startWatch() })
onUnmounted(()=>{ if(stopWatch) stopWatch() })

</script>

<style scoped>
.toolbar{ display:flex; align-items:center; gap:8px; margin-bottom:8px }
</style>

