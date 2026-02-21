<template>
  <div class="interrupt-wrapper">
    <!-- Header Badge -->
    <div class="header-badge-container">
      <div class="action-badge">
        <div class="pulse-dot"></div>
        <span class="badge-text">ACTION REQUIRED</span>
      </div>
    </div>

    <div class="interrupt-card">
      <!-- Card Header -->
      <div class="card-header">
        <div class="header-main">
          <div class="icon-wrapper">
            <div class="agent-icon">
              <span class="material-symbols-outlined icon">smart_toy</span>
            </div>
            <div class="bolt-icon">
              <span class="material-symbols-outlined icon-small">bolt</span>
            </div>
          </div>
          <div class="title-section">
            <h1 class="card-title">Review Agent Action</h1>
            <span class="card-subtitle">
              <span class="material-symbols-outlined icon-tiny">schedule</span>
              Pending manual review
            </span>
          </div>
        </div>
      </div>

      <!-- Content/Preview Area -->
      <div class="card-body">
        <div class="content-box">
          <div class="left-decor"></div>
          
          <div v-if="interruptDescription" class="description-text">
            <h3 class="section-label">GENERATED OUTPUT</h3>
            <MarkdownRenderer :content="interruptDescription" />
          </div>

          <!-- Preview Section -->
          <div v-if="previewContent" class="preview-container">
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
      </div>

      <!-- Action Buttons -->
      <div class="action-buttons">
        <button 
          class="btn-approve" 
          :disabled="loading"
          @click="handleApprove"
        >
          <span class="material-symbols-outlined">check_circle</span>
          <span>Approve</span>
        </button>
        
        <button 
          class="btn-reject" 
          :disabled="loading"
          @click="handleReject"
        >
          <span class="material-symbols-outlined">cancel</span>
          <span>Reject</span>
        </button>
      </div>

      <!-- Feedback Area (Animated) -->
      <div class="feedback-area">
        <div class="feedback-input-wrapper">
           <label class="feedback-label">
              Reason for Rejection
              <span class="label-hint">Required for training</span>
           </label>
           
           <div class="textarea-container">
             <textarea 
               v-model="feedback"
               class="feedback-textarea" 
               placeholder="Please explain why you rejected this action so the Agent can adjust..."
               :disabled="loading"
             ></textarea>
             
             <div class="textarea-footer">
               <span class="footer-tag">FEEDBACK LOOP</span>
               <span class="material-symbols-outlined footer-icon">edit_note</span>
             </div>
           </div>
        </div>
      </div>
      
      <!-- Submit Button (Only visible if feedback entered or rejected) -->
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
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
  if (data.action_requests || data.preview || data.review_configs || data.chart || data.option) return data
  if (data.interrupt && Array.isArray(data.interrupt)) return unwrapData(data.interrupt[0])
  if (data.__interrupt__ && Array.isArray(data.__interrupt__)) return unwrapData(data.__interrupt__[0])
  if (Array.isArray(data)) return unwrapData(data[0])
  if (data.data && typeof data.data === 'object') {
     if (!data.series && !data.xAxis) return unwrapData(data.data)
  }
  return data
}

// Extract description
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

// Extract preview content
const previewContent = computed(() => {
  const data = unwrapData(props.interruptData)
  if (!data) return null
  
  if (data?.preview) {
    if (typeof data.preview === 'string') {
        let jsonStr = data.preview
        if (jsonStr.includes('VISUALIZER_AGENT_COMPLETE:')) jsonStr = jsonStr.replace('VISUALIZER_AGENT_COMPLETE:', '').trim()
        else if (jsonStr.includes('REPORT_AGENT_COMPLETE:')) jsonStr = jsonStr.replace('REPORT_AGENT_COMPLETE:', '').trim()
        
        try {
            const parsed = JSON.parse(jsonStr)
            if (parsed.type === 'chart' && parsed.data) return parsed.data
            if (parsed.type === 'report' && parsed.content) return parsed.content
            if (parsed.chart || parsed.option) return parsed
        } catch {}
    }
    return data.preview
  }
  
  if (data?.chart || data?.option) return data
  if (data?.review_configs) return JSON.stringify(data.review_configs, null, 2)
  return typeof data === 'string' ? data : null
})

const previewType = computed(() => {
  const data = unwrapData(props.interruptData)
  if (data?.preview) {
      if (typeof data.preview === 'object' && (data.preview.series || data.preview.option)) return 'chart'
      if (typeof data.preview === 'string') {
          let jsonStr = data.preview
          if (jsonStr.includes('VISUALIZER_AGENT_COMPLETE:')) jsonStr = jsonStr.replace('VISUALIZER_AGENT_COMPLETE:', '').trim()
          else if (jsonStr.includes('REPORT_AGENT_COMPLETE:')) jsonStr = jsonStr.replace('REPORT_AGENT_COMPLETE:', '').trim()
          try {
             const parsed = JSON.parse(jsonStr)
             if (parsed.type === 'chart' && parsed.data) return 'chart'
             if (parsed.chart || parsed.option) return 'chart'
          } catch {}
      }
      return 'text'
  }
  if (data?.chart || data?.option || data?.series) return 'chart'
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
/* 字体引入在 index.html 或 App.vue 中完成 (Material Symbols) */

.interrupt-wrapper {
  position: relative;
  width: 100%;
  max-width: 600px;
  background: white;
  border-radius: 16px;
  box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.01);
  border: 1px solid rgb(226, 232, 240);
  overflow: visible; /* Logo floats outside */
  margin: 24px 0;
  font-family: 'Inter', system-ui, sans-serif;
}

.dark .interrupt-wrapper {
  background: rgb(30, 41, 59);
  border-color: rgb(51, 65, 85);
}

/* --- Badge --- */
.header-badge-container {
  position: absolute;
  top: -12px;
  right: 24px;
  z-index: 20;
}

.action-badge {
  display: flex;
  align-items: center;
  gap: 8px;
  background: rgb(254, 242, 242);
  border: 1px solid rgb(254, 226, 226);
  padding: 6px 12px;
  border-radius: 9999px;
  box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
}

.dark .action-badge {
  background: rgba(127, 29, 29, 0.2);
  border-color: rgba(127, 29, 29, 0.4);
}

.pulse-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: rgb(239, 68, 68);
  animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
}

