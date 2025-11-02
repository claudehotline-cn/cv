<template>
  <el-row :gutter="16">
    <el-col :span="12">
      <el-card>
        <template #header>订阅（Subscribe）</template>
        <el-form :model="sub" label-width="100px">
          <el-form-item label="Stream ID"><el-input v-model="sub.stream" /></el-form-item>
          <el-form-item label="Profile"><el-input v-model="sub.profile" placeholder="det_720p" /></el-form-item>
          <el-form-item label="RTSP URI"><el-input v-model="sub.uri" placeholder="rtsp://127.0.0.1:8554/camera_01" /></el-form-item>
          <el-form-item label="Model 可选"><el-input v-model="sub.model" placeholder="det:yolo:v12l" /></el-form-item>
          <el-form-item><el-button type="primary" @click="doSub" :loading="loading">订阅</el-button></el-form-item>
        </el-form>
      </el-card>
    </el-col>
    <el-col :span="12">
      <el-card>
        <template #header>退订（Unsubscribe）</template>
        <el-form :model="un" label-width="100px">
          <el-form-item label="Stream ID"><el-input v-model="un.stream" /></el-form-item>
          <el-form-item label="Profile"><el-input v-model="un.profile" placeholder="det_720p" /></el-form-item>
          <el-form-item><el-button type="danger" @click="doUnsub" :loading="loading">退订</el-button></el-form-item>
        </el-form>
      </el-card>
    </el-col>
  </el-row>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useAnalysisStore } from '@/stores/analysis'
import { ElMessage } from 'element-plus'
const loading = ref(false)
const sub = ref({ stream: 'camera_01', profile: 'det_720p', uri: 'rtsp://127.0.0.1:8554/camera_01', model: '' })
const un = ref({ stream: 'camera_01', profile: 'det_720p' })
const store = useAnalysisStore()

async function doSub(){
  loading.value = true
  try{
    // 统一走异步订阅 + SSE：设置当前选择并触发 startAnalysis
    store.setSource(sub.value.stream)
    store.setPipeline(sub.value.profile)
    if (sub.value.model) store.setModel(sub.value.model)
    // 覆盖源 URI（如果 Sources 列表无该 URI）
    const src = store.sources.find(s => s.id === sub.value.stream)
    if (!src) {
      // 动态添加一个临时源（仅用于 UI，后端仍以传入的 URI 订阅）
      store.sources.push({ id: sub.value.stream, name: sub.value.stream, uri: sub.value.uri } as any)
    }
    const res = await store.startAnalysis()
    if (!res.ok) ElMessage.error((res as any).reasons?.join('；') || '订阅失败')
  } finally { loading.value=false }
}
async function doUnsub(){
  loading.value = true
  try{
    // 统一走异步取消：仅对当前订阅生效
    if (store.currentSubId) await store.stopAnalysis()
    else ElMessage.info('当前无活跃订阅可取消')
  } finally { loading.value=false }
}
</script>
