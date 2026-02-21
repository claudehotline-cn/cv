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
              <span class="pill-text">{{ chatStore.activeTasks.length }} Jobs Running</span>
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
      <div class="messages-container" ref="scrollContainer" @scroll="handleScroll">
         <div class="messages-content">
            <!-- Date Divider -->
            <div class="date-divider">
               <span>Today, 2:30 PM</span>
            </div>
            
            <template v-for="msg in chatStore.messages" :key="msg.id">
              <MessageItem
                v-if="isValidMessage(msg)"
                :message="msg"
              />
            </template>
            
            <!-- Streaming Message -->
            <div v-if="chatStore.isStreaming" class="message assistant streaming-message">
              <div class="avatar-container">
                <div class="ai-avatar-square">
                   <el-icon><DataAnalysis /></el-icon>
                </div>
              </div>
              <div class="message-body">
                <template v-for="(block, idx) in chatStore.streamingBlocks" :key="idx">
                   <!-- Thinking Block -->
                   <ThinkingBlock
                     v-if="block.type === 'thinking'"
                     :content="block.content || ''"
                     :subgraph-name="block.subgraph"
                     :isStreaming="true"
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
                     :call-id="block.callId || ''"
                     :output="block.output || ''"
                     :subgraph-name="block.subgraph"
                   />
                   
                   <!-- Content Block -->
                   <div v-else-if="block.type === 'content'" class="content-wrapper">
                      <MarkdownRenderer :content="block.content || ''" />
                   </div>
                   
                   <!-- Chart Block -->
                   <ChartRenderer 
                     v-else-if="block.type === 'chart'" 
                     :chartData="block.data" 
                   />
                   
                   <!-- Interrupt Block -->
                   <div v-else-if="block.type === 'interrupt'" class="interrupt-block">
                      <!-- TODO: Add Interrupt Component -->
                      <p>Waiting for user approval...</p>
                   </div>
                </template>
                
                <div v-if="chatStore.isLoading && chatStore.streamingBlocks.length === 0" class="content-wrapper">
                   Thinking...
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
               <el-button 
                  class="attach-btn" 
                  circle 
                  text
               >
                  <el-icon :size="24"><CirclePlusFilled /></el-icon>
               </el-button>
               
               <el-input
                  v-model="inputMessage"
                  type="textarea"
                  :autosize="{ minRows: 1, maxRows: 6 }"
                  placeholder="Message Data Analyst..."
                  class="chat-input-el"
                  resize="none"
                  @keydown.enter.exact.prevent="handleSend"
                  ref="textareaRef"
               />
               
               <el-button 
                  v-if="chatStore.isStreaming"
                  class="stop-btn" 
                  circle
                  type="danger"
                  @click="chatStore.stopStream"
               >
                  <el-icon><VideoPause /></el-icon>
               </el-button>

               <el-button 
                  v-else
                  class="async-toggle-btn"
                  :class="{ active: chatStore.asyncMode }"
                  circle
                  @click="chatStore.asyncMode = !chatStore.asyncMode"
                  title="Async Mode"
               >
                  <el-icon><Timer /></el-icon>
               </el-button>

               <el-button 
                  v-if="!chatStore.isStreaming && inputMessage.trim()"
                  class="send-btn" 
                  circle
                  type="primary"
                  :disabled="!inputMessage.trim()"
                  @click="handleSend"
               >
                  <el-icon><Top /></el-icon>
               </el-button>
            </div>
         </div>
      </div>
      <!-- Scroll to Bottom Button -->
      <transition name="fade">
        <button 
          v-show="userHasScrolledUp" 
          class="scroll-bottom-btn"
          @click="manualScrollToBottom"
        >
          <el-icon><ArrowDownBold /></el-icon>
        </button>
      </transition>

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
  CirclePlusFilled, Top, VideoPause,
  Moon, Sunny, ArrowDownBold, Timer
} from '@element-plus/icons-vue'
import { useChatStore } from '@/stores/chat'
import MessageItem from '@/components/chat/MessageItem.vue'
import ThinkingBlock from '@/components/chat/ThinkingBlock.vue'
import ToolCallBlock from '@/components/chat/ToolCallBlock.vue'
import ToolOutputBlock from '@/components/chat/ToolOutputBlock.vue'
import MarkdownRenderer from '@/components/chat/MarkdownRenderer.vue'
import ChartRenderer from '@/components/chat/ChartRenderer.vue'
import AgentRightSidebar from '@/components/chat/AgentRightSidebar.vue'

