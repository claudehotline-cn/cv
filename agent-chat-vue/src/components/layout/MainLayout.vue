<template>
  <div class="app-container">
    <!-- Left Sidebar -->
    <aside class="sidebar-left">
      <!-- Header -->
      <div class="sidebar-header">
        <div class="brand">
          <div class="brand-icon">
            <el-icon><Cpu /></el-icon>
          </div>
          <span class="brand-text">Nexus Hub</span>
        </div>
        <button class="new-thread-btn" @click="handleNewChat">
          <el-icon class="icon-sm"><Plus /></el-icon>
          <span>New Thread</span>
        </button>
      </div>

      <!-- Navigation Content -->
      <div class="sidebar-scroll">
        <!-- System Section -->
        <div class="nav-group">
          <div class="group-title">System</div>
          <button class="nav-item">
             <div class="nav-icon-wrapper">
               <el-icon class="nav-icon"><List /></el-icon>
               <span class="status-dot"></span>
             </div>
             <span class="nav-label">Active Tasks</span>
             <span class="nav-badge">2</span>
          </button>
          
          <router-link to="/agents" class="nav-item" active-class="active">
             <el-icon class="nav-icon"><Grid /></el-icon>
             <span class="nav-label">Agent Marketplace</span>
          </router-link>
        </div>

        <!-- Recent Chats -->
        <div class="nav-group">
          <div class="group-title">Recent Chats</div>
          <template v-if="chatStore.isLoading">
             <div class="loading-placeholder">Processing...</div>
          </template>
          <div v-else class="chat-list">
             <div 
               v-for="session in chatStore.sessions.slice(0, 5)" 
               :key="session.id"
               class="nav-item"
               :class="{ active: session.id === chatStore.currentSessionId && $route.path === '/' }"
               @click="handleSelectSession(session.id)"
             >
               <el-icon class="nav-icon"><ChatDotRound /></el-icon>
               <span class="nav-label text-truncate">{{ session.title }}</span>
             </div>
             <router-link to="/history" class="nav-item">
               <el-icon class="nav-icon"><Clock /></el-icon>
               <span class="nav-label text-secondary">View All History</span>
             </router-link>
          </div>
        </div>

        <!-- My Agents -->
        <div class="nav-group">
           <div class="group-title">My Agents</div>
           <div class="agent-list">
             <div v-for="agent in myAgents" :key="agent.id" class="nav-item agent-item" @click="handleSelectAgent(agent)">
                <div class="agent-avatar-mini" :style="{ background: getAgentColor(agent.name) }">
                   {{ agent.name.substring(0, 2).toUpperCase() }}
                </div>
                <span class="nav-label text-truncate">{{ agent.name }}</span>
                <span class="status-indicator"></span>
             </div>
             <router-link to="/custom-agents" class="nav-item text-secondary">
                <el-icon class="nav-icon"><Setting /></el-icon>
                <span class="nav-label">Manage Agents</span>
             </router-link>
           </div>
        </div>
      </div>

      <!-- Footer -->
      <div class="sidebar-footer">
         <button class="user-profile">
            <div class="user-avatar-circle" style="background-image: url('/avatar-placeholder.jpg')">
               <!-- Fallback if no image -->
               <span class="user-initials">AM</span>
            </div>
            <div class="user-info">
               <span class="user-name">Alex Morgan</span>
            </div>
            <el-icon class="settings-icon"><Setting /></el-icon>
         </button>
      </div>
    </aside>

    <!-- Main Content -->
    <main class="main-area">
       <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { 
  Cpu, Plus, List, Grid, ChatDotRound, Clock, Setting 
} from '@element-plus/icons-vue'
import { useChatStore } from '@/stores/chat'
import apiClient from '@/api/client'

const router = useRouter()
const chatStore = useChatStore()
const myAgents = ref<any[]>([])

onMounted(async () => {
  await chatStore.loadSessions()
  try {
     const agents = await apiClient.listAgents()
     // Mock filter for "My Agents" -> just take first 3
     myAgents.value = agents.slice(0, 3)
  } catch (e) {
     console.error("Failed to load agents", e)
  }
})

async function handleNewChat() {
  chatStore.resetSession()
  router.push('/')
}

async function handleSelectSession(sessionId: string) {
  await chatStore.selectSession(sessionId)
  router.push('/')
}

async function handleSelectAgent(agent: any) {
    chatStore.setCurrentAgent(agent.id)
    handleNewChat()
}

