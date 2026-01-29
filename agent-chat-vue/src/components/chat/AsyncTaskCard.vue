<template>
  <div class="async-task-card">
    <div class="task-header">
      <div class="header-left">
        <el-icon class="task-icon" :class="{ spin: isActive }"><Loading /></el-icon>
        <span class="task-name">{{ taskName || 'Async Task' }}</span>
      </div>
      <span class="task-percentage">{{ progress }}%</span>
    </div>
    
    <div class="progress-bar">
      <div class="progress-fill" :style="{ width: progress + '%' }"></div>
    </div>
    
    <div class="task-status">
      <span v-if="status === 'failed'">{{ error || statusMessage || 'Failed' }}</span>
      <span v-else>{{ statusMessage || (status === 'completed' ? 'Completed' : 'Processing...') }}</span>
    </div>

    <div v-if="status === 'waiting_approval' && interruptDescription" class="task-interrupt">
      <div class="task-interrupt-title">Action required</div>
      <div class="task-interrupt-desc">{{ interruptDescription }}</div>

      <textarea
        v-model="feedback"
        class="task-feedback"
        placeholder="Optional feedback (for reject reason, etc.)"
        rows="2"
      />
    </div>
    
    <div class="task-footer" v-if="taskId">
      <span class="task-id">ID: {{ taskId.slice(0, 8) }}</span>
      <div class="task-actions">
        <button
          v-if="status === 'running' || status === 'pending'"
          class="cancel-btn"
          @click.stop="$emit('cancel', taskId)"
        >
          Cancel
        </button>
        <template v-else-if="status === 'waiting_approval'">
          <button class="approve-btn" @click.stop="handleResume('approve')">Approve</button>
          <button class="reject-btn" @click.stop="handleResume('reject')">Reject</button>
          <router-link v-if="resultUrl" class="result-link" :to="resultUrl">Details</router-link>
        </template>
        <router-link
          v-else-if="status === 'completed' && resultUrl"
          class="result-link"
          :to="resultUrl"
        >
          View Result
        </router-link>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { Loading } from '@element-plus/icons-vue'

const props = defineProps<{
  progress: number
  status: string
  statusMessage?: string
  taskId?: string
  taskName?: string
  resultUrl?: string
  error?: string
  interruptData?: any
}>()

const emit = defineEmits<{
  (e: 'cancel', taskId: string): void
  (e: 'resume', taskId: string, decision: 'approve' | 'reject', feedback: string): void
}>()

const isActive = computed(() => props.status === 'running' || props.status === 'pending')

const feedback = ref('')

function unwrapInterrupt(data: any): any {
  if (!data) return null
  if (data.action_requests || data.review_configs) return data
  if (Array.isArray(data)) return unwrapInterrupt(data[0])
  if (data.__interrupt__ && Array.isArray(data.__interrupt__)) return unwrapInterrupt(data.__interrupt__[0])
  return data
}

const interruptDescription = computed(() => {
  const data = unwrapInterrupt(props.interruptData)
  if (!data) return ''
  if (Array.isArray(data.action_requests)) {
    return data.action_requests
      .map((r: any) => r?.description)
      .filter(Boolean)
      .join('\n')
  }
  return ''
})

function handleResume(decision: 'approve' | 'reject') {
  if (!props.taskId) return
  emit('resume', props.taskId, decision, feedback.value)
}
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

.task-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}

.task-interrupt {
  margin-top: 10px;
  padding: 10px;
  border-radius: 10px;
  border: 1px solid var(--border-color);
  background: var(--bg-secondary);
}

.task-interrupt-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 6px;
}

.task-interrupt-desc {
  font-size: 12px;
  color: var(--text-secondary);
  white-space: pre-wrap;
}

.task-feedback {
  width: 100%;
  margin-top: 8px;
  font-size: 12px;
  padding: 8px;
  border-radius: 8px;
  border: 1px solid var(--border-color);
  background: var(--bg-primary);
  color: var(--text-primary);
  resize: vertical;
}

.result-link {
  font-size: 11px;
  color: var(--accent-primary);
  text-decoration: none;
}

.result-link:hover {
  text-decoration: underline;
}

.cancel-btn:hover {
  background: #fee2e2;
}

.approve-btn,
.reject-btn {
  font-size: 11px;
  border: none;
  cursor: pointer;
  padding: 2px 8px;
  border-radius: 6px;
}

.approve-btn {
  background: rgba(34, 197, 94, 0.15);
  color: rgb(22, 163, 74);
}

.reject-btn {
  background: rgba(239, 68, 68, 0.12);
  color: rgb(220, 38, 38);
}

.approve-btn:hover {
  background: rgba(34, 197, 94, 0.22);
}

.reject-btn:hover {
  background: rgba(239, 68, 68, 0.18);
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
