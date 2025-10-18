<template>
  <el-menu
    :default-active="active"
    router
    class="menu"
    background-color="transparent"
    text-color="var(--va-text-2)"
    active-text-color="var(--va-text-1)"
  >
    <el-menu-item index="/dashboard"><el-icon><DataAnalysis/></el-icon><span>总览</span></el-menu-item>
    <el-menu-item index="/analysis"><el-icon><DataAnalysis/></el-icon><span>分析</span></el-menu-item>

    <el-sub-menu index="/pipelines">
      <template #title><el-icon><DataLine/></el-icon><span>Pipelines</span></template>
      <el-menu-item index="/pipelines">列表</el-menu-item>
      <el-menu-item index="/pipelines/editor">编辑器</el-menu-item>
    </el-sub-menu>

    <el-menu-item index="/sources"><el-icon><Connection/></el-icon><span>Sources</span></el-menu-item>
    <el-menu-item index="/models"><el-icon><Box/></el-icon><span>Models</span></el-menu-item>

    <el-sub-menu index="/observability">
      <template #title><el-icon><Monitor/></el-icon><span>Observability</span></template>
      <el-menu-item index="/observability">概览</el-menu-item>
      <el-menu-item index="/observability/metrics">Metrics</el-menu-item>
      <el-menu-item index="/observability/logs">Logs</el-menu-item>
      <el-menu-item index="/observability/events">Events</el-menu-item>
      <el-menu-item index="/observability/sessions">Sessions</el-menu-item>
    </el-sub-menu>

    <el-menu-item index="/orchestration"><el-icon><Connection/></el-icon><span>Orchestration</span></el-menu-item>
    <el-menu-item index="/settings"><el-icon><Setting/></el-icon><span>设置</span></el-menu-item>
    <el-menu-item index="/about"><el-icon><InfoFilled/></el-icon><span>关于</span></el-menu-item>
  </el-menu>
  <div class="copyright">© 2025 CV Platform</div>
</template>

<script setup lang="ts">
import { useRoute } from 'vue-router'
import { DataAnalysis, DataLine, Connection, Box, Monitor, Setting, InfoFilled } from '@element-plus/icons-vue'
const active = useRoute().path
</script>

<style scoped>
.menu{ border-right: none; padding-top: 8px; }
.copyright{ color: var(--va-text-2); opacity: .6; font-size: 12px; padding: 12px; }
</style>
