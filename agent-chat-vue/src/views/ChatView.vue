<template>
  <div class="chat-view">
    <!-- Top Right Controls -->
    <div class="top-right-controls">
      <el-button circle text @click="toggleTheme" class="theme-toggle-btn">
        <el-icon v-if="isDark" class="theme-icon"><Moon /></el-icon>
        <el-icon v-else class="theme-icon"><Sunny /></el-icon>
      </el-button>
    </div>

    <!-- Chat Header (Only show if session active or chatting) -->
    <div v-if="chatStore.currentSessionId" class="chat-header glass-panel">
      <div class="header-info">
        <h3>{{ chatStore.currentSession?.title || '新对话' }}</h3>
        <el-tag size="small" type="success" effect="dark" round>{{ currentAgentName }}</el-tag>
      </div>
    </div>

    <!-- Messages Area (Only show if session active) -->
    <el-scrollbar v-if="chatStore.currentSessionId" ref="messageListRef" class="message-list-container">
      <div class="message-list-inner">
        <MessageItem
          v-for="msg in chatStore.messages"
          :key="msg.id"
          :message="msg"
        />
        
        <!-- Streaming Message -->
        <div v-if="chatStore.isStreaming" class="message assistant streaming-message">
          <div class="avatar-container">
            <el-avatar :size="36" class="ai-avatar">AI</el-avatar>
          </div>
          <div class="message-body">
            <ThinkingBlock
              v-if="chatStore.streamingThinking"
              :content="chatStore.streamingThinking"
              :isStreaming="true"
            />
            <ToolCallBlock 
               :toolCalls="chatStore.streamingToolCalls"
            />
            <div class="content-wrapper glass-panel">
              <MarkdownRenderer :content="chatStore.streamingContent || '思考中...'" />
            </div>
          </div>
        </div>
        
        <!-- HITL Panel -->
        <div v-if="chatStore.isInterrupted" class="hitl-wrapper">
          <HITLPanel
            :interruptData="chatStore.interruptData"
            @approve="handleApprove"
            @reject="handleReject"
          />
        </div>

        <!-- Chart -->
        <div v-if="chatStore.currentChart" class="chart-wrapper">
          <ChartRenderer :chartData="chatStore.currentChart" />
        </div>
        
        <div class="bottom-spacer"></div>
      </div>
    </el-scrollbar>

    <!-- Input Area (Handle both Center and Bottom positions) -->
    <div 
      class="input-container" 
      :class="{ 'centered-input': !chatStore.currentSessionId }"
    >
      <div v-if="!chatStore.currentSessionId" class="welcome-section">
        <div class="logo-box">
          <el-icon class="logo-icon"><Cpu /></el-icon>
        </div>
        <h1 class="welcome-title">有什么可以帮你的吗?</h1>
      </div>

      <div class="input-box glass-panel">
        <div v-if="chatStore.isStreaming" class="stop-btn-wrapper">
          <el-button round size="small" @click="handleStop">
            <el-icon><VideoPause /></el-icon> 停止生成
          </el-button>
        </div>
        
        <el-input
          v-model="inputMessage"
          type="textarea"
          :autosize="{ minRows: 1, maxRows: 8 }"
          placeholder="输入消息，或者上传图片/文件..."
          resize="none"
          class="custom-textarea"
          :disabled="chatStore.isStreaming || chatStore.isInterrupted"
          @keydown.enter.exact.prevent="handleSend"
        />
        
        <div class="input-footer">
          <div class="tools-btn">
            <el-tooltip content="上传图片" placement="top">
              <el-button circle text :icon="Picture" />
            </el-tooltip>
            <el-tooltip content="上传文件" placement="top">
              <el-button circle text :icon="Document" />
            </el-tooltip>
            <el-tooltip content="增强模式" placement="top">
              <el-button circle text :icon="MagicStick" />
            </el-tooltip>
          </div>
          <el-button
            type="primary"
            circle
            :disabled="!inputMessage.trim() || chatStore.isInterrupted"
            :loading="chatStore.isStreaming"
            @click="handleSend"
            class="send-btn"
          >
            <el-icon v-if="!chatStore.isStreaming"><Position /></el-icon>
          </el-button>
        </div>
      </div>
      
      <div class="footer-text">
        AI 可能会犯错，请核对重要信息。
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, nextTick, watch } from 'vue'
import { 
  Cpu, Position, VideoPause, Moon, Sunny,
  Picture, Document, MagicStick
} from '@element-plus/icons-vue'
import { useChatStore } from '@/stores/chat'
import MessageItem from '@/components/chat/MessageItem.vue'
import ThinkingBlock from '@/components/chat/ThinkingBlock.vue'
import ToolCallBlock from '@/components/chat/ToolCallBlock.vue'
import MarkdownRenderer from '@/components/chat/MarkdownRenderer.vue'
import HITLPanel from '@/components/chat/HITLPanel.vue'
import ChartRenderer from '@/components/chat/ChartRenderer.vue'
import apiClient from '@/api/client'

const chatStore = useChatStore()
const inputMessage = ref('')
const messageListRef = ref()
const isDark = ref(true)
const agentName = ref('')

const currentAgentName = computed(() => {
  // Can be enhanced to fetch agent name based on ID
  return 'qwen3:30b' 
})

onMounted(async () => {
  if (document.documentElement.classList.contains('light')) {
    isDark.value = false
  }
})

