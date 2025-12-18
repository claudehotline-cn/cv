<script setup lang="ts">
import { ref, nextTick, onMounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { ChatLineRound, User, Service, Position } from '@element-plus/icons-vue'
import MarkdownIt from 'markdown-it'
// @ts-ignore
import mdTexmath from 'markdown-it-texmath'
import Katex from 'katex'
import hljs from 'highlight.js'
import 'highlight.js/styles/atom-one-dark.css'
import { knowledgeBaseApi } from '../api'

const md = new MarkdownIt({
  html: false,
  linkify: true,
  typographer: true,
  highlight: function (str: string, lang: string) {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return hljs.highlight(str, { language: lang }).value
      } catch (__) {}
    }
    return '' // use external default escaping
  }
})

// Support both $...$ and \[...\] delimiters
md.use(mdTexmath, {
  engine: Katex,
  delimiters: 'dollars',
  katexOptions: { macros: { "\\RR": "\\mathbb{R}" } }
})
md.use(mdTexmath, {
  engine: Katex,
  delimiters: 'brackets',
  katexOptions: { macros: { "\\RR": "\\mathbb{R}" } }
})

const renderMarkdown = (content: string) => {
  if (!content) return ''
  return md.render(content)
}

interface Message {
  id: number
  role: 'user' | 'assistant'
  content: string
  sources?: any[]
  loading?: boolean
}

interface KnowledgeBase {
  id: number
  name: string
}

const query = ref('')
const messages = ref<Message[]>([
  {
    id: 1,
    role: 'assistant',
    content: '你好！我是你的智能知识库助手。请选择一个知识库，然后问我任何关于文档的问题。'
  }
])
const loading = ref(false)
const selectedKb = ref<number | undefined>(undefined)
const knowledgeBases = ref<KnowledgeBase[]>([])
const chatContainer = ref<HTMLElement | null>(null)

// 会话ID - 用于对话历史
const sessionId = ref<string>(localStorage.getItem('chat_session_id') || generateSessionId())

function generateSessionId(): string {
  const id = `session_${Date.now()}_${Math.random().toString(36).slice(2, 11)}`
  localStorage.setItem('chat_session_id', id)
  return id
}

// 加载知识库列表
onMounted(async () => {
  try {
    const res = await knowledgeBaseApi.list()
    knowledgeBases.value = res.data.items
    if (knowledgeBases.value && knowledgeBases.value.length > 0) {
      selectedKb.value = knowledgeBases.value[0]?.id
    }
  } catch (err) {
    console.error('Failed to load knowledge bases', err)
  }
})

// 自动滚动到底部
const scrollToBottom = () => {
  nextTick(() => {
    if (chatContainer.value) {
      chatContainer.value.scrollTop = chatContainer.value.scrollHeight
    }
  })
}

watch(messages, scrollToBottom, { deep: true })

