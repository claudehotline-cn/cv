<template>
  <div class="page">
    <el-page-header content="事件列表 / 实时 / DB" />
    <div class="toolbar">
      <el-segmented v-model="mode" :options="['LIVE','DB']" size="small" />
    </div>
    <div class="body">
      <EventsList :limit="50" :useSSE="mode==='LIVE'" />
    </div>
  </div>
  
</template>

<script setup lang="ts">
import { ref } from 'vue'
import EventsList from '@/components/observability/EventsList.vue'

const mode = ref<'LIVE'|'DB'>('LIVE')
</script>

<style scoped>
.page{ padding:4px; }
.body{ margin-top:12px; }
.toolbar{ display:flex; gap:10px; align-items:center; margin: 8px 0 }
</style>
