<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { trainStart, trainStatus, trainList, trainEventsUrl, trainDeploy } from '@/api/cp'

// 结构化表单（替换大 textarea）
const form = reactive({
  run: { experiment: 'cv-classification', run_name: 'resnet18-baseline', seed: 42, device: 'cpu' as 'cpu'|'gpu' },
  data: { format: 'image_folder', train_dir: '', val_dir: '', num_classes: 2 },
  model: { arch: 'resnet18', pretrained: true },
  train: { epochs: 5, batch_size: 16, lr: 0.001 },
  export: { onnx: true, opset: 17, dynamic_axes: false, preset: 224 as number| 'custom', image_h: 224, image_w: 224 },
  register: { model_name: 'cv/resnet18', promote: 'none' as 'none'|'canary'|'prod' }
})

type JobItem = { id: string; status?: string; phase?: string; progress?: number }
const jobs = ref<JobItem[]>([])
const watchingId = ref<string>('')
const events: any[] = []
let es: EventSource | null = null
const progress = ref<number>(0)
const phase = ref<string>('')
const artifacts = ref<{ name:string; url:string; size_mb?: number; s3_uri?: string }[]>([])
const modelId = ref<string>('cv/resnet18')
const metrics = ref<{ time:number; key:string; value:number }[]>([])
const sseLines = ref<string[]>([])
const accMin = ref<number>(0.7)

// 转换进度对话框（导入仓库后跟踪）
const convertDlg = ref(false)
const convertProgress = ref(0)
const convertPhase = ref('')
let convES: EventSource | null = null

async function fetchList() {
  try { const r = await trainList(); jobs.value = (r?.data||[]) as any[] } catch { /* ignore */ }
}

async function startJob() {
  try {
    // 同步表单中的模型 ID 到注册信息
    form.register.model_name = modelId.value || form.register.model_name
    // 由表单构建配置
    // 计算导出尺寸（方形预设或自定义 HxW）
    let h = 224, w = 224
    if (form.export.preset === 'custom') {
      h = Math.max(32, Math.min(2048, Number(form.export.image_h || 224)))
      w = Math.max(32, Math.min(2048, Number(form.export.image_w || 224)))
    } else {
      const sz = Number(form.export.preset || 224)
      h = sz; w = sz
    }
    const cfg = {
      run: { ...form.run },
      data: { ...form.data },
      model: { ...form.model },
      train: { ...form.train },
      export: { onnx: form.export.onnx, opset: form.export.opset, dynamic_axes: form.export.dynamic_axes, input_size: [1, 3, h, w] },
      register: { ...form.register }
    }
    const r: any = await trainStart(cfg)
    const id = r?.data?.job
    if (!id) throw new Error('invalid response')
    ElMessage.success('已启动训练: ' + id)
    watchJob(id)
    fetchList()
  } catch (e:any) { ElMessage.error(e?.message || '启动失败') }
}

function watchJob(id: string) {
  if (es) { try { es.close() } catch {} es = null }
  watchingId.value = id
  progress.value = 0; phase.value = ''
  const url = trainEventsUrl(id)
  es = new EventSource(url)
  es.addEventListener('state', (ev: MessageEvent) => {
    try { const d = JSON.parse(ev.data); if (typeof d.progress === 'number') progress.value = Math.max(progress.value, d.progress*100); if (d.phase) phase.value = d.phase } catch {}
    sseLines.value.push(`[state] ${ev.data}`)
  })
  es.addEventListener('metrics', (ev: MessageEvent) => {
    try {
      const d = JSON.parse(ev.data)
      const now = Date.now()
      Object.entries(d || {}).forEach(([k,v]) => {
        if (typeof v === 'number') metrics.value.push({ time: now, key: k, value: v as number })
      })
    } catch {}
    sseLines.value.push(`[metrics] ${ev.data}`)
  })
  es.addEventListener('done', () => { ElMessage.success('训练完成'); if (es) { es.close(); es=null } fetchList(); refreshArtifacts(id) })
  es.onerror = () => { /* 网络抖动可忽略 */ }
}

onMounted(() => { fetchList(); const t = setInterval(fetchList, 4000); (window as any).__trainTimer = t })

