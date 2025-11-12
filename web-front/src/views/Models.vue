<template>
  <el-card shadow="hover">
    <template #header>
      <div class="card-header">
        <div>
          <span class="title">模型仓库</span>
          <span class="subtitle">GET /api/repo/list · 回退 /api/models · POST /api/repo/(load|unload|poll)</span>
        </div>
        <el-space>
          <el-input v-model="keyword" placeholder="按名称/任务筛选" size="small" clearable class="search">
            <template #prefix><el-icon><Search/></el-icon></template>
          </el-input>
          <el-button size="small" @click="load" :loading="loading">刷新</el-button>
          <el-button size="small" type="success" @click="openAddDialog">添加模型</el-button>
          <el-divider direction="vertical" />
          <el-input v-model="modelId" placeholder="模型ID（Triton 仓库）" size="small" clearable class="model-id" />
          <el-button size="small" type="primary" @click="repoLoadById" :disabled="!modelId">Load</el-button>
          <el-button size="small" type="warning" @click="repoUnloadById" :disabled="!modelId">Unload</el-button>
          <el-button size="small" text @click="repoPoll">Poll</el-button>
        </el-space>
      </div>
    </template>

    <el-empty v-if="!loading && !filtered.length" description="暂无模型" />
    <el-table v-else :data="filtered" height="480" size="small" stripe>
      <el-table-column prop="id" label="模型 ID" width="220" />
      <el-table-column v-if="!isRepoMode" prop="task" label="任务" width="140" />
      <el-table-column v-if="!isRepoMode" prop="family" label="系列" width="140" />
      <el-table-column v-if="!isRepoMode" prop="variant" label="版本" width="140" />
      <el-table-column prop="path" label="模型路径" show-overflow-tooltip />
      <el-table-column v-if="isRepoMode" label="状态" width="120">
        <template #default="{ row }">
          <el-tag v-if="typeof (row as any).ready !== 'undefined'" :type="(row as any).ready ? 'success' : 'info'" size="small">
            {{ (row as any).ready ? 'ready' : 'unknown' }}
          </el-tag>
          <span v-else>-</span>
        </template>
      </el-table-column>
      <el-table-column v-if="isRepoMode" label="版本列表" width="220">
        <template #default="{ row }">
          <template v-if="(row as any).versions && (row as any).versions.length">
            <el-space wrap>
              <el-tag v-for="v in (row as any).versions" :key="v" size="small" effect="plain" :type="(row as any).active_version === v ? 'success' : 'info'">{{ v }}</el-tag>
            </el-space>
          </template>
          <span v-else>-</span>
        </template>
      </el-table-column>
      <el-table-column v-if="!isRepoMode" label="输入尺寸" width="140">
        <template #default="{ row }">{{ row.input_shape || '-' }}</template>
      </el-table-column>
      <el-table-column v-if="!isRepoMode" label="参数量" width="120">
        <template #default="{ row }">{{ row.params || '-' }}</template>
      </el-table-column>
      <el-table-column label="操作" width="360" fixed="right">
        <template #default="{ row }">
          <el-space>
            <el-button size="small" @click="repoLoad(row.id)">Load</el-button>
            <el-button size="small" @click="repoUnload(row.id)">Unload</el-button>
            <el-button size="small" text @click="repoPoll">Poll</el-button>
            <el-button size="small" text type="primary" @click="openConfig(row.id)" :disabled="!isRepoMode">查看配置</el-button>
          </el-space>
        </template>
      </el-table-column>
    </el-table>

    <div class="footer">
      <el-tag type="info" effect="dark" size="small">共 {{ filtered.length }} 个模型</el-tag>
      <el-tag v-if="tasks.length" type="success" size="small" effect="plain">任务覆盖：{{ tasks.join(', ') }}</el-tag>
    </div>
  </el-card>
  <el-drawer v-model="drawer" size="30%">
    <template #header>
      <div class="cfg-drawer-title">
        <span>模型配置</span>
        <el-tag type="info" effect="plain" size="small">{{ currentModel }}/config.pbtxt</el-tag>
      </div>
    </template>
    <template #default>
      <div class="cfg-toolbar">
        <el-space>
          <el-button size="small" @click="copyConfig" :disabled="!configText">复制</el-button>
          <el-button size="small" @click="downloadConfig" :disabled="!configText">下载</el-button>
          <el-divider direction="vertical" />
          <el-switch v-model="editMode" active-text="编辑" inactive-text="只读" />
          <el-divider direction="vertical" />
          <el-switch v-model="wrapOn" active-text="自动换行" inactive-text="不换行" />
          <el-input-number v-model="fontSize" :min="10" :max="18" size="small" />
        </el-space>
        <div class="cfg-actions" v-if="editMode">
          <el-space>
            <el-button type="primary" size="small" @click="saveConfig" :disabled="!configText || saving">保存</el-button>
            <el-button size="small" @click="reloadConfig" :disabled="saving">重载</el-button>
          </el-space>
        </div>
      </div>
      <div v-if="configText" class="cfg-container">
        <template v-if="!editMode">
          <pre class="cfg-text" :class="{ wrap: wrapOn }" :style="{ fontSize: fontSize + 'px' }"><code v-html="highlightedConfig"></code></pre>
        </template>
        <template v-else>
          <el-input v-model="configText" type="textarea" :autosize="{ minRows: 20, maxRows: 36 }" class="cfg-editor" />
        </template>
      </div>
      <el-empty v-else description="未获取到配置或模型无配置文件" />
    </template>
  </el-drawer>
  <el-dialog v-model="addDlg" title="添加模型" width="640">
    <div style="display:flex; flex-direction:column; gap:12px;">
      <el-form label-width="120px" size="small">
        <el-form-item label="模型 ID">
          <el-input v-model="addForm.model" placeholder="例如 yolov8n" />
        </el-form-item>
        <el-form-item label="平台">
          <el-select v-model="addForm.platform" style="width:100%">
            <el-option label="ONNX Runtime (onnxruntime_onnx)" value="onnxruntime_onnx" />
            <el-option label="TensorRT Plan (tensorrt_plan)" value="tensorrt_plan" />
            <el-option label="自定义（手写）" value="custom" />
          </el-select>
        </el-form-item>
        <el-form-item label="config.pbtxt">
          <el-input type="textarea" :rows="12" v-model="addForm.config" placeholder="配置内容（可自动生成后再调整）" />
        </el-form-item>
        <el-form-item label="版本号">
          <el-input v-model="addForm.version" placeholder="默认 1" />
        </el-form-item>
        <el-form-item label="上传权重文件">
          <div style="display:flex; flex-direction:column; gap:6px;">
            <div>
              <input type="file" @change="onPickFile" :disabled="convertInProgress || uploadInProgress || !addForm.model" />
              <span v-if="addFileName" style="margin-left:8px;color:#666;">{{ addFileName }}</span>
              <span v-if="!addForm.model" style="margin-left:8px;color:#999;">请先填写模型 ID</span>
            </div>
            <div v-if="addForm.platform==='tensorrt_plan' && addIsOnnx">
              <el-tag :type="convertPhase==='done' ? 'success' : (convertPhase==='failed' ? 'danger' : 'info')" size="small" effect="plain">
                {{ convertPhase === 'running' ? '转换中…' : (convertPhase==='uploading' ? '上传中…' : convertPhase || '就绪') }}
              </el-tag>
              <el-progress :percentage="progressPercent" :indeterminate="progressIndeterminate" :status="progressStatus"
                           :stroke-width="8" style="max-width:420px; margin-top:6px;" />
              <pre class="cfg-text" style="max-height:32vh; overflow:auto; white-space:pre-wrap; background:#0b1020; color:#c7d3ff; padding:8px; border-radius:6px; margin-top:6px;" v-text="convertLogs"></pre>
            </div>
            <div v-else-if="addFileName">
              <el-tag v-if="uploadInProgress" type="info" size="small" effect="plain">上传中…</el-tag>
              <el-tag v-else-if="uploadStatus==='uploaded'" type="success" size="small" effect="plain">已上传</el-tag>
              <el-tag v-else-if="uploadStatus==='failed'" type="danger" size="small" effect="plain">上传失败</el-tag>
            </div>
          </div>
        </el-form-item>
        <el-form-item label="创建后立即加载">
          <el-switch v-model="addForm.load" />
        </el-form-item>
      </el-form>
      <el-alert type="info" :closable="false" show-icon
        title="当前为最小实现：创建模型目录与 config.pbtxt。模型文件请通过外部方式放入仓库（FS 或 S3），再在此页面执行 Load。" />
    </div>
    <template #footer>
      <span class="dialog-footer">
        <el-button @click="addDlg=false">取消</el-button>
        <el-button type="primary" :loading="adding" @click="submitAdd">提交</el-button>
      </span>
    </template>
  </el-dialog>
  
