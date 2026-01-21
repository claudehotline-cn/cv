<template>
  <div class="tool-output-block" :class="{ 'subgraph-output': !!subgraphName }">
    <div class="output-header">
      <el-icon class="output-icon"><Connection /></el-icon>
      <span class="header-text">
        <span v-if="subgraphName" class="subgraph-badge">{{ formatSubgraphName(subgraphName) }}</span>
        工具执行结果
      </span>
      <span class="call-id">#{{ callId.slice(-4) }}</span>
    </div>
    
    <div class="output-content">
      <div v-if="isCode" class="code-result">
        {{ output }}
      </div>
      <div v-else class="text-result">
        {{ output }}
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Connection } from '@element-plus/icons-vue'

const props = defineProps<{
  callId: string
  output: string
  subgraphName?: string
}>()

const isCode = computed(() => {
    const text = props.output.trim()
    return text.startsWith('{') || text.startsWith('[') || text.includes('DataFrame')
})

function formatSubgraphName(name: string): string {
    const readable: Record<string, string> = {
        'sql_agent': 'SQL',
        'python_agent': 'Python',
        'visualizer_agent': 'Viz',
    }
    return readable[name] || name
}
</script>

<style scoped>
.tool-output-block {
  margin: 8px 0;
  border-left: 2px solid var(--border-color);
  padding-left: 12px;
}

.subgraph-output {
    border-left-color: var(--accent-primary, #6366f1);
}

.output-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 6px;
}

.output-icon {
    font-size: 14px;
}

.header-text {
    font-weight: 500;
    display: flex;
    align-items: center;
}

.call-id {
    font-family: monospace;
    opacity: 0.5;
}

.subgraph-badge {
    display: inline-block;
    padding: 1px 6px;
    margin-right: 6px;
    background: var(--accent-primary, #6366f1);
    color: white;
    border-radius: 4px;
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
}

.output-content {
    font-size: 13px;
    color: var(--text-primary);
    background: var(--bg-tertiary);
    padding: 8px 12px;
    border-radius: 6px;
    max-height: 300px;
    overflow-y: auto;
}

.code-result {
    font-family: 'JetBrains Mono', monospace;
    white-space: pre-wrap;
    word-break: break-all;
}
</style>
