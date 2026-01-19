<template>
  <div class="chat-layout">
    <!-- Center Panel: Chat -->
    <main class="chat-main">
      <!-- Chat Header -->
      <header class="chat-header">
        <div class="header-left">
          <div class="agent-icon-square">
            <el-icon><DataAnalysis /></el-icon>
          </div>
          <div>
            <h2 class="header-title">Data Analyst Agent</h2>
            <div class="header-subtitle">
              <span class="status-dot">
                <span class="animate-ping"></span>
                <span class="dot-inner"></span>
              </span>
              <span>Online • Model v4.0</span>
            </div>
          </div>
        </div>
        
        <div class="header-right">
           <div class="jobs-pill">
              <div class="loading-bars">
                 <span></span><span></span><span></span>
              </div>
              <span class="pill-text">2 Jobs Running</span>
           </div>
           
           <button class="icon-btn" @click="toggleTheme" title="Toggle Theme">
              <el-icon v-if="isDark"><Moon /></el-icon>
              <el-icon v-else><Sunny /></el-icon>
           </button>
           
           <button class="icon-btn">
              <el-icon><Search /></el-icon>
           </button>
           <button class="icon-btn lg-hidden" @click="toggleRightSidebar">
              <el-icon><info-filled /></el-icon>
           </button>
        </div>
      </header>
      
      <!-- Messages Area -->
      <div class="messages-container" ref="scrollContainer">
         <div class="messages-content">
            <!-- Date Divider -->
            <div class="date-divider">
               <span>Today, 2:30 PM</span>
            </div>
            
            <MessageItem
              v-for="msg in chatStore.messages"
              :key="msg.id"
              :message="msg"
            />
            
            <!-- Streaming Message -->
            <div v-if="chatStore.isStreaming" class="message assistant streaming-message">
              <div class="avatar-container">
                <div class="ai-avatar-square">
                   <el-icon><DataAnalysis /></el-icon>
                </div>
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
                <div class="content-wrapper">
                  <MarkdownRenderer :content="chatStore.streamingContent || 'Thinking...'" />
                </div>
              </div>
            </div>
            
            <!-- Bottom Spacer for Floating Input -->
            <div class="bottom-spacer"></div>
         </div>
      </div>
      
      <!-- Floating Input Area -->
      <div class="input-layer">
         <div class="input-wrapper">
            <div class="input-box">
               <button class="attach-btn">
                  <el-icon><CirclePlusFilled /></el-icon>
               </button>
               
               <textarea
                  v-model="inputMessage"
                  class="chat-input"
                  placeholder="Message Data Analyst..."
                  rows="1"
                  @keydown.enter.exact.prevent="handleSend"
                  @input="autoResize"
                  ref="textareaRef"
               ></textarea>
               
               <button 
                  class="send-btn" 
                  :disabled="!inputMessage.trim() || chatStore.isStreaming"
                  @click="handleSend"
               >
                  <el-icon v-if="!chatStore.isStreaming"><Top /></el-icon>
                  <el-icon v-else class="is-loading"><Loading /></el-icon>
               </button>
            </div>
         </div>
      </div>
    </main>

    <!-- Right Sidebar (Desktop) -->
    <AgentRightSidebar class="hidden-mobile" />
    
    <!-- Right Drawer (Mobile) -->
    <el-drawer
      v-model="showRightDrawer"
      size="320px"
      :with-header="false"
      direction="rtl"
    >
       <AgentRightSidebar />
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, nextTick, watch } from 'vue'
import { 
  DataAnalysis, Search, InfoFilled, 
  CirclePlusFilled, Top, Loading,
  Moon, Sunny
} from '@element-plus/icons-vue'
import { useChatStore } from '@/stores/chat'
import MessageItem from '@/components/chat/MessageItem.vue'
import ThinkingBlock from '@/components/chat/ThinkingBlock.vue'
import ToolCallBlock from '@/components/chat/ToolCallBlock.vue'
import MarkdownRenderer from '@/components/chat/MarkdownRenderer.vue'
import AgentRightSidebar from '@/components/chat/AgentRightSidebar.vue'

