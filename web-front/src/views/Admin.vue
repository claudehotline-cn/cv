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
    <el-row :gutter="16" style="margin-top:12px;">
      <el-col :span="12">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <div>
                <div class="title">Model Cache</div>
                <div class="subtitle">GET /api/system/info · data.registry.cache</div>
              </div>
              <el-button size="small" @click="loadInfo" :loading="loading">刷新</el-button>
            </div>
          </template>
          <el-descriptions :column="2" size="small" border>
            <el-descriptions-item label="enabled">{{ cache.enabled? 'true':'false' }}</el-descriptions-item>
            <el-descriptions-item label="entries">{{ cache.entries }}</el-descriptions-item>
            <el-descriptions-item label="capacity">{{ cache.capacity }}</el-descriptions-item>
            <el-descriptions-item label="idle_ttl_seconds">{{ cache.idle_ttl_seconds }}</el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>
    </el-row>
    <el-row :gutter="16" style="margin-top:12px;">
      <el-col :span="12">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <div>
                <div class="title">Quotas / ACL</div>
                <div class="subtitle">GET /api/system/info → data.quotas</div>
              </div>
              <el-button size="small" @click="loadInfo" :loading="loading">刷新</el-button>
            </div>
          </template>
          <el-descriptions :column="2" size="small" border>
            <el-descriptions-item label="enabled">{{ quotas.enabled? 'true':'false' }}</el-descriptions-item>
            <el-descriptions-item label="header_key">{{ quotas.header_key }}</el-descriptions-item>
            <el-descriptions-item label="observe_only">{{ quotas.observe_only? 'true':'false' }}</el-descriptions-item>
            <el-descriptions-item label="enforce_percent">{{ quotas.enforce_percent }}</el-descriptions-item>
            <el-descriptions-item label="allowed_schemes" :span="2">
              <div class="word-wrap">{{ (quotas.acl?.allowed_schemes||[]).join(', ') }}</div>
            </el-descriptions-item>
            <el-descriptions-item label="allowed_profiles" :span="2">
              <div class="word-wrap">{{ (quotas.acl?.allowed_profiles||[]).join(', ') }}</div>
            </el-descriptions-item>
            <el-descriptions-item label="exempt_keys">{{ (quotas.exempt_keys||[]).length }}</el-descriptions-item>
            <el-descriptions-item label="overrides">{{ (quotas.key_overrides||[]).length }}</el-descriptions-item>
          </el-descriptions>
          <div v-if="(quotas.key_overrides||[]).length" style="margin-top:8px;">
            <el-table :data="quotas.key_overrides" size="small" border>
              <el-table-column prop="key" label="key" width="160" />
              <el-table-column prop="concurrent" label="concurrent" width="110" />
              <el-table-column prop="rate_per_min" label="rate_per_min" width="130" />
              <el-table-column prop="observe_only" label="observe_only" width="130">
                <template #default="{row}">{{ row.observe_only? 'true':'false' }}</template>
              </el-table-column>
              <el-table-column prop="enforce_percent" label="enforce_percent" width="150" />
            </el-table>
          </div>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <div>
                <div class="title">Alerts</div>
                <div class="subtitle">Prometheus 规则与 Grafana 面板</div>
              </div>
              <el-space>
                <el-button size="small" @click="openAlerts">下载 alerts.yaml</el-button>
                <el-button size="small" type="primary" :disabled="!grafanaBase" @click="openGrafana">打开 Grafana</el-button>
              </el-space>
            </div>
          </template>
          <div class="word-wrap text-sm">
            - Prometheus 规则范例：包含 dropped/would-drop、enforce% 与失败率告警。
            <br/>
            - Grafana：可导入项目仓库提供的 Dashboard JSON，或使用现有大盘。
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
const cache = ref<any>({ enabled:false, capacity:0, idle_ttl_seconds:0, entries:0 })
const quotas = ref<any>({ enabled:false, header_key:'X-API-Key', observe_only:false, enforce_percent:100, acl:{allowed_schemes:[], allowed_profiles:[]}, exempt_keys:[], key_overrides:[] })
const tailN = ref(200)
const tail = ref<string[]>([])
const grafanaBase = (((import.meta as any).env?.VITE_GRAFANA_BASE) || '').toString().trim()

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
    const q = (r?.data?.quotas) || {}
    quotas.value = {
      enabled: !!q.enabled,
      header_key: q.header_key || 'X-API-Key',
      observe_only: !!q.observe_only,
      enforce_percent: q.enforce_percent ?? 100,
      acl: q.acl || { allowed_schemes:[], allowed_profiles:[] },
      exempt_keys: Array.isArray(q.exempt_keys)? q.exempt_keys: [],
      key_overrides: Array.isArray(q.key_overrides)? q.key_overrides: []
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
function openAlerts(){ window.open('/alerts/va_alerts.yaml', '_blank') }
function openGrafana(){ if (!grafanaBase) return; window.open(String(grafanaBase), '_blank') }
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
.text-sm{ font-size: 12px; color: var(--va-text-2); }
</style>
    const c = (r?.data?.registry?.cache) || {}
    cache.value = {
      enabled: !!c.enabled,
      capacity: c.capacity ?? 0,
      idle_ttl_seconds: c.idle_ttl_seconds ?? 0,
      entries: c.entries ?? 0
    }
