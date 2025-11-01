<template>
  <el-row :gutter="0" :class="['page', { fullscreen: isFullscreen }]">
    <el-col :span="24">
      <div class="canvas-shell" ref="shellRef">
        <GraphEditorCanvas
          v-model="graphJson"
          @update:selection="onSelect"
          @edge-connected="onEdgeConnected"
          @connect-error="onConnectError"
          @export="onExport"
          @open-props="onOpenProps"
          ref="canvasRef"
        />
        <div class="editor-toolbar" ref="toolbarRef">
        <el-tooltip content="系统打开(可保存)" placement="top">
          <el-button class="icon-btn" :icon="FolderOpened" @click="openYamlFS" plain />
        </el-tooltip>
        <el-tooltip content="保存到源文件" placement="top">
          <el-button class="icon-btn" :icon="DocumentChecked" @click="saveYamlFS" :disabled="!yamlHandle" plain />
        </el-tooltip>
        <el-tooltip content="导入 YAML" placement="top">
          <el-button class="icon-btn" :icon="Upload" @click="openYaml" plain />
        </el-tooltip>
        <el-tooltip content="导出 YAML" placement="top">
          <el-button class="icon-btn" :icon="Download" @click="exportYaml" plain />
        </el-tooltip>
        <el-tooltip content="自动排布" placement="top">
          <el-button class="icon-btn" :icon="Rank" @click="autoLayout" plain />
        </el-tooltip>
        <el-tooltip content="居中视图" placement="top">
          <el-button class="icon-btn" :icon="Aim" @click="fitView" plain />
        </el-tooltip>
        <el-tooltip :content="isFullscreen ? '退出全屏' : '全屏'" placement="top">
          <el-button class="icon-btn" :icon="FullScreen" @click="toggleFullscreen" plain />
        </el-tooltip>
        <el-tooltip content="Apply 到 CP" placement="top">
          <el-button class="icon-btn" :icon="Check" @click="showApply = true" type="success" plain />
        </el-tooltip>
        </div>
      </div>
      <div class="editor-fabs">
        <el-space direction="vertical">
          <el-button type="primary" plain size="small" @click="showProps = true">属性</el-button>
          <el-button type="success" plain size="small" @click="showApply = true">Apply</el-button>
          <el-button type="info" plain size="small" @click="openYaml()">导入YAML</el-button>
          <el-button type="warning" plain size="small" @click="exportYaml()">导出YAML</el-button>
        </el-space>
      </div>
      <input ref="yamlInputRef" type="file" accept=".yaml,.yml" style="display:none" @change="onYamlPicked" />`r`n      <div class="editor-fabs-4">`r`n        <el-button type="info" plain size="small" @click="autoLayout()">自动排布</el-button>`r`n      </div>
      <div class="editor-fabs-3">
        <el-button type="info" plain size="small" @click="fitView()">居中视图</el-button>
      </div>
      <div class="editor-fabs-2">
        <el-button :type="isFullscreen ? 'danger' : 'info'" plain size="small" @click="toggleFullscreen()">{{ isFullscreen ? '退出全屏' : '全屏' }}</el-button>
      </div>
    </el-col>
  </el-row>

  <el-drawer v-model="showProps" title="节点属性" size="360px" :with-header="true">
    <NodePropsForm :model="selected" :errors="selectedErrors" @update="onUpdateNode" />
  </el-drawer>

  <el-drawer v-model="showApply" title="Graph & Apply" size="420px" :with-header="true">
    <el-form label-width="88px">
      <el-form-item label="Graph">
        <el-select v-model="graphId" placeholder="select graph_id" filterable style="width:100%">
          <el-option v-for="g in graphs" :key="g.graph_id" :label="g.name || g.graph_id" :value="g.graph_id"/>
        </el-select>
      </el-form-item>
      <el-form-item label="Pipeline">
        <el-input v-model="pipelineName" placeholder="e.g. det_720p" />
      </el-form-item>
      <el-form-item>
        <el-button type="success" @click="applyToCp">Apply to CP</el-button>
      </el-form-item>
    </el-form>
    <el-divider />
    <el-space>
      <el-button size="small" @click="exportYaml()">导出 YAML</el-button>
    </el-space>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import { Upload, Download, Rank, Aim, FullScreen, Check, FolderOpened, DocumentChecked } from '@element-plus/icons-vue'
