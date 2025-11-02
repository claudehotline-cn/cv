<template>
  <div class="about">
    <el-page-header content="关于 VisionOps" />
    <el-row :gutter="16" style="margin-top:12px">
      <el-col :span="12">
        <el-card shadow="hover">
          <template #header>
            <div class="card-title">平台信息</div>
          </template>
          <el-descriptions :column="1" size="small" border>
            <el-descriptions-item label="控制平面">{{ online ? '在线' : '离线' }}</el-descriptions-item>
            <el-descriptions-item label="版本">{{ system?.version ?? '未知' }}</el-descriptions-item>
            <el-descriptions-item label="构建时间">{{ system?.build_time ?? '暂无' }}</el-descriptions-item>
            <el-descriptions-item label="GPU">{{ system?.engine_runtime?.gpu_active ?? 'N/A' }}</el-descriptions-item>
            <el-descriptions-item label="文档">
              <el-link href="/docs" target="_blank">/docs</el-link>
            </el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card shadow="hover">
          <template #header>
            <div class="card-title">前端栈</div>
          </template>
          <el-descriptions :column="1" size="small" border>
            <el-descriptions-item label="前端">Vue 3 + Vite + TypeScript</el-descriptions-item>
            <el-descriptions-item label="UI 库">Element Plus</el-descriptions-item>
            <el-descriptions-item label="状态管理">Pinia</el-descriptions-item>
            <el-descriptions-item label="可视化">ECharts (Metrics)、X6 (Graph editor)</el-descriptions-item>
            <el-descriptions-item label="源码">
              <el-link href="https://element-plus.org" target="_blank">Element Plus 文档</el-link>
            </el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { onMounted, computed } from 'vue'
import { useAppStore } from '@/stores/app'

const app = useAppStore()
onMounted(() => { app.refresh() })

const online = computed(() => app.online)
const system = computed(() => app.system)
</script>

<style scoped>
.about{ padding:12px 4px; }
.card-title{ font-weight:600; }
</style>
