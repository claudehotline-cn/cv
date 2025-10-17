<template>
  <el-row :gutter="16" class="settings-grid">
    <el-col :span="12">
      <el-card shadow="hover">
        <template #header>
          <div class="card-header">
            <div>
              <div class="title">引擎参数</div>
              <div class="subtitle">POST /api/engine/set</div>
            </div>
            <el-button type="primary" size="small" @click="apply" :loading="loading">保存配置</el-button>
          </div>
        </template>
        <el-form :model="engine" label-width="140px" size="small">
          <el-form-item label="启用 NVDEC">
            <el-switch v-model="engine.use_nvdec" />
          </el-form-item>
          <el-form-item label="启用 NVENC">
            <el-switch v-model="engine.use_nvenc" />
          </el-form-item>
          <el-form-item label="多阶段流水线">
            <el-switch v-model="engine.use_multistage" />
          </el-form-item>
          <el-form-item label="CUDA 渲染">
            <el-switch v-model="engine.render_cuda" />
          </el-form-item>
          <el-form-item label="CUDA NMS">
            <el-switch v-model="engine.use_cuda_nms" />
          </el-form-item>
          <el-form-item label="叠加线宽">
            <el-input-number v-model="engine.overlay_thickness" :min="1" :max="6" :step="1" />
          </el-form-item>
          <el-form-item label="叠加透明度">
            <el-input-number v-model="engine.overlay_alpha" :min="0" :max="1" :step="0.05" />
          </el-form-item>
        </el-form>
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
      </el-card>
    </el-col>
  </el-row>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { setEngine, applyPipeline as cpApply, applyPipelines as cpApplyBatch } from '@/api/cp'

const loading = ref(false)
const engine = ref({
  use_nvdec: true,
  use_nvenc: true,
  use_multistage: true,
  render_cuda: true,
  use_cuda_nms: true,
  overlay_thickness: 3,
  overlay_alpha: 0.25
})

async function apply(){
  loading.value = true
  try {
    await setEngine(engine.value as any)
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
    const resp: any = await cpApply(JSON.parse(applyJson.value))
    const ws = resp?.warnings || resp?.data?.warnings || []
    if (Array.isArray(ws) && ws.length) warnings.value = ws
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
</script>

<style scoped>
.settings-grid{ align-items: stretch; }
.card-header{ display:flex; align-items:center; justify-content:space-between; }
.title{ font-weight:600; color: var(--va-text-1); }
.subtitle{ font-size:12px; color: var(--va-text-2); opacity:.75; }
.helper{ margin-top:8px; display:flex; justify-content:flex-end; }
</style>

