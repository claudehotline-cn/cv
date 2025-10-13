<template>
  <div class="page">
    <el-page-header content="事件列表 / 实时 / 告警" />
    <div class="body">
      <EventsList :limit="50" :useSSE="true" />
    </div>
  </div>
</template>

<script setup lang="ts">
import EventsList from '@/components/observability/EventsList.vue'
</script>

<style scoped>
.page{ padding:4px; }
.body{ margin-top:12px; }
</style>

