<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { trainStart, trainStatus, trainList, trainEventsUrl, trainDeploy } from '@/api/cp'

const cfgText = ref<string>(`{
  "run": { "experiment": "cv-classification", "run_name": "resnet18-baseline", "seed": 42, "device": "cpu" },
  "data": { "format": "image_folder", "train_dir": "", "val_dir": "", "num_classes": 2 },
  "model": { "arch": "resnet18", "pretrained": true },
  "train": { "epochs": 5, "batch_size": 16, "lr": 0.001 },
  "export": { "onnx": true, "opset": 17, "dynamic_axes": false, "input_size": [1,3,224,224] },
  "register": { "model_name": "cv/resnet18", "promote": "none" }
}`)

type JobItem = { id: string; status?: string; phase?: string; progress?: number }
const jobs = ref<JobItem[]>([])
const watchingId = ref<string>('')
const events: any[] = []
let es: EventSource | null = null
const progress = ref<number>(0)
const phase = ref<string>('')
const artifacts = ref<{ name:string; url:string; size_mb?: number; s3_uri?: string }[]>([])
const modelId = ref<string>('')
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
    const cfg = JSON.parse(cfgText.value)
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
      <div style="display:flex; gap:8px; margin-bottom:8px">
        <el-input v-model="modelId" placeholder="模型 ID（如：cv/resnet18）" />
        <el-input v-model.number="accMin" style="width:180px" placeholder="accuracy_min (0~1)" />
      </div>
      <el-input v-model="cfgText" type="textarea" :rows="10" />
      <div style="margin-top:10px; text-align:right">
        <el-button type="primary" @click="startJob">开始训练</el-button>
      </div>
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
</style>
