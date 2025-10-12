<template>
  <el-card>
    <template #header>
      <div class="card-header">
        <span>系统总览</span>
        <el-button size="small" @click="refresh" :loading="loading">刷新</el-button>
      </div>
    </template>
    <el-descriptions v-if="info" :column="2" border>
      <el-descriptions-item label="Provider">{{ info.engine_runtime?.provider }}</el-descriptions-item>
      <el-descriptions-item label="GPU">{{ info.engine_runtime?.gpu_active }}</el-descriptions-item>
      <el-descriptions-item label="IO Binding">{{ info.engine_runtime?.io_binding }}</el-descriptions-item>
      <el-descriptions-item label="Device Binding">{{ info.engine_runtime?.device_binding }}</el-descriptions-item>
      <el-descriptions-item label="Models">{{ info.model_count }}</el-descriptions-item>
      <el-descriptions-item label="Profiles">{{ info.profile_count }}</el-descriptions-item>
    </el-descriptions>
    <div style="margin-top:16px">
      <el-card>
        <template #header>WHEP 播放</template>
        <whep-player />
      </el-card>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { useAppStore } from '@/stores/app'
import WhepPlayer from '@/widgets/WhepPlayer/WhepPlayer.vue'

const app = useAppStore()
const info = computed(() => app.system)
const loading = ref(false)
const refresh = async () => { loading.value = true; await app.refresh(); loading.value = false }
onMounted(refresh)
</script>

<style scoped>
.card-header{ display:flex; align-items:center; justify-content:space-between; }
</style>

