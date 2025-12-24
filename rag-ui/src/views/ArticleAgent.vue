<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Document, Plus, Delete, Link, Loading } from '@element-plus/icons-vue'
import MarkdownIt from 'markdown-it'
import texmath from 'markdown-it-texmath'
import katex from 'katex'
import 'katex/dist/katex.min.css'
import { knowledgeBaseApi } from '../api'

// 配置带公式渲染的 Markdown 解析器
const md = new MarkdownIt({
  html: true,
  linkify: true,
  typographer: true
}).use(texmath, {
  engine: katex,
  delimiters: 'dollars',
  katexOptions: { displayMode: false }
})

// 状态
const urls = ref<string[]>([''])
const files = ref<File[]>([])
const instruction = ref('')
const title = ref('')
const loading = ref(false)
const resultMarkdown = ref('')

// 知识库相关
const useKnowledgeBase = ref(false)
const selectedKb = ref<number | null>(null)
const knowledgeBases = ref<any[]>([])

// 思维链相关
interface ThinkingEvent {
  id: string
  type: 'thinking' | 'tool_call' | 'tool_result' | 'step'
  content: string
  toolName?: string
  timestamp: number
}
const thinkingEvents = ref<ThinkingEvent[]>([])
const currentStep = ref('')

// 文件上传
const fileInput = ref<HTMLInputElement | null>(null)

onMounted(async () => {
  try {
    const res = await knowledgeBaseApi.list()
    knowledgeBases.value = res.data.items
  } catch (err) {
    console.error('Failed to load knowledge bases', err)
  }
})

// URL 管理
const addUrl = () => {
  urls.value.push('')
}

const removeUrl = (index: number) => {
  urls.value.splice(index, 1)
}

// 文件管理
const triggerFileUpload = () => {
  fileInput.value?.click()
}

const handleFileSelect = (event: Event) => {
  const target = event.target as HTMLInputElement
  if (target.files) {
    files.value = [...files.value, ...Array.from(target.files)]
  }
}

const removeFile = (index: number) => {
  files.value.splice(index, 1)
}

// 添加思维事件
const addThinkingEvent = (type: ThinkingEvent['type'], content: string, toolName?: string) => {
  thinkingEvents.value.push({
    id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
    type,
    content,
    toolName,
    timestamp: Date.now()
  })
}

