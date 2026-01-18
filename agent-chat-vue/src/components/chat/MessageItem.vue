<template>
  <div class="message-row" :class="message.role">
    <!-- Avatar -->
    <div class="avatar-container">
      <el-avatar v-if="message.role === 'assistant'" :size="36" class="ai-avatar">AI</el-avatar>
      <el-avatar v-else :size="36" class="user-avatar" icon="UserFilled" />
    </div>

    <!-- Message Body -->
    <div class="message-body">
      <!-- Chat Bubble -->
      <div class="message-bubble glass-panel">
        <!-- CoT (Collapsed) -->
        <ThinkingBlock v-if="message.thinking" :content="message.thinking" />
        
        <!-- Main Content -->
        <div class="message-content">
          <MarkdownRenderer :content="message.content" />
        </div>
        
        <!-- Tool Calls -->
        <div v-if="message.toolCalls?.length" class="tool-calls">
          <div v-for="(tool, idx) in message.toolCalls" :key="idx" class="tool-call">
            <el-icon><Setting /></el-icon>
            <span class="tool-name">使用了 {{ tool.name }}</span>
            <el-popover placement="top" :width="400" trigger="hover">
              <template #reference>
                <el-icon class="info-icon"><InfoFilled /></el-icon>
              </template>
              <div class="tool-details">
                <h4>输入:</h4>
                <pre>{{ tool.args }}</pre>
                <h4>结果:</h4>
                <pre>{{ tool.result }}</pre>
              </div>
            </el-popover>
          </div>
        </div>

        <!-- Chart -->
        <ChartRenderer v-if="message.chartData" :chartData="message.chartData" />
      </div>
      
      <!-- Timestamp (Optional) -->
      <!-- <div class="message-meta">{{ formatDate(message.createdAt) }}</div> -->
    </div>
  </div>
</template>

<script setup lang="ts">
import { Setting, InfoFilled } from '@element-plus/icons-vue'
import type { Message } from '@/types'
import ThinkingBlock from './ThinkingBlock.vue'
import MarkdownRenderer from './MarkdownRenderer.vue'
import ChartRenderer from './ChartRenderer.vue'

defineProps<{
  message: Message
}>()
</script>

<style scoped>
.message-row {
  display: flex;
  gap: 16px;
  margin-bottom: 24px;
}

.avatar-container {
  flex-shrink: 0;
}

.ai-avatar {
  background: var(--accent-gradient);
  font-weight: 600;
  font-size: 14px;
}

.user-avatar {
  background: var(--bg-tertiary);
  color: var(--text-secondary);
}

.message-body {
  flex: 1;
  min-width: 0;
  max-width: 100%;
}

.message-bubble {
  display: inline-block;
  padding: 16px 24px;
  border-radius: 12px;
  max-width: 100%;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
}

/* User Message Specifics */
.message-row.user {
  flex-direction: row-reverse;
}

.message-row.user .message-bubble {
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  border-top-right-radius: 2px;
}

/* AI Message Specifics */
.message-row.assistant .message-bubble {
  background: var(--glass-bg);
  border-top-left-radius: 2px;
  width: 100%; /* AI answers often take full width */
}

/* Tool Calls */
.tool-calls {
  margin-top: 12px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.tool-call {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  background: rgba(0, 0, 0, 0.2);
  border-radius: 6px;
  font-size: 12px;
  color: var(--text-secondary);
}

.tool-name {
  font-family: var(--font-mono);
}

.info-icon {
  cursor: pointer;
  margin-left: 4px;
}

.info-icon:hover {
  color: var(--text-primary);
}

.tool-details pre {
  background: var(--bg-primary);
  padding: 8px;
  border-radius: 4px;
  overflow-x: auto;
  font-size: 12px;
}
</style>