const chatStore = useChatStore()
const inputMessage = ref('')
const scrollContainer = ref<HTMLElement>()
const textareaRef = ref<HTMLTextAreaElement>()
const showRightDrawer = ref(false)
const isDark = ref(true)

// Auto resize textarea
function autoResize() {
   const el = textareaRef.value
   if (el) {
      el.style.height = 'auto'
      el.style.height = el.scrollHeight + 'px'
   }
}

function scrollToBottom() {
   nextTick(() => {
     if (scrollContainer.value) {
       scrollContainer.value.scrollTop = scrollContainer.value.scrollHeight
     }
   })
}

function toggleRightSidebar() {
   showRightDrawer.value = !showRightDrawer.value
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

async function handleSend() {
  const msg = inputMessage.value.trim()
  if (!msg || chatStore.isStreaming) return
  
  if (!chatStore.currentSessionId) {
     await chatStore.createSession(msg.slice(0, 20))
  }
  
  chatStore.sendMessage(msg)
  inputMessage.value = ''
  if (textareaRef.value) textareaRef.value.style.height = 'auto'
}

watch(
  () => [chatStore.messages.length, chatStore.streamingContent],
  scrollToBottom
)

onMounted(() => {
   if (document.documentElement.classList.contains('light')) {
      isDark.value = false
   }
   scrollToBottom()
})
</script>

<style scoped>
.chat-layout {
  display: flex;
  height: 100vh;
  width: 100%;
  background: var(--bg-primary); /* background-light */
}

.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  position: relative;
  min-width: 0;
}

/* Header */
.chat-header {
  height: 64px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 24px;
  border-bottom: 1px solid var(--border-color);
  background: rgba(255, 255, 255, 0.5);
  backdrop-filter: blur(12px);
  position: sticky;
  top: 0;
  z-index: 20;
}

/* Dark mode header background fix */
:deep(.dark) .chat-header {
    background: rgba(34, 38, 42, 0.5);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.agent-icon-square {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-size: 20px;
}

.header-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0;
  line-height: 1.2;
}

.header-subtitle {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 500;
  color: var(--text-secondary); /* Text secondary */
}

/* Updated Status Dot styles */
.status-dot {
  position: relative;
  display: flex;
  height: 8px;
  width: 8px;
}

.status-dot .dot-inner {
  position: relative;
  display: inline-flex;
  border-radius: 9999px;
  height: 8px;
  width: 8px;
  background-color: #22c55e;
}

.status-dot .animate-ping {
  position: absolute;
  display: inline-flex;
  height: 100%;
  width: 100%;
  border-radius: 9999px;
  background-color: #4ade80;
  opacity: 0.75;
  animation: ping 1s cubic-bezier(0, 0, 0.2, 1) infinite;
}

@keyframes ping {
  75%, 100% {
    transform: scale(2);
    opacity: 0;
  }
}

.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.jobs-pill {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 12px;
  border-radius: 99px;
  background: #fdf2f8; /* amber-50 equivalent but generic */
  border: 1px solid #f9a8d4;
  color: #db2777; /* pink-600 */
}

/* Dark mode jobs pill override via variables */
.jobs-pill {
    background: rgba(245, 158, 11, 0.05); /* amber-500/5 */
    border: 1px solid rgba(245, 158, 11, 0.2);
    color: #b45309; /* amber-700 */
}

.loading-bars {
  display: flex;
  gap: 2px;
  height: 8px;
}

.loading-bars span {
  width: 2px;
  background: currentColor;
  border-radius: 2px;
  animation: barHeight 1s ease-in-out infinite;
}

.loading-bars span:nth-child(2) { animation-delay: 0.2s; }
.loading-bars span:nth-child(3) { animation-delay: 0.4s; }

@keyframes barHeight {
  0%, 100% { height: 100%; }
  50% { height: 50%; }
}