const handleSend = async () => {
  if (!query.value.trim() || !selectedKb.value || loading.value) return

  const userQuery = query.value
  query.value = ''
  
  // 添加用户消息
  messages.value.push({
    id: Date.now(),
    role: 'user',
    content: userQuery
  })

  // 添加AI加载消息
  const aiMsgId = Date.now() + 1
  messages.value.push({
    id: aiMsgId,
    role: 'assistant',
    content: '',
    sources: [],
    loading: true
  })

  loading.value = true

  try {
    // 使用流式API
    const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:18200/api'
    const response = await fetch(`${apiUrl}/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        query: userQuery,
        knowledge_base_id: selectedKb.value,
        top_k: 5,
        session_id: sessionId.value,
      }),
    })

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`)
    }

    const reader = response.body?.getReader()
    if (!reader) {
      throw new Error('No reader available')
    }

    const decoder = new TextDecoder()
    let buffer = ''
    let firstToken = true  // 标记是否是第一个token

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      
      // 处理SSE格式的数据
      const lines = buffer.split('\n\n')
      buffer = lines.pop() || '' // 保留不完整的部分

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6))
            
            if (data.type === 'sources') {
              // 更新来源信息
              const idx = messages.value.findIndex(m => m.id === aiMsgId)
              if (idx !== -1) {
                messages.value[idx]!.sources = data.sources
              }
            } else if (data.type === 'token') {
              // 追加token到内容
              const idx = messages.value.findIndex(m => m.id === aiMsgId)
              if (idx !== -1) {
                // 第一个token到达时取消loading动画
                if (firstToken) {
                  messages.value[idx]!.loading = false
                  firstToken = false
                }
                messages.value[idx]!.content += data.content
              }
              scrollToBottom()
            } else if (data.type === 'error') {
              ElMessage.error(data.message)
            }
          } catch (e) {
            console.error('Failed to parse SSE data:', e)
          }
        }
      }
    }
  } catch (err: any) {
    console.error('Streaming error:', err)
    const aiMsgIndex = messages.value.findIndex(m => m.id === aiMsgId)
    if (aiMsgIndex !== -1) {
      messages.value[aiMsgIndex] = {
        id: aiMsgId,
        role: 'assistant',
        content: '抱歉，遇到了一些问题，请稍后再试。',
        loading: false
      }
    }
    ElMessage.error('发送失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="chat-page">
    <!-- 顶部工具栏 -->
    <div class="chat-header">
      <div class="header-left">
        <el-icon class="header-icon"><ChatLineRound /></el-icon>
        <span class="header-title">智能问答</span>
      </div>
      <div class="header-right">
        <el-select 
          v-model="selectedKb" 
          placeholder="选择知识库" 
          class="kb-select"
          effect="dark"
        >
          <el-option
            v-for="kb in knowledgeBases"
            :key="kb.id"
            :label="kb.name"
            :value="kb.id"
          />
        </el-select>
      </div>
    </div>

    <!-- 聊天区域 -->
    <div class="chat-container" ref="chatContainer">
      <div class="messages-list">
        <div 
          v-for="msg in messages" 
          :key="msg.id" 
          class="message-wrapper"
          :class="{ 'user-msg': msg.role === 'user', 'ai-msg': msg.role === 'assistant' }"
        >
          <div class="avatar">
            <el-icon v-if="msg.role === 'user'"><User /></el-icon>
            <el-icon v-else><Service /></el-icon>
          </div>
          
          <div class="message-content">
            <div class="bubble">
              <div v-if="msg.loading" class="typing-indicator">
                <span></span><span></span><span></span>
              </div>
              <div v-else class="markdown-body" v-html="renderMarkdown(msg.content)"></div>
            </div>
            
            <!-- 来源引用 -->
            <div v-if="msg.sources && msg.sources.length > 0" class="sources-panel">
              <div class="sources-title">参考来源:</div>
              <div v-for="(source, idx) in msg.sources" :key="idx" class="source-item">
                <span class="source-index">{{ idx + 1 }}</span>
                <span class="source-text">{{ source.content_preview }}</span>
                <span class="source-score">Wait: {{ (source.score * 100).toFixed(1) }}%</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 输入区域 -->
    <div class="input-area">
      <div class="input-wrapper">
        <el-input
          v-model="query"
          type="textarea"
          :rows="1"
          autosize
          placeholder="请输入您的问题..."
          resize="none"
          @keydown.enter.prevent="handleSend"
          class="custom-input"
        />
        <el-button 
          type="primary" 
          circle 
          @click="handleSend"
          :loading="loading"
          class="send-btn"
        >
          <el-icon v-if="!loading"><Position /></el-icon>
        </el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-page {
  height: calc(100vh - 48px); /* 减去外层padding */
  display: flex;
  flex-direction: column;
  background: #181825;
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
  border: 1px solid #313244;
}

.chat-header {
  height: 60px;
  padding: 0 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: rgba(30, 30, 46, 0.95);
  backdrop-filter: blur(10px);
  border-bottom: 1px solid #313244;
  z-index: 10;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
  color: #cdd6f4;
}

.header-icon {
  font-size: 24px;
  color: #89b4fa;
}

.header-title {
  font-size: 18px;
  font-weight: 600;
}

.kb-select {
  width: 200px;
}

.chat-container {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  scroll-behavior: smooth;
  background-image: radial-gradient(circle at 50% 50%, rgba(137, 180, 250, 0.05) 0%, transparent 50%);
}

.messages-list {
  max-width: 800px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.message-wrapper {
  display: flex;
  gap: 16px;
  align-items: flex-start;
}

.user-msg {
  flex-direction: row-reverse;
}

.avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  background: #313244;
  color: #cdd6f4;
  font-size: 20px;
}

.ai-msg .avatar {
  background: linear-gradient(135deg, #89b4fa 0%, #cba6f7 100%);
  color: #1e1e2e;
}

.user-msg .avatar {
  background: linear-gradient(135deg, #f5e0dc 0%, #f2cdcd 100%);
  color: #1e1e2e;
}

.message-content {
  max-width: 80%;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.user-msg .message-content {
  align-items: flex-end;
}

.bubble {
  padding: 12px 16px;
  border-radius: 12px;
  line-height: 1.6;
  font-size: 15px;
  position: relative;
  word-wrap: break-word;
}

.ai-msg .bubble {
  background: #313244;
  color: #cdd6f4;
  border-top-left-radius: 2px;
}

.user-msg .bubble {
  background: #89b4fa;
  color: #1e1e2e;
  border-top-right-radius: 2px;
  font-weight: 500;
}

.sources-panel {
  background: rgba(49, 50, 68, 0.5);
  border-radius: 8px;
  padding: 12px;
  margin-top: 4px;
  border: 1px solid #45475a;
  font-size: 13px;
}

.sources-title {
  color: #a6adc8;
  margin-bottom: 8px;
  font-weight: 600;
}

.source-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 6px;
  padding: 4px;
  border-radius: 4px;
  color: #bac2de;
}

.source-item:last-child {
  margin-bottom: 0;
}

.source-index {
  background: #45475a;
  color: #cdd6f4;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  flex-shrink: 0;
  margin-top: 2px;
}

.source-text {
  flex: 1;
  opacity: 0.9;
}

.source-score {
  font-size: 10px;
  color: #f38ba8;
  white-space: nowrap;
}

.input-area {
  padding: 24px;
  background: #181825;
  border-top: 1px solid #313244;
}

.input-wrapper {
  max-width: 800px;
  margin: 0 auto;
  position: relative;
  background: #313244;
  border-radius: 24px;
  padding: 6px;
  display: flex;
  align-items: flex-end;
  border: 1px solid transparent;
  transition: all 0.3s ease;
}

.input-wrapper:focus-within {
  border-color: #89b4fa;
  box-shadow: 0 0 0 2px rgba(137, 180, 250, 0.2);
}

.custom-input :deep(.el-textarea__inner) {
  background: transparent;
  box-shadow: none;
  border: none;
  color: #cdd6f4;
  padding: 12px 16px;
  min-height: 44px !important;
  font-size: 15px;
}

.custom-input :deep(.el-textarea__inner::placeholder) {
  color: #6c7086;
}

.send-btn {
  margin: 4px;
  flex-shrink: 0;
  width: 36px;
  height: 36px;
}

/* 打字动画 */
.typing-indicator {
  display: flex;
  gap: 4px;
  padding: 4px 0;
}

.typing-indicator span {
  width: 6px;
  height: 6px;
  background: #89b4fa;
  border-radius: 50%;
  animation: bounce 1.4s infinite ease-in-out both;
}

.typing-indicator span:nth-child(1) { animation-delay: -0.32s; }
.typing-indicator span:nth-child(2) { animation-delay: -0.16s; }

@keyframes bounce {
  0%, 80%, 100% { transform: scale(0); }
  40% { transform: scale(1); }
}

/* Markdown Styles Override for darker theme match */
.markdown-body {
  box-sizing: border-box;
  min-width: 200px;
  max-width: 980px;
  margin: 0 auto;
  padding: 15px;
  background-color: transparent !important;
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif !important;
}

/* Force text color in markdown body */
.markdown-body {
  color: #cdd6f4 !important;
}

.markdown-body pre {
  background-color: #1e1e2e !important;
  border: 1px solid rgba(255, 255, 255, 0.1);
}

/* KaTeX Adjustments */
.markdown-body :deep(.katex-display) {
  overflow-x: auto;
  overflow-y: hidden;
  padding: 8px 0;
  margin: 1em 0;
}

.markdown-body :deep(.katex) {
  font-size: 1.1em;
  color: #cdd6f4;
}
</style>
