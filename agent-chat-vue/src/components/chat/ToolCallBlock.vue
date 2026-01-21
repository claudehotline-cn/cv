<template>
  <div v-if="(toolCalls && toolCalls.length) || toolCall" class="tool-calls-container" :class="{ 'vertical-layout': !!toolCall, 'subgraph-tool': !!subgraphName }">
    <!-- Single Tool Call Mode -->
    <template v-if="toolCall">
      <div class="tool-call-item single-mode">
        <el-icon class="tool-icon"><Setting /></el-icon>
        <span class="tool-name">
            <span v-if="subgraphName" class="subgraph-badge">{{ formatSubgraphName(subgraphName) }}</span>
            使用了 {{ toolCall.name }}
        </span>
        
        <!-- Inline Details for Single Mode (Always visible or toggleable, here using popover for consistency but could be changed) -->
        <el-popover placement="top" :width="500" trigger="hover" popper-class="tool-popover">
          <template #reference>
            <el-icon class="info-icon"><InfoFilled /></el-icon>
          </template>
          <div class="tool-details">
            <div class="detail-section">
              <h4>输入参数</h4>
              <div class="code-block">{{ formatJson(toolCall.args) }}</div>
            </div>
          </div>
        </el-popover>
      </div>
    </template>

    <!-- Multiple Tool Calls Mode (Legacy) -->
    <template v-else>
      <div v-for="(tool, idx) in toolCalls" :key="tool.id || idx" class="tool-call-item">
        <el-icon class="tool-icon"><Setting /></el-icon>
        <span class="tool-name">使用了 {{ tool.name }}</span>
        
        <el-popover placement="top" :width="400" trigger="hover" popper-class="tool-popover">
          <template #reference>
            <el-icon class="info-icon"><InfoFilled /></el-icon>
          </template>
          <div class="tool-details">
            <div class="detail-section">
              <h4>输入参数</h4>
              <div class="code-block">{{ formatJson(tool.args) }}</div>
            </div>
            
            <div class="detail-section">
              <h4>执行结果</h4>
              <template v-if="tool.result">
                 <div class="code-block result">{{ formatResult(tool.result) }}</div>
              </template>
              <template v-else>
                 <span class="status-running">
                   <el-icon class="is-loading"><Loading /></el-icon> 执行中...
                 </span>
              </template>
            </div>
          </div>
        </el-popover>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { Setting, InfoFilled, Loading } from '@element-plus/icons-vue'
import type { ToolCall } from '@/types'

defineProps<{
  toolCalls?: ToolCall[]
  toolCall?: ToolCall  // Single tool call mode
  subgraphName?: string
}>()

function formatSubgraphName(name: string): string {
    const readable: Record<string, string> = {
        'sql_agent': 'SQL',
        'python_agent': 'Python',
        'visualizer_agent': 'Viz',
    }
    return readable[name] || name
}

function formatJson(val: any) {
  try {
      if (typeof val === 'string') return val
      return JSON.stringify(val, null, 2)
  } catch {
      return String(val)
  }
}

function formatResult(val: any) {
    let str = String(val)
    if (str.length > 800) {
        return str.slice(0, 800) + '... (truncated)'
    }
    return str
}
</script>

<style scoped>
.tool-calls-container {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 8px 0;
}

.tool-call-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: var(--bg-tertiary, #f3f4f6);
  border: 1px solid var(--border-color, #e5e7eb);
  border-radius: 8px;
  font-size: 13px;
  color: var(--text-secondary, #6b7280);
  transition: all 0.2s;
  user-select: none;
}

.dark .tool-call-item {
    background: rgba(255, 255, 255, 0.05);
    border-color: rgba(255, 255, 255, 0.1);
}

.tool-call-item:hover {
    background: var(--bg-secondary);
    border-color: var(--accent-primary, #6366f1);
    color: var(--text-primary);
}

.tool-name {
  font-family: var(--font-mono, monospace);
  font-weight: 500;
}

.info-icon {
  margin-left: 4px;
  opacity: 0.6;
  cursor: help;
}

.info-icon:hover {
    opacity: 1;
    color: var(--accent-primary);
}

.tool-details {
    max-height: 400px;
    overflow-y: auto;
}

.detail-section {
    margin-bottom: 12px;
}

.detail-section h4 {
    margin: 0 0 6px 0;
    font-size: 12px;
    color: var(--text-secondary);
    font-weight: 600;
}

.code-block {
    background: var(--bg-primary, #ffffff);
    padding: 8px 12px;
    border-radius: 6px;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 12px;
    white-space: pre-wrap;
    word-break: break-all;
    border: 1px solid var(--border-color);
    color: var(--text-primary);
}

.dark .code-block {
    background: #1e1e2e;
}

.status-running {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    color: var(--accent-primary);
    font-size: 12px;
}
</style>