// 生成文章
const generateArticle = async () => {
  const validUrls = urls.value.filter(u => u.trim())
  
  if (validUrls.length === 0 && files.value.length === 0) {
    ElMessage.warning('请至少输入一个 URL 或上传一个文件')
    return
  }
  
  if (!instruction.value.trim()) {
    ElMessage.warning('请输入文章指令')
    return
  }
  
  loading.value = true
  resultMarkdown.value = ''
  thinkingEvents.value = []
  currentStep.value = '初始化...'
  
  try {
    // 构建请求参数
    const articleId = `article-${Date.now()}`
    const validUrlsList = validUrls  // 用于后续引用
    
    // 不显示技术性事件，只显示来自后端的有意义步骤
    
    // 如果开启知识库，先用 RAG 获取相关内容（不显示给用户）
    if (useKnowledgeBase.value && selectedKb.value) {
      // 知识库检索技术细节不显示
    }
    
    // 调用 Article Agent（不显示技术细节）
    currentStep.value = '准备中...'
    
    const response = await fetch('/api/agents/article/threads', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({})
    })
    
    if (!response.ok) {
      throw new Error('创建线程失败')
    }
    
    const thread = await response.json()
    // 线程创建成功，不显示给用户
    
    // 运行 Agent - 使用 content-deep-agent 获取流式 step_events
    // 启动 Agent，不显示技术细节
    currentStep.value = '运行 Agent...'
    
    const runResponse = await fetch(`/api/agents/article/threads/${thread.thread_id}/runs/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        assistant_id: 'content-deep-agent',  // 使用 deep graph 直接流式输出
        input: {
          instruction: instruction.value,
          urls: validUrlsList,
          file_paths: [],
          article_id: articleId,
          title: title.value || ''
        },
        stream_mode: ['values']  // 流式输出 state
      })
    })
    
    if (!runResponse.ok) {
      throw new Error('运行 Agent 失败')
    }
    
    // 解析流式响应
    const reader = runResponse.body?.getReader()
    const decoder = new TextDecoder()
    let lastStepHistoryLength = 0  // 跟踪已处理的 step_events 数量
    let lineBuffer = ''  // 处理跨 chunk 的行
    
    while (reader) {
      const { done, value } = await reader.read()
      if (done) break
      
      // 拼接到 buffer 处理跨 chunk 的行
      lineBuffer += decoder.decode(value, { stream: true })
      const lines = lineBuffer.split('\n')
      
      // 保留最后一个可能不完整的行
      lineBuffer = lines.pop() || ''
      
      for (const line of lines) {
        // 跳过心跳和空行
        if (!line || line.startsWith(':')) continue
        
        if (line.startsWith('event: ')) {
          // 不显示 SSE 事件类型（如 values, metadata），只显示来自 step_events 的有意义内容
          continue
        }
        
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6))
            console.log('[SSE] Received data:', data.step_history, data.step_events?.length)
            
            // LangGraph values 模式：data 就是整个 state
            // 处理 step_events（增量处理避免重复）
            if (data.step_events && Array.isArray(data.step_events)) {
              const newCount = data.step_events.length
              if (newCount > lastStepHistoryLength) {
                const newEvents = data.step_events.slice(lastStepHistoryLength)
                lastStepHistoryLength = newCount
                
                for (const evt of newEvents) {
                  if (evt.type === 'step') {
                    addThinkingEvent('step', evt.step + (evt.details ? `: ${evt.details}` : ''))
                    currentStep.value = evt.step
                  } else if (evt.type === 'thinking') {
                    addThinkingEvent('thinking', evt.thinking)
                  } else if (evt.type === 'tool_call' && evt.tool_call) {
                    addThinkingEvent('tool_call', evt.tool_call.description || evt.tool_call.name || '', evt.tool_call.name)
                  } else if (evt.type === 'tool_result' && evt.tool_result) {
                    addThinkingEvent('tool_result', evt.tool_result.summary || '完成', evt.tool_result.name)
                  }
                }
              }
            }
            
            // 处理 step_history (兼容)
            if (data.step_history && Array.isArray(data.step_history)) {
              const lastStep = data.step_history[data.step_history.length - 1]
              if (lastStep && typeof lastStep === 'string') {
                currentStep.value = lastStep
              }
            }
            
            // markdown 内容
            if (data.final_markdown) {
              resultMarkdown.value = data.final_markdown
            } else if (data.refined_markdown) {
              resultMarkdown.value = data.refined_markdown
            } else if (data.draft_markdown) {
              resultMarkdown.value = data.draft_markdown
            }
            
          } catch (e) {
            console.warn('[SSE] JSON parse failed:', line.slice(0, 100))
          }
        }
      }
    }
    
    currentStep.value = '完成'
    addThinkingEvent('step', '文章生成完成')
    ElMessage.success('文章生成完成')
    
  } catch (error: any) {
    ElMessage.error(error.message || '生成失败')
    addThinkingEvent('step', `错误: ${error.message}`)
    console.error(error)
  } finally {
    loading.value = false
  }
}

// 渲染 Markdown
const renderedHtml = () => {
  return md.render(resultMarkdown.value)
}

// 格式化时间
const formatTime = (timestamp: number) => {
  const date = new Date(timestamp)
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

// 下载 Markdown 文件
const downloadMarkdown = () => {
  if (!resultMarkdown.value) return
  
  // 生成文件名（使用标题或时间戳）
  const fileName = title.value?.trim() 
    ? `${title.value.trim().replace(/[\\/:*?"<>|]/g, '_')}.md`
    : `article_${Date.now()}.md`
  
  // 创建 Blob 对象
  const blob = new Blob([resultMarkdown.value], { type: 'text/markdown;charset=utf-8' })
  
  // 创建下载链接
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = fileName
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
  
  ElMessage.success(`已下载: ${fileName}`)
}
</script>

<template>
  <div class="article-agent-page">
    <!-- 顶部标题栏 -->
    <div class="page-header">
      <div class="header-left">
        <el-icon class="header-icon"><Document /></el-icon>
        <span class="header-title">文档整理</span>
      </div>
      <div class="header-right">
        <!-- 知识库开关 -->
        <el-switch
          v-model="useKnowledgeBase"
          active-text="知识库"
          inactive-text=""
          style="margin-right: 12px"
        />
        <el-select
          v-if="useKnowledgeBase"
          v-model="selectedKb"
          placeholder="选择知识库"
          class="kb-select"
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

    <div class="page-body">
      <!-- 左侧输入区 -->
      <div class="input-panel">
        <div class="section-title">来源链接</div>
        <div class="url-list">
          <div v-for="(_, index) in urls" :key="index" class="url-item">
            <el-input
              v-model="urls[index]"
              placeholder="输入网页 URL"
              :prefix-icon="Link"
            />
            <el-button
              v-if="urls.length > 1"
              type="danger"
              :icon="Delete"
              circle
              size="small"
              @click="removeUrl(index)"
            />
          </div>
          <el-button type="primary" :icon="Plus" text @click="addUrl">
            添加链接
          </el-button>
        </div>

        <div class="section-title" style="margin-top: 20px">上传文件</div>
        <input
          type="file"
          ref="fileInput"
          style="display: none"
          accept=".pdf,.doc,.docx,.txt,.md"
          multiple
          @change="handleFileSelect"
        />
        <div class="file-list">
          <div v-for="(file, index) in files" :key="index" class="file-item">
            <span>{{ file.name }}</span>
            <el-button
              type="danger"
              :icon="Delete"
              circle
              size="small"
              @click="removeFile(index)"
            />
          </div>
          <el-button type="primary" text @click="triggerFileUpload">
            选择文件
          </el-button>
        </div>

        <div class="section-title" style="margin-top: 20px">文章标题（可选）</div>
        <el-input v-model="title" placeholder="输入文章标题" />

        <div class="section-title" style="margin-top: 20px">生成指令</div>
        <el-input
          v-model="instruction"
          type="textarea"
          :rows="4"
          placeholder="描述你想要的文章类型、风格、受众等..."
        />

        <el-button
          type="primary"
          size="large"
          style="width: 100%; margin-top: 20px"
          :loading="loading"
          @click="generateArticle"
        >
          生成文章
        </el-button>
      </div>

      <!-- 中间预览区 -->
      <div class="preview-panel">
        <div class="section-title-row">
          <span class="section-title">预览结果</span>
          <el-button
            v-if="resultMarkdown"
            type="success"
            size="small"
            @click="downloadMarkdown"
          >
            下载 MD
          </el-button>
        </div>
        <div v-if="resultMarkdown" class="markdown-preview" v-html="renderedHtml()" />
        <div v-else class="empty-preview">
          文章生成后将在此显示预览
        </div>
      </div>

      <!-- 右侧思维链面板 -->
      <div class="thinking-panel">
        <div class="thinking-header">
          <el-icon v-if="loading" class="thinking-icon rotating"><Loading /></el-icon>
          <el-icon v-else class="thinking-icon"><Document /></el-icon>
          <span class="thinking-title">{{ loading ? 'AI 思考中...' : 'AI 思考过程' }}</span>
        </div>
        
        <div v-if="currentStep && loading" class="current-step">
          {{ currentStep }}
        </div>
        
        <div class="thinking-content">
          <div
            v-for="event in thinkingEvents"
            :key="event.id"
            :class="['thinking-event', `event-${event.type}`]"
          >
            <div class="event-time">{{ formatTime(event.timestamp) }}</div>
            <div class="event-body">
              <div v-if="event.toolName" class="event-tool">
                <span class="tool-badge">{{ event.toolName }}</span>
              </div>
              <div class="event-content">{{ event.content }}</div>
            </div>
          </div>
          
          <div v-if="thinkingEvents.length === 0 && !loading" class="empty-thinking">
            开始生成后，AI 的思考过程将在此显示
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.article-agent-page {
  height: calc(100vh - 48px);
  display: flex;
  flex-direction: column;
  background: #181825;
  border-radius: 16px;
  overflow: hidden;
  border: 1px solid #313244;
}

.page-header {
  height: 60px;
  padding: 0 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid #313244;
  background: rgba(30, 30, 46, 0.8);
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

.header-right {
  display: flex;
  align-items: center;
}

.kb-select {
  width: 180px;
}

.page-body {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.input-panel {
  width: 300px;
  min-width: 280px;
  padding: 20px;
  border-right: 1px solid #313244;
  overflow-y: auto;
  background: #1e1e2e;
}

.preview-panel {
  flex: 1;
  min-width: 400px;
  padding: 20px;
  overflow-y: auto;
  background: #11111b;
}

.thinking-panel {
  width: 320px;
  min-width: 280px;
  display: flex;
  flex-direction: column;
  border-left: 1px solid #313244;
  background: #1e1e2e;
}

.thinking-header {
  height: 48px;
  padding: 0 16px;
  display: flex;
  align-items: center;
  gap: 8px;
  border-bottom: 1px solid #313244;
  background: rgba(137, 180, 250, 0.1);
}

.thinking-icon {
  font-size: 18px;
  color: #89b4fa;
}

.thinking-icon.rotating {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.thinking-title {
  font-size: 14px;
  font-weight: 600;
  color: #89b4fa;
}

.current-step {
  padding: 8px 16px;
  font-size: 12px;
  color: #a6e3a1;
  background: rgba(166, 227, 161, 0.1);
  border-bottom: 1px solid #313244;
}

.thinking-content {
  flex: 1;
  padding: 12px;
  overflow-y: auto;
}

.thinking-event {
  margin-bottom: 12px;
  padding: 8px 12px;
  border-radius: 8px;
  background: rgba(49, 50, 68, 0.5);
}

.event-thinking {
  border-left: 3px solid #cba6f7;
}

.event-tool_call {
  border-left: 3px solid #f9e2af;
}

.event-tool_result {
  border-left: 3px solid #a6e3a1;
}

.event-step {
  border-left: 3px solid #89b4fa;
}

.event-time {
  font-size: 10px;
  color: #6c7086;
  margin-bottom: 4px;
}

.event-body {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.event-tool {
  display: flex;
}

.tool-badge {
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 4px;
  background: rgba(137, 180, 250, 0.2);
  color: #89b4fa;
}

.event-content {
  font-size: 12px;
  color: #cdd6f4;
  line-height: 1.5;
  word-break: break-word;
}

.empty-thinking {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100px;
  color: #6c7086;
  font-size: 12px;
  text-align: center;
}

.section-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: #cdd6f4;
}

.url-list, .file-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.url-item, .file-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.url-item .el-input {
  flex: 1;
}

.file-item {
  padding: 8px 12px;
  background: rgba(137, 180, 250, 0.1);
  border-radius: 6px;
  color: #a6adc8;
}

.file-item span {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.markdown-preview {
  background: #1e1e2e;
  padding: 20px;
  border-radius: 8px;
  color: #cdd6f4;
  line-height: 1.8;
}

.markdown-preview :deep(h1),
.markdown-preview :deep(h2),
.markdown-preview :deep(h3) {
  color: #89b4fa;
  margin-top: 1.5em;
  margin-bottom: 0.5em;
}

.markdown-preview :deep(p) {
  margin-bottom: 1em;
}

.markdown-preview :deep(img) {
  max-width: 100%;
  height: auto;
  border-radius: 8px;
  margin: 1em 0;
  display: block;
}

.markdown-preview :deep(ul),
.markdown-preview :deep(ol) {
  margin: 1em 0;
  padding-left: 2em;
}

.markdown-preview :deep(li) {
  margin-bottom: 0.5em;
}

.markdown-preview :deep(blockquote) {
  border-left: 4px solid #89b4fa;
  padding-left: 1em;
  margin: 1em 0;
  color: #a6adc8;
  background: rgba(137, 180, 250, 0.05);
}

.markdown-preview :deep(code) {
  background: rgba(137, 180, 250, 0.1);
  padding: 2px 6px;
  border-radius: 4px;
  font-family: 'Fira Code', 'Monaco', monospace;
}

.markdown-preview :deep(pre) {
  background: #11111b;
  padding: 16px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 1em 0;
}

.markdown-preview :deep(pre code) {
  background: transparent;
  padding: 0;
}

.markdown-preview :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 1em 0;
}

.markdown-preview :deep(th),
.markdown-preview :deep(td) {
  border: 1px solid #45475a;
  padding: 8px 12px;
  text-align: left;
}

.markdown-preview :deep(th) {
  background: rgba(137, 180, 250, 0.1);
  color: #89b4fa;
}

.empty-preview {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 300px;
  color: #6c7086;
  background: #1e1e2e;
  border-radius: 8px;
}
</style>
