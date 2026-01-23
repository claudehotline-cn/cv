<template>
  <div class="async-task-card">
    <div class="task-header">
      <div class="header-left">
        <el-icon class="task-icon spin"><Loading /></el-icon>
        <span class="task-name">Async Task</span>
      </div>
      <span class="task-percentage">{{ progress }}%</span>
    </div>
    
    <div class="progress-bar">
      <div class="progress-fill" :style="{ width: progress + '%' }"></div>
    </div>
    
    <div class="task-status">
      {{ statusMessage || 'Processing...' }}
    </div>
    
    <div class="task-footer" v-if="taskId">
      <span class="task-id">ID: {{ taskId.slice(0, 8) }}</span>
      <button v-if="status === 'running'" class="cancel-btn" @click.stop="$emit('cancel', taskId)">
        Cancel
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { Loading } from '@element-plus/icons-vue'

defineProps<{
  progress: number
  status: string
  statusMessage?: string
  taskId?: string
  taskName?: string
}>()

defineEmits(['cancel'])
</script>

<style scoped>
.async-task-card {
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 16px;
  width: 100%;
  max-width: 320px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.05);
  margin-top: 8px;
}

.task-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  color: var(--text-primary);
  font-size: 14px;
}

.task-percentage {
  font-family: monospace;
  font-weight: 700;
  color: var(--accent-primary);
  font-size: 13px;
}

.progress-bar {
  height: 6px;
  background: var(--bg-tertiary);
  border-radius: 99px;
  overflow: hidden;
  margin-bottom: 12px;
}

.progress-fill {
  height: 100%;
  background: var(--accent-primary);
  transition: width 0.3s ease;
  border-radius: 99px;
}

.task-status {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.4;
  margin-bottom: 8px;
}

.task-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 12px;
  padding-top: 8px;
  border-top: 1px solid var(--border-color);
}

.task-id {
  font-size: 11px;
  color: var(--text-tertiary);
  font-family: monospace;
}

.cancel-btn {
  font-size: 11px;
  color: #ef4444;
  background: transparent;
  border: none;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 4px;
}

.cancel-btn:hover {
  background: #fee2e2;
}

.spin {
  animation: spin 2s linear infinite;
  color: var(--accent-primary);
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