.badge-text {
  font-size: 11px;
  font-weight: 700;
  color: rgb(220, 38, 38);
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

.dark .badge-text {
  color: rgb(252, 165, 165);
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: .5; }
}

/* --- Header --- */
.card-header {
  padding: 32px 32px 16px;
}

.header-main {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 8px;
}

.icon-wrapper {
  position: relative;
}

.agent-icon {
  width: 56px;
  height: 56px;
  background: rgb(248, 250, 252);
  border: 1px solid rgb(226, 232, 240);
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: rgb(51, 65, 85);
}

.dark .agent-icon {
  background: rgb(30, 41, 59);
  border-color: rgb(51, 65, 85);
  color: white;
}

.icon {
  font-size: 28px !important;
}

.bolt-icon {
  position: absolute;
  bottom: -4px;
  right: -4px;
  background: white;
  border: 1px solid rgb(241, 245, 249);
  border-radius: 50%;
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.dark .bolt-icon {
  background: rgb(30, 41, 59);
  border-color: rgb(51, 65, 85);
}

.icon-small {
  font-size: 14px !important;
  font-weight: bold;
  color: rgb(249, 115, 22); /* Primary Orange/Gold */
}

.title-section {
  padding-top: 4px;
}

.card-title {
  font-size: 20px;
  font-weight: 700;
  color: rgb(15, 23, 42);
  line-height: 1.25;
  margin: 0;
  font-family: inherit;
}

.dark .card-title {
  color: white;
}

.card-subtitle {
  margin-top: 4px;
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 14px;
  font-weight: 500;
  color: rgb(100, 116, 139);
}

.icon-tiny {
  font-size: 14px !important;
}

/* --- Body --- */
.card-body {
  padding: 0 32px 24px;
}

.content-box {
  position: relative;
  background: rgb(248, 250, 252);
  border: 1px solid rgb(226, 232, 240);
  border-radius: 8px;
  padding: 20px;
}

.dark .content-box {
  background: rgba(30, 41, 59, 0.5);
  border-color: rgb(51, 65, 85);
}

.left-decor {
  position: absolute;
  top: 0;
  left: 0;
  width: 4px;
  height: 100%;
  background: rgb(203, 213, 225);
  border-radius: 8px 0 0 8px;
}

.dark .left-decor {
  background: rgb(71, 85, 105);
}

.section-label {
  font-size: 11px;
  font-weight: 700;
  color: rgb(100, 116, 139);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin: 0 0 8px 0;
}

.description-text {
  font-size: 15px;
  line-height: 1.6;
  color: rgb(51, 65, 85);
}

.dark .description-text {
  color: rgb(203, 213, 225);
}

/* --- Buttons --- */
.action-buttons {
  padding: 0 32px 16px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  position: relative;
  z-index: 10;
}

.btn-approve, .btn-reject {
  height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  border: none;
}

.btn-approve {
  background: rgb(59, 130, 246);
  color: white;
  box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
}

.btn-approve:hover {
  background: rgb(37, 99, 235);
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
}

.btn-reject {
  background: rgb(254, 242, 242);
  border: 1px solid rgb(254, 202, 202);
  color: rgb(220, 38, 38);
}

.dark .btn-reject {
  background: rgba(127, 29, 29, 0.2);
  border-color: rgba(127, 29, 29, 0.5);
  color: rgb(252, 165, 165);
}

.btn-reject:hover {
  background: rgb(254, 226, 226);
}

.dark .btn-reject:hover {
  background: rgba(127, 29, 29, 0.3);
}

/* --- Feedback --- */
.feedback-area {
  padding: 8px 32px 32px;
  display: flex;
  flex-direction: column;
}

.feedback-input-wrapper {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
}

.feedback-label {
  display: flex;
  justify-content: space-between;
  font-size: 14px;
  font-weight: 600;
  color: rgb(30, 41, 59);
}

.dark .feedback-label {
  color: white;
}

.label-hint {
  font-size: 12px;
  font-weight: 400;
  color: rgb(100, 116, 139);
}

.textarea-container {
  position: relative;
}

.feedback-textarea {
  width: 100%;
  min-height: 140px;
  padding: 16px;
  padding-bottom: 36px; /* Space for footer */
  border-radius: 12px;
  border: 1px solid rgb(203, 213, 225);
  background: white;
  font-size: 14px;
  line-height: 1.6;
  color: rgb(30, 41, 59);
  resize: vertical;
  outline: none;
  transition: all 0.2s;
  font-family: inherit;
}

.dark .feedback-textarea {
  background: rgb(15, 23, 42);
  border-color: rgb(71, 85, 105);
  color: white;
}

.feedback-textarea:focus {
  border-color: rgb(59, 130, 246);
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2);
}

.textarea-footer {
  position: absolute;
  bottom: 12px;
  left: 12px;
  right: 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  pointer-events: none;
}

.footer-tag {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: rgb(203, 213, 225);
}

.footer-icon {
  font-size: 16px !important;
  color: rgb(203, 213, 225);
}


</style>