</template>

<script setup lang="ts">
import { ref, computed, onMounted, reactive, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import { listModels, cp } from '@/api/cp'

type ModelItem = { id:string; task?:string; family?:string; variant?:string; path?:string; input_shape?:string; params?:string }

const loading = ref(false)
const rows = ref<ModelItem[]>([])
const keyword = ref('')
const modelId = ref('')
const drawer = ref(false)
const currentModel = ref('')
const configText = ref('')
const wrapOn = ref(true)
const fontSize = ref(13)
const editMode = ref(false)
const saving = ref(false)
const truncated = ref(false)
const highlightedConfig = computed(() => highlightPbtxt(configText.value || ''))

// add model dialog state
const addDlg = ref(false)
const adding = ref(false)
const addForm = reactive({ model: '', platform: 'onnxruntime_onnx', config: '', version: '1', load: false })
const addFile = ref<File | null>(null)
const addIsOnnx = computed(() => !!(addFile.value && isOnnxFile(addFile.value.name)))
const addFileName = ref('')
// convert progress (inline under upload widget)
// 不展示日志，仅显示阶段和进度
const convertPhase = ref<'created'|'running'|'uploading'|'done'|'failed'|''>('')
const progressPercent = ref(0)
const progressIndeterminate = ref(true)
const progressStatus = ref<'success'|'exception'|''>('')
const convertInProgress = ref(false)
// direct upload state (non-conversion)
const uploadInProgress = ref(false)
const uploadStatus = ref<'uploaded'|'failed'|''>('')
let convertEs: EventSource | null = null
let convertUploaded = false

async function load(){
  loading.value = true
  try{
    // Prefer Triton repo list via CP proxy; fallback to DB list
    let items: any[] = []
    try {
      const repo = await cp.repoList()
      items = (repo as any).data || (repo as any).items || []
    } catch (_) { /* ignore and fallback */ }
    if (!items.length) {
      const resp = await listModels()
      items = (resp as any).data || (resp as any).items || []
    }
    rows.value = items as any[]
  } catch (e:any){
    ElMessage.error(e?.message || '加载模型失败')
  } finally {
    loading.value = false
  }
}

const isRepoMode = computed(() => rows.value.some((r:any) => typeof (r as any).ready !== 'undefined' || (r as any).versions))

const filtered = computed(() => {
  if (!keyword.value) return rows.value
  const k = keyword.value.toLowerCase()
  return rows.value.filter((r:any) => {
    const fields = [`${r.id}`, r.task || '', r.family || '', r.variant || '']
    if (Array.isArray(r.versions)) fields.push(...r.versions.map((x:string)=>String(x)))
    if (r.active_version) fields.push(String(r.active_version))
    return fields.some(v => String(v).toLowerCase().includes(k))
  })
})

const tasks = computed(() => Array.from(new Set(filtered.value.map(r => r.task).filter(Boolean))) as string[])

onMounted(load)

async function repoLoad(id: string){ try { await cp.repoLoad(id); ElMessage.success('Load 已提交') } catch(e:any){ ElMessage.error(e?.message||'Load 失败') } }
async function repoUnload(id: string){ try { await cp.repoUnload(id); ElMessage.success('Unload 已提交') } catch(e:any){ ElMessage.error(e?.message||'Unload 失败') } }
async function repoPoll(){ try { await cp.repoPoll(); ElMessage.success('Poll 已提交') } catch(e:any){ ElMessage.error(e?.message||'Poll 失败') } }

async function repoLoadById(){ if (!modelId.value) return; await repoLoad(modelId.value) }
async function repoUnloadById(){ if (!modelId.value) return; await repoUnload(modelId.value) }

async function openConfig(id: string){
  try{
    currentModel.value = id
    const r:any = await cp.repoConfig(id)
    configText.value = (r?.data?.content || '') as string
    truncated.value = false
    drawer.value = true
  }catch(e:any){ ElMessage.error(e?.message || '获取配置失败') }
}
async function copyConfig(){ try{ await navigator.clipboard.writeText(configText.value); ElMessage.success('已复制') } catch{ ElMessage.error('复制失败') } }
async function downloadConfig(){
  try{
    const blob = new Blob([configText.value || ''], { type: 'text/plain;charset=utf-8' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `${currentModel.value || 'model'}.config.pbtxt`
    document.body.appendChild(a); a.click(); a.remove()
    URL.revokeObjectURL(a.href)
  }catch{ ElMessage.error('下载失败') }
}
async function saveConfig(){
  try{
    saving.value = true
    await cp.repoSaveConfig(currentModel.value, configText.value || '')
    ElMessage.success('已保存')
    editMode.value = false
  }catch(e:any){ ElMessage.error(e?.message || '保存失败') }
  finally{ saving.value = false }
}
async function reloadConfig(){ await openConfig(currentModel.value) }

function highlightPbtxt(src: string): string {
  const MAX_LEN = 200000; const MAX_LINES = 2000;
  const esc = (s: string) => s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
  let raw = src
  if (raw.length > MAX_LEN) { raw = raw.slice(0, MAX_LEN); truncated.value = true }
  let lines = raw.split(/\r?\n/)
  if (lines.length > MAX_LINES) { lines = lines.slice(0, MAX_LINES); truncated.value = true }
  const kw = ['name','platform','max_batch_size','version_policy','input','output','dims','data_type','format','instance_group','count','kind','backend','parameters','optimization','graph_level','dynamic_batching']
  const consts = ['KIND_GPU','KIND_CPU','FORMAT_NCHW','FORMAT_NHWC','TYPE_FP32','TYPE_FP16','TYPE_INT8','TYPE_INT32','TYPE_UINT8']
  const kwRe = new RegExp('\\b(' + kw.join('|') + ')\\b','g')
  const cstRe = new RegExp('\\b(' + consts.join('|') + ')\\b','g')
  const numRe = /\b\d+(?:\.\d+)?\b/g
  const strRe = /"(?:[^"\\]|\\.)*"/g
  const out: string[] = []
  for (let i=0;i<lines.length;i++) {
    const ln = lines[i]
    let code = esc(ln)
    code = code.replace(strRe, (s) => `<span class=tok-str>${s}</span>`)
    code = code.replace(numRe, (s) => `<span class=tok-num>${s}</span>`)
    code = code.replace(cstRe, (s) => `<span class=tok-const>${s}</span>`)
    code = code.replace(kwRe, (s) => `<span class=tok-key>${s}</span>`)
    const idxHash = code.indexOf('#')
    const idxSl = code.indexOf('//')
    let idx = -1
    if (idxHash >=0 && idxSl >=0) idx = Math.min(idxHash, idxSl); else idx = (idxHash>=0? idxHash: idxSl)
    if (idx >= 0) code = code.slice(0, idx) + `<span class=tok-comment>${code.slice(idx)}</span>`
    out.push(code)
  }
  return out.join('\n')
}

function openAddDialog(){
  addForm.model = ''
  addForm.platform = 'onnxruntime_onnx'
  addForm.config = ''
  addForm.version = '1'
  addForm.load = false
  addFile.value = null
  addFileName.value = ''
  addDlg.value = true
}

watch(() => addForm.platform, (p) => {
  if (!addForm.config || addForm.config.trim().length === 0 || addForm.config.indexOf('name:') === 0) {
    const name = addForm.model || '<model>'
    if (p === 'onnxruntime_onnx') {
      addForm.config = [
        `name: "${name}"`,
        `platform: "onnxruntime_onnx"`,
        `max_batch_size: 1`,
        `input: [ { name: "images", data_type: TYPE_FP32, dims: [ 3, -1, -1 ], format: FORMAT_NCHW } ]`,
        `output: [ { name: "output", data_type: TYPE_FP32, dims: [ -1 ] } ]`
      ].join('\n')
    } else if (p === 'tensorrt_plan') {
      addForm.config = [
        `name: "${name}"`,
        `platform: "tensorrt_plan"`,
        `max_batch_size: 1`
      ].join('\n')
    } else {
      addForm.config = `name: "${name}"\n# 自定义 config.pbtxt`
    }
  }
})

watch(() => addForm.model, (m) => {
  if (addForm.config && addForm.config.startsWith('name:')) {
    addForm.config = addForm.config.replace(/name:\s*\"[^\"]*\"/, `name: "${m}"`)
  }
})

async function submitAdd(){
  if (!addForm.model) { ElMessage.warning('请填写模型ID'); return }
  try{
    adding.value = true
    await cp.repoAddModel({ model: addForm.model, config: addForm.config, load: false })
    // Load only when requested and not during in-progress conversion
    if (addForm.load) {
      if (convertInProgress.value) {
        ElMessage.info('转换未完成，稍后请在列表中执行 Load')
      } else {
        try { await cp.repoLoad(addForm.model); ElMessage.success('Load 已提交') } catch(e:any){ ElMessage.error(e?.message||'Load 失败') }
      }
    }
    ElMessage.success('已创建模型配置')
    addDlg.value = false
    await load()
  } catch(e:any) {
    ElMessage.error(e?.message || '创建失败')
  } finally {
    adding.value = false
  }
}

function onPickFile(e: Event){
  const t = e.target as HTMLInputElement
  const f = t.files && t.files[0]
  if (f) {
    addFile.value = f; addFileName.value = `${f.name} (${Math.round(f.size/1024)} KB)`
    // Auto-convert when platform is TensorRT and file is ONNX
    if (addForm.platform === 'tensorrt_plan' && isOnnxFile(f.name)) {
      startConvertUpload()
    } else {
      startDirectUpload()
    }
  }
}

function isOnnxFile(name: string){ return /\.onnx$/i.test(name || '') }

async function startConvertUpload(){
  if (!addForm.model) { ElMessage.warning('请先填写模型ID'); return }
  if (!addFile.value) return
  try {
    convertInProgress.value = true
    convertUploaded = false
    // 初始提示由进度条体现，无需日志
    convertPhase.value = 'running'
    progressIndeterminate.value = true
    progressStatus.value = ''
    progressPercent.value = 3
    const r:any = await cp.repoConvertUpload({ model: addForm.model || '<model>', version: addForm.version || '1', file: addFile.value })
    const events = (r?.data?.events || '') as string
    if (!events) { convertPhase.value = 'failed'; ElMessage.error('转换任务创建失败'); convertInProgress.value = false; return }
    // 优先使用绝对事件 URL；否则拼接 CP 基础地址
    const evAbs = (r?.data?.events_abs || '') as string
    const base = ((import.meta as any).env?.DEV ? '' : ((((import.meta as any).env?.VITE_CP_BASE_URL || (import.meta as any).env?.VITE_API_BASE || '')) as string)).toString().replace(/\/+$/, '')
    const url = evAbs || `${base}${events}`
    convertEs && convertEs.close(); convertEs = new EventSource(url)
    convertEs.addEventListener('state', (ev:any) => {
      try {
        const d = JSON.parse(ev.data)
        if (d.phase) convertPhase.value = d.phase as any
        if (typeof d.progress === 'number') { progressIndeterminate.value = false; progressPercent.value = Math.max(progressPercent.value, Math.min(100, Math.max(0, Math.round(d.progress)))) }
      } catch {}
      if (convertPhase.value === 'uploading') { progressIndeterminate.value = false; progressPercent.value = Math.max(progressPercent.value, 90) }
      if (convertPhase.value === 'failed') { progressIndeterminate.value = false; progressStatus.value = 'exception' }
    })
    convertEs.addEventListener('done', async (ev:any) => {
      try { const d = JSON.parse(ev.data); convertPhase.value = (d.phase || 'done') as any } catch { convertPhase.value = 'done' as any }
      convertEs && convertEs.close(); convertEs = null
      convertInProgress.value = false; convertUploaded = (convertPhase.value==='done')
      progressIndeterminate.value = false
      progressPercent.value = (convertPhase.value==='done') ? 100 : progressPercent.value
      if (convertPhase.value==='done') progressStatus.value = 'success'
      await load()
    })
    convertEs.onerror = () => {
      // 提示用户事件流连不上，但不终止转换（后台仍可能进行）
      if (convertPhase.value === 'running') {
        // 无日志模式，静默退让：仅以进度条不确定状态显示
        progressIndeterminate.value = true
      }
    }
  } catch (err:any) {
    convertPhase.value = 'failed'
    convertInProgress.value = false
    ElMessage.error(err?.message || '转换启动失败')
  }
}

async function startDirectUpload(){
  if (!addFile.value) return
  try {
    uploadInProgress.value = true
    uploadStatus.value = ''
    await cp.repoUpload({ model: addForm.model, version: addForm.version || '1', file: addFile.value })
    uploadStatus.value = 'uploaded'
    ElMessage.success('文件已上传到模型仓库')
  } catch (err:any) {
    uploadStatus.value = 'failed'
    ElMessage.error(err?.message || '上传失败')
  } finally {
    uploadInProgress.value = false
  }
}

function closeConvert(){
  convertEs && convertEs.close(); convertEs = null
  convertDlg.value = false
}
</script>

<style scoped>
.card-header{ display:flex; align-items:center; justify-content:space-between; gap:12px; }
.title{ font-weight:600; color: var(--va-text-1); }
.subtitle{ font-size:12px; color: var(--va-text-2); margin-left:4px; }
.search{ width: 220px; }
.model-id{ width: 260px; }
.footer{ margin-top:12px; display:flex; gap:8px; }
.cfg-drawer-title{ display:flex; align-items:center; gap:8px; font-weight:600; }
.cfg-toolbar{ display:flex; justify-content:space-between; align-items:center; padding:8px 0 12px; }
.cfg-container{ border:1px solid #eaecef; border-radius:6px; background:#f6f8fa; }
.cfg-text{ margin:0; padding:12px; color:#24292e; line-height:1.5; max-height:65vh; overflow:auto; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; white-space:pre; }
.cfg-text.wrap{ white-space:pre-wrap; word-break:break-word; }
.cfg-editor :deep(textarea){ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
.tok-key{ color:#005cc5; font-weight:600; }
.tok-const{ color:#6f42c1; }
.tok-num{ color:#e36209; }
.tok-str{ color:#032f62; }
.tok-comment{ color:#6a737d; }
</style>