import { useTheme } from '@/composables/useTheme'

const { isDark, toggleTheme } = useTheme()
const chatStore = useChatStore()
const inputMessage = ref('')
const scrollContainer = ref<HTMLElement>()
const textareaRef = ref<any>()
const showRightDrawer = ref(false)


// 智能滚动：用户向上滚动时停止跟随，回到底部时恢复
const userHasScrolledUp = ref(false)

function scrollToBottom() {
   // 只有当用户没有向上滚动时才自动滚动
   if (userHasScrolledUp.value) return
   
   nextTick(() => {
     if (scrollContainer.value) {
       scrollContainer.value.scrollTop = scrollContainer.value.scrollHeight
     }
   })
}

function handleScroll() {
   const el = scrollContainer.value
   if (!el) return
   
   // 计算距离底部的距离
   const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
   
   // 如果距离底部小于 50px，认为用户回到了底部
   if (distanceFromBottom < 50) {
      userHasScrolledUp.value = false
   } else {
      userHasScrolledUp.value = true
   }
}

function manualScrollToBottom() {
   const el = scrollContainer.value
   if (!el) return
   
   el.scrollTo({
     top: el.scrollHeight,
     behavior: 'smooth'
   })
   userHasScrolledUp.value = false
}

function toggleRightSidebar() {
   showRightDrawer.value = !showRightDrawer.value
}

async function handleSend() {
  const msg = inputMessage.value.trim()
  if (!msg || chatStore.isStreaming) return
  
  if (!chatStore.currentSessionId) {
     await chatStore.createSession(msg.slice(0, 20))
  }
  
  // 发送消息时重置滚动状态，自动跟随新消息
  userHasScrolledUp.value = false
  
  await chatStore.sendMessage(msg)
  inputMessage.value = ''
  await nextTick()
  textareaRef.value?.focus?.()
}

watch(
  () => [chatStore.messages.length, chatStore.streamingBlocks],
  scrollToBottom,
  { deep: true }
)

onMounted(() => {
   scrollToBottom()
})

function isValidMessage(msg: any): boolean {
  if (!msg.blocks || msg.blocks.length === 0) return false
  
  // 检查是否包含有效内容
  return msg.blocks.some((block: any) => {
    if (block.type === 'content') {
      return block.content && block.content.trim().length > 0
    }
    // 其他类型的块 (thinking, tool_call, tool_output, chart) 都视为有效
    return true
  })
}
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

:deep(.chat-input-el .el-textarea__inner) {
  background: transparent;
  border: none;
  box-shadow: none;
  padding: 10px 0;
  min-height: 24px !important;
  color: var(--text-primary);
  font-family: inherit;
  font-size: 16px; 
  resize: none;
}
:deep(.chat-input-el .el-textarea__inner:focus) {
  box-shadow: none;
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

.stop-btn {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  border: none;
  background: #ef4444;
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  font-size: 20px;
  flex-shrink: 0;
  transition: all 0.2s;
  box-shadow: 0 4px 6px -1px rgba(239, 68, 68, 0.3);
  margin-bottom: 2px;
}

.stop-btn:hover {
  background: #dc2626;
  transform: translateY(-1px);
}

.stop-btn:active {
  transform: scale(0.95);
}

.async-toggle-btn {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  border: 1px solid var(--border-color);
  background: var(--bg-primary);
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  font-size: 20px;
  flex-shrink: 0;
  transition: all 0.2s;
  margin-bottom: 2px;
}

.async-toggle-btn.active {
  background: #f0fdf4; /* green-50 */
  color: #16a34a; /* green-600 */
  border-color: #86efac;
}

.async-toggle-btn:hover {
  background: var(--bg-tertiary);
  transform: translateY(-1px);
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

/* Scroll to Bottom Button */
.scroll-bottom-btn {
  position: absolute;
  bottom: 8rem; /* Closer to input area (was 15rem) */
  left: 50%;
  transform: translateX(-50%);
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  z-index: 15;
  transition: all 0.2s;
}

.scroll-bottom-btn:hover {
  background: var(--bg-tertiary);
  color: var(--accent-primary);
  transform: translateX(-50%) translateY(-2px);
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.15);
}

/* Fade Transition */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease, transform 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(10px);
}
</style>
