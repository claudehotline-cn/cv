<template>
  <div class="thinking-wrapper" :class="{ 'subgraph-thinking': subgraphName }">
    <div class="thinking-header" @click="toggle">
      <div class="header-left">
        <el-icon class="status-icon" :class="{ rotating: isStreaming }">
          <Loading v-if="isStreaming" />
          <Cpu v-else />
        </el-icon>
        <span class="label">
          <span v-if="subgraphName" class="subgraph-badge">{{ formatSubgraphName(subgraphName) }}</span>
          {{ subgraphName ? '思考过程' : '思考过程' }}
        </span>
      </div>
      <el-icon class="arrow" :class="{ expanded: isOpen }"><ArrowRight /></el-icon>
    </div>
    
    <div v-show="isOpen" class="thinking-body">
      <div class="thinking-content">
        {{ content }}
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { Loading, Cpu, ArrowRight } from '@element-plus/icons-vue'

const props = defineProps<{
  content: string
  isStreaming?: boolean
  subgraphName?: string  // Optional subgraph identifier
}>()

const isOpen = ref(!!props.isStreaming)

function toggle() {
  isOpen.value = !isOpen.value
}

function formatSubgraphName(name: string): string {
  // Convert snake_case to readable format
  const readable: Record<string, string> = {
    'sql_agent': 'SQL Agent',
    'python_agent': 'Python Agent',
    'visualizer_agent': 'Visualizer',
    'report_agent': 'Report Agent',
    'reviewer_agent': 'Reviewer',
  }
  return readable[name] || name.replace(/_/g, ' ')
}
</script>

<style scoped>
.thinking-wrapper {
  margin-bottom: 16px;
  border-radius: 8px;
  background: rgba(0, 0, 0, 0.2);
  border: 1px solid var(--border-color);
  overflow: hidden;
}

.thinking-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  cursor: pointer;
  transition: background 0.2s;
  user-select: none;
}

.thinking-header:hover {
  background: rgba(255, 255, 255, 0.05);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
}

.status-icon {
  font-size: 14px;
}

.status-icon.rotating {
  animation: spin 1s linear infinite;
  color: var(--accent-primary);
}

.arrow {
  font-size: 12px;
  color: var(--text-tertiary);
  transition: transform 0.2s;
}

.arrow.expanded {
  transform: rotate(90deg);
}

.thinking-body {
  border-top: 1px solid var(--border-color);
  background: rgba(0, 0, 0, 0.1);
}

.thinking-content {
  padding: 12px 16px;
  font-family: var(--font-mono);
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-secondary);
  white-space: pre-wrap;
  word-break: break-word;
}

/* Subgraph-specific styling */
.subgraph-thinking {
  border-left: 3px solid var(--accent-primary, #6366f1);
  margin-left: 8px;
}

.subgraph-badge {
  display: inline-block;
  padding: 2px 8px;
  margin-right: 6px;
  background: var(--accent-primary, #6366f1);
  color: white;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
