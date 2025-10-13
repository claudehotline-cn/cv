<template>
  <div class="page">
    <el-page-header content="日志查看 / 过滤 / 实时" />
    <div class="body">
      <LogsViewer />
    </div>
  </div>
</template>

<script setup lang="ts">
import LogsViewer from '@/components/observability/LogsViewer.vue'
</script>

<style scoped>
.page{ padding:4px; }
.body{ margin-top:12px; }
</style>

