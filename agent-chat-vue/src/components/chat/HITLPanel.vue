<template>
  <div class="hitl-alert glass-panel">
    <div class="alert-icon">
      <el-icon><WarningFilled /></el-icon>
    </div>
    
    <div class="alert-content">
      <h4 class="alert-title">需要批准</h4>
      <p class="alert-desc">{{ interruptData?.reason || 'Agent 需要您的确认才能继续。' }}</p>
      
      <!-- Preview Data -->
      <div v-if="interruptData?.preview" class="data-preview">
        <pre>{{ JSON.stringify(interruptData.preview, null, 2) }}</pre>
      </div>
      
      <!-- Feedback Input -->
      <div class="feedback-section">
        <el-input
          v-model="feedbackMessage"
          placeholder="给 Agent 的可选指令..."
          size="small"
          class="feedback-input"
        >
          <template #prefix>
            <el-icon><EditPen /></el-icon>
          </template>
        </el-input>
      </div>
    
      <div class="alert-actions">
        <el-button type="danger" plain size="small" @click="handleReject">
          拒绝
        </el-button>
        <el-button type="primary" size="small" @click="handleApprove">
          批准并继续
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { WarningFilled, EditPen } from '@element-plus/icons-vue'

defineProps<{
  interruptData?: {
    reason?: string
    preview?: Record<string, unknown>
  }
}>()

const emit = defineEmits<{
  approve: []
  reject: [message: string]
}>()

const feedbackMessage = ref('')

function handleApprove() {
  emit('approve')
}

function handleReject() {
  emit('reject', feedbackMessage.value)
}
</script>

<style scoped>
.hitl-alert {
  display: flex;
  gap: 16px;
  padding: 20px;
  margin: 16px 0;
  border-radius: 12px;
  border-left: 4px solid var(--el-color-warning);
  background: linear-gradient(to right, rgba(230, 162, 60, 0.1), rgba(230, 162, 60, 0.05));
}

.alert-icon {
  font-size: 24px;
  color: var(--el-color-warning);
  padding-top: 2px;
}

.alert-content {
  flex: 1;
}

.alert-title {
  margin: 0 0 4px 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.alert-desc {
  margin: 0 0 16px 0;
  color: var(--text-secondary);
  font-size: 14px;
}

.data-preview {
  background: rgba(0, 0, 0, 0.2);
  padding: 12px;
  border-radius: 6px;
  margin-bottom: 16px;
}

.data-preview pre {
  margin: 0;
  font-size: 12px;
  color: var(--text-tertiary);
  font-family: var(--font-mono);
}

.feedback-section {
  margin-bottom: 16px;
}

.alert-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}
</style>
