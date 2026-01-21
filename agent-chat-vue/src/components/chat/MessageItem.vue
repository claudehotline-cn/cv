<template>
  <div class="message-row" :class="message.role">
    <!-- User Layout (Right Aligned) -->
    <template v-if="message.role === 'user'">
       <div class="message-container user">
          <div class="message-bubble user-bubble">
             <MarkdownRenderer :content="getUserContent(message)" />
          </div>
          <span class="message-meta">Alex • {{ formatTime(message.createdAt) }}</span>
       </div>
    </template>

    <!-- Assistant Layout (Left Aligned) -->
    <template v-else>
       <div class="message-container assistant">
          <div class="avatar-col">
             <div class="ai-avatar-square">
                <el-icon><DataAnalysis /></el-icon>
             </div>
          </div>
          
          <div class="content-col">
             <div class="message-card">
                <template v-if="message.blocks && message.blocks.length">
                   <div v-for="(block, idx) in message.blocks" :key="idx" class="message-block">
                      <!-- Thinking Block -->
                      <ThinkingBlock
                         v-if="block.type === 'thinking'"
                         :content="block.content"
                         :subgraph-name="block.subgraph"
                      />
                      
                      <!-- Tool Call Block -->
                      <ToolCallBlock
                         v-else-if="block.type === 'tool_call'"
                         :tool-call="block.call"
                         :subgraph-name="block.subgraph"
                      />
                      
                      <!-- Tool Output Block -->
                      <ToolOutputBlock
                         v-else-if="block.type === 'tool_output'"
                         :call-id="block.callId"
                         :output="block.output"
                         :subgraph-name="block.subgraph"
                      />
                      
                      <!-- Content Block -->
                      <div v-else-if="block.type === 'content'" class="text-content">
                         <MarkdownRenderer :content="block.content" />
                      </div>
                      
                      <!-- Chart Block -->
                      <ChartRenderer 
                         v-else-if="block.type === 'chart'"
                         :chartData="block.data" 
                      />
                      
                     <!-- Interrupt Block -->
                     <div v-else-if="block.type === 'interrupt'" class="interrupt-block">
                        <p>Waiting for user approval...</p>
                     </div>
                   </div>
                </template>
                
                <!-- Fallback/Empty State -->
                <div v-else-if="!message.blocks || message.blocks.length === 0" class="text-content">
                    <p class="text-gray-400 italic">Empty message</p>
                </div>
             </div>
             <span class="message-meta pl-1">Data Analyst • {{ formatTime(message.createdAt) }}</span>
          </div>
       </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { DataAnalysis } from '@element-plus/icons-vue'
import type { Message, ContentBlock } from '@/types'
import ThinkingBlock from './ThinkingBlock.vue'
import ToolCallBlock from './ToolCallBlock.vue'
import ToolOutputBlock from './ToolOutputBlock.vue' // New
import MarkdownRenderer from './MarkdownRenderer.vue'
import ChartRenderer from './ChartRenderer.vue'
import dayjs from 'dayjs'

defineProps<{
  message: Message
}>()

function formatTime(date: Date | string) {
   return dayjs(date).format('h:mm A')
}

function getUserContent(message: Message): string {
    if (!message.blocks) return ''
    const contentBlock = message.blocks.find(b => b.type === 'content') as ContentBlock | undefined
    return contentBlock ? contentBlock.content : ''
}
</script>

<style scoped>
.message-row {
  width: 100%;
  margin-bottom: 24px;
  display: flex;
}

.message-row.user {
  justify-content: flex-end;
}

.message-row.assistant {
  justify-content: flex-start;
}

.message-container {
  display: flex;
  max-width: 85%;
  flex-direction: column;
  gap: 4px;
}

.message-container.user {
  align-items: flex-end;
}

.message-container.assistant {
  flex-direction: row;
  align-items: flex-start;
  gap: 12px;
}

/* User Bubble */
.user-bubble {
  background: var(--message-user-bg); /* #1f96ad */
  color: var(--message-user-text);    /* white */
  padding: 12px 20px;
  border-radius: 16px;
  border-top-right-radius: 2px;
  box-shadow: 0 1px 2px rgba(31, 150, 173, 0.2);
  font-size: 14px;
  line-height: 1.6;
}

/* AI Layout */
.avatar-col {
  flex-shrink: 0;
  margin-top: 4px;
}

.ai-avatar-square {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-size: 16px;
  box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}

.content-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.message-card {
  background: var(--bg-primary); /* white/dark */
  border: 1px solid var(--border-color);
  padding: 16px 20px;
  border-radius: 16px;
  border-top-left-radius: 2px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.05);
  color: var(--text-primary);
  font-size: 14px;
  line-height: 1.6;
}

.message-meta {
  font-size: 10px;
  color: var(--text-secondary);
  padding: 0 4px;
}

/* Markdown Content Styling Overrides for User Bubble */
.user-bubble :deep(p) {
  margin: 0;
}

.user-bubble :deep(a) {
  color: white;
  text-decoration: underline;
}
</style>