import { useRoute } from 'vue-router'
import GraphEditorCanvas from '@/widgets/GraphEditor/GraphEditorCanvas.vue'
import NodePropsForm from '@/widgets/GraphEditor/NodePropsForm.vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { validateGraph, GraphValidateResult } from '@/utils/graph'
import { applyPipeline as cpApply } from '@/api/cp'
import { dataProvider } from '@/api/dataProvider'
import { useAppStore } from '@/stores/app'

const route = useRoute()
const graphJson = ref<any>({ nodes: [], edges: [] })
const selected = ref<any | null>(null)
const canvasRef = ref<any>(null)
const shellRef = ref<HTMLElement | null>(null)
const toolbarRef = ref<HTMLElement | null>(null)
const yamlHandle = ref<any | null>(null)
const vr = ref<GraphValidateResult | null>(null)
const graphs = ref<any[]>([])
const graphId = ref<string>('')
const pipelineName = ref<string>('')
const showProps = ref(false)
const showApply = ref(false)
const app = useAppStore()
const isFullscreen = computed(() => app.fullscreenEditor)
function toggleFullscreen(){ app.setFullscreenEditor(!app.fullscreenEditor) }

// ===== YAML 导入 =====
const yamlInputRef = ref<HTMLInputElement | null>(null)
function openYaml(){ yamlInputRef.value?.click() }
function fitView(){ try { canvasRef.value?.fitView && canvasRef.value.fitView() } catch {} }
async function openYamlFS(){
  try{
    const picker = (window as any).showOpenFilePicker
    if (!picker) { ElMessage.error('当前浏览器不支持系统文件访问'); return }
    const [handle] = await picker({ multiple:false, types:[{ description:'YAML', accept:{ 'text/yaml':['.yaml','.yml'] } }] })
    const file = await handle.getFile()
    const text = await file.text()
    const g = parseGraphYaml(text)
    graphJson.value = g
    yamlHandle.value = handle
    canvasRef.value?.fromJSON && canvasRef.value.fromJSON(g)
    try { canvasRef.value?.fitView && canvasRef.value.fitView() } catch {}
    ElMessage.success(`已打开：${file.name}`)
    runValidation(true)
  } catch(e:any){ if (e?.name !== 'AbortError') ElMessage.error(e?.message || '系统打开失败') }
}
async function saveYamlFS(){
  try{
    let handle = yamlHandle.value
    if (!handle){
      const saver = (window as any).showSaveFilePicker
      if (!saver) { ElMessage.error('当前浏览器不支持系统保存'); return }
      handle = await saver({ suggestedName:'analyzer_multistage.yaml', types:[{ description:'YAML', accept:{ 'text/yaml':['.yaml','.yml'] } }] })
      yamlHandle.value = handle
    }
    const g:any = graphJson.value || { nodes: [], edges: [] }
    const nameOf = (id:string) => { const n:any = (g.nodes||[]).find((x:any)=>x.id===id); return (n && (n.name||n.id)) || id }
    const toParamsInline = (p:any) => { const entries = Object.entries(p||{}); if (!entries.length) return '{}'; const kv = entries.map(([k,v])=> `${k}: "${String(v)}"`).join(', '); return `{ ${kv} }` }
    const lines:string[] = []
    lines.push('analyzer:')
    lines.push('  multistage:')
    lines.push('    nodes:')
    for (const n of (g.nodes||[])){
      const nm = n.name || n.id
      const tp = n.yamlType || n.type || (n.data?.yamlType) || (n.data?.type) || ''
      lines.push(`      - name: ${nm}`)
      lines.push(`        type: ${tp}`)
      if (n.params && Object.keys(n.params).length){ lines.push(`        params: ${toParamsInline(n.params)}`) }
    }
    lines.push('    edges:')
    for (const e of (g.edges||[])){
      lines.push(`      - [${nameOf(e.source)}, ${nameOf(e.target)}]`)
    }
    const text = lines.join('\n')
    const writable = await handle.createWritable()
    await writable.write(text)
    await writable.close()
    try {
      if (graphId.value) {
        const name = (pipelineName.value || String(route.query.name || '') || 'from_ui').toString()
        await cpApply({ pipeline_name: name, spec: { graph_id: graphId.value } })
        ElMessage.success('已同步到后端')
      } else {
        ElMessage.info('已保存，未选择 graph_id，跳过同步')
      }
    } catch(e:any){ ElMessage.error(e?.message || '后端同步失败') }
    ElMessage.success('已保存到源文件')
  } catch(e:any){ if (e?.name !== 'AbortError') ElMessage.error(e?.message || '保存失败') }
}
function autoLayout(){ try { canvasRef.value?.autoArrange && canvasRef.value.autoArrange(); canvasRef.value?.fitView && canvasRef.value.fitView() } catch {} }
function onYamlPicked(ev: Event){
  try {
    const input = ev.target as HTMLInputElement
    const file = input?.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = () => {
      try {
        const text = String(reader.result || '')
        const g = parseGraphYaml(text)
        graphJson.value = g
        canvasRef.value?.fromJSON && canvasRef.value.fromJSON(g)
        try { canvasRef.value?.fitView && canvasRef.value.fitView() } catch {}
        ElMessage.success('YAML 已导入')
        runValidation(true)
      } catch(e:any){ ElMessage.error(e?.message || '解析 YAML 失败') }
    }
    reader.readAsText(file)
    try { (ev.target as HTMLInputElement).value = '' } catch {}
  } catch {}
}

