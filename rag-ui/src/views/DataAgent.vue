<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { DataAnalysis, Connection, Document, VideoPlay, Loading } from '@element-plus/icons-vue'
import { knowledgeBaseApi } from '../api'

// Markdown 渲染
import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'
import 'highlight.js/styles/atom-one-dark.css'

// ECharts
import * as echarts from 'echarts'

// 初始化 Markdown 渲染器
const md = new MarkdownIt({
  html: true,
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

const renderMarkdown = (content: string) => {
  if (!content) return ''
  
  // 检查是否包含结构化数据标记
  let markerMatch = null
  if (content.includes('DATA_RESULT:')) {
     markerMatch = content.match(/DATA_RESULT:(\{.*\})/s)
  } else if (content.includes('CHART_DATA:')) {
     markerMatch = content.match(/CHART_DATA:(\{.*\})/s)
  } else if (content.includes('REPORT_CONTENT:')) {
     // 报告内容：直接渲染 Markdown
     const reportContent = content.split('REPORT_CONTENT:')[1]
     return md.render(reportContent || '')
  }

  if (markerMatch && markerMatch[1]) {
    try {
      let toolResult = JSON.parse(markerMatch[1])
      // 兼容 ToolStrategy 结构: { name: "...", arguments: { ... } }
      if (toolResult.arguments) {
          toolResult = toolResult.arguments
      }
      
      // 增强逻辑：如果包含结构化数据（如 chart option），不要直接返回空字符串
      // 而是移除标记后渲染剩余的文本。这支持 "混合内容" (文字 + 图表数据)
      
      // 如果有显式的 summary (MainAgentOutput), 使用 summary
      if (toolResult && toolResult.summary) {
        return md.render(toolResult.summary)
      }

      // 如果没有显式 summary，移除标记，渲染原始内容
      const cleanText = content.replace(markerMatch[0], '')
      return md.render(cleanText)
    } catch (e) {
      console.warn('Failed to parse marker in renderMarkdown', e)
      // 解析失败，回退到移除标记尝试显示
      return md.render(content.replace(markerMatch[0], ''))
    }
  }

  return md.render(content)
}

// 状态
const dataSource = ref<'db' | 'excel'>('db')
const dbName = ref('cv_cp') // 默认数据库
const query = ref('')
const loading = ref(false)
const chartContainer = ref<HTMLElement | null>(null)
let chartInstance: echarts.ECharts | null = null

// 知识库相关
const useKnowledgeBase = ref(false)
const selectedKb = ref<number | null>(null)
const knowledgeBases = ref<any[]>([])

// Excel 上传
const fileInput = ref<HTMLInputElement | null>(null)
const excelFile = ref<File | null>(null)

// 结果展示
const analysisResult = ref('')
const chartConfig = ref<any>(null)

onMounted(async () => { console.log('DataAgent v2.3 SCROLL');
  try {
    const res = await knowledgeBaseApi.list()
    knowledgeBases.value = res.data.items
  } catch (err) {
    console.error('Failed to load knowledge bases', err)
  }
})

// Excel 文件处理
const triggerFileUpload = () => {
  fileInput.value?.click()
}

const handleFileSelect = (event: Event) => {
  const target = event.target as HTMLInputElement
  if (target.files && target.files.length > 0) {
    const file = target.files[0]
    if (file instanceof File) {
      excelFile.value = file
    }
  }
}

// 思维链相关
interface ThinkingEvent {
  id: string
  type: 'thinking' | 'tool_call' | 'tool_result' | 'step'
  content: string
  toolName?: string
  timestamp: number
}
const thinkingEvents = ref<ThinkingEvent[]>([])
// 跟踪已处理的消息 ID，避免重复显示
let processedMsgIds = new Set<string>()

// 格式化时间
const formatTime = (timestamp: number) => {
  const date = new Date(timestamp)
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

const addThinkingEvent = (type: ThinkingEvent['type'], content: string, toolName?: string) => {
  thinkingEvents.value.push({
    id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
    type,
    content,
    toolName,
    timestamp: Date.now()
  })
}

// 从内容中提取代码部分
const extractCode = (content: string): string => {
  if (!content) return ''
  // 移除前缀如 "执行 SQL:\n" 或 "执行 Python:\n"
  const lines = content.split('\n')
  if (lines.length > 0 && lines[0]?.includes(':')) {
    return lines.slice(1).join('\n')
  }
  return content
}

// 提取文字标签（冒号前的部分）
const getCodeLabel = (content: string): string => {
  if (!content) return ''
  const lines = content.split('\n')
  if (lines.length > 0 && lines[0]?.includes(':')) {
    return lines[0].split(':')[0] || ''
  }
  return ''
}

// 使用 highlight.js 高亮代码
const highlightCode = (code: string, lang: string): string => {
  if (!code) return ''
  try {
    if (hljs.getLanguage(lang)) {
      return hljs.highlight(code, { language: lang }).value
    }
  } catch (e) {
    console.error('Highlight error:', e)
  }
  return code
}

// 执行分析
const runAnalysis = async () => {
  if (!query.value.trim()) {
    ElMessage.warning('请输入分析查询')
    return
  }
  
  if (dataSource.value === 'excel' && !excelFile.value) {
    ElMessage.warning('请先上传 Excel 文件')
    return
  }
  
  loading.value = true
  analysisResult.value = ''
  chartConfig.value = null
  thinkingEvents.value = []
  processedMsgIds.clear()
  
  if (chartInstance) {
    chartInstance.dispose()
    chartInstance = null
  }
  
  try {
    let graphId = ''
    let input: any = {}
    
    // 生成 analysis_id 用于结果持久化
    const analysisId = Date.now().toString(36) + Math.random().toString(36).substr(2, 5)
    
    // 如果开启知识库，先获取 RAG 上下文
    if (useKnowledgeBase.value && selectedKb.value) {
      // TODO: 调用 RAG API 并增强 query
    }
    
    if (dataSource.value === 'db') {
      graphId = 'data_deep_agent'
      input = {
        messages: [{
          role: 'human',
          content: `[analysis_id=${analysisId}] 请分析数据库 ${dbName.value}：${query.value}`
        }]
      }
    } else {
      // Excel 模式
      graphId = 'data_deep_agent'
      input = {
        messages: [{
          role: 'human',
          content: `[analysis_id=${analysisId}] 请分析 Excel 文件：${query.value}`
        }]
      }
    }
    
    addThinkingEvent('step', '开始分析任务...')
    
    // 1. 创建线程
    const threadRes = await fetch('/api/agents/data/threads', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({})
    })
    
    if (!threadRes.ok) throw new Error('创建线程失败')
    const thread = await threadRes.json()
    
    // 2. 运行 Agent (使用 stream 端点)
    const runRes = await fetch(`/api/agents/data/threads/${thread.thread_id}/runs/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        assistant_id: graphId,
        input: input,
        stream_mode: ["values"],
        config: {
          configurable: {
            user_id: "mock_user_from_tool_call_999",  // TODO: Replace with actual user ID from auth context
            analysis_id: analysisId
          }
        }
      })
    })
    
    if (!runRes.ok) throw new Error('运行分析失败')
    
    // 3. 处理流式响应
    const reader = runRes.body?.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    
    while (reader) {
      const { done, value } = await reader.read()
      if (done) break
      
      // 🚀 核心修复：处理 SSE 分包 (Packet Splitting)
      // 网络包可能在任意位置截断，导致单行 JSON 不完整。必须使用 Buffer 拼接。
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      // 保留最后一行（可能是半截数据），留待下一次拼接
      buffer = lines.pop() || ''
      
      for (const line of lines) {
        const trimmed = line.trim()
        if (!trimmed) continue
        
        if (trimmed.startsWith('data: ')) {
          try {
            const data = JSON.parse(trimmed.slice(6))
            // Deep Agent 返回 messages 数组
            if (data.messages && Array.isArray(data.messages)) {
              for (const msg of data.messages) {
                // 跳过已处理的消息
                if (msg.id && processedMsgIds.has(msg.id)) continue
                if (msg.id) processedMsgIds.add(msg.id)

                // 🚀 核心修复：忽略后端泄露的 MainAgentOutput 原始对象消息
                // 该消息包含 Python str() 格式的数据，会覆盖正常的 DATA_RESULT，导致渲染失败
                // if (msg.name === 'MainAgentOutput') {
                //    console.log('Skipping MainAgentOutput raw message')
                //    continue
                // }

                // DEBUG: 打印消息结构
                console.log('MSG:', msg.type, msg.id?.slice(-8), 'content:', msg.content?.slice(0, 50), 'tool_calls:', !!msg.tool_calls)

                // 1. 处理 AI 消息 (可能是工具调用或最终回复)
                // LangGraph 可能使用 'ai' 或消息 ID 以 'lc_run' 开头来标识 AI 消息
                const isAIMessage = msg.type === 'ai' || (msg.id && msg.id.includes('lc_run'))
                if (isAIMessage) {
                  // 处理工具调用请求
                  if (msg.tool_calls && msg.tool_calls.length > 0) {
                    for (const toolCall of msg.tool_calls) {
                      let content = ''
                      const args = toolCall.args || {}
                      
                      // DEBUG: 输出工具调用名称
                      console.log('TOOL_CALL:', toolCall.name, 'args keys:', Object.keys(args))
                      
                      if (toolCall.name === 'data_db_run_sql') {
                        content = `执行 SQL:\n${args.sql}`
                      } else if (toolCall.name === 'python_execute') {
                        content = `执行 Python:\n${args.code}`
                      } else if (toolCall.name === 'data_generate_chart' || toolCall.name === 'chart_agent' || (args && args.option)) {
                        // 支持多种可能的工具名称，或者直接检测 args.option
                        content = `生成图表配置...`
                        // 关键修复：从工具调用参数中提取 option 并立即渲染图表
                        if (args.option) {
                          console.log('CHART: Found option in tool call args, toolName:', toolCall.name)
                          // 解析 option（可能是字符串或对象）
                          let chartOption = args.option
                          if (typeof chartOption === 'string') {
                            try {
                              chartOption = JSON.parse(chartOption)
                            } catch (e) {
                              console.warn('Failed to parse option string:', e)
                            }
                          }
                          if (chartOption && typeof chartOption === 'object') {
                            console.log('CHART: Setting chartConfig from tool call args')
                            chartConfig.value = chartOption
                            setTimeout(renderChart, 100)
                          }
                        }
                      } else {
                        content = `调用工具: ${toolCall.name} ${JSON.stringify(args).slice(0, 100)}`
                      }
                      addThinkingEvent('tool_call', content, toolCall.name)
                    }
                  }
                  // 处理 AI 消息内容（无论是否有 tool_calls，只要有 content 就更新）
                  if (msg.content && typeof msg.content === 'string' && msg.content.trim()) {
                    console.log('AI message content:', msg.content.slice(0, 100))
                    analysisResult.value = msg.content
                    
                    // 🚀 核心修复：Middleware 返回的是 AI 消息，包含 DATA_RESULT，此前被漏了解析
                    // 必须在此处提取图表配置，否则图表无法渲染
                    try {
                        let content = msg.content
                        let markerMatch = null
                        if (content.includes('DATA_RESULT:')) {
                            markerMatch = content.match(/DATA_RESULT:(\{.*\})/s)
                        } else if (content.includes('CHART_DATA:')) {
                            markerMatch = content.match(/CHART_DATA:(\{.*\})/s)
                        }
                        
                        if (markerMatch && markerMatch[1]) {
                           let toolResult = JSON.parse(markerMatch[1])
                           // 提取图表配置 (复用之前的增强逻辑)
                           let chartOpt = null
                           if (toolResult.chart && toolResult.chart.option) {
                               chartOpt = toolResult.chart.option
                           } else if (toolResult.chart && toolResult.chart.series) {
                               chartOpt = toolResult.chart
                           } else if (toolResult.option) {
                               chartOpt = toolResult.option
                           }
                           
                           if (chartOpt) {
                               console.log('AI_MSG: Found chart config, rendering...')
                               chartConfig.value = chartOpt
                               setTimeout(renderChart, 100)
                           }
                        }
                    } catch (e) {
                        console.warn('Failed to parse chart from AI message', e)
                    }
                  }
                }
                
                // 2. 处理工具执行结果
                // DEBUG: 输出完整消息结构（用于调试）
                if (msg.type === 'tool' || msg.name) {
                  console.log('FULL MSG:', JSON.stringify(msg, null, 2)?.slice(0, 500))
                }
                
                if ((msg.type === 'tool' || msg.name === 'data_generate_chart' || msg.name === 'data_db_run_sql' || msg.name === 'python_execute') && msg.content) {
                  try {
                    // 尝试解析 JSON
                    let toolResult = null
                    const content = msg.content
                    let markerMatch = null
                    if (typeof content === 'string') {
                       // Debug log
                       if (content.includes('DATA_RESULT') || content.includes('CHART_DATA')) {
                           console.log('DEBUG: Found marker in content:', content.substring(0, 100) + '...')
                       }

                       if (content.includes('DATA_RESULT:')) {
                           markerMatch = content.match(/DATA_RESULT:(\{.*\})/s)
                       } else if (content.includes('CHART_DATA:')) {
                           markerMatch = content.match(/CHART_DATA:(\{.*\})/s)
                       }
                    }

                    if (markerMatch && markerMatch[1]) {
                        console.log('DEBUG: Regex matched!')
                        try {
                          let toolResult = JSON.parse(markerMatch[1])
                          console.log('DEBUG: Parsed JSON keys:', Object.keys(toolResult))
                          
                          // 兼容 ToolStrategy 结构: { name: "...", arguments: { ... } }
                          if (toolResult.arguments) {
                              console.log('DEBUG: Found arguments wrapper, unwrapping...')
                              toolResult = toolResult.arguments
                          }

                          console.log('STRUCTURED DATA FOUND:', { 
                              keys: Object.keys(toolResult), 
                              hasOption: !!toolResult.option,
                              hasSummary: !!toolResult.summary 
                          })
                          
                          // 1. 处理图表
                          // 优先检查标准结构 toolResult.chart.option，其次是兼容结构 toolResult.option
                          let chartOpt = null
                          if (toolResult.chart && toolResult.chart.option) {
                              console.log('DEBUG: Found chart option in toolResult.chart.option')
                              chartOpt = toolResult.chart.option
                          } else if (toolResult.chart && toolResult.chart.series) {
                              // 兼容 Hybrid/Flatten 结构
                              console.log('DEBUG: Found chart option in toolResult.chart (flattened)')
                              chartOpt = toolResult.chart
                          } else if (toolResult.option) {
                              console.log('DEBUG: Found chart option in toolResult.option (legacy)')
                              chartOpt = toolResult.option
                          }

                          if (chartOpt) {
                            console.log('DEBUG: Setting chartConfig and triggering render...')
                            chartConfig.value = chartOpt
                            // Use nextTick + timeout to ensure DOM is ready
                            setTimeout(() => {
                                console.log('DEBUG: Calling renderChart()')
                                renderChart()
                            }, 100)
                          }
                          // 2. 处理 Summary (renderMarkdown 已处理显示)
                          
                        } catch (e) {
                          console.warn('Failed to parse STRUCTURED DATA:', e)
                        }
                    } else if (typeof content === 'string' && (content.includes('DATA_RESULT') || content.includes('CHART_DATA'))) {
                        console.warn('DEBUG: Marker found but Regex FAILED to match JSON payload! Check newline handling.')
                    }
                    
                    // 方法1: 直接解析（如果还没解析成功）
                    if (!toolResult && typeof content === 'object') {
                      toolResult = content
                    } else if (!toolResult && typeof content === 'string') {
                      // 方法2: 检查是否以 { 开头
                      const trimmed = content.trim()
                      if (trimmed.startsWith('{')) {
                        try {
                          toolResult = JSON.parse(trimmed)
                        } catch (e) {
                          // 尝试提取 JSON
                          const start = trimmed.indexOf('{')
                          const end = trimmed.lastIndexOf('}')
                          if (start !== -1 && end !== -1) {
                            try {
                              toolResult = JSON.parse(trimmed.slice(start, end + 1))
                            } catch (e2) {}
                          }
                        }
                      }
                    }
                    
                    if (toolResult) {
                      console.log('Tool Result parsed:', {name: msg.name, hasOption: !!toolResult.option, keys: Object.keys(toolResult)})
                    } else {
                      console.log('Tool Result NOT JSON:', msg.name, content?.slice?.(0, 100))
                    }
                    
                    let resultDisplay = ''
                    if (msg.name === 'data_db_run_sql') {
                       resultDisplay = `SQL 执行结果: ${toolResult.total_rows} 行数据`
                    } else if (msg.name === 'data_generate_chart' || (toolResult && toolResult.option)) {
                        // 检查是否是图表生成工具的结果
                        // 增强：即使 msg.name 不匹配，只要 option 存在就渲染图表
                        // 支持从 chart.option 或 option 读取
                        let chartOpt = toolResult.option
                        if (!chartOpt && toolResult.chart) {
                             if (toolResult.chart.option) chartOpt = toolResult.chart.option
                             else if (toolResult.chart.series) chartOpt = toolResult.chart
                        }

                        if (chartOpt) {
                          console.log('Found chart option:', chartOpt)
                          chartConfig.value = chartOpt
                          // renderChart 在 watch 或 nextTick 处理
                          setTimeout(renderChart, 100) 
                          resultDisplay = `图表生成成功: ${toolResult.chart_type || (toolResult.chart && toolResult.chart.chart_type) || 'unknown'}`
                        }
                    } else if (msg.name === 'python_execute') {
                        resultDisplay = `Python 执行结果:\n${JSON.stringify(toolResult.result || toolResult, null, 2)}`
                    } else {
                        resultDisplay = typeof msg.content === 'string' ? msg.content.slice(0, 200) + '...' : JSON.stringify(msg.content).slice(0, 200)
                    }
                    
                    addThinkingEvent('tool_result', resultDisplay, msg.name)
                    
                  } catch (e) {
                    console.error('Parse tool result error:', e, msg.content)
                    addThinkingEvent('tool_result', `工具执行完成: ${msg.content.slice(0, 100)}...`, msg.name)
                  }
                }
              }
            }
          } catch {}
        }
      }
    }
    
    addThinkingEvent('step', '分析任务完成')
    ElMessage.success('分析完成')
    
  } catch (err: any) {
    ElMessage.error(err.message || '分析失败')
    addThinkingEvent('step', `错误: ${err.message}`)
    console.error(err)
  } finally {
    loading.value = false
  }
}

const renderChart = () => {
  console.log('renderChart called, container:', !!chartContainer.value, 'config:', !!chartConfig.value, 'config preview:', JSON.stringify(chartConfig.value)?.slice(0, 200))
  if (!chartContainer.value || !chartConfig.value) {
    console.warn('renderChart aborted: missing container or config')
    return
  }
  
  try {
    chartInstance = echarts.init(chartContainer.value, 'dark')
    
    // 处理 tooltip 换行：将 series data 中的 \n 替换为 <br/>
    const config = JSON.parse(JSON.stringify(chartConfig.value)) // deep clone
    if (config.series) {
      config.series.forEach((s: any) => {
        if (s.data && Array.isArray(s.data)) {
          s.data.forEach((d: any) => {
            if (d && typeof d.name === 'string') {
              d.name = d.name.replace(/\n/g, '<br/>')
            }
          })
        }
      })
    }
    
    // 如果是散点图，使用函数 formatter 来正确渲染 HTML
    if (config.tooltip && config.tooltip.formatter === '{b}') {
      config.tooltip.formatter = function(params: any) {
        return params.name // name 字段已经包含 <br/> 标签
      }
    }
    
    chartInstance.setOption(config)
    console.log('ECharts setOption succeeded')
  } catch (e) {
    console.error('ECharts setOption failed:', e)
  }
  
  window.addEventListener('resize', () => {
    chartInstance?.resize()
  })
}
</script>

<template>
  <div class="data-agent-page">
    <!-- 顶部标题栏 -->
    <div class="page-header">
      <div class="header-left">
        <el-icon class="header-icon"><DataAnalysis /></el-icon>
        <span class="header-title">数据分析</span>
      </div>
      <div class="header-right">
        <el-switch
          v-model="useKnowledgeBase"
          active-text="知识库辅助"
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
      <!-- 左侧控制区 -->
      <div class="control-panel">
        <div class="section-title">数据源类型</div>
        <el-radio-group v-model="dataSource" class="source-switch">
          <el-radio-button label="db">
            <el-icon><Connection /></el-icon> 数据库
          </el-radio-button>
          <el-radio-button label="excel">
            <el-icon><Document /></el-icon> Excel 文件
          </el-radio-button>
        </el-radio-group>

        <!-- 数据库配置 -->
        <div v-if="dataSource === 'db'" class="config-section">
          <div class="label">数据库名称</div>
          <el-input v-model="dbName" placeholder="默认: cv_cp" disabled />
          <div class="hint">目前仅支持查询默认业务数据库</div>
        </div>

        <!-- Excel 配置 -->
        <div v-else class="config-section">
          <div class="label">上传数据表</div>
          <input
            type="file"
            ref="fileInput"
            style="display: none"
            accept=".xlsx,.xls,.csv"
            @change="handleFileSelect"
          />
          <div class="file-upload-area" @click="triggerFileUpload">
            <div v-if="excelFile" class="file-info">
              <el-icon size="24"><Document /></el-icon>
              <span>{{ excelFile.name }}</span>
            </div>
            <div v-else class="upload-placeholder">
              <el-icon size="24"><Plus /></el-icon>
              <span>点击上传 Excel 文件</span>
            </div>
          </div>
        </div>

        <div class="section-title" style="margin-top: 24px">分析指令</div>
        <el-input
          v-model="query"
          type="textarea"
          :rows="6"
          placeholder="例如：统计上个月的销售趋势，或者按城市分布绘制饼图..."
        />

        <el-button
          type="primary"
          size="large"
          class="run-btn"
          :loading="loading"
          :icon="VideoPlay"
          @click="runAnalysis"
        >
          开始分析
        </el-button>
      </div>

      <!-- 右侧展示区 (中部) -->
      <div class="result-panel">
        <div class="result-container">
          <!-- 图表区域 -->
          <div class="chart-wrapper">
            <div ref="chartContainer" class="chart-box"></div>
            <div v-if="!chartConfig && !loading" class="empty-chart">
              图表将在此显示
            </div>
          </div>
          
          <!-- 分析结果文本 -->
          <div class="text-result">
            <div v-if="analysisResult" class="markdown-body" v-html="renderMarkdown(analysisResult)"></div>
            <div v-else-if="!loading" class="empty-text">
              分析结果将在此显示
            </div>
            <div v-else class="loading-state">
              <el-icon class="is-loading"><Loading /></el-icon>
              <span>正在分析数据...</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 最右侧执行过程面板 -->
      <div class="thinking-panel">
        <div class="thinking-header">
          <el-icon v-if="loading" class="thinking-icon rotating"><Loading /></el-icon>
          <el-icon v-else class="thinking-icon"><VideoPlay /></el-icon>
          <span class="thinking-title">{{ loading ? '执行中...' : '执行过程' }}</span>
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
              <div class="event-content">
                <template v-if="event.toolName === 'data_db_run_sql' || event.toolName === 'python_execute'">
                  <div class="code-label">{{ getCodeLabel(event.content) }}</div>
                  <pre class="code-block"><code v-html="highlightCode(extractCode(event.content), event.toolName === 'data_db_run_sql' ? 'sql' : 'python')"></code></pre>
                </template>
                <template v-else-if="event.toolName === 'data_generate_chart'">
                  <div class="code-label">{{ getCodeLabel(event.content) }}</div>
                  <pre class="code-block"><code v-html="highlightCode(extractCode(event.content), 'json')"></code></pre>
                </template>
                <template v-else>
                  <div class="event-text">{{ event.content }}</div>
                </template>
              </div>
            </div>
          </div>
          
          <div v-if="thinkingEvents.length === 0 && !loading" class="empty-thinking">
            开始分析后，执行过程将在此显示
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.data-agent-page {
  height: calc(100vh - 48px);
  display: flex;
  flex-direction: column;
  background: #181825;
  border-radius: 16px;
  overflow-x: auto; overflow-y: hidden;
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
  overflow-x: auto; overflow-y: hidden;
}

.control-panel {
  width: 320px;
  min-width: 300px; flex-shrink: 0;
  padding: 24px;
  border-right: 1px solid #313244;
  background: #1e1e2e;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: #a6adc8;
  margin-bottom: 12px;
}

.source-switch {
  width: 100%;
  margin-bottom: 24px;
  display: flex;
}

.source-switch :deep(.el-radio-button) {
  flex: 1;
}

.source-switch :deep(.el-radio-button__inner) {
  width: 50%;
  background: #313244;
  border-color: #313244;
  color: #a6adc8;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border-radius: 0;
}

.source-switch :deep(.el-radio-button:first-child .el-radio-button__inner) {
  border-radius: 4px 0 0 4px;
}

.source-switch :deep(.el-radio-button:last-child .el-radio-button__inner) {
  border-radius: 0 4px 4px 0;
}

.source-switch :deep(.el-radio-button__original-radio:checked + .el-radio-button__inner) {
  background: #89b4fa;
  border-color: #89b4fa;
  color: #1e1e2e;
  box-shadow: none;
}

.config-section {
  background: #313244;
  border-radius: 8px;
  padding: 16px;
  border: 1px solid #313244;
}

.label {
  font-size: 12px;
  color: #a6adc8;
  margin-bottom: 8px;
}

.hint {
  font-size: 12px;
  color: #6c7086;
  margin-top: 8px;
}

.file-upload-area {
  border: 2px dashed #45475a;
  border-radius: 8px;
  padding: 20px;
  text-align: center;
  cursor: pointer;
  transition: all 0.3s;
}

.file-upload-area:hover {
  border-color: #89b4fa;
  background: rgba(137, 180, 250, 0.1);
}

.file-info {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #89b4fa;
}

.upload-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  color: #a6adc8;
}

.run-btn {
  width: 100%;
  margin-top: 24px;
  height: 48px;
  font-size: 16px;
  font-weight: 600;
}

.result-panel {
  flex: 1;
  padding: 24px;
  background: #11111b;
  overflow-y: auto;
  min-width: 400px;
}

.result-container {
  max-width: 1000px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 24px;
  height: 100%;
}

.chart-wrapper {
  flex: 1;
  min-height: 400px;
  background: #1e1e2e;
  border-radius: 12px;
  padding: 16px;
  border: 1px solid #313244;
  position: relative;
}

.chart-box {
  width: 100%;
  height: 100%;
}

.empty-chart {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  color: #6c7086;
  font-size: 14px;
}

.text-result {
  flex: 1;
  background: #1e1e2e;
  border-radius: 12px;
  padding: 24px;
  border: 1px solid #313244;
  color: #cdd6f4;
  overflow-y: auto;
}

.empty-text {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #6c7086;
}

.loading-state {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: #89b4fa;
}

.thinking-panel {
  width: 380px;
  min-width: 300px; flex-shrink: 0;
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

.thinking-content {
  flex: 1;
  padding: 12px;
  overflow-y: auto;
}

.empty-thinking {
  padding: 20px;
  text-align: center;
  color: #6c7086;
  font-size: 13px;
}

.thinking-event {
  margin-bottom: 12px;
  padding: 12px;
  border-radius: 8px;
  background: rgba(49, 50, 68, 0.5);
  border: 1px solid #313244;
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

.event-tool {
  margin-bottom: 6px;
}

.tool-badge {
  font-size: 10px;
  padding: 2px 6px;
  background: #313244;
  border-radius: 4px;
  color: #f9e2af;
}

.event-content {
  font-size: 13px;
  color: #cdd6f4;
  line-height: 1.5;
}

.code-label {
  font-size: 10px;
  color: #6c7086;
  margin-bottom: 4px;
  text-transform: uppercase;
}

.code-block {
  background: #11111b;
  border-radius: 6px;
  padding: 12px;
  margin: 0;
  overflow-x: auto;
  max-height: 300px;
  overflow-y: auto;
  font-family: 'Fira Code', 'Consolas', monospace;
  font-size: 12px;
  line-height: 1.5;
}

.code-block code {
  color: #cdd6f4;
  white-space: pre;
  display: block;
}

.event-text {
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
