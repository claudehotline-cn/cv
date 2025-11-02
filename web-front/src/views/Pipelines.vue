<template>
  <el-card>
    <template #header>
      <div class="card-header">
        <span>Pipelines</span>
        <div>
          <el-button size="small" @click="load" :loading="loading">刷新</el-button>
        </div>
      </div>
    </template>
    <el-table :data="rows" style="width: 100%" height="480">
      <el-table-column prop="key" label="Key" width="220" />
      <el-table-column prop="stream_id" label="Stream" width="140" />
      <el-table-column prop="profile" label="Profile" width="120" />
      <el-table-column prop="running" label="Running" width="100">
        <template #default="{ row }">
          <el-tag :type="row.running ? 'success' : 'info'">{{ row.running ? 'Y' : 'N' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="fps" label="FPS" width="100" />
      <el-table-column prop="transport_bytes" label="Bytes" width="140" />
      <el-table-column prop="decoder_label" label="Decoder" />
      <el-table-column label="操作" width="360">
        <template #default="{ row }">
          <el-button size="small" type="danger" @click="unsub(row)">Unsubscribe</el-button>
          <el-input v-model="row._model" placeholder="model_id" size="small" style="width:160px;margin:0 8px" />
          <el-button size="small" type="primary" @click="switchM(row)">切换模型</el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-card>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { listPipelines, switchModel } from '@/api/cp'
import { useAnalysisStore } from '@/stores/analysis'
import { ElMessage } from 'element-plus'

const loading = ref(false)
const rows = ref<any[]>([])
async function load() {
  loading.value = true
  try {
    const resp = await listPipelines()
    rows.value = (resp as any).items || (resp as any).data || []
  } finally { loading.value = false }
}
const store = useAnalysisStore()
async function unsub(row: any) {
  // 仅对当前订阅生效，统一走异步取消
  if (store.currentSubId && row.stream_id === store.currentSourceId && row.profile === store.currentPipeline) {
    await store.stopAnalysis()
    await load()
  } else {
    ElMessage.info('仅支持取消当前页面发起的异步订阅')
  }
}
async function switchM(row: any) {
  if (!row._model) return
  await switchModel(row.stream_id, row.profile, row._model)
}
onMounted(load)
</script>

<style scoped>
.card-header{ display:flex; align-items:center; justify-content:space-between; }
</style>