// Helper for colors
function getAgentColor(name: string) {
    const colors = [
        'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)',
        'linear-gradient(135deg, #f97316 0%, #ef4444 100%)',
        'linear-gradient(135deg, #06b6d4 0%, #3b82f6 100%)'
    ]
    const index = name.charCodeAt(0) % colors.length
    return colors[index]
}
</script>

<style scoped>
.app-container {
  display: flex;
  height: 100vh;
  width: 100vw;
  background: var(--bg-primary);
  overflow: hidden;
}

/* Left Sidebar */
.sidebar-left {
  width: 260px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: var(--bg-secondary);
  border-right: 1px solid var(--border-color);
  transition: all 0.3s ease;
}

.sidebar-header {
  padding: 20px 16px 16px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
  padding: 0 8px;
}

.brand-icon {
  width: 32px;
  height: 32px;
  background: rgba(31, 150, 173, 0.1);
  color: var(--accent-primary);
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.brand-text {
  font-size: 18px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--text-primary);
}

.new-thread-btn {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  background: var(--accent-primary);
  color: white;
  border: none;
  border-radius: 12px;
  padding: 10px;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  box-shadow: 0 4px 6px -1px rgba(31, 150, 173, 0.2);
  transition: all 0.2s;
}

.new-thread-btn:hover {
  background: #1a8599;
  transform: translateY(-1px);
  box-shadow: 0 6px 10px -2px rgba(31, 150, 173, 0.3);
}

.new-thread-btn:active {
  transform: scale(0.98);
}

.sidebar-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 0 12px 16px;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.group-title {
  padding: 0 12px;
  margin-bottom: 8px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-secondary);
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  border-radius: 8px;
  cursor: pointer;
  color: var(--text-primary);
  text-decoration: none;
  transition: all 0.2s;
  background: transparent;
  border: none;
  width: 100%;
  text-align: left;
}

.nav-item:hover {
  background: var(--bg-tertiary); /* equivalent to hover:bg-[#e8f0f2] */
}

.nav-item.active {
  background: var(--bg-tertiary);
  color: var(--text-primary);
}

.nav-icon-wrapper {
  position: relative;
}

.nav-icon {
  font-size: 18px;
  color: var(--text-secondary);
}

.nav-item:hover .nav-icon {
  color: var(--accent-primary);
}

.status-dot {
  position: absolute;
  top: -2px;
  right: -2px;
  width: 8px;
  height: 8px;
  background: #f59e0b;
  border: 2px solid var(--bg-secondary);
  border-radius: 50%;
}

.nav-label {
  flex: 1;
  font-size: 13px;
  font-weight: 500;
}

.nav-badge {
  background: rgba(245, 158, 11, 0.1);
  color: #d97706;
  font-size: 11px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 99px;
}

.text-truncate {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.text-secondary {
    color: var(--text-secondary);
    font-size: 12px;
}

/* Agent Item */
.agent-item {
    background: rgba(31, 150, 173, 0.05); /* primary/5 */
    border: 1px solid rgba(31, 150, 173, 0.1);
    margin-bottom: 4px;
}

.agent-item:hover {
    background: rgba(31, 150, 173, 0.1);
}

.agent-avatar-mini {
    width: 24px;
    height: 24px;
    border-radius: 6px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: white;
    font-size: 10px;
    font-weight: 700;
}

.status-indicator {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #22c55e;
}

/* Footer */
.sidebar-footer {
    padding: 16px;
    border-top: 1px solid var(--border-color);
}

.user-profile {
    display: flex;
    align-items: center;
    gap: 12px;
    width: 100%;
    background: transparent;
    border: none;
    cursor: pointer;
    padding: 8px;
    border-radius: 12px;
    transition: background 0.2s;
}

.user-profile:hover {
    background: var(--bg-tertiary);
}

.user-avatar-circle {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    background-color: var(--bg-tertiary);
    background-size: cover;
    background-position: center;
    border: 1px solid var(--border-color);
    display: flex;
    align-items: center;
    justify-content: center;
}

.user-initials {
    font-size: 11px;
    font-weight: 700;
    color: var(--text-secondary);
}

.user-info {
    flex: 1;
    text-align: left;
}

.user-name {
    display: block;
    font-size: 13px;
    font-weight: 700;
    color: var(--text-primary);
}

.settings-icon {
    color: var(--text-secondary);
}

.main-area {
    flex: 1;
    background: var(--bg-primary); /* background-light */
    position: relative;
    overflow: hidden;
}

/* Dark mode adjustment for scrollbar if needed */
.sidebar-scroll::-webkit-scrollbar {
    width: 4px;
}
</style>
