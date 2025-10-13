<template>
  <div class="page">
    <el-page-header content="指标查询 / 看板 / CSV 导出" />
    <div class="body">
      <MetricsQueryPanel />
    </div>
  </div>
</template>

<script setup lang="ts">
import MetricsQueryPanel from '@/components/analytics/MetricsQueryPanel.vue'
</script>

<style scoped>
.page{ padding:4px; }
.body{ margin-top:12px; }
</style>