function parseGraphYaml(text: string){
  const lines = (text||'').split(/\r?\n/).map(l=>l.trim())
  const nodes: any[] = []
  const edges: any[] = []
  let inNodes = false, inEdges = false
  let cur: any = null
  const flushNode = () => { if (cur && cur.name && cur.yamlType){ nodes.push(cur); cur=null } }
  const parseParamsInline = (s: string) => {
    const res: Record<string,string> = {}
    const m = s.match(/\{(.+)\}/)
    if (!m) return res
    const body = m[1]
    body.split(',').forEach(pair => {
      const kv = pair.split(':')
      if (kv.length>=2){
        const k = kv[0].trim()
        const v = kv.slice(1).join(':').trim().replace(/^"|"$/g,'')
        if (k) res[k]=v
      }
    })
    return res
  }
  const mapKind = (tp:string): 'preprocess'|'model'|'nms'|'overlay' => {
    const t = (tp||'').toLowerCase()
    if (t.startsWith('preproc.')) return 'preprocess'
    if (t.startsWith('overlay.')) return 'overlay'
    if (t.startsWith('post.')) return 'nms'
    return 'model'
  }
  for (const raw of lines){
    const line = raw
    if (!line) continue
    if (/^nodes\s*:\s*$/.test(line)) { flushNode(); inNodes=true; inEdges=false; continue }
    if (/^edges\s*:\s*$/.test(line)) { flushNode(); inNodes=false; inEdges=true; continue }
    if (inNodes){
      const nameM = line.match(/^-\s*name:\s*(.+)\s*$/)
      if (nameM) { flushNode(); cur = { name: nameM[1].trim(), yamlType: '', type: 'model', params: {} }; continue }
      const typeM = line.match(/^type:\s*(.+)\s*$/)
      if (typeM && cur){ const yt = typeM[1].trim(); cur.yamlType=yt; cur.type=mapKind(yt); continue }
      const paramsM = line.match(/^params:\s*(\{.*\})\s*$/)
      if (paramsM && cur){ cur.params = parseParamsInline(paramsM[1]); continue }
    } else if (inEdges){
      const eM = line.match(/^-\s*\[\s*([^,\]]+)\s*,\s*([^\]]+)\s*\]\s*$/)
      if (eM){
        const a = eM[1].trim(); const b = eM[2].trim()
        edges.push({ source: a, target: b })
      }
    }
  }
  flushNode()
  const idNodes = nodes.map(n => ({ id: n.name, name: n.name, type: n.type, yamlType: n.yamlType, params: n.params, position: { x: 60, y: 60 } }))
  const idSet = new Set(idNodes.map(n=>n.id))
  const idEdges = edges
    .filter(e => idSet.has(e.source) && idSet.has(e.target))
    .map(e => ({ source: e.source, target: e.target }))
  if (!idNodes.length) throw new Error('未解析到任何节点（请确认 YAML 结构：analyzer.multistage.nodes/edges）')
  return { nodes: idNodes, edges: idEdges }
}
function generateYaml(): string {
  const g:any = graphJson.value || { nodes: [], edges: [] }
  const nameOf = (id:string) => {
    const n:any = (g.nodes||[]).find((x:any)=>x.id===id)
    return (n && (n.name||n.id)) || id
  }
  const toParamsInline = (p:any) => {
    const entries = Object.entries(p||{})
    if (!entries.length) return "{}"
    const kv = entries.map(([k,v])=> `${k}: "${String(v)}"`).join(", ")
    return `{ ${kv} }`
  }
  const lines:string[] = []
  lines.push("analyzer:")
  lines.push("  multistage:")
  lines.push("    nodes:")
  for (const n of (g.nodes||[])){
    const nm = n.name || n.id
    const tp = n.yamlType || n.type || (n.data?.yamlType) || (n.data?.type) || ""
    lines.push(`      - name: ${nm}`)
    lines.push(`        type: ${tp}`)
    if (n.params && Object.keys(n.params).length){ lines.push(`        params: ${toParamsInline(n.params)}`) }
  }
  lines.push("    edges:")
  for (const e of (g.edges||[])){
    lines.push(`      - [${nameOf(e.source)}, ${nameOf(e.target)}]`)
  }
  return lines.join("\n")
}
function exportYaml(){ const blob = new Blob([generateYaml()], { type: "text/yaml" }); const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = `analyzer_multistage_${Date.now()}.yaml`; a.click(); URL.revokeObjectURL(a.href) }