async function refreshArtifacts(id: string) {
  try {
    const r = await fetch(`/api/train/artifacts?id=${encodeURIComponent(id)}`)
    const j = await r.json()
    artifacts.value = (j?.data||[]) as any[]
  } catch { artifacts.value = [] }
}

async function importToRepo() {
  if (!watchingId.value) { ElMessage.warning('请选择一个训练任务'); return }
  if (!modelId.value) { ElMessage.warning('请输入模型 ID'); return }
  try {
    const item = artifacts.value.find(a => a.name === 'model.onnx')
    if (!item) { ElMessage.error('未找到 ONNX 工件'); return }
    const resp = await fetch(`/api/train/artifacts/download?id=${encodeURIComponent(watchingId.value)}&name=model.onnx`)
    if (!resp.ok) throw new Error('下载工件失败')
    const blob = await resp.blob()
    const file = new File([blob], 'model.onnx', { type: 'application/octet-stream' })
    const base = ((import.meta as any).env?.DEV ? '' : (((import.meta as any).env?.VITE_API_BASE || '') as string)).toString().replace(/\/+$/, '')
    const q = new URLSearchParams({ model: modelId.value, filename: file.name, version: '1' })
    const url = `${base}/api/repo/convert_upload?${q.toString()}`
    const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: file })
    if (!r.ok) { const t = await r.text().catch(()=> ''); throw new Error(t || 'convert_upload 失败') }
    const j = await r.json()
    const evUrl = (j?.data?.events || '') as string
    if (evUrl) {
      // 订阅转换进度
      openConvertDialog(evUrl)
    } else {
      ElMessage.success('已发起导入与转换。')
    }
  } catch (e:any) {
    ElMessage.error(e?.message || '导入失败')
  }
}

async function deployWithGates() {
  if (!watchingId.value) { ElMessage.warning('请选择一个训练任务'); return }
  if (!modelId.value) { ElMessage.warning('请输入模型 ID'); return }
  try {
    const payload: any = { job: watchingId.value, model: modelId.value, version: '1', gates: { accuracy_min: accMin.value } }
    const r: any = await trainDeploy(payload)
    const evUrl = (r?.data?.events || '') as string
    if (evUrl) {
      openConvertDialog(evUrl)
      ElMessage.success('已触发部署与转换（带门槛）')
    } else {
      ElMessage.success('已触发部署与转换')
    }
  } catch (e:any) {
    ElMessage.error(e?.message || '部署失败')
  }
}

function openConvertDialog(eventsUrl: string) {
  // 计算绝对 URL
  const base = ((import.meta as any).env?.DEV ? '' : (((import.meta as any).env?.VITE_API_BASE || '') as string)).toString().replace(/\/+$/, '')
  const abs = eventsUrl.startsWith('/') ? (base + eventsUrl) : eventsUrl
  convertDlg.value = true
  convertProgress.value = 0
  convertPhase.value = 'running'
  if (convES) { try { convES.close() } catch {} convES = null }
  convES = new EventSource(abs)
  convES.addEventListener('state', (ev: MessageEvent) => {
    try { const d = JSON.parse(ev.data); if (typeof d.progress === 'number') convertProgress.value = Math.max(convertProgress.value, d.progress*100); if (d.phase) convertPhase.value = d.phase } catch {}
  })
  convES.addEventListener('done', async () => {
    convertProgress.value = 100; convertPhase.value = 'done'
    if (convES) { try { convES.close() } catch {} convES = null }
    // 自动加载 VA
    try {
      const resp = await fetch('/api/repo/load', { method: 'POST', headers: { 'Content-Type':'application/json' }, body: JSON.stringify({ model: modelId.value }) })
      if (resp.ok) ElMessage.success('已转换并加载到 VA')
      else ElMessage.warning('已转换，但加载 VA 失败')
    } catch { /* ignore */ }
  })
  convES.onerror = () => { /* 网络抖动可忽略 */ }
}
</script>

