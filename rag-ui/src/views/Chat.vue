<script setup lang="ts">
import { ref, nextTick, onMounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { ChatLineRound, User, Service, Position, Picture, Loading, Close, DataAnalysis } from '@element-plus/icons-vue'

import MarkdownIt from 'markdown-it'
// @ts-ignore
import mdTexmath from 'markdown-it-texmath'
import Katex from 'katex'
import hljs from 'highlight.js'
import 'highlight.js/styles/atom-one-dark.css'
import { knowledgeBaseApi, chatApi, multimodalApi } from '../api'

const fileInput = ref<HTMLInputElement | null>(null)
const selectedImages = ref<{ file: File, url: string, description?: string }[]>([])
const isUploading = ref(false)
const isChartMode = ref(false)
const chartAnalysisResult = ref<{ json: any, analysis: string, conclusion: string } | null>(null)
const MAX_IMAGES = 5  // 最多支持5张图片


const triggerFileUpload = () => {
  fileInput.value?.click()
}

const handleFileSelect = async (event: Event) => {
  const target = event.target as HTMLInputElement
  const files = target.files
  if (!files || files.length === 0) return

  // 检查是否超过数量限制
  if (selectedImages.value.length + files.length > MAX_IMAGES) {
    ElMessage.warning(`最多支持上传 ${MAX_IMAGES} 张图片`)
    return
  }

  isUploading.value = true
  
  try {
    for (const file of Array.from(files)) {
      // 类型检查
      if (!file.type.startsWith('image/')) {
        ElMessage.warning(`${file.name} 不是图片文件，已跳过`)
        continue
      }

      const imageUrl = URL.createObjectURL(file)
      const newImage = { file, url: imageUrl }
      selectedImages.value.push(newImage)
      
      // 上传并获取描述
      try {
        const res = await multimodalApi.uploadImage(file)
        const idx = selectedImages.value.findIndex(img => img.url === imageUrl)
        if (idx !== -1) {
          selectedImages.value[idx]!.description = res.data.description
        }
      } catch (err) {
        console.error(`Upload ${file.name} failed`, err)
        // 单张失败不影响其他图片
      }
    }
    ElMessage.success('图片解析完成')
  } finally {
    isUploading.value = false
    if (target) target.value = ''
  }
}

const handleChartAnalysis = async () => {
  if (selectedImages.value.length === 0) return 
  
  // 使用第一张图片进行图表分析
  const chartImage = selectedImages.value[0]!
  
  loading.value = true
  chartAnalysisResult.value = null
  
  // 添加用户消息
  messages.value.push({
    id: Date.now(),
    role: 'user',
    content: `![Chart](${chartImage.url})\n\n请分析这张图表`
  })
  
  // 添加AI加载消息
  const aiMsgId = Date.now() + 1
  messages.value.push({
    id: aiMsgId,
    role: 'assistant',
    content: '正在进行深度图表分析...',
    loading: true
  })

  try {
    const res = await multimodalApi.analyzeChart(chartImage.file)
    const result = res.data
    
    // 解析结果
    let jsonContent = result.json_data || {}
    let analysisText = ""
    
    if (result.raw_response) {
       // 尝试从原始响应中提取分析和结论
       // 假设 raw_response 是 JSON 字符串包含 analysis 和 conclusion 字段
       try {
         const parsed = JSON.parse(result.raw_response)
         if (parsed.analysis) analysisText += `### 趋势分析\n\n${parsed.analysis}\n\n`
         if (parsed.conclusion) analysisText += `### 结论\n\n${parsed.conclusion}`
         if (parsed.data) jsonContent = parsed.data
       } catch (e) {
         // 如果不是标准 JSON结构，直接显示原始文本
         analysisText = result.raw_response
       }
    }
    
    const idx = messages.value.findIndex(m => m.id === aiMsgId)
    if (idx !== -1) {
      messages.value[idx]!.loading = false
      
      // 构建显示内容
      let content = analysisText
      if (Object.keys(jsonContent).length > 0) {
        content += `\n\n### 提取数据\n\n\`\`\`json\n${JSON.stringify(jsonContent, null, 2)}\n\`\`\``
      }
      messages.value[idx]!.content = content
    }
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || '分析失败')
    const idx = messages.value.findIndex(m => m.id === aiMsgId)
    if (idx !== -1) messages.value[idx]!.content = '图表分析失败，请重试。'
  } finally {
    loading.value = false
    clearSelectedImage()  // 清除所有图片
    scrollToBottom()
  }
}