async function applyToCp(){
  try{
    if (!graphId.value) { ElMessage.error('please select graph_id'); return }
    const name = (pipelineName.value || String(route.query.name || '') || 'from_ui').toString()
    await ElMessageBox.confirm(`Apply graph '${graphId.value}' as pipeline '${name}'?`, 'Confirm', { type:'warning' })
    await cpApply({ pipeline_name: name, spec: { graph_id: graphId.value } })
    ElMessage.success('Apply submitted')
  } catch(e:any){ if (e !== 'cancel') ElMessage.error(e?.message || 'Apply failed') }
}

const selectedErrors = computed(() => {
  if (!selected.value || !vr.value) return []
  return vr.value.nodeErrors?.[selected.value.id] || []
})

function runValidation(highlight = false) {
  const result = validateGraph(graphJson.value)
  vr.value = result
  if (highlight) {
    const ids = Object.keys(result.nodeErrors || {})
    if (ids.length) canvasRef.value?.highlightInvalid && canvasRef.value.highlightInvalid(ids)
    else canvasRef.value?.clearHighlight && canvasRef.value.clearHighlight()
  }
}

function onSelect(node: any) { selected.value = node }
function onOpenProps(node: any) { try { selected.value = node; showProps.value = true } catch {} }

function onUpdateNode(n: any) {
  const target = graphJson.value.nodes.find((x: any) => x.id === n.id)
  if (target) { target.name = n.name; target.params = n.params }
  runValidation()
}

function onEdgeConnected(ev: { source: string, target: string }) {
  runValidation(true)
  try { const tgt = (graphJson.value.nodes || []).find((x:any)=> x.id === ev.target); if (tgt) selected.value = tgt } catch {}
}

function onConnectError(e: { msg: string }) { try { ElMessage.warning(e?.msg || '连接无效') } catch {} }

