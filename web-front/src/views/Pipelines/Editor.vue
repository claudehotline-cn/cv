<template>
  <el-row :gutter="12" class="page">
    <el-col :span="16">
      <GraphEditorCanvas v-model="graphJson" @update:selection="onSelect" @edge-connected="onEdgeConnected" @export="onExport" ref="canvasRef" />
    </el-col>
    <el-col :span="8">
      <el-card shadow="never" style="margin-bottom:12px">
        <template #header>Graph & Apply</template>
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
      </el-card>
      <NodePropsForm :model="selected" :errors="selectedErrors" @update="onUpdateNode" />
      <el-card shadow="never" style="margin-top:12px">
        <el-space>
          <el-button type="primary" @click="apply">应用</el-button>
          <el-button @click="saveDraft">保存草稿</el-button>
          <el-button @click="loadDraft">恢复草稿</el-button>
          <el-button @click="clearDraft">清除草稿</el-button>
          <el-button @click="clearCanvas">清空画布</el-button>
        </el-space>
      </el-card>
      <el-card v-if="vr && !vr.ok" shadow="never" style="margin-top:12px">
        <template #header>校验结果</template>
        <div class="errs">
          <div v-for="(msg, idx) in (vr?.errors||[])" :key="`g-${idx}`" class="err">- {{ msg }}</div>
          <div v-for="(errs, nid) in (vr?.nodeErrors||{})" :key="nid" class="err-node">
            <div class="nid">{{ nid }}</div>
            <div v-for="(e, i) in errs" :key="i" class="err">• {{ e }}</div>
          </div>
        </div>
      </el-card>
    </el-col>
  </el-row>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import GraphEditorCanvas from '@/widgets/GraphEditor/GraphEditorCanvas.vue'
import NodePropsForm from '@/widgets/GraphEditor/NodePropsForm.vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { toDagSpec, toLinearSpec, validateGraph, GraphValidateResult } from '@/utils/graph'
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

function onSelect(node: any) {
  selected.value = node
}

function onUpdateNode(n: any) {
  const target = graphJson.value.nodes.find((x: any) => x.id === n.id)
  if (target) {
    target.name = n.name
    target.params = n.params
  }
  runValidation()
}

function onEdgeConnected(ev: { source: string, target: string }) {
  // 连线后：自动校验并联动到目标节点属性
  runValidation(true)
  try {
    const tgt = (graphJson.value.nodes || []).find((x:any)=> x.id === ev.target)
    if (tgt) selected.value = tgt
  } catch {}
}

function onExport(json: any) {
  const blob = new Blob([JSON.stringify(json, null, 2)], { type: 'application/json' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `pipeline_${Date.now()}.json`
  a.click()
  URL.revokeObjectURL(a.href)
}

function draftKey() {
  const name = String(route.query.name || '')
  return name ? `pipeline_draft_${name}` : 'pipeline_draft'
}

function saveDraft() {
  try {
    const key = draftKey()
    localStorage.setItem(key, JSON.stringify(graphJson.value))
    localStorage.setItem('pipeline_draft', JSON.stringify(graphJson.value))
    ElMessage.success('草稿已保存')
  } catch {
    ElMessage.error('保存失败')
  }
}

function loadDraft() {
  try {
    const key = draftKey()
    const text = localStorage.getItem(key) || localStorage.getItem('pipeline_draft')
    if (!text) {
      ElMessage.info('暂无历史草稿')
      return
    }
    const json = JSON.parse(text)
    graphJson.value = json
    canvasRef.value?.fromJSON && canvasRef.value.fromJSON(json)
    ElMessage.success('草稿已载入')
  } catch {
    ElMessage.error('载入失败')
  }
}

function clearDraft() {
  try {
    const key = draftKey()
    localStorage.removeItem(key)
    ElMessage.success('草稿已清除')
  } catch {}
}

function clearCanvas() {
  const empty = { nodes: [], edges: [] }
  graphJson.value = empty
  canvasRef.value?.fromJSON && canvasRef.value.fromJSON(empty)
  canvasRef.value?.clearHighlight && canvasRef.value.clearHighlight()
  runValidation()
}

async function apply() {
  runValidation(true)
  if (!vr.value.ok) {
    ElMessage.error('校验未通过，请检查节点配置')
    return
  }

  canvasRef.value?.clearHighlight && canvasRef.value.clearHighlight()

  let spec: any
  try {
    spec = toDagSpec(graphJson.value, 'pipeline-from-ui')
  } catch {
    spec = toLinearSpec(graphJson.value, 'pipeline-from-ui')
  }

  try {
    await ElMessageBox.confirm('确认将当前 Pipeline Apply 到后端？', '确认', { type: 'warning' })
    const r = await fetch(`${import.meta.env.VITE_CP_BASE_URL}/pipelines:apply`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(spec)
    })
    if (!r.ok) throw new Error(await r.text() || 'apply failed')
    ElMessage.success('已提交 Apply 请求')
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(e?.message || 'Apply 失败')
  }
}

onMounted(() => {
  try {
    const name = String(route.query.name || '')
    let key = 'pipeline_draft'
    if (name) key = `pipeline_draft_${name}`
    const text = localStorage.getItem(key)
    if (text) {
      graphJson.value = JSON.parse(text)
      canvasRef.value?.fromJSON && canvasRef.value.fromJSON(graphJson.value)
    }
  } catch {}
  // load graphs for selection (via CP)
  ;(async()=>{ try{ const resp:any = await (dataProvider as any).listGraphs?.(); const raw = ((resp?.data?.items) ?? resp?.data ?? resp?.items ?? []) as any[]; graphs.value = Array.isArray(raw)? raw: [] } catch{} })()
  runValidation()
})

watch(graphJson, () => runValidation(), { deep: true })
</script>

<style scoped>
.page{ height: calc(100vh - 64px - 36px - 16px*2); }
.errs{ font-size:12px; color:#ffb4b4; line-height:1.6; }
.err-node{ margin-top:6px; padding-top:6px; border-top:1px dashed rgba(255,255,255,.12); }
.nid{ color:#ffd479; font-weight:600; }
</style>

