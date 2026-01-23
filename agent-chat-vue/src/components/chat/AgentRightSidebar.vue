<template>
  <aside class="right-sidebar">
    <div class="sidebar-header">
      <h3 class="title">Agent Details</h3>
      <button class="icon-btn">
        <el-icon><MoreFilled /></el-icon>
      </button>
    </div>

    <div class="sidebar-content">
      <!-- Agent Card -->
      <div class="agent-card glass-panel">
        <div class="agent-avatar-large">
          <el-icon class="agent-icon"><DataAnalysis /></el-icon>
        </div>
        <div class="agent-info">
          <h4 class="agent-name">Data Analyst</h4>
          <p class="agent-desc">Specialized in Big Data & Visualization</p>
        </div>

        <div class="agent-stats">
          <div class="stat-item">
            <span class="stat-value">4.0</span>
            <span class="stat-label">Model</span>
          </div>
          <div class="stat-item">
            <span class="stat-value">128k</span>
            <span class="stat-label">Context</span>
          </div>
          <div class="stat-item">
            <span class="stat-value">Python</span>
            <span class="stat-label">Tool</span>
          </div>
        </div>
      </div>

      <!-- Background Tasks -->
      <div class="section" v-if="chatStore.currentTask">
        <div class="section-header">
          <h4 class="section-title">Background Tasks</h4>
          <span class="badge active">1 Active</span>
        </div>
        
        <div class="task-list">
          <div class="task-card active">
            <div class="task-header">
              <div class="task-title-row">
                <el-icon class="task-icon spin"><Loading /></el-icon>
                <span class="task-name">{{ chatStore.currentTask.name }}</span>
              </div>
              <span class="task-progress-text">{{ chatStore.currentTask.progress }}%</span>
            </div>
            <div class="progress-bar">
              <div class="progress-fill" :style="{ width: chatStore.currentTask.progress + '%' }"></div>
            </div>
            <p class="task-meta">ID #{{ chatStore.currentTask.id.slice(0, 8) }} • {{ chatStore.currentTask.status }}</p>
          </div>
        </div>
      </div>

      <!-- Capabilities -->
      <div class="section">
        <h4 class="section-title mb-3">Capabilities</h4>
        <div class="capabilities-list">
          <div class="cap-tag">
            <el-icon><Monitor /></el-icon> Code Interpreter
          </div>
          <div class="cap-tag">
            <el-icon><Search /></el-icon> Browsing
          </div>
          <div class="cap-tag">
            <el-icon><Picture /></el-icon> DALL-E 3
          </div>
        </div>
      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { 
  DataAnalysis, Monitor, Search, Picture, Loading 
} from '@element-plus/icons-vue'
import { useChatStore } from '@/stores/chat'

const chatStore = useChatStore()
</script>

<style scoped>
.right-sidebar {
  width: 320px;
  background: var(--bg-secondary);
  border-left: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  height: 100%;
  flex-shrink: 0;
}

.sidebar-header {
  padding: 20px;
  padding-bottom: 8px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.title {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0;
}

.icon-btn {
  background: transparent;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  padding: 4px;
  display: flex;
}

.icon-btn:hover {
  color: var(--accent-primary);
}

.sidebar-content {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  padding-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

/* Agent Card */
.agent-card {
  background: var(--bg-primary); /* Use white/dark bg instead of sidebar color */
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 24px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.05);
}

.agent-avatar-large {
  width: 64px;
  height: 64px;
  border-radius: 16px;
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-size: 32px;
  box-shadow: 0 4px 6px -1px rgba(99, 102, 241, 0.3);
}

.agent-info {
  text-align: center;
}

.agent-name {
  font-size: 18px;
  font-weight: 700;
  margin: 0 0 4px 0;
  color: var(--text-primary);
}

.agent-desc {
  font-size: 12px;
  color: var(--text-secondary);
  margin: 0;
}

.agent-stats {
  display: flex;
  width: 100%;
  gap: 8px;
  margin-top: 8px;
}

.stat-item {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  background: var(--bg-secondary);
  padding: 8px;
  border-radius: 8px;
}

.stat-value {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-primary);
}

.stat-label {
  font-size: 10px;
  color: var(--text-tertiary); /* Adjusted to tertiary for better contrast */
}

/* Section Common */
.section-title {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-secondary);
  margin: 0;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.badge {
  font-size: 10px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 4px;
}

.badge.active {
  background: #6366f1;
  color: white;
}

/* Task List */
.task-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.task-card {
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 12px;
  background: var(--bg-primary);
  transition: all 0.2s;
}

.task-card:hover {
  box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);
}

.task-card.active {
  border-color: rgba(99, 102, 241, 0.3);
  background: rgba(99, 102, 241, 0.05);
}

.task-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 8px;
}

.task-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.task-name {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-primary);
}

.task-icon {
  font-size: 16px;
}

.task-icon.spin {
  animation: spin 2s linear infinite;
  color: var(--accent-primary);
}

.task-icon.warning {
  color: #f59e0b;
}

.task-progress-text {
  font-size: 10px;
  font-family: monospace;
  color: var(--accent-primary);
}

.task-status {
  font-size: 10px;
  font-family: monospace;
  color: var(--text-secondary);
}

.progress-bar {
  height: 6px;
  width: 100%;
  background: var(--bg-tertiary);
  border-radius: 99px;
  overflow: hidden;
  margin-bottom: 8px;
}

.progress-fill {
  height: 100%;
  background: var(--accent-primary);
  border-radius: 99px;
}

.progress-fill.pending {
  background: #f59e0b;
}

.task-meta {
  font-size: 10px;
  color: var(--text-secondary);
  margin: 0;
}

/* Capabilities */
.capabilities-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.cap-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  font-size: 11px;
  font-weight: 500;
  color: var(--text-secondary);
}

.mb-3 {
  margin-bottom: 12px;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