watch(
  () => [chatStore.messages.length, chatStore.streamingContent],
  async () => {
    await nextTick()
    if (messageListRef.value) {
      const wrap = messageListRef.value.wrapRef
      wrap.scrollTop = wrap.scrollHeight
    }
  }
)

function toggleTheme() {
  isDark.value = !isDark.value
  const html = document.documentElement
  if (isDark.value) {
    html.classList.add('dark')
    html.classList.remove('light')
  } else {
    html.classList.add('light')
    html.classList.remove('dark')
  }
}

async function handleSend() {
  const msg = inputMessage.value.trim()
  if (!msg) return
  
  if (!chatStore.currentSessionId) {
    try {
      const title = msg.slice(0, 20) || '新对话'
      await chatStore.createSession(title)
    } catch (e) {
      console.error('Failed to create session automatically', e)
      return
    }
  }

  chatStore.sendMessage(msg)
  inputMessage.value = ''
}

function handleStop() {
  chatStore.stopStream()
}

function handleApprove() {
  chatStore.sendFeedback('approve')
}

function handleReject(message: string) {
  chatStore.sendFeedback('reject', message)
}
</script>

<style scoped>
.chat-view {
  height: 100%;
  display: flex;
  flex-direction: column;
  position: relative;
}

.top-right-controls {
  position: absolute;
  top: 16px;
  right: 16px;
  z-index: 100;
  display: flex;
  gap: 8px;
}

.theme-toggle-btn {
  width: 40px;
  height: 40px;
  background: var(--glass-bg);
  backdrop-filter: blur(8px);
  border: 1px solid var(--border-color);
  color: var(--text-secondary);
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.theme-toggle-btn:hover {
  background: var(--bg-tertiary);
  color: var(--text-primary);
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.theme-icon {
  font-size: 20px;
}

.chat-header {
  padding: 16px 24px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid var(--border-color);
  background: var(--glass-bg);
  z-index: 10;
}

.header-info h3 {
  font-size: 16px;
  margin: 0 0 4px 0;
  color: var(--text-primary);
}

/* Message List */
.message-list-container {
  flex: 1;
}

.message-list-inner {
  max-width: 900px;
  margin: 0 auto;
  padding: 24px;
}

.streaming-message {
  display: flex;
  gap: 16px;
  margin-bottom: 24px;
}

.ai-avatar {
  background: var(--accent-gradient);
  font-weight: 600;
  font-size: 14px;
  color: white;
}

.message-body {
  flex: 1;
  min-width: 0;
}

.content-wrapper {
  padding: 16px 24px;
  border-radius: 12px;
  border-top-left-radius: 2px;
}

.bottom-spacer {
  height: 160px;
}

/* Input Styles */
.input-container {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  padding: 24px;
  background: linear-gradient(to top, var(--bg-primary) 50%, transparent);
  transition: all 0.5s cubic-bezier(0.4, 0, 0.2, 1);
  display: flex;
  flex-direction: column;
  align-items: center;
}

.input-box {
  width: 100%;
  max-width: 900px;
  border-radius: 24px;
  padding: 16px;
  position: relative;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
  background: var(--glass-bg);
  border: 1px solid var(--border-color);
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.input-box:focus-within {
  border-color: var(--accent-primary);
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.2), 0 8px 40px rgba(0, 0, 0, 0.2);
  transform: translateY(-2px);
}

/* Centered Input State */
.input-container.centered-input {
  top: 0;
  bottom: 0;
  background: transparent;
  justify-content: center;
  padding-bottom: 20vh;
}

.welcome-section {
  text-align: center;
  margin-bottom: 40px;
  animation: fadeIn 0.8s ease-out;
}

.logo-box {
  width: 80px;
  height: 80px;
  border-radius: 20px;
  background: linear-gradient(135deg, #2e2a5e 0%, #1e1b4b 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 24px;
  font-size: 40px;
  color: var(--accent-primary);
  box-shadow: 0 10px 20px rgba(0, 0, 0, 0.3);
}

.welcome-title {
  font-size: 32px;
  font-weight: 700;
  background: linear-gradient(to right, var(--text-primary), var(--text-secondary));
  background-clip: text;
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.stop-btn-wrapper {
  position: absolute;
  top: -46px;
  left: 50%;
  transform: translateX(-50%);
}

.custom-textarea :deep(.el-textarea__inner) {
  border: none;
  background: transparent !important;
  padding: 8px 12px;
  font-size: 16px;
  line-height: 1.6;
}

.custom-textarea :deep(.el-textarea__inner:focus) {
  box-shadow: none;
}

.input-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px 4px;
  margin-top: 4px;
}

.tools-btn {
  display: flex;
  gap: 8px;
}

.send-btn {
  width: 36px;
  height: 36px;
  min-width: 36px;
  padding: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  background: var(--accent-gradient);
  border: none;
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
}

.send-btn:hover {
  transform: scale(1.05);
  box-shadow: 0 6px 16px rgba(99, 102, 241, 0.4);
}

.send-btn:active {
  transform: scale(0.95);
}

.send-btn.is-disabled {
  background: var(--btn-disabled-bg) !important;
  color: var(--btn-disabled-color) !important;
  box-shadow: none;
  cursor: not-allowed;
}

.footer-text {
  text-align: center;
  font-size: 12px;
  color: var(--text-tertiary);
  margin-top: 16px;
  opacity: 0.8;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(20px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
