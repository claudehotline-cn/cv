<template>
  <div class="thinking-wrapper">
    <button class="thinking-header" @click="toggle">
      <div class="header-left">
        <span class="thinking-icon">🧠</span>
        <span class="label">THINKING PROCESS</span>
        <span v-if="isStreaming" class="streaming-indicator"></span>
      </div>
      <span class="arrow" :class="{ expanded: isOpen }">
        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="6 9 12 15 18 9"></polyline>
        </svg>
      </span>
    </button>
    
    <div v-show="isOpen" class="thinking-body">
      <div class="thinking-content">{{ content }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

defineProps<{
  content: string
  isStreaming?: boolean
  subgraphName?: string
}>()

const isOpen = ref(true)

function toggle() {
  isOpen.value = !isOpen.value
}
</script>

<style scoped>
.thinking-wrapper {
  margin-bottom: 16px;
  border-radius: 12px;
  background: linear-gradient(135deg, rgba(147, 51, 234, 0.05) 0%, rgba(168, 85, 247, 0.08) 100%);
  border: 1px solid rgba(147, 51, 234, 0.15);
  overflow: hidden;
}

.thinking-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 12px 16px;
  cursor: pointer;
  transition: background 0.2s;
  user-select: none;
  background: transparent;
  border: none;
  text-align: left;
}

.thinking-header:hover {
  background: rgba(147, 51, 234, 0.08);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.thinking-icon {
  font-size: 18px;
}

.label {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: rgb(107, 33, 168);
}

.dark .label {
  color: rgb(192, 132, 252);
}

.streaming-indicator {
  width: 8px;
  height: 8px;
  background: rgb(147, 51, 234);
  border-radius: 50%;
  animation: pulse 1.2s ease-in-out infinite;
  margin-left: 4px;
}

@keyframes pulse {
  0%, 100% { opacity: 0.4; transform: scale(0.8); }
  50% { opacity: 1; transform: scale(1); }
}

.arrow {
  color: rgba(147, 51, 234, 0.6);
  transition: transform 0.2s;
  display: flex;
  align-items: center;
}

.arrow.expanded {
  transform: rotate(180deg);
}

.thinking-body {
  border-top: 1px solid rgba(147, 51, 234, 0.1);
  background: rgba(147, 51, 234, 0.03);
}

.thinking-content {
  padding: 12px 16px;
  font-size: 13px;
  line-height: 1.7;
  color: rgb(83, 136, 147);
  white-space: pre-wrap;
  word-break: break-word;
}

.dark .thinking-content {
  color: rgba(192, 132, 252, 0.85);
}
</style>
