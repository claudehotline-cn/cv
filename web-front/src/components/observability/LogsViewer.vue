<template>
  <el-card shadow="hover" class="logs-card">
    <template #header>
      <div class="toolbar">
        <el-input v-model="kw" placeholder="关键字过滤" clearable class="w260">
          <template #prefix><el-icon><Search/></el-icon></template>
        </el-input>
        <el-select v-model="pipeline" filterable clearable placeholder="Pipeline" class="w220">
          <el-option v-for="p in pipelines" :key="p" :label="p" :value="p" />
        </el-select>
        <el-select v-model="level" clearable placeholder="级别" class="w160">
          <el-option label="Info" value="Info"/>
          <el-option label="Warning" value="Warning"/>
          <el-option label="Error" value="Error"/>
        </el-select>
        <el-button text size="small" @click="refresh">刷新</el-button>
        <el-switch v-model="tailing" active-text="跟随到底部" />
        <el-tag size="small" effect="dark" :type="esConnected?'success':'info'">{{ esConnected?'LIVE':'PAUSED' }}</el-tag>
        <el-button text size="small" @click="toggleLive">{{ esConnected ? '暂停' : '恢复' }}</el-button>
        <el-button text size="small" @click="scrollBottom">滚动到底部</el-button>
        <el-button text size="small" @click="exportLogs">导出</el-button>
        <div style="margin-left:auto"><el-button text size="small" @click="clear">清空</el-button></div>
      </div>
  </template>

  <div class="logs-wrap">
    <el-alert v-if="errorMsg" :title="errorMsg" type="error" show-icon style="margin:8px" />
    <VirtualList class="vlist" :data-key="'id'" :data-sources="filtered" :data-component="Row" :keeps="300" :estimate-size="22" :extra-props="{ highlight: kw }" ref="vlistRef" />
  </div>
</el-card>
  </template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import VirtualList from 'vue3-virtual-scroll-list'
import { dataProvider } from '@/api/dataProvider'
import { Search } from '@element-plus/icons-vue'

const Row = {
  props: ['data', 'index', 'highlight'],
  methods: {
    color(level:string){ const t = (level||'').toLowerCase(); if (t.includes('error')) return 'danger'; if (t.includes('warn')) return 'warning'; return 'info' },
    fmt(ts:number|string){ return new Date(typeof ts==='number'?ts:Date.parse(ts)).toLocaleTimeString() },
    hl(text:string, key:string){ if(!key) return text; try{ const re = new RegExp(`(${key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`,'ig'); return text.replace(re,'<mark>$1</mark>') }catch{ return text } }
  },
  template: `
  <div class=\"log-row\">\n    <span class=\"ts\">{{ fmt(data.ts) }}</span>\n    <el-tag :type=\"color(data.level)\" size=\"small\" effect=\"dark\">{{ data.level }}</el-tag>\n    <span class=\"pipe\" v-if=\"data.pipeline\">[{{ data.pipeline }}]</span>\n    <span class=\"node\" v-if=\"data.node\">({{ data.node }})</span>\n    <span class=\"msg\" v-html=\"hl(data.msg, highlight)\"></span>\n  </div>`
}

const pipelines = ref<string[]>([])
const list = ref<any[]>([])
const errorMsg = ref('')
const kw = ref(''); const pipeline = ref(''); const level = ref('')
const tailing = ref(true); const esConnected = ref(false)
const vlistRef = ref()

function filteredFn(item:any){
  if (pipeline.value && item.pipeline !== pipeline.value) return false
  if (level.value && (item.level||'').toLowerCase() !== level.value.toLowerCase()) return false
  if (kw.value && !(`${item.msg||''}`.toLowerCase().includes(kw.value.toLowerCase()))) return false
  return true
}
const filtered = computed(()=> list.value.filter(filteredFn).map((it,idx)=>({ ...it, id: it.id || `${it.ts}-${idx}` })))

async function refresh(){ try { const data = await dataProvider.logsRecent({ pipeline: pipeline.value, level: level.value, limit: 500 }); list.value = (data as any).items || []; errorMsg.value=''; requestAnimationFrame(()=> vlistRef.value?.scrollToBottom && vlistRef.value.scrollToBottom()) } catch (e:any) { list.value = []; errorMsg.value = e?.message || '加载日志失败' } }
let unsubscribe: null | (()=>void) = null
function startSSE(){ stopSSE(); esConnected.value = true; unsubscribe = dataProvider.logsSubscribe((obj)=>{ list.value.push(obj); if (tailing.value) vlistRef.value?.scrollToBottom && vlistRef.value.scrollToBottom(); if (list.value.length > 5000) list.value.splice(0, list.value.length - 5000) }, { pipeline: pipeline.value || undefined, level: level.value || undefined }) }
function stopSSE(){ if (unsubscribe) unsubscribe(); unsubscribe=null; esConnected.value=false }
function clear(){ list.value = [] }

function toggleLive(){ esConnected.value ? stopSSE() : startSSE() }
function scrollBottom(){ vlistRef.value?.scrollToBottom && vlistRef.value.scrollToBottom() }
function exportLogs(){
  const rows = filtered.value
  const text = rows.map(r => {
    const ts = new Date(typeof r.ts==='number'?r.ts:Date.parse(r.ts)).toISOString()
    const lvl = r.level
    const p = r.pipeline ? `[${r.pipeline}]` : ''
    const n = r.node ? `(${r.node})` : ''
    return `${ts} ${lvl} ${p}${n} ${r.msg ?? ''}`.trim()
  }).join('\n')
  const blob = new Blob([text], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `logs_${Date.now()}.txt`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

onMounted(async ()=>{ try{ const data = await dataProvider.listPipelines(); pipelines.value = (data as any).items?.map((i:any)=>i.name) ?? [] } catch{}; await refresh(); startSSE() })
import { watch } from 'vue'
watch(pipeline, () => { if (esConnected.value) startSSE() })
watch(level,    () => { if (esConnected.value) startSSE() })
onBeforeUnmount(()=> stopSSE())
</script>

<style scoped>
.logs-card { min-height: 380px; }
.toolbar{ display:flex; gap:10px; align-items:center; }
.w260{ width: 260px } .w220{ width: 220px } .w160{ width: 160px }
.logs-wrap{ height: 520px; background: #0b0e14; border:1px solid rgba(255,255,255,.06); border-radius:8px; overflow: hidden; }
.vlist{ height: 100%; overflow:auto; padding: 8px 10px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace; }
.log-row{ display:flex; align-items:center; gap:8px; line-height: 20px; }
.ts{ color: #8aa1b4; font-variant-numeric: tabular-nums; width:84px; display:inline-block; }
.pipe{ color:#a0b3c6; }
.node{ color:#7da8ff; }
.msg{ color: var(--va-text-1); white-space: pre-wrap; word-break: break-word; }
:deep(mark){ background: rgba(255, 184, 0, .25); color: #ffd479; padding: 0 2px; border-radius: 3px; }
</style>
