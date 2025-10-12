<template>
  <el-container style="height: 100vh">
    <el-aside width="220px">
      <div class="brand">AI 视频分析</div>
      <el-menu :default-active="route.path" router>
        <el-menu-item index="/dashboard">总览</el-menu-item>
        <el-menu-item index="/pipelines">Pipelines</el-menu-item>
        <el-menu-item index="/sources">Sources</el-menu-item>
        <el-menu-item index="/models">Models</el-menu-item>
        <el-menu-item index="/observability">Observability</el-menu-item>
        <el-menu-item index="/settings">Settings</el-menu-item>
        <el-menu-item index="/about">About</el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header>
        <el-breadcrumb separator="/">
          <el-breadcrumb-item>AI 平台</el-breadcrumb-item>
          <el-breadcrumb-item>{{ title }}</el-breadcrumb-item>
        </el-breadcrumb>
        <div class="spacer" />
        <el-tag type="success" v-if="online">Online</el-tag>
        <el-tag type="info" v-else>Offline</el-tag>
      </el-header>
      <el-main>
        <router-view />
      </el-main>
      <el-footer>
        <span>© 2025 CV Platform</span>
      </el-footer>
    </el-container>
  </el-container>
  <el-backtop />
  <el-notification v-if="notify.text" :title="notify.title" :type="notify.type" :duration="2500">
    {{ notify.text }}
  </el-notification>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useAppStore } from './stores/app'

const route = useRoute()
const title = computed(() => {
  switch (route.path) {
    case '/dashboard': return 'Dashboard'
    case '/pipelines': return 'Pipelines'
    case '/sources': return 'Sources'
    case '/models': return 'Models'
    case '/observability': return 'Observability'
    case '/settings': return 'Settings'
    case '/about': return 'About'
    default: return ''
  }
})

const app = useAppStore()
const online = computed(() => app.online)
const notify = computed(() => app.notification)
</script>

<style scoped>
.brand { font-weight: 700; font-size: 16px; padding: 14px 12px; }
.spacer { flex: 1 }
.el-header { display:flex; align-items:center; gap: 12px; }
</style>

