<template>
  <div class="admin-grid">
    <el-row :gutter="16">
      <el-col :span="12">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <div>
                <div class="title">Registry Preheat</div>
                <div class="subtitle">GET /api/system/info · data.registry.preheat</div>
              </div>
              <el-button size="small" @click="loadInfo" :loading="loading">刷新</el-button>
            </div>
          </template>
          <el-descriptions :column="1" size="small" border>
            <el-descriptions-item label="enabled">{{preheat.enabled? 'true':'false'}}</el-descriptions-item>
            <el-descriptions-item label="concurrency">{{preheat.concurrency}}</el-descriptions-item>
            <el-descriptions-item label="status">{{preheat.status}}</el-descriptions-item>
            <el-descriptions-item label="warmed">{{preheat.warmed}}</el-descriptions-item>
            <el-descriptions-item label="list">
              <div class="word-wrap">{{preheat.list?.join(', ')}}</div>
            </el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <div>
                <div class="title">WAL</div>
                <div class="subtitle">/api/admin/wal/summary & /tail</div>
              </div>
              <el-space>
                <el-button size="small" @click="loadWal" :loading="loadingWal">刷新</el-button>
                <el-input-number v-model="tailN" :min="10" :max="1000" :step="10" size="small" />
                <el-button size="small" @click="loadTail" :loading="loadingTail">Tail</el-button>
                <el-button size="small" @click="downloadTail" :disabled="!tail.length">下载</el-button>
              </el-space>
            </div>
          </template>
          <el-descriptions :column="1" size="small" border>
            <el-descriptions-item label="enabled">{{ wal.enabled? 'true':'false' }}</el-descriptions-item>
            <el-descriptions-item label="failed_restart">{{ wal.failed_restart }}</el-descriptions-item>
          </el-descriptions>
          <div v-if="tail.length" class="tail-box">
            <div class="tail-title">Tail ({{tail.length}})</div>
            <pre class="tail-pre">{{ tail.join('\n') }}</pre>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
  
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getSystemInfo, getWalSummary, getWalTail } from '@/api/admin'

const loading = ref(false)
const loadingWal = ref(false)
const loadingTail = ref(false)
const preheat = ref<any>({ enabled:false, concurrency:0, list:[], status:'idle', warmed:0 })
const wal = ref<{enabled:boolean; failed_restart:number}>({ enabled:false, failed_restart:0 })
const tailN = ref(200)
const tail = ref<string[]>([])

async function loadInfo(){
  loading.value = true
  try{
    const r = await getSystemInfo()
    const pre = (r?.data?.registry?.preheat) || {}
    preheat.value = {
      enabled: !!pre.enabled,
      concurrency: pre.concurrency ?? 0,
      list: Array.isArray(pre.list)? pre.list : [],
      status: pre.status || 'idle',
      warmed: pre.warmed ?? 0
    }
  }catch(e:any){ ElMessage.error(e?.message || '加载失败') }
  finally{ loading.value = false }
}

async function loadWal(){
  loadingWal.value = true
  try{
    const r = await getWalSummary(); wal.value = r.data
  }catch(e:any){ ElMessage.error(e?.message || '加载失败') }
  finally{ loadingWal.value = false }
}

async function loadTail(){
  loadingTail.value = true
  try{
    const r = await getWalTail(tailN.value)
    tail.value = r.data.items || []
  }catch(e:any){ ElMessage.error(e?.message || '加载失败') }
  finally{ loadingTail.value = false }
}

function downloadTail(){
  if (!tail.value.length) return
  const blob = new Blob([tail.value.join('\n')], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `subscriptions.tail.${Date.now()}.wal.txt`
  a.click()
  URL.revokeObjectURL(url)
}

onMounted(() => { loadInfo(); loadWal() })
</script>

<style scoped>
.admin-grid{ }
.card-header{ display:flex; align-items:center; justify-content:space-between; }
.title{ font-weight:600; color: var(--va-text-1); }
.subtitle{ font-size:12px; color: var(--va-text-2); opacity:.75; }
.word-wrap{ white-space: pre-wrap; word-break: break-all; }
.tail-box{ margin-top: 8px; }
.tail-title{ font-size:12px; color: var(--va-text-2); margin-bottom:4px; }
.tail-pre{ max-height: 240px; overflow:auto; background: rgba(255,255,255,.03); border:1px solid rgba(255,255,255,.08); padding:8px; border-radius:6px; }
</style>

