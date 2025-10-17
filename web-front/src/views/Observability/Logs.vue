<template>
  <div class="page">
    <el-page-header content="日志查看 / 过滤 / 实时" />
    <div class="toolbar">
      <el-segmented v-model="mode" :options="['LIVE','DB']" size="small" />
      <el-date-picker v-if="mode==='DB'" v-model="dateRange" type="datetimerange" value-format="x" size="small" />
    </div>
    <div class="body">
      <LogsViewer v-if="mode==='LIVE'" />
      <DBLogsList v-else :from-ts="fromTs" :to-ts="toTs" />
    </div>
  </div>
  
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import LogsViewer from '@/components/observability/LogsViewer.vue'
import DBLogsList from '@/components/observability/DBLogsList.vue'

const mode = ref<'LIVE'|'DB'>('LIVE')
const dateRange = ref<any[]>([])
const fromTs = computed(()=> Array.isArray(dateRange.value)&&dateRange.value.length===2 ? Number(dateRange.value[0]) : undefined)
const toTs   = computed(()=> Array.isArray(dateRange.value)&&dateRange.value.length===2 ? Number(dateRange.value[1]) : undefined)
</script>

<style scoped>
.page{ padding:4px; }
.body{ margin-top:12px; }
.toolbar{ display:flex; gap:10px; align-items:center; margin: 8px 0 }
</style>

