<template>
  <el-container class="main-layout">
    <!-- Sidebar -->
    <el-aside width="260px" class="sidebar glass-panel">
      <!-- Top Section: App Brand & Nav -->
      <div class="sidebar-top">
        <div class="brand-header">
          <div class="logo-icon">
            <el-icon><Cpu /></el-icon>
          </div>
          <span class="brand-text">Agent 平台</span>
        </div>

        <nav class="main-nav">
          <router-link to="/agents" class="nav-item" active-class="active">
            <el-icon><Grid /></el-icon>
            <span>Agent 市场</span>
          </router-link>
          <router-link to="/custom-agents" class="nav-item" active-class="active">
            <el-icon><Setting /></el-icon>
            <span>自定义 Agent</span>
          </router-link>
        </nav>
      </div>

      <!-- Divider -->
      <div class="divider">
        <span>对话列表</span>
      </div>

      <!-- Action Button -->
      <div class="new-chat-wrapper">
        <el-button class="new-chat-btn" @click="handleNewChat">
          <el-icon><Plus /></el-icon> 新建对话
        </el-button>
      </div>

      <!-- Thread List -->
      <el-scrollbar class="thread-list">
        <div v-if="chatStore.isLoading" class="loading-threads">
          <el-skeleton :rows="3" animated />
        </div>
        
        <template v-else>
          <div
            v-for="session in chatStore.sessions"
            :key="session.id"
            class="thread-item"
            :class="{ active: session.id === chatStore.currentSessionId && $route.path === '/' }"
            @click="handleSelectSession(session.id)"
          >
            <el-icon class="thread-icon"><ChatDotRound /></el-icon>
            <div class="thread-info">
              <span class="thread-title">{{ session.title }}</span>
              <span class="thread-date">{{ formatDate(session.updatedAt) }}</span>
            </div>
            <div class="thread-actions">
              <el-icon class="delete-icon" @click.stop="handleDeleteSession(session.id)"><Delete /></el-icon>
            </div>
          </div>
        </template>
      </el-scrollbar>

      <!-- User Footer -->
      <div class="sidebar-footer">
        <div class="user-info">
          <el-avatar :size="32" class="user-avatar">AD</el-avatar>
          <div class="user-details">
            <span class="user-name">管理员</span>
            <span class="user-role">系统管理</span>
          </div>
        </div>
      </div>
    </el-aside>

    <!-- Main Content Area -->
    <el-main class="content-area">
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </el-main>
  </el-container>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { 
  Cpu, Grid, Setting, Plus, ChatDotRound, Delete 
} from '@element-plus/icons-vue'
import { useChatStore } from '@/stores/chat'
import dayjs from 'dayjs'

const router = useRouter()
const chatStore = useChatStore()

onMounted(async () => {
  await chatStore.loadSessions()
})

function formatDate(date: string | Date) {
  return dayjs(date).format('MMM D')
}

async function handleNewChat() {
  chatStore.resetSession()
  router.push('/')
}

async function handleSelectSession(sessionId: string) {
  await chatStore.selectSession(sessionId)
  router.push('/')
}

async function handleDeleteSession(sessionId: string) {
  await chatStore.deleteSession(sessionId)
}
</script>

<style scoped>
.main-layout {
  height: 100vh;
  width: 100vw;
  background: var(--bg-primary);
}

.sidebar {
  border-right: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  background: var(--glass-bg);
  backdrop-filter: blur(20px);
}

.sidebar-top {
  padding: 24px 16px 16px;
}

.brand-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 32px;
  padding: 0 8px;
}

.logo-icon {
  width: 32px;
  height: 32px;
  background: var(--accent-gradient);
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
}

.brand-text {
  font-weight: 700;
  font-size: 16px;
  letter-spacing: -0.02em;
}

.main-nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 8px;
  color: var(--text-secondary);
  text-decoration: none;
  transition: all 0.2s;
  font-size: 14px;
  font-weight: 500;
}

.nav-item:hover {
  background: rgba(255, 255, 255, 0.05);
  color: var(--text-primary);
}

.nav-item.active {
  background: rgba(99, 102, 241, 0.1);
  color: var(--accent-primary);
}

.divider {
  padding: 0 24px;
  margin: 16px 0 8px;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-tertiary);
  letter-spacing: 0.1em;
}

.new-chat-wrapper {
  padding: 0 16px 16px;
}

.new-chat-btn {
  width: 100%;
  background: rgba(255, 255, 255, 0.05);
  border: 1px dashed var(--border-color);
  color: var(--text-secondary);
  justify-content: flex-start;
  padding: 16px;
}

.new-chat-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  border-color: var(--text-secondary);
  color: var(--text-primary);
}

.thread-list {
  flex: 1;
  padding: 0 16px;
}

.thread-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  margin-bottom: 2px;
  color: var(--text-secondary);
  transition: all 0.2s;
}

.thread-item:hover {
  background: rgba(255, 255, 255, 0.05);
  color: var(--text-primary);
}

.thread-item.active {
  background: var(--bg-secondary);
  color: var(--text-primary);
  border: 1px solid var(--border-color);
}

.thread-info {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.thread-title {
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.thread-date {
  font-size: 10px;
  color: var(--text-tertiary);
}

.thread-actions {
  opacity: 0;
  transition: opacity 0.2s;
}

.thread-item:hover .thread-actions {
  opacity: 1;
}

.delete-icon:hover {
  color: #ef4444;
}

.sidebar-footer {
  padding: 16px;
  border-top: 1px solid var(--border-color);
}

.user-info {
  display: flex;
  align-items: center;
  gap: 12px;
}

.user-avatar {
  background: var(--bg-tertiary);
  font-size: 12px;
  color: var(--text-secondary);
}

.user-details {
  display: flex;
  flex-direction: column;
}

.user-name {
  font-size: 13px;
  font-weight: 500;
}

.user-role {
  font-size: 11px;
  color: var(--text-tertiary);
}

.content-area {
  padding: 0;
  background: var(--bg-secondary);
  position: relative;
  overflow: hidden;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
