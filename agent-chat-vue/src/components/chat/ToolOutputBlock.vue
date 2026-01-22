<template>
  <div class="tool-output-wrapper">
    <div class="output-header">
      <div class="header-left">
        <span class="success-icon">
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="20 6 9 17 4 12"></polyline>
          </svg>
        </span>
        <span class="status-text">Success: {{ title }}</span>
      </div>
      <button class="expand-btn" @click="toggleExpand">
        {{ isExpanded ? 'Collapse' : 'Expand' }}
      </button>
    </div>
    
    <div v-if="isExpanded" class="output-body">
      <div class="text-output">
        <pre>{{ output }}</pre>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'

const props = defineProps<{
  callId: string
  output: string
  subgraphName?: string
}>()

const isExpanded = ref(false)

function toggleExpand() {
  isExpanded.value = !isExpanded.value
}

const title = computed(() => {
  const text = props.output.toLowerCase()
  if (text.includes('chart') || text.includes('图表')) return 'Chart Generated'
  if (text.includes('dataframe') || text.includes('rows')) return 'Data Loaded'
  if (text.includes('success') || text.includes('成功')) return 'Task Completed'
  return 'Execution Complete'
})
</script>

<style scoped>
.tool-output-wrapper {
  margin: 16px 0;
  max-width: 384px;
  border-radius: 12px;
  overflow: hidden;
  border: 1px solid rgb(239, 244, 245);
  background: white;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03);
}

.dark .tool-output-wrapper {
  border-color: rgb(47, 52, 58);
  background: rgb(30, 34, 38);
}

.output-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: rgb(252, 253, 254);
  border-bottom: 1px solid rgb(240, 244, 246);
}

.dark .output-header {
  background: rgb(37, 42, 48);
  border-bottom-color: rgb(47, 52, 58);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.success-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: rgb(220, 252, 231);
  color: rgb(22, 163, 74);
}

.dark .success-icon {
  background: rgba(34, 197, 94, 0.2);
  color: rgb(74, 222, 128);
}

.status-text {
  font-size: 12px;
  font-weight: 600;
  color: rgb(15, 24, 26);
}

.dark .status-text {
  color: white;
}

.expand-btn {
  font-size: 12px;
  font-weight: 500;
  color: rgb(83, 136, 147);
  background: none;
  border: none;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 4px;
  transition: all 0.2s;
}

.expand-btn:hover {
  color: rgb(31, 150, 173);
  background: rgba(31, 150, 173, 0.1);
}

.output-body {
  padding: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.text-output {
  width: 100%;
  font-family: ui-monospace, SFMono-Regular, monospace;
  font-size: 12px;
  color: rgb(71, 85, 105);
  max-height: 200px;
  overflow-y: auto;
}

.dark .text-output {
  color: rgb(203, 213, 225);
}

.text-output pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
