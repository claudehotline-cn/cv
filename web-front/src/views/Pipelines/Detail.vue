<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import MetricsTimeseries from '@/components/analytics/MetricsTimeseries.vue'
import EventsList from '@/components/observability/EventsList.vue'
// 预览占位：如需实际 WHEP 播放，可引入 WhepPlayer
// import WhepPlayer from '@/widgets/WhepPlayer/WhepPlayer.vue'

const route = useRoute()
const name = computed(() => decodeURIComponent(String(route.params.name||'')))
</script>

<template>
  <div class="page">
    <el-page-header :content="`Pipeline: ${name}`"/>

    <el-row :gutter="12" style="margin-top:12px">
      <el-col :span="12">
        <el-card shadow="never" class="chart-card" header="Pipeline FPS">
          <MetricsTimeseries metric="pipeline_fps" :range-minutes="30" :pipeline="name"/>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card shadow="never" class="chart-card" header="Inference P95 Latency">
          <MetricsTimeseries metric="latency_ms_p95" :range-minutes="30" :pipeline="name"/>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="12" style="margin-top:12px">
      <el-col :span="24">
        <el-card shadow="hover" header="最近事件">
          <EventsList :limit="30" :pipeline="name"/>
        </el-card>
      </el-col>
    </el-row>

    <!-- 如需预览流，可启用 WhepPlayer
    <el-row :gutter="12" style="margin-top:12px">
      <el-col :span="24">
        <el-card shadow="hover" header="预览（WHEP）">
          <WhepPlayer />
        </el-card>
      </el-col>
    </el-row>
    -->
  </div>
</template>

<style scoped>
.page{ padding: 4px; }
.chart-card{ min-height: 260px; }
</style>

