<template>
  <div class="interrupt-block">
    <div class="interrupt-header">
      <el-icon class="status-icon warning"><Warning /></el-icon>
      <span class="label">等待用户审核</span>
    </div>
    
    <!-- Description Section -->
    <div v-if="interruptDescription" class="description-section">
      <MarkdownRenderer :content="interruptDescription" />
    </div>

    <!-- Preview Section -->
    <div v-if="previewContent" class="preview-section">
      <div class="preview-label">预览内容</div>
      <div class="preview-content">
        <ChartRenderer 
          v-if="previewType === 'chart'" 
          :chartData="previewContent" 
        />
        <MarkdownRenderer 
          v-else 
          :content="previewContent" 
        />
      </div>
    </div>
    
    <!-- Feedback Section -->
    <div class="feedback-section">
      <el-input
        v-model="feedback"
        type="textarea"
        :rows="2"
        placeholder="可选：输入反馈或修改建议..."
        :disabled="loading"
      />
    </div>
    
    <!-- Action Buttons -->
    <div class="action-buttons">
      <el-button 
        type="success" 
        :loading="loading && decision === 'approve'"
        :disabled="loading"
        @click="handleApprove"
      >
        <el-icon><Check /></el-icon>
        批准
      </el-button>
      <el-button 
        type="danger"
        :loading="loading && decision === 'reject'"
        :disabled="loading"
        @click="handleReject"
      >
        <el-icon><Close /></el-icon>
        拒绝
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { Warning, Check, Close } from '@element-plus/icons-vue'
import ChartRenderer from './ChartRenderer.vue'
import MarkdownRenderer from './MarkdownRenderer.vue'

const props = defineProps<{
  interruptData: any
}>()

const emit = defineEmits<{
  (e: 'resume', decision: 'approve' | 'reject', feedback: string): void
}>()

const feedback = ref('')
const loading = ref(false)
const decision = ref<'approve' | 'reject' | null>(null)

function unwrapData(data: any): any {
  if (!data) return null
  
  // Found target?
  if (data.action_requests || data.preview || data.review_configs || data.chart || data.option) {
      return data
  }
  
  // Unwrap .interrupt
  if (data.interrupt && Array.isArray(data.interrupt)) {
      return unwrapData(data.interrupt[0])
  }

  // Unwrap .__interrupt__ (seen in debug output)
  if (data.__interrupt__ && Array.isArray(data.__interrupt__)) {
      return unwrapData(data.__interrupt__[0])
  }
  
  // Unwrap array
  if (Array.isArray(data)) {
      return unwrapData(data[0])
  }
  
  // Unwrap .data
  if (data.data && typeof data.data === 'object') {
     // Careful not to unwrap chart data structure which also has .data
     if (!data.series && !data.xAxis) {
         return unwrapData(data.data)
     }
  }

  return data
}

// Extract description from interrupt data
const interruptDescription = computed(() => {
  const data = unwrapData(props.interruptData)
  if (!data) return null

  if (data?.action_requests && Array.isArray(data.action_requests)) {
      const descriptions = data.action_requests
          .map((req: any) => req.description)
          .filter(Boolean)
      if (descriptions.length > 0) return descriptions.join('\n\n')
  }
  return null
})

// Extract preview content from interrupt data
const previewContent = computed(() => {
  const data = unwrapData(props.interruptData)
  if (!data) return null
  
  // 1. Check for explicit preview content (from middleware)
  if (data?.preview) {
    // If preview is a string that looks like JSON, try to parse it for chart detection
    if (typeof data.preview === 'string') {
        let jsonStr = data.preview
        // Strip common prefixes
        if (jsonStr.includes('VISUALIZER_AGENT_COMPLETE:')) {
            jsonStr = jsonStr.replace('VISUALIZER_AGENT_COMPLETE:', '').trim()
        } else if (jsonStr.includes('REPORT_AGENT_COMPLETE:')) {
            jsonStr = jsonStr.replace('REPORT_AGENT_COMPLETE:', '').trim()
        }
        
        try {
            const parsed = JSON.parse(jsonStr)
            
            // Handle chart type
            if (parsed.type === 'chart' && parsed.data) {
                return parsed.data
            }
            
            // Handle report type - extract markdown content
            if (parsed.type === 'report' && parsed.content) {
                return parsed.content
            }
            
            if (parsed.chart || parsed.option) return parsed
        } catch {
            // Not JSON, return as string (Markdown)
        }
    }
    return data.preview
  }
  
  // 2. Check for chart object directly
  if (data?.chart || data?.option) {
    return data
  }
  
  // 4. Check for review_configs
  if (data?.review_configs) {
    return JSON.stringify(data.review_configs, null, 2)
  }
  
  // Fallback to string representation if it's a string, otherwise null (to hide preview section)
  return typeof data === 'string' ? data : null
})

const previewType = computed(() => {
  const data = unwrapData(props.interruptData)
  
  // Check explicit preview
  if (data?.preview) {
      if (typeof data.preview === 'object' && (data.preview.series || data.preview.option)) return 'chart'
      if (typeof data.preview === 'string') {
          let jsonStr = data.preview
          if (jsonStr.includes('VISUALIZER_AGENT_COMPLETE:')) {
            jsonStr = jsonStr.replace('VISUALIZER_AGENT_COMPLETE:', '').trim()
          } else if (jsonStr.includes('REPORT_AGENT_COMPLETE:')) {
            jsonStr = jsonStr.replace('REPORT_AGENT_COMPLETE:', '').trim()
          }

          try {
             const parsed = JSON.parse(jsonStr)
             
             if (parsed.type === 'chart' && parsed.data) return 'chart'
             if (parsed.chart || parsed.option) return 'chart'
          } catch {}
      }
      return 'text'
  }
  
  if (data?.chart || data?.option || data?.series) {
    return 'chart'
  }
  return 'text'
})

async function handleApprove() {
  decision.value = 'approve'
  loading.value = true
  emit('resume', 'approve', feedback.value)
}

async function handleReject() {
  decision.value = 'reject'
  loading.value = true
  emit('resume', 'reject', feedback.value)
}
</script>

<style scoped>
.interrupt-block {
  background: rgba(250, 173, 20, 0.1);
  border: 1px solid rgba(250, 173, 20, 0.3);
  border-radius: 8px;
  padding: 16px;
  margin: 12px 0;
}

.interrupt-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  font-weight: 500;
  color: #faad14;
}

.status-icon {
  font-size: 18px;
}

.preview-section {
  margin-bottom: 12px;
}

.preview-label {
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 6px;
}

.preview-content {
  background: var(--bg-secondary);
  border-radius: 6px;
  padding: 12px;
  max-height: 300px;
  overflow: auto;
}

.feedback-section {
  margin-bottom: 12px;
}

.action-buttons {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
}
</style>
