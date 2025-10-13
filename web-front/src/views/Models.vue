<template>
  <el-card shadow="hover">
    <template #header>
      <div class="card-header">
        <div>
          <span class="title">模型仓库</span>
          <span class="subtitle">GET /api/models</span>
        </div>
        <el-space>
          <el-input v-model="keyword" placeholder="按名称/任务筛选" size="small" clearable class="search">
            <template #prefix><el-icon><Search/></el-icon></template>
          </el-input>
          <el-button size="small" @click="load" :loading="loading">刷新</el-button>
        </el-space>
      </div>
    </template>

    <el-empty v-if="!loading && !filtered.length" description="暂无模型" />
    <el-table v-else :data="filtered" height="480" size="small" stripe>
      <el-table-column prop="id" label="模型 ID" width="220" />
      <el-table-column prop="task" label="任务" width="140" />
      <el-table-column prop="family" label="系列" width="140" />
      <el-table-column prop="variant" label="版本" width="140" />
      <el-table-column prop="path" label="模型路径" show-overflow-tooltip />
      <el-table-column label="输入尺寸" width="140">
        <template #default="{ row }">{{ row.input_shape || '-' }}</template>
      </el-table-column>
      <el-table-column label="参数量" width="120">
        <template #default="{ row }">{{ row.params || '-' }}</template>
      </el-table-column>
    </el-table>

    <div class="footer">
      <el-tag type="info" effect="dark" size="small">共 {{ filtered.length }} 个模型</el-tag>
      <el-tag v-if="tasks.length" type="success" size="small" effect="plain">任务覆盖：{{ tasks.join(', ') }}</el-tag>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import { listModels } from '@/api/cp'

type ModelItem = { id:string; task?:string; family?:string; variant?:string; path?:string; input_shape?:string; params?:string }

const loading = ref(false)
const rows = ref<ModelItem[]>([])
const keyword = ref('')

async function load(){
  loading.value = true
  try{
    const resp = await listModels()
    rows.value = (resp as any).data || []
  } catch (e:any){
    ElMessage.error(e?.message || '加载模型失败')
  } finally {
    loading.value = false
  }
}

const filtered = computed(() => {
  if (!keyword.value) return rows.value
  const k = keyword.value.toLowerCase()
  return rows.value.filter(r =>
    [`${r.id}`, r.task || '', r.family || '', r.variant || ''].some(v => v.toLowerCase().includes(k))
  )
})

const tasks = computed(() => Array.from(new Set(filtered.value.map(r => r.task).filter(Boolean))) as string[])

onMounted(load)
</script>

<style scoped>
.card-header{ display:flex; align-items:center; justify-content:space-between; gap:12px; }
.title{ font-weight:600; color: var(--va-text-1); }
.subtitle{ font-size:12px; color: var(--va-text-2); margin-left:4px; }
.search{ width: 220px; }
.footer{ margin-top:12px; display:flex; gap:8px; }
</style>

