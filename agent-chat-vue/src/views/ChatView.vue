<template>
  <el-container class="chat-layout">
    <!-- Glass Sidebar -->
    <el-aside width="300px" class="sidebar glass-panel">
      <div class="sidebar-header">
        <h2 class="brand-title">
          <span class="gradient-text">Agent Chat</span>
        </h2>
        <el-button type="primary" circle :icon="Plus" @click="handleNewChat" class="new-chat-btn" />
      </div>
      
      <el-scrollbar class="session-list">
        <div v-if="chatStore.isLoading" class="loading-state">
          <el-skeleton animated :rows="3" />
        </div>
        
        <div
          v-else
          v-for="session in chatStore.sessions"
          :key="session.id"
          class="session-item"
          :class="{ active: session.id === chatStore.currentSessionId }"
          @click="handleSelectSession(session.id)"
        >
          <div class="session-icon">
            <el-icon><ChatDotRound /></el-icon>
          </div>
          <div class="session-info">
            <span class="session-title">{{ session.title }}</span>
            <span class="session-date">{{ formatDate(session.updatedAt) }}</span>
          </div>
          <el-button
            class="delete-btn"
            type="danger"
            text
            circle
            :icon="Delete"
            @click.stop="handleDeleteSession(session.id)"
          />
        </div>
      </el-scrollbar>
      
      <div class="sidebar-footer">
        <div class="user-profile">
          <el-avatar :size="32" src="https://cube.elemecdn.com/0/88/03b0d39583f48206768a7534e55bcpng.png" />
          <span class="username">管理员</span>
        </div>
        
        <!-- Theme Toggle -->
        <el-button circle text @click="toggleTheme" class="theme-btn">
          <el-icon v-if="isDark"><Moon /></el-icon>
          <el-icon v-else><Sunny /></el-icon>
        </el-button>
      </div>
    </el-aside>

    <!-- Main Chat Area -->
    <el-main class="chat-main">
      <!-- Chat Header (Only show if session active or chatting) -->
      <div v-if="chatStore.currentSessionId" class="chat-header glass-panel">
        <div class="header-info">
          <h3>{{ chatStore.currentSession?.title || '新对话' }}</h3>
          <el-tag size="small" type="success" effect="dark" round>qwen3:30b</el-tag>
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
    </el-main>
  </el-container>
</template>

<script setup lang="ts">
import { ref, onMounted, nextTick, watch } from 'vue'
import { 
  Plus, Delete, ChatDotRound, Cpu, Position, 
  VideoPause, Moon, Sunny,
  Picture, Document, MagicStick
} from '@element-plus/icons-vue'
import { useChatStore } from '@/stores/chat'
import MessageItem from '@/components/chat/MessageItem.vue'
import ThinkingBlock from '@/components/chat/ThinkingBlock.vue'
import MarkdownRenderer from '@/components/chat/MarkdownRenderer.vue'
import HITLPanel from '@/components/chat/HITLPanel.vue'
import ChartRenderer from '@/components/chat/ChartRenderer.vue'
import dayjs from 'dayjs'

const chatStore = useChatStore()
const inputMessage = ref('')
const messageListRef = ref()
const isDark = ref(true)

onMounted(async () => {
  await chatStore.loadSessions()
  // Init theme
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

function formatDate(date: Date | string) {
  return dayjs(date).format('MMM D, HH:mm')
}

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

// ... existing handlers ...
async function handleNewChat() {
  await chatStore.createSession()
}

async function handleSelectSession(sessionId: string) {
  await chatStore.selectSession(sessionId)
}

async function handleDeleteSession(sessionId: string) {
  await chatStore.deleteSession(sessionId)
}

async function handleSend() {
  const msg = inputMessage.value.trim()
  if (!msg) return
  
  // Auto-create session if none exists
  if (!chatStore.currentSessionId) {
    try {
      // Use first 20 chars as title, or "New Chat"
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
.chat-layout {
  height: 100vh;
  width: 100vw;
}

/* Sidebar Styling */
.sidebar {
  border-right: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  background: var(--glass-bg);
  backdrop-filter: blur(12px);
}

.sidebar-header {
  padding: 24px 20px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.brand-title {
  font-size: 20px;
  font-weight: 700;
  margin: 0;
  letter-spacing: -0.5px;
}

.session-list {
  flex: 1;
  padding: 0 12px;
}

.session-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  margin-bottom: 4px;
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.2s ease;
  color: var(--text-secondary);
}

.session-item:hover {
  background: var(--el-fill-color-light);
  color: var(--text-primary);
}

.session-item.active {
  background: var(--active-bg, rgba(99, 102, 241, 0.1));
  color: var(--accent-primary);
  border: 1px solid rgba(99, 102, 241, 0.2);
}

.session-info {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.session-title {
  font-size: 14px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.session-date {
  font-size: 11px;
  color: var(--text-tertiary);
}

.sidebar-footer {
  padding: 20px;
  border-top: 1px solid var(--border-color);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.user-profile {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.2s;
}

.user-profile:hover {
  background: var(--el-fill-color-light);
}

.username {
  font-size: 14px;
  font-weight: 500;
}

.theme-btn {
  color: var(--text-secondary);
  transition: color 0.2s;
}

.theme-btn:hover {
  color: var(--text-primary);
}

/* Main Chat Styling */
.chat-main {
  padding: 0;
  display: flex;
  flex-direction: column;
  position: relative;
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
  /* padding-bottom will be handled by bottom-spacer */
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
  height: 160px; /* Space for input */
}

/* Input Area - Shared Styles */
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
  top: 0; /* Cover full height */
  bottom: 0;
  background: transparent; /* Remove gradient */
  justify-content: center;
  padding-bottom: 20vh; /* Visual balance */
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

/* Input Styles */
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
