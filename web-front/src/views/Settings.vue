<template>
  <el-row :gutter="16" class="settings-grid">
    <el-col :span="12">
      <el-card shadow="hover">
        <template #header>
          <div class="card-header">
            <div>
              <div class="title">引擎参数</div>
              <div class="subtitle">Schema: GET /api/ui/schema/engine · 保存: POST /api/control/set_engine</div>
            </div>
            <el-button type="primary" size="small" @click="apply" :loading="loading">保存配置</el-button>
          </div>
        </template>
        <EngineForm ref="ef" />
      </el-card>
    </el-col>

    <el-col :span="12">
      <el-card shadow="hover">
        <template #header>
          <div class="card-header">
            <div>
              <div class="title">Apply Pipeline</div>
              <div class="subtitle">POST /api/control/apply_pipeline</div>
            </div>
            <el-space>
              <el-select v-model="exampleKey" placeholder="选择示例" size="small" style="width: 180px" @change="onPickExample">
                <el-option label="single_apply" value="single_apply" />
                <el-option label="batch_apply" value="batch_apply" />
              </el-select>
              <el-button text size="small" @click="loadExample">示例</el-button>
              <el-button type="primary" size="small" @click="applyPipeline" :loading="loading">单个 Apply</el-button>
              <el-button size="small" @click="applyPipelines" :loading="loading">批量 Apply</el-button>
              <el-button text size="small" :disabled="!lastPipelineName" @click="onViewStatus">查看状态</el-button>
            </el-space>
          </div>
        </template>
        <el-input
          v-model="applyJson"
          type="textarea"
          :rows="16"
          placeholder="粘贴 overrides JSON，支持单个 JSON 或 { items: [] } 格式"
        />
        <div class="helper">
          <el-link type="primary" href="/docs/examples/rest_apply_overrides.md" target="_blank">查看后端示例文档</el-link>
        </div>
        <el-alert v-if="warnings.length"
          type="warning"
          :closable="true"
          show-icon
          title="后端返回的未识别 overrides 键"
          :description="warnings.join(', ')"
          style="margin-top:8px"/>
        <div v-if="statusData" class="status-panel">
          <div class="status-title">状态摘要（{{ lastPipelineName }}）</div>
          <pre class="status-json">{{ JSON.stringify(statusData, null, 2) }}</pre>
        </div>
      </el-card>
    </el-col>
  </el-row>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { setEngineControl, applyPipeline as cpApply, applyPipelines as cpApplyBatch } from '@/api/cp'
import EngineForm from '@/components/forms/EngineForm.vue'
import { http } from '@/api/http'

const loading = ref(false)
const ef = ref<any>(null)

async function apply(){
  loading.value = true
  try {
    const vals = (ef.value?.getValues && ef.value.getValues()) || {}
    await setEngineControl(vals as any)
    ElMessage.success('配置已更新')
  } catch (e:any) {
    ElMessage.error(e?.message || '更新失败')
  } finally {
    loading.value = false
  }
}

const applyJson = ref('')
const exampleKey = ref('')
const warnings = ref<string[]>([])
let examples: Record<string, any> | null = null
const statusData = ref<any | null>(null)
const lastPipelineName = ref<string>('')
const statusLoading = ref(false)

async function loadExamples(){
  try {
    const r = await fetch('/examples/overrides_examples.json')
    if (r.ok) examples = await r.json()
  } catch { /* ignore */ }
}

function onPickExample(){
  if (!examples || !exampleKey.value) return
  const obj = (examples as any)[exampleKey.value]
  if (obj) applyJson.value = JSON.stringify(obj, null, 2)
}

async function applyPipeline(){
  if(!applyJson.value) { ElMessage.info('请粘贴 Pipeline JSON'); return }
  loading.value = true
  try {
    warnings.value = []
    const spec = JSON.parse(applyJson.value)
    const resp: any = await cpApply(spec)
    const ws = resp?.warnings || resp?.data?.warnings || []
    if (Array.isArray(ws) && ws.length) warnings.value = ws
    // 记录 pipeline_name 并拉取状态
    const name = getPipelineName(spec)
    if (name) { lastPipelineName.value = name; await fetchStatus(name) }
    ElMessage.success('已提交单个 Pipeline Apply')
  } catch (e:any) {
    ElMessage.error(e?.message || 'Apply 失败')
  } finally {
    loading.value = false
  }
}

async function applyPipelines(){
  if(!applyJson.value) { ElMessage.info('请粘贴 Pipeline JSON'); return }
  loading.value = true
  try {
    const obj = JSON.parse(applyJson.value)
    const items = obj.items ? obj.items : [obj.single_apply || obj]
    const resp: any = await cpApplyBatch(items)
    ElMessage.success(`已提交 ${items.length} 个 Pipeline Apply`)
    // 若只有一个条目，尝试获取名称并查询状态
    if (items.length === 1) {
      const name = getPipelineName(items[0])
      if (name) { lastPipelineName.value = name; await fetchStatus(name) }
    }
  } catch (e:any) {
    ElMessage.error(e?.message || '批量 Apply 失败')
  } finally {
    loading.value = false
  }
}

function loadExample(){
  applyJson.value = `{
  "items": [
    {
      "name": "pipeline_demo",
      "source_ref": "rtsp://camera/demo",
      "nodes": [
        { "id": "detector", "type": "model", "params": { "modelUri": "models/detector.onnx" } }
      ]
    }
  ]
}`
}

onMounted(() => { loadExamples() })

function getPipelineName(spec: any): string {
  if (!spec) return ''
  if (typeof spec.pipeline_name === 'string' && spec.pipeline_name) return spec.pipeline_name
  if (typeof spec.name === 'string' && spec.name) return spec.name
  return ''
}

async function fetchStatus(name: string){
  try {
    statusLoading.value = true
    const r: any = await http.get(`/api/control/status?name=${encodeURIComponent(name)}`)
    statusData.value = r?.data || r
  } catch (e:any) {
    ElMessage.error(e?.message || '获取状态失败')
  } finally {
    statusLoading.value = false
  }
}

async function onViewStatus(){
  if (lastPipelineName.value) await fetchStatus(lastPipelineName.value)
}
</script>

<style scoped>
.settings-grid{ align-items: stretch; }
.card-header{ display:flex; align-items:center; justify-content:space-between; }
.title{ font-weight:600; color: var(--va-text-1); }
.subtitle{ font-size:12px; color: var(--va-text-2); opacity:.75; }
.helper{ margin-top:8px; display:flex; justify-content:flex-end; }
.status-panel{ margin-top:8px; background: rgba(255,255,255,.03); border:1px solid rgba(255,255,255,.08); border-radius:6px; padding:8px; }
.status-title{ font-size:12px; color: var(--va-text-2); margin-bottom:4px; }
.status-json{ font-size:12px; line-height:1.5; white-space:pre-wrap; word-break:break-all; }
</style>
