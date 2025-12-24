<script setup lang="ts">
import { useRoute } from 'vue-router'
import { computed } from 'vue'

const route = useRoute()

const activeMenu = computed(() => {
  if (route.path.startsWith('/knowledge-bases')) return '/knowledge-bases'
  if (route.path.startsWith('/chat')) return '/chat'
  if (route.path.startsWith('/article-agent')) return '/article-agent'
  if (route.path.startsWith('/data-agent')) return '/data-agent'
  return route.path
})
</script>

<template>
  <el-container class="layout-container">
    <!-- 侧边栏 -->
    <el-aside width="220px" class="sidebar">
      <div class="logo">
        <el-icon size="28"><Collection /></el-icon>
        <span class="logo-text">RAG 知识库</span>
      </div>
      <el-menu
        :default-active="activeMenu"
        class="sidebar-menu"
        background-color="#1e1e2e"
        text-color="#cdd6f4"
        active-text-color="#89b4fa"
        router
      >
        <el-menu-item index="/knowledge-bases">
          <el-icon><FolderOpened /></el-icon>
          <span>知识库管理</span>
        </el-menu-item>
        <el-menu-item index="/chat">
          <el-icon><ChatDotRound /></el-icon>
          <span>智能问答</span>
        </el-menu-item>
        <el-menu-item index="/article-agent">
          <el-icon><Document /></el-icon>
          <span>文档整理</span>
        </el-menu-item>
        <el-menu-item index="/data-agent">
          <el-icon><DataAnalysis /></el-icon>
          <span>数据分析</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <!-- 主内容区 -->
    <el-main class="main-content">
      <slot></slot>
    </el-main>
  </el-container>
</template>

<style scoped>
.layout-container {
  height: 100vh;
  background: linear-gradient(135deg, #1e1e2e 0%, #181825 100%);
}

.sidebar {
  background: #1e1e2e;
  border-right: 1px solid #313244;
  display: flex;
  flex-direction: column;
}

.logo {
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  border-bottom: 1px solid #313244;
  background: linear-gradient(135deg, #89b4fa 0%, #cba6f7 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.logo-text {
  font-size: 18px;
  font-weight: 700;
  letter-spacing: 1px;
}

.sidebar-menu {
  border: none;
  flex: 1;
  padding-top: 12px;
}

.sidebar-menu .el-menu-item {
  height: 48px;
  margin: 4px 12px;
  border-radius: 8px;
  transition: all 0.3s ease;
}

.sidebar-menu .el-menu-item:hover {
  background: rgba(137, 180, 250, 0.1) !important;
}

.sidebar-menu .el-menu-item.is-active {
  background: linear-gradient(135deg, rgba(137, 180, 250, 0.2) 0%, rgba(203, 166, 247, 0.1) 100%) !important;
}

.main-content {
  background: #11111b;
  padding: 24px;
  overflow-y: auto;
}
</style>