function onExport(json: any) {
  const blob = new Blob([JSON.stringify(json, null, 2)], { type: 'application/json' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `pipeline_${Date.now()}.json`
  a.click()
  URL.revokeObjectURL(a.href)
}

function draftKey() { const name = String(route.query.name || ''); return name ? `pipeline_draft_${name}` : 'pipeline_draft' }

function saveDraft() { try{ const key=draftKey(); localStorage.setItem(key, JSON.stringify(graphJson.value)); ElMessage.success('已保存到草稿（导出/Apply 再生效）') } catch { ElMessage.error('保存失败') } }
function loadDraft() { try{ const key=draftKey(); const text=localStorage.getItem(key); if(!text){ ElMessage.info('无历史草稿'); return } const json=JSON.parse(text); graphJson.value=json; canvasRef.value?.fromJSON && canvasRef.value.fromJSON(json); ElMessage.success('草稿已载入') } catch { ElMessage.error('载入失败') } }
function clearDraft() { try{ const key=draftKey(); localStorage.removeItem(key); ElMessage.success('草稿已清除') } catch {} }
function clearCanvas(){ const empty={ nodes:[], edges:[] }; graphJson.value=empty; canvasRef.value?.fromJSON && canvasRef.value.fromJSON(empty); canvasRef.value?.clearHighlight && canvasRef.value.clearHighlight(); runValidation() }

onMounted(() => {
  const placeToolbar = () => {
    try {
      const sh = shellRef.value
      const tb = toolbarRef.value
      if (!sh || !tb) return
      // 保持 8px 内边距；若容器太小，至少留 4px
      const pad = 8
      tb.style.left = pad + 'px'
      tb.style.bottom = pad + 'px'
    } catch {}
  }
  try { new ResizeObserver(() => placeToolbar()).observe(shellRef.value!) } catch {}
  try { window.addEventListener('resize', placeToolbar) } catch {}
  nextTick(placeToolbar)
  try { (document.body as any).dataset._prevOverflowY = document.body.style.overflowY; document.body.style.overflowY = 'hidden' } catch {}
  try {
    const name = String(route.query.name || '')
    const key = name ? `pipeline_draft_${name}` : 'pipeline_draft'
    const text = localStorage.getItem(key)
    if (text) { graphJson.value = JSON.parse(text); canvasRef.value?.fromJSON && canvasRef.value.fromJSON(graphJson.value) }
  } catch {}
  (async()=>{ try{ const resp:any = await (dataProvider as any).listGraphs?.(); const raw = ((resp?.data?.items) ?? resp?.data ?? resp?.items ?? []) as any[]; graphs.value = Array.isArray(raw)? raw: [] } catch{} })()
  runValidation()
})

onBeforeUnmount(()=>{ if (app.fullscreenEditor) app.setFullscreenEditor(false) })
onBeforeUnmount(()=>{ try { const prev=(document.body as any).dataset._prevOverflowY || ''; document.body.style.overflowY = prev } catch {} })

watch(graphJson, () => runValidation(), { deep: true })
</script>

<style scoped>
.page{ height: 100%; margin-left:0 !important; margin-right:0 !important; }
.page.fullscreen{ height: 100%; }
.page :deep(.el-col){ height: 100%; overflow: hidden; }
.page :deep(.el-col){ padding-left:0 !important; padding-right:0 !important; }
.errs{ font-size:12px; color:#ffb4b4; line-height:1.6; }
.err-node{ margin-top:6px; padding-top:6px; border-top:1px dashed rgba(255,255,255,.12); }
.nid{ color:#ffd479; font-weight:600; }
.editor-fabs, .editor-fabs-2, .editor-fabs-3, .editor-fabs-4{ display: none !important; }
.canvas-shell{ position: relative; height: 100%; }
.editor-toolbar{ position: absolute; left: 8px; bottom: 8px; display: flex; gap: 2px; z-index: 6; padding: 4px 6px; border-radius: 8px; background: rgba(17,20,26,0.28); border: 1px solid rgba(148,163,184,0.18); backdrop-filter: blur(6px); pointer-events: auto; }
.editor-toolbar > *{ margin: 0 }
.icon-btn{ width: 22px; height: 22px; min-width: 0; padding: 0; display:inline-flex; align-items:center; justify-content:center; border-radius: 6px; background: rgba(255,255,255,0.06) !important; border: 1px solid rgba(255,255,255,0.12) !important; }
.icon-btn:hover{ background: rgba(255,255,255,0.12) !important; border-color: rgba(255,255,255,0.2) !important; }
.icon-btn:active{ background: rgba(255,255,255,0.16) !important; }
.icon-btn :deep(.el-icon){ font-size: 13px; opacity: .9; }

/* 减弱遮罩，营造半透明悬浮感（仅编辑器页生命周期内生效） */
:deep(.el-overlay){ background: transparent !important; }
:deep(.el-drawer){
  background: rgba(20, 26, 33, 0.88);
  backdrop-filter: blur(8px);
  border-left: 1px solid rgba(148,163,184,.25);
  box-shadow: 0 10px 30px rgba(0,0,0,.35);
}
:deep(.el-drawer__header){ margin-bottom: 8px; }
:deep(.el-drawer__body){ padding: 12px 14px; }
</style>











