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
import { subscribePipeline, unsubscribePipeline } from '@/api/cp'
const loading = ref(false)
const sub = ref({ stream: 'camera_01', profile: 'det_720p', uri: 'rtsp://127.0.0.1:8554/camera_01', model: '' })
const un = ref({ stream: 'camera_01', profile: 'det_720p' })

async function doSub(){
  loading.value = true
  try{ await subscribePipeline(sub.value.stream, sub.value.profile, sub.value.uri, sub.value.model || undefined) } finally { loading.value=false }
}
async function doUnsub(){
  loading.value = true
  try{ await unsubscribePipeline(un.value.stream, un.value.profile) } finally { loading.value=false }
}
</script>

