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
  <el-drawer v-model="drawer" size="55%">
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
          <el-switch v-model="wrapOn" active-text="自动换行" inactive-text="不换行" />
          <el-input-number v-model="fontSize" :min="10" :max="18" size="small" />
        </el-space>
      </div>
      <div v-if="configText" class="cfg-container">
        <pre class="cfg-text" :class="{ wrap: wrapOn }" :style="{ fontSize: fontSize + 'px' }"><code>{{ configText }}</code></pre>
      </div>
      <el-empty v-else description="未获取到配置或模型无配置文件" />
    </template>
  </el-drawer>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
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
</style>