.pill-text {
  font-size: 12px;
  font-weight: 700;
}

.icon-btn {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: 20px;
  cursor: pointer;
  transition: all 0.2s;
}

.icon-btn:hover {
  background: var(--bg-tertiary);
  color: var(--accent-primary);
}

/* Messages Area */
.messages-container {
  flex: 1;
  overflow-y: auto;
  padding: 24px 16px;
  scroll-behavior: smooth;
}

.messages-content {
  max-width: 768px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.date-divider {
  display: flex;
  justify-content: center;
  margin-bottom: 24px;
}

.date-divider span {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-secondary);
  background: var(--bg-secondary);
  padding: 4px 12px;
  border-radius: 99px;
  border: 1px solid var(--border-color);
}

.bottom-spacer {
  height: 120px;
}

/* Streaming Message Styles (Partial Duplication of MessageItem logic for Stream) */
.streaming-message {
  display: flex;
  gap: 12px;
  width: 100%;
}

.avatar-container {
   flex-shrink: 0;
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
   margin-top: 4px;
   box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}

.message-body {
   display: flex;
   flex-direction: column;
   gap: 4px;
   min-width: 0; /* Text truncate fix */
   flex: 1;
   align-items: flex-start;
}

.content-wrapper {
   background: var(--bg-primary); /* white */
   border: 1px solid var(--border-color);
   padding: 16px 20px;
   border-radius: 16px;
   border-top-left-radius: 2px;
   color: var(--text-primary);
   box-shadow: 0 1px 2px rgba(0,0,0,0.05);
   max-width: 100%;
}

/* Input Styles */
.input-layer {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 10;
  padding: 24px 16px 40px; /* Reduced vertical padding */
  background: linear-gradient(to top, var(--bg-primary) 20%, transparent); /* Fade out */
  display: flex;
  justify-content: center;
  pointer-events: none; /* Allow clicking through upper transparent part */
}

.input-wrapper {
  width: 100%;
  max-width: 768px;
  pointer-events: auto; /* Re-enable pointer events for input */
}

.input-box {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  background: var(--bg-primary); /* white/dark */
  border: 1px solid var(--border-color);
  border-radius: 24px;
  padding: 8px;
  padding-left: 16px;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
  /* Ring focus equivalent */
  transition: all 0.2s;
}

.input-box:focus-within {
  border-color: rgba(99, 102, 241, 0.5);
  box-shadow: 0 0 0 4px rgba(99, 102, 241, 0.1);
}

.attach-btn {
  color: var(--text-secondary);
  background: transparent;
  border: none;
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  cursor: pointer;
  border-radius: 50%;
  transition: background 0.2s;
  flex-shrink: 0;
  margin-bottom: 2px; /* Alignment fix */
}

.attach-btn:hover {
  background: var(--bg-tertiary);
  color: var(--accent-primary);
}

.chat-input {
  flex: 1;
  background: transparent;
  border: none;
  font-family: inherit;
  font-size: 16px;
  padding: 10px 0;
  max-height: 200px;
  resize: none;
  color: var(--text-primary);
  min-height: 24px;
}

.chat-input:focus {
  outline: none;
}

.send-btn {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  border: none;
  background: var(--accent-primary);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  font-size: 20px;
  flex-shrink: 0;
  transition: all 0.2s;
  box-shadow: 0 4px 6px -1px rgba(99, 102, 241, 0.3);
  margin-bottom: 2px;
}

.send-btn:hover:not(:disabled) {
  background: #1a8599; /* dark accent */
  transform: translateY(-1px);
}

.send-btn:active:not(:disabled) {
  transform: scale(0.95);
}

.send-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  box-shadow: none;
}

.is-loading {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* Response for Mobile */
@media (max-width: 1280px) {
  .hidden-mobile {
    display: none;
  }
}

.lg-hidden {
   display: none;
}

@media (max-width: 1280px) {
  .lg-hidden {
    display: flex;
  }
}
</style>
