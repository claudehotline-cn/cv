<template>
  <el-card shadow="hover" class="summary">
    <template #header>
      <div class="hdr">运行时指标摘要</div>
    </template>
    <div class="grid">
      <div class="item">
        <div class="k">DB Pool</div>
        <div class="v">max: {{ val('db_pool_max') }} | min: {{ val('db_pool_min') }}</div>
        <div class="v">idle: {{ val('db_pool_idle') }} | in_use: {{ val('db_pool_in_use') }}</div>
        <div class="v">created: {{ val('db_pool_created') }}</div>
      </div>
      <div class="item">
        <div class="k">Writer Queues</div>
        <div class="v">logs: {{ valLike('writer_queue_logs') }} | events: {{ valLike('writer_queue_events') }}</div>
      </div>
      <div class="item">
        <div class="k">Retention</div>
        <div class="v">runs: {{ valLike('retention_runs_total') }} | failures: {{ valLike('retention_failures_total') }}</div>
        <div class="v">last_ms: {{ valLike('retention_last_ms') }}</div>
      </div>
      <div class="item">
        <div class="k">Writer Queue (logs) <span class="hint">warn≥{{ warnThreshold }} / danger≥{{ dangerThreshold }}</span></div>
        <div class="v" :class="levelClass(num('log_writer_queue'))">{{ safe(num('log_writer_queue')) }}</div>
      </div>
      <div class="item">
        <div class="k">Writer Queue (events) <span class="hint">warn≥{{ warnThreshold }} / danger≥{{ dangerThreshold }}</span></div>
        <div class="v" :class="levelClass(num('event_writer_queue'))">{{ safe(num('event_writer_queue')) }}</div>
      </div>
    </div>
    <div v-if="errorMsg" class="err">{{ errorMsg }}</div>
  </el-card>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'

function apiBase(){ const b = ((import.meta as any).env?.VITE_API_BASE) || '/'; return String(b).replace(/\/$/, '') }

const metrics = ref<Record<string, number>>({})
const warnThreshold = Number((import.meta as any).env?.VITE_WRITER_WARN) || 100
const dangerThreshold = Number((import.meta as any).env?.VITE_WRITER_DANGER) || 1000
const errorMsg = ref('')

function parseProm(text: string){
  const map: Record<string, number> = {}
  for (const line of text.split(/\r?\n/)){
    const s = line.trim(); if (!s || s.startsWith('#')) continue
    const m = s.match(/^([a-zA-Z_:][a-zA-Z0-9_:]*)\s+([0-9eE+\-.]+)/)
    if (m){ const k = m[1]; const v = Number(m[2]); if (isFinite(v)) map[k]=v }
  }
  return map
}

async function load(){
  try{
    const r = await fetch(apiBase() + '/metrics', { cache:'no-cache' })
    if (!r.ok){ try{ errorMsg.value = await r.text() }catch{}; if(!errorMsg.value) errorMsg.value='metrics 获取失败'; return }
    const t = await r.text()
    if (t.trim().startsWith('{')){ try{ const j = JSON.parse(t); metrics.value = j } catch { metrics.value = {} } }
    else { metrics.value = parseProm(t) }
    errorMsg.value = ''
  }catch(e:any){ errorMsg.value = e?.message || 'metrics 获取失败'; metrics.value = {} }
}

onMounted(load)

function val(k: string){ const v = metrics.value[k]; return (typeof v==='number' && isFinite(v)) ? v : '-' }
function valLike(part: string){ const ent = Object.entries(metrics.value).find(([k])=>k.includes(part)); return ent? ent[1] : '-' }
function num(k: string){ const v = metrics.value[k]; return (typeof v==='number' && isFinite(v)) ? v : NaN }
function safe(v: number){ return isFinite(v) ? v : '-' }
function levelClass(v: number){ if (!isFinite(v)) return ''; if (v >= dangerThreshold) return 'danger'; if (v >= warnThreshold) return 'warn'; return '' }
</script>

<style scoped>
.summary{ margin-bottom: 12px }
.grid{ display:grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap:12px }
.item{ background: rgba(255,255,255,.03); border:1px solid rgba(255,255,255,.06); border-radius:8px; padding:10px }
.k{ font-weight:600; margin-bottom:6px }
.v{ color: var(--va-text-2); font-size:13px }
.v.warn{ color:#ffb020 }
.v.danger{ color:#ff5d6c; font-weight:600 }
.err{ margin-top:8px; color:#ff5d6c; font-size:12px }
</style>
