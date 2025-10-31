<template>
  <el-row :gutter="12" class="page">
    <el-col :span="16">
      <GraphEditorCanvas
        v-model="graphJson"
        @update:selection="onSelect"
        @edge-connected="onEdgeConnected"
        @connect-error="onConnectError"
        @export="onExport"
        ref="canvasRef"
      />
      <div class="editor-fabs">
        <el-space direction="vertical">
          <el-button type="primary" plain size="small" @click="showProps = true">属性</el-button>
          <el-button type="success" plain size="small" @click="showApply = true">Apply</el-button>
          <el-button type="warning" plain size="small" @click="exportYaml()">导出YAML</el-button>
        </el-space>
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
import { computed, ref, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import GraphEditorCanvas from '@/widgets/GraphEditor/GraphEditorCanvas.vue'
import NodePropsForm from '@/widgets/GraphEditor/NodePropsForm.vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { validateGraph, GraphValidateResult } from '@/utils/graph'
import { applyPipeline as cpApply } from '@/api/cp'
import { dataProvider } from '@/api/dataProvider'

const route = useRoute()
const graphJson = ref<any>({ nodes: [], edges: [] })
const selected = ref<any | null>(null)
const canvasRef = ref<any>(null)
const vr = ref<GraphValidateResult | null>(null)
const graphs = ref<any[]>([])
const graphId = ref<string>('')
const pipelineName = ref<string>('')
const showProps = ref(false)
const showApply = ref(false)

function exportYaml(){
  const g:any = graphJson.value || { nodes: [], edges: [] }
  const nameOf = (id:string) => {
    const n:any = (g.nodes||[]).find((x:any)=>x.id===id)
    return (n && (n.name||n.id)) || id
  }
  const toParamsInline = (p:any) => {
    const entries = Object.entries(p||{})
    if (!entries.length) return '{}'
    const kv = entries.map(([k,v])=> `${k}: \"${String(v)}\"`).join(', ')
    return `{ ${kv} }`
  }
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
  const blob = new Blob([lines.join('\n')], { type: 'text/yaml' })
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = `analyzer_multistage_${Date.now()}.yaml`; a.click(); URL.revokeObjectURL(a.href)
}

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
  try {
    const name = String(route.query.name || '')
    const key = name ? `pipeline_draft_${name}` : 'pipeline_draft'
    const text = localStorage.getItem(key)
    if (text) { graphJson.value = JSON.parse(text); canvasRef.value?.fromJSON && canvasRef.value.fromJSON(graphJson.value) }
  } catch {}
  (async()=>{ try{ const resp:any = await (dataProvider as any).listGraphs?.(); const raw = ((resp?.data?.items) ?? resp?.data ?? resp?.items ?? []) as any[]; graphs.value = Array.isArray(raw)? raw: [] } catch{} })()
  runValidation()
})

watch(graphJson, () => runValidation(), { deep: true })
</script>

<style scoped>
.page{ height: calc(100vh - 64px); }
.page :deep(.el-col){ height: 100%; }
.errs{ font-size:12px; color:#ffb4b4; line-height:1.6; }
.err-node{ margin-top:6px; padding-top:6px; border-top:1px dashed rgba(255,255,255,.12); }
.nid{ color:#ffd479; font-weight:600; }
.editor-fabs{ position: fixed; right: 18px; top: 98px; z-index: 5; }
</style>
