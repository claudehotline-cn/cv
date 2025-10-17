<template>
  <el-card shadow="hover" class="db-panel">
    <template #header>
      <div class="hdr">
        <div class="title">数据库与保留策略趋势</div>
        <div class="right">
          <el-select v-model="sel" multiple collapse-tags placeholder="选择指标" size="small" class="w360">
            <el-option v-for="m in metricList" :key="m.key" :label="m.label" :value="m.key" />
          </el-select>
          <el-select v-model="win" placeholder="窗口" size="small" class="w120">
            <el-option label="最近 2 分钟" :value="120000" />
            <el-option label="最近 5 分钟" :value="300000" />
            <el-option label="最近 10 分钟" :value="600000" />
          </el-select>
          <el-button size="small" @click="refresh">刷新</el-button>
          <el-button size="small" @click="exportCSV">导出 CSV</el-button>
        </div>
      </div>
    </template>
    <div class="cards">
      <div class="card">
        <div class="k">DB in_use</div>
        <div class="v">{{ last('db_pool_in_use') }}</div>
      </div>
      <div class="card">
        <div class="k">DB idle</div>
        <div class="v">{{ last('db_pool_idle') }}</div>
      </div>
      <div class="card">
        <div class="k">Retention last_ms</div>
        <div class="v">{{ last('retention_last_ms') }}</div>
      </div>
      <div class="card">
        <div class="k">Retention runs</div>
        <div class="v">{{ last('retention_runs_total') }}</div>
      </div>
      <div class="card">
        <div class="k">Retention failures</div>
        <div class="v">{{ last('retention_failures_total') }}</div>
      </div>
      <div class="card">
        <div class="k">Writer Queue (logs) <span class="hint">warn≥{{ warnThreshold }} / danger≥{{ dangerThreshold }}</span></div>
        <div class="v">{{ last('log_writer_queue') }}</div>
      </div>
      <div class="card">
        <div class="k">Writer Queue (events) <span class="hint">warn≥{{ warnThreshold }} / danger≥{{ dangerThreshold }}</span></div>
        <div class="v">{{ last('event_writer_queue') }}</div>
      </div>
    </div>
    <div class="chart">
      <ChartBase :option="option" />
    </div>
    <div v-if="errorMsg" class="err">{{ errorMsg }}</div>
  </el-card>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import ChartBase from '@/components/analytics/ChartBase.vue'

function apiBase(){ const b = ((import.meta as any).env?.VITE_API_BASE) || '/'; return String(b).replace(/\/$/, '') }

const pollMs = ref(5000)
const win = ref<number>(120000)
const errorMsg = ref('')
const warnThreshold = Number((import.meta as any).env?.VITE_WRITER_WARN) || 100
const dangerThreshold = Number((import.meta as any).env?.VITE_WRITER_DANGER) || 1000

type SeriesMap = Record<string, { t: number, v: number }[]>
const series = ref<SeriesMap>({})

// 选择指标（key 是内部别名，非原始 /metrics 名称）
const metricList = [
  { key: 'db_pool_in_use', label: 'DB in_use' },
  { key: 'db_pool_idle', label: 'DB idle' },
  { key: 'retention_last_ms', label: 'Retention last_ms' },
  { key: 'retention_runs_total', label: 'Retention runs_total' },
  { key: 'retention_failures_total', label: 'Retention failures_total' },
  { key: 'log_writer_queue', label: 'Writer Queue (logs)' },
  { key: 'event_writer_queue', label: 'Writer Queue (events)' },
]
const sel = ref<string[]>(metricList.map(m=>m.key))

function parseProm(text: string){
  const map: Record<string, number> = {}
  for (const line of text.split(/\r?\n/)){
    const s = line.trim(); if (!s || s.startsWith('#')) continue
    const m = s.match(/^([a-zA-Z_:][a-zA-Z0-9_:]*)\s+([0-9eE+\-.]+)/)
    if (m){ const k = m[1]; const v = Number(m[2]); if (isFinite(v)) map[k]=v }
  }
  return map
}

function findKey(metrics: Record<string, number>, candidates: string[]): string | null {
  for (const c of candidates){ if (c in metrics) return c }
  // fallback: includes 匹配
  for (const k of Object.keys(metrics)){
    if (candidates.some(c=>k.includes(c))) return k
  }
  return null
}

