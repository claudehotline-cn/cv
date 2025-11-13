<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { trainStart, trainStatus, trainList, trainEventsUrl } from '@/api/cp'

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
  })
  es.addEventListener('metrics', (ev: MessageEvent) => { /* 可扩展显示 */ })
  es.addEventListener('done', () => { ElMessage.success('训练完成'); if (es) { es.close(); es=null } fetchList() })
  es.onerror = () => { /* 网络抖动可忽略 */ }
}

onMounted(() => { fetchList(); const t = setInterval(fetchList, 4000); (window as any).__trainTimer = t })
</script>

<template>
  <div class="wrap">
    <el-card class="card">
      <template #header>
        <div class="card-hd">启动训练</div>
      </template>
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
      </div>
    </el-card>
  </div>
  
</template>

<style scoped>
.wrap{ padding: 16px; }
.card{ margin-bottom: 16px; }
.card-hd{ font-weight: 600; }
.watch{ margin-top: 12px; }
.phase{ margin-left: 8px; color: var(--va-text-2); }
</style>

