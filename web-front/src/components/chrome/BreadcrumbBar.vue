<template>
  <div class="crumb">
    <el-breadcrumb separator="/">
      <el-breadcrumb-item>AI 平台</el-breadcrumb-item>
      <el-breadcrumb-item>{{ routeName }}</el-breadcrumb-item>
    </el-breadcrumb>
  </div>
  </template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const routeName = computed(() => {
  const p = route.path
  if (p.startsWith('/pipeline')) return 'Pipelines'
  if (p.startsWith('/source')) return 'Sources'
  if (p.startsWith('/model')) return 'Models'
  if (p.startsWith('/observability')) return 'Observability'
  if (p.startsWith('/settings')) return 'Settings'
  if (p.startsWith('/about')) return 'About'
  return 'Dashboard'
})
  </script>

<style scoped>
.crumb{ display:flex; align-items:center; justify-content:flex-start; padding: 0 0 8px 0; }
</style>