async function load(){
  try{
    const r = await fetch(apiBase() + '/metrics', { cache:'no-cache' })
    if (!r.ok){ errorMsg.value = await r.text().catch(()=> 'metrics 获取失败'); return }
    const t = await r.text()
    const m = parseProm(t)
    errorMsg.value = ''
    const now = Date.now()
    const mapping: Record<string, string[]>= {
      db_pool_in_use: ['va_db_pool_in_use','db_pool_in_use'],
      db_pool_idle: ['va_db_pool_idle','db_pool_idle'],
      retention_last_ms: ['va_db_retention_last_ms','retention_last_ms'],
      retention_runs_total: ['va_db_retention_runs_total','retention_runs_total'],
      retention_failures_total: ['va_db_retention_failures_total','retention_failures_total'],
      log_writer_queue: ['log_writer_queue','va_log_writer_queue'],
      event_writer_queue: ['event_writer_queue','va_event_writer_queue']
    }
    for (const alias of Object.keys(mapping)){
      const key = findKey(m, mapping[alias])
      if (!series.value[alias]) series.value[alias] = []
      const arr = series.value[alias]
      const v = key ? m[key] : NaN
      if (isFinite(v)) arr.push({ t: now, v })
      // trim window
      const cutoff = now - (win.value || 120000)
      while (arr.length && arr[0].t < cutoff) arr.shift()
      // 限制最多 2000 点
      if (arr.length > 2000) arr.splice(0, arr.length - 2000)
    }
  }catch(e:any){ errorMsg.value = e?.message || 'metrics 获取失败' }
}

let timer: any = null
function start(){ stop(); timer = setInterval(load, pollMs.value); load() }
function stop(){ if (timer){ clearInterval(timer); timer = null } }

onMounted(start)
onBeforeUnmount(stop)

function refresh(){ load() }

function exportCSV(){
  const now = Date.now()
  const start = now - (win.value || 120000)
  const keys = sel.value.length ? sel.value.slice() : Object.keys(series.value)
  const timesSet = new Set<number>()
  for (const k of keys){ for (const p of (series.value[k] || [])) if (p.t >= start) timesSet.add(p.t) }
  const times = Array.from(timesSet).sort((a,b)=>a-b)
  const header = ['time', ...keys]
  const rows: string[] = []
  for (const t of times){
    const cols: string[] = [new Date(t).toISOString()]
    for (const k of keys){
      const arr = (series.value[k] || []).filter(p=>p.t === t)
      const v = arr.length ? arr[arr.length-1].v : ''
      cols.push(String(v))
    }
    rows.push(cols.join(','))
  }
  const csv = [header.join(','), ...rows].join('\n')
  const blob = new Blob([csv], { type:'text/csv;charset=utf-8;' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `metrics_db_${Date.now()}.csv`
  a.click()
  URL.revokeObjectURL(a.href)
}

function last(alias: string){ const arr = series.value[alias] || []; const v = arr.length? arr[arr.length-1].v : NaN; return isFinite(v)? v : '-' }

const palette = ['#22b2ff','#7cc9ff','#ffd479','#ff8f6b','#16c28a','#c58af9']
const option = computed(()=>{
  const now = Date.now()
  const start = now - (win.value || 120000)
  const legend = sel.value
  const srs = legend.map((alias, idx)=>({
    name: alias,
    type: 'line',
    showSymbol: false,
    smooth: true,
    areaStyle: { opacity: 0.06 },
    lineStyle: { width: 2, color: palette[idx % palette.length] },
    data: (series.value[alias] || []).map(p=>[p.t, p.v]).filter(p=>p[0] >= start)
  }))
  return {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis' },
    legend: { top: 8, textStyle: { color: 'var(--va-text-2)' }, data: legend },
    grid: { left: 50, right: 20, top: 40, bottom: 40 },
    xAxis: { type: 'time', axisLabel: { color: 'var(--va-text-2)' }, splitLine: { lineStyle: { color: 'rgba(255,255,255,.08)' } } },
    yAxis: { type: 'value', axisLabel: { color: 'var(--va-text-2)' }, splitLine: { lineStyle: { color: 'rgba(255,255,255,.08)' } } },
    series: srs
  } as any
})
</script>

<style scoped>
.db-panel{ margin-top: 12px }
.hdr{ display:flex; align-items:center; }
.title{ font-weight:600 }
.hdr .right{ margin-left:auto; display:flex; gap:8px; align-items:center }
.cards{ display:grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap:10px; margin-bottom: 8px }
.card{ background: rgba(255,255,255,.03); border:1px solid rgba(255,255,255,.06); border-radius:8px; padding:10px }
.k{ font-size:12px; color: var(--va-text-2) }
.k .hint{ margin-left:6px; color: var(--va-text-3, #9aa4af); font-weight: normal; font-size: 11px }
.v{ font-size:20px; font-weight:700 }
.chart{ height: 280px }
.w360{ width:360px } .w120{ width:120px }
.err{ margin-top:8px; color:#ff5d6c; font-size:12px }
</style>