const clearSelectedImage = (index?: number) => {
  if (index !== undefined) {
    // 清除指定图片
    const img = selectedImages.value[index]
    if (img) {
      URL.revokeObjectURL(img.url)
      selectedImages.value.splice(index, 1)
    }
  } else {
    // 清除所有图片
    selectedImages.value.forEach(img => URL.revokeObjectURL(img.url))
    selectedImages.value = []
  }
}

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
  evaluation?: {
    faithfulness?: number
    answer_relevance?: number
    loading: boolean
    evaluated: boolean
  }
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
  if ((!query.value.trim() && selectedImages.value.length === 0) || loading.value) return

  const userQuery = query.value
  const currentImages = [...selectedImages.value]  // 复制当前图片列表
  
  // 重置状态
  query.value = ''
  clearSelectedImage()  // 清除所有图片

  // 构建用户消息内容
  let displayContent = userQuery
  if (currentImages.length > 0) {
    const imageMarkdown = currentImages.map(img => `![Uploaded Image](${img.url})`).join('\n')
    displayContent = `${imageMarkdown}\n\n${userQuery}`
  }
  
  // 添加用户消息
  messages.value.push({
    id: Date.now(),
    role: 'user',
    content: displayContent
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
    // 判断是普通对话还是多模态对话
    if (currentImages.length > 0 && currentImages[0]!.description) {
      // 多模态查询 (非流式) - 使用第一张图片的描述
      const descriptions = currentImages.map(img => img.description || '').join('\n')
      const res = await multimodalApi.multimodalQuery(userQuery || '描述这些图片', descriptions)
      
      const idx = messages.value.findIndex(m => m.id === aiMsgId)
      if (idx !== -1) {
        messages.value[idx]!.loading = false
        messages.value[idx]!.content = res.data.answer
        if (res.data.sources) {
           messages.value[idx]!.sources = res.data.sources
        }
      }
    } else {
      // 原有的流式文本对话
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
    }
  } catch (err: any) {
    console.error('Request error:', err)
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

const handleEvaluate = async (msg: Message, index: number) => {
  const prevMsg = messages.value[index - 1]
  if (index === 0 || !prevMsg || msg.role !== 'assistant') return

  // 获取对应的问题
  const question = prevMsg.content
  const answer = msg.content
  const contexts = msg.sources?.map((s: any) => s.content) || []

  // 初始化评估状态
  msg.evaluation = {
    loading: true,
    evaluated: false
  }

  try {
    const res = await chatApi.evaluate(question, answer, contexts)
    msg.evaluation = {
      faithfulness: res.data.faithfulness,
      answer_relevance: res.data.answer_relevance,
      loading: false,
      evaluated: true
    }
    ElMessage.success('评估完成')
  } catch (e) {
    console.error('Evaluation failed', e)
    ElMessage.error('评估失败')
    msg.evaluation = undefined
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
        <el-switch
          v-model="isChartMode"
          active-text="图表深度分析"
          inactive-text="普通对话"
          style="margin-right: 16px"
          v-if="selectedImages.length === 0"
        />
        <el-select 
          v-if="!isChartMode"
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

            <!-- 评估反馈 -->
            <div v-if="msg.role === 'assistant' && !msg.loading && msg.content" class="evaluation-panel">
              <!-- 已评估显示结果 -->
              <div v-if="msg.evaluation?.evaluated" class="evaluation-result">
                <span>📊 质量评估: </span>
                <el-tag size="small" :type="msg.evaluation!.faithfulness! > 0.7 ? 'success' : 'warning'">
                  Faithfulness {{ msg.evaluation!.faithfulness?.toFixed(2) }}
                </el-tag>
                <el-tag size="small" :type="msg.evaluation!.answer_relevance! > 0.7 ? 'success' : 'warning'" style="margin-left: 5px">
                  Relevance {{ msg.evaluation!.answer_relevance?.toFixed(2) }}
                </el-tag>
              </div>

              <!-- 未评估显示按钮 -->
              <div v-else class="evaluation-actions">
                <el-button 
                  size="small" 
                  @click="handleEvaluate(msg, messages.indexOf(msg))"
                  :loading="msg.evaluation?.loading"
                >
                  👍 有帮助
                </el-button>
                <el-button 
                  size="small" 
                  @click="handleEvaluate(msg, messages.indexOf(msg))"
                  :loading="msg.evaluation?.loading"
                >
                  👎 需改进
                </el-button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

  <!-- 输入区域 -->
    <div class="input-area">
      <!-- 图片预览 -->
      <div v-if="selectedImages.length > 0" class="image-preview">
        <div 
          v-for="(img, index) in selectedImages" 
          :key="img.url" 
          class="preview-wrapper"
        >
          <img :src="img.url" alt="preview" />
          <div class="preview-overlay" v-if="isUploading && !img.description">
            <el-icon class="is-loading"><Loading /></el-icon>
            <span>分析中...</span>
          </div>
          <el-button 
            v-else
            class="close-btn" 
            circle 
            size="small"
            type="danger"
            @click="clearSelectedImage(index)"
          >
            <el-icon><Close /></el-icon>
          </el-button>
        </div>
      </div>

      <div class="input-wrapper">
        <input 
          type="file" 
          ref="fileInput" 
          style="display: none" 
          accept="image/*"
          multiple
          @change="handleFileSelect"
        />
        <el-button 
          circle 
          text
          class="upload-btn"
          @click="triggerFileUpload"
          :disabled="isUploading"
        >
          <el-icon><Picture /></el-icon>
        </el-button>

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
          @click="isChartMode ? handleChartAnalysis() : handleSend()"
          :loading="loading"
          class="send-btn"
          :disabled="isChartMode && selectedImages.length === 0"
        >
          <el-icon v-if="!loading && !isChartMode"><Position /></el-icon>
          <el-icon v-else-if="!loading && isChartMode"><DataAnalysis /></el-icon>
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

/* Image Preview Styles */
.image-preview {
  padding: 0 0 12px 12px;
}

.preview-wrapper {
  position: relative;
  display: inline-block;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid #45475a;
}

.preview-wrapper img {
  height: 80px;
  display: block;
}

.preview-overlay {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: white;
  font-size: 12px;
  gap: 4px;
}

.close-btn {
  position: absolute;
  top: 4px;
  right: 4px;
  width: 20px !important;
  height: 20px !important;
  min-height: 0 !important;
}

.upload-btn {
  margin: 4px;
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  color: #89b4fa;
}

.upload-btn:hover {
  background-color: rgba(137, 180, 250, 0.1);
}
</style>
