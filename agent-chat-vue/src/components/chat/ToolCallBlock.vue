<template>
  <div class="tool-call-wrapper">
    <div class="tool-header">
      <div class="header-left">
        <span class="terminal-icon">⌨️</span>
        <span class="tool-label">Using Tool: <strong>{{ toolName }}</strong></span>
      </div>
      <span class="lang-badge">JSON</span>
    </div>
    
    <div class="tool-body">
      <pre class="code-content"><code v-html="highlightedJson"></code></pre>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ToolCall } from '@/types'

const props = defineProps<{
  toolCall?: ToolCall
  toolCalls?: ToolCall[]
  subgraphName?: string
}>()

const toolName = computed(() => {
  if (props.toolCall) return props.toolCall.name
  if (props.toolCalls?.length) return props.toolCalls[0].name
  return 'unknown'
})

const toolArgs = computed(() => {
  if (props.toolCall) return props.toolCall.args
  if (props.toolCalls?.length) return props.toolCalls[0].args
  return {}
})

const highlightedJson = computed(() => {
  try {
    const json = typeof toolArgs.value === 'string' 
      ? toolArgs.value 
      : JSON.stringify(toolArgs.value, null, 2)
    
    // Syntax highlighting
    return json
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      // Keys (quoted strings before colon)
      .replace(/"([^"]+)"(?=\s*:)/g, '<span class="json-key">"$1"</span>')
      // String values
      .replace(/:\s*"([^"]*)"/g, ': <span class="json-string">"$1"</span>')
      // Numbers
      .replace(/:\s*(\d+\.?\d*)/g, ': <span class="json-number">$1</span>')
      // Booleans
      .replace(/:\s*(true|false)/g, ': <span class="json-boolean">$1</span>')
      // Null
      .replace(/:\s*(null)/g, ': <span class="json-null">$1</span>')
  } catch {
    return String(toolArgs.value)
  }
})
</script>

<style scoped>
.tool-call-wrapper {
  margin: 16px 0;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid rgb(226, 232, 240);
  background: rgb(248, 250, 252);
  font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
  font-size: 12px;
}

.dark .tool-call-wrapper {
  border-color: rgb(51, 65, 85);
  background: rgb(15, 23, 42);
}

.tool-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: rgb(241, 245, 249);
  border-bottom: 1px solid rgb(226, 232, 240);
}

.dark .tool-header {
  background: rgb(30, 41, 59);
  border-bottom-color: rgb(51, 65, 85);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  color: rgb(71, 85, 105);
}

.dark .header-left {
  color: rgb(148, 163, 184);
}

.terminal-icon {
  font-size: 14px;
}

.tool-label {
  font-size: 12px;
}

.tool-label strong {
  color: rgb(15, 23, 42);
  font-weight: 600;
}

.dark .tool-label strong {
  color: rgb(226, 232, 240);
}

.lang-badge {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: rgb(148, 163, 184);
  opacity: 0.6;
}

.tool-body {
  padding: 12px;
  overflow-x: auto;
}

.code-content {
  margin: 0;
  line-height: 1.6;
  color: rgb(71, 85, 105);
}

.dark .code-content {
  color: rgb(203, 213, 225);
}

/* JSON Syntax Highlighting */
:deep(.json-key) {
  color: rgb(147, 51, 234);
}

.dark :deep(.json-key) {
  color: rgb(192, 132, 252);
}

:deep(.json-string) {
  color: rgb(217, 119, 6);
}

.dark :deep(.json-string) {
  color: rgb(251, 191, 36);
}

:deep(.json-number) {
  color: rgb(5, 150, 105);
}

.dark :deep(.json-number) {
  color: rgb(52, 211, 153);
}

:deep(.json-boolean) {
  color: rgb(59, 130, 246);
}

.dark :deep(.json-boolean) {
  color: rgb(96, 165, 250);
}

:deep(.json-null) {
  color: rgb(156, 163, 175);
}
</style>
