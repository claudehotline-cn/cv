<template>
  <div class="eval-page">
    <div class="panel">
      <h3>评测数据集</h3>
      <div class="row">
        <el-input v-model="newDatasetName" placeholder="新数据集名称" />
        <el-button type="primary" @click="createDataset">创建</el-button>
      </div>
      <el-table :data="datasets" size="small" @row-click="onSelectDataset" height="260">
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="description" label="描述" />
      </el-table>
    </div>

    <div class="panel" v-if="selectedDatasetId">
      <h3>用例</h3>
      <div class="row">
        <el-button @click="importSampleCases">导入示例用例</el-button>
      </div>
      <el-table :data="cases" size="small" height="260">
        <el-table-column prop="id" label="ID" width="280" />
        <el-table-column label="输入">
          <template #default="scope">
            <span>{{ stringify(scope.row.input) }}</span>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div class="panel" v-if="selectedDatasetId">
      <h3>运行</h3>
      <div class="row">
        <el-button type="success" @click="createRun">创建并执行</el-button>
      </div>
      <el-table :data="runs" size="small" @row-click="onSelectRun" height="220">
        <el-table-column prop="id" label="Run ID" width="280" />
        <el-table-column prop="status" label="状态" width="120" />
        <el-table-column label="Summary">
          <template #default="scope">
            <span>{{ stringify(scope.row.summary) }}</span>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div class="panel" v-if="selectedRunId">
      <h3>运行结果</h3>
      <el-table :data="results" size="small" height="240">
        <el-table-column prop="case_id" label="Case ID" width="280" />
        <el-table-column prop="status" label="状态" width="120" />
        <el-table-column label="Scores">
          <template #default="scope">
            <span>{{ stringify(scope.row.scores) }}</span>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import apiClient from '@/api/client'

const route = useRoute()
const agentId = String(route.params.id || '')

const datasets = ref<any[]>([])
const selectedDatasetId = ref<string>('')
const newDatasetName = ref('')
const cases = ref<any[]>([])
const runs = ref<any[]>([])
const selectedRunId = ref<string>('')
const results = ref<any[]>([])

function stringify(v: any) {
  try {
    return JSON.stringify(v)
  } catch {
    return String(v)
  }
}

async function loadDatasets() {
  const res = await apiClient.listAgentEvalDatasets(agentId)
  datasets.value = res.items || []
}

async function createDataset() {
  if (!newDatasetName.value.trim()) {
    ElMessage.warning('请输入数据集名称')
    return
  }
  await apiClient.createAgentEvalDataset(agentId, { name: newDatasetName.value.trim() })
  ElMessage.success('数据集已创建')
  newDatasetName.value = ''
  await loadDatasets()
}

async function onSelectDataset(row: any) {
  selectedDatasetId.value = row.id
  await loadCases()
  await loadRuns()
}

async function loadCases() {
  if (!selectedDatasetId.value) return
  const res = await apiClient.listAgentEvalCases(agentId, selectedDatasetId.value)
  cases.value = res.items || []
}

async function importSampleCases() {
  if (!selectedDatasetId.value) return
  await apiClient.importAgentEvalCases(agentId, selectedDatasetId.value, {
    cases: [
      {
        input: { messages: [{ role: 'user', content: 'hello eval' }] },
        expected_output: { final_answer: 'hello' },
        tags: ['sample'],
      },
    ],
  })
  ElMessage.success('已导入示例用例')
  await loadCases()
}

async function createRun() {
  if (!selectedDatasetId.value) return
  await apiClient.createAgentEvalRun(agentId, {
    dataset_id: selectedDatasetId.value,
    config: { evaluators: ['trajectory_match', 'llm_judge'] },
  })
  ElMessage.success('评测运行已完成')
  await loadRuns()
}

async function loadRuns() {
  if (!selectedDatasetId.value) return
  const res = await apiClient.listAgentEvalRuns(agentId)
  runs.value = (res.items || []).filter((r: any) => r.dataset_id === selectedDatasetId.value)
}

async function onSelectRun(row: any) {
  selectedRunId.value = row.id
  const res = await apiClient.listAgentEvalResults(agentId, row.id)
  results.value = res.items || []
}

onMounted(async () => {
  if (!agentId) return
  await loadDatasets()
})
</script>

<style scoped>
.eval-page {
  display: grid;
  gap: 16px;
  grid-template-columns: 1fr;
  padding: 16px;
}
.panel {
  border: 1px solid var(--el-border-color);
  border-radius: 10px;
  padding: 12px;
  background: var(--el-bg-color);
}
.row {
  display: flex;
  gap: 8px;
  margin-bottom: 10px;
}
</style>