<template>
  <div class="wrap">
    <el-card class="card">
      <template #header>
        <div class="card-hd">启动训练</div>
      </template>
      <el-form :model="form" label-width="120px" label-position="left" class="train-form" size="small">
        <div class="grid">
          <el-form-item label="模型 ID">
            <el-input v-model="modelId" class="w-lg" placeholder="例如：cv/resnet18" />
          </el-form-item>
          <el-form-item label="accuracy_min">
            <el-input-number v-model="accMin" class="w-sm" :min="0" :max="1" :step="0.01" :precision="2" />
          </el-form-item>
        </div>

        <el-divider content-position="left">运行</el-divider>
        <div class="grid">
          <el-form-item label="实验名">
            <el-input v-model="form.run.experiment" class="w-md" placeholder="cv-classification" />
          </el-form-item>
          <el-form-item label="运行名">
            <el-input v-model="form.run.run_name" class="w-md" placeholder="resnet18-baseline" />
          </el-form-item>
          <el-form-item label="随机种子">
            <el-input-number v-model="form.run.seed" class="w-sm" :min="0" :max="999999" />
          </el-form-item>
          <el-form-item label="设备">
            <el-select v-model="form.run.device" class="w-md">
              <el-option label="CPU" value="cpu" />
              <el-option label="GPU" value="gpu" />
            </el-select>
          </el-form-item>
        </div>

        <el-divider content-position="left">数据</el-divider>
        <div class="grid">
          <el-form-item label="格式">
            <el-select v-model="form.data.format" class="w-md">
              <el-option label="image_folder" value="image_folder" />
            </el-select>
          </el-form-item>
          <el-form-item label="类别数">
            <el-input-number v-model="form.data.num_classes" class="w-sm" :min="2" />
          </el-form-item>
          <el-form-item label="训练目录" class="span-2">
            <el-input v-model="form.data.train_dir" class="w-lg" placeholder="/data/train" />
          </el-form-item>
          <el-form-item label="验证目录" class="span-2">
            <el-input v-model="form.data.val_dir" class="w-lg" placeholder="/data/val" />
          </el-form-item>
        </div>

        <el-divider content-position="left">模型</el-divider>
        <div class="grid">
          <el-form-item label="架构">
            <el-select v-model="form.model.arch" class="w-md">
              <el-option label="resnet18" value="resnet18" />
              <el-option label="resnet34" value="resnet34" />
              <el-option label="resnet50" value="resnet50" />
              <el-option label="mobilenet_v3_small" value="mobilenet_v3_small" />
            </el-select>
          </el-form-item>
          <el-form-item label="预训练">
            <el-switch v-model="form.model.pretrained" />
          </el-form-item>
        </div>

        <el-divider content-position="left">训练</el-divider>
        <div class="grid">
          <el-form-item label="epochs">
            <el-input-number v-model="form.train.epochs" class="w-sm" :min="1" :max="1000" />
          </el-form-item>
          <el-form-item label="batch_size">
            <el-input-number v-model="form.train.batch_size" class="w-sm" :min="1" :max="4096" />
          </el-form-item>
          <el-form-item label="learning rate">
            <el-input-number v-model="form.train.lr" class="w-sm" :step="0.0001" :precision="6" :min="0" />
          </el-form-item>
        </div>

        <el-divider content-position="left">导出</el-divider>
        <div class="grid">
          <el-form-item label="导出 ONNX">
            <el-switch v-model="form.export.onnx" />
          </el-form-item>
          <el-form-item label="opset">
            <el-input-number v-model="form.export.opset" class="w-sm" :min="11" :max="21" />
          </el-form-item>
          <el-form-item label="dynamic_axes">
            <el-switch v-model="form.export.dynamic_axes" />
          </el-form-item>
          <el-form-item label="输入尺寸">
            <div class="size-row">
              <el-select v-model="form.export.preset" class="w-md">
                <el-option label="224 × 224" :value="224" />
                <el-option label="256 × 256" :value="256" />
                <el-option label="320 × 320" :value="320" />
                <el-option label="384 × 384" :value="384" />
                <el-option label="自定义" value="custom" />
              </el-select>
              <template v-if="form.export.preset === 'custom'">
                <span class="dims">H</span>
                <el-input-number v-model="form.export.image_h" class="w-sm" :min="32" :max="2048" />
                <span class="sep">×</span>
                <span class="dims">W</span>
                <el-input-number v-model="form.export.image_w" class="w-sm" :min="32" :max="2048" />
              </template>
            </div>
          </el-form-item>
        </div>

        <el-divider content-position="left">注册</el-divider>
        <div class="grid">
          <el-form-item label="别名策略">
            <el-select v-model="form.register.promote" class="w-md">
              <el-option label="none" value="none" />
              <el-option label="canary" value="canary" />
              <el-option label="prod" value="prod" />
            </el-select>
          </el-form-item>
        </div>

        <div style="margin-top:10px; text-align:right">
          <el-button type="primary" @click="startJob">开始训练</el-button>
        </div>
      </el-form>
    </el-card>

    <el-card class="card">
      <template #header>
        <div class="card-hd">任务列表</div>
      </template>
      <el-table :data="jobs" size="small" stripe>
        <el-table-column prop="id" label="Job ID" width="260" />
        <el-table-column prop="status" label="状态" width="120" />
        <el-table-column prop="phase" label="阶段" width="160" />
        <el-table-column label="进度">
          <template #default="{ row }">
            <el-progress :percentage="Math.round((row.progress||0)*100)" :stroke-width="10" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="140">
          <template #default="{ row }">
            <el-button size="small" @click="watchJob(row.id)">查看</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="watchingId" class="watch">
        <div class="watch-hd">监控：{{watchingId}} <span class="phase">{{phase}}</span></div>
        <el-progress :percentage="Math.round(progress)" :stroke-width="12" status="success" />
        <div v-if="artifacts.length" style="margin-top:10px">
          <div>工件：</div>
          <el-table :data="artifacts" size="small" style="width:100%">
            <el-table-column prop="name" label="文件" width="160" />
            <el-table-column prop="size_mb" label="大小(MB)" width="120">
              <template #default="{ row }">{{ row.size_mb ?? '-' }}</template>
            </el-table-column>
            <el-table-column label="下载">
              <template #default="{ row }">
                <a :href="`/api/train/artifacts/download?id=${encodeURIComponent(watchingId)}&name=${encodeURIComponent(row.name)}`" target="_blank">下载</a>
              </template>
            </el-table-column>
            <el-table-column prop="s3_uri" label="对象存储 URI">
              <template #default="{ row }"><span style="font-family:monospace">{{ row.s3_uri || '-' }}</span></template>
            </el-table-column>
          </el-table>
          <el-button type="success" size="small" @click="importToRepo">仅导入并转换</el-button>
          <el-button type="primary" size="small" @click="deployWithGates">部署（带门槛）</el-button>
        </div>
      </div>
    </el-card>
  </div>

  <el-dialog v-model="convertDlg" title="转换进度" width="520px">
    <div style="padding:8px 4px">
      <div style="margin-bottom:6px">阶段：{{convertPhase}}</div>
      <el-progress :percentage="Math.round(convertProgress)" :stroke-width="12" />
    </div>
    <template #footer>
      <el-button @click="convertDlg=false">关闭</el-button>
    </template>
  </el-dialog>
  
</template>

<style scoped>
.wrap{ padding: 16px; }
.card{ margin-bottom: 16px; }
.card-hd{ font-weight: 600; }
.watch{ margin-top: 12px; }
.phase{ margin-left: 8px; color: var(--va-text-2); }
.train-form .inline{ display:inline-flex; align-items:center; gap:6px; }
.train-form .dims{ color: var(--va-text-2); font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
.train-form .grid{ display:grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 8px 16px; align-items: center; }
.train-form .span-2{ grid-column: span 2; }
.train-form .w-sm{ width: 140px; }
.train-form .w-md{ width: 260px; }
.train-form .w-lg{ width: 420px; max-width: 100%; }
.train-form .size-row{ display:flex; align-items:center; gap:8px; flex-wrap: wrap; }
.train-form .sep{ color: var(--va-text-2); margin: 0 2px; }
@media (max-width: 960px){
  .train-form .span-2{ grid-column: auto; }
  .train-form .w-lg{ width: 100%; }
}
</style>
