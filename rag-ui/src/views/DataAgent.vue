<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { DataAnalysis, Connection, Document, VideoPlay } from '@element-plus/icons-vue'
import { knowledgeBaseApi } from '../api'

// ECharts
import * as echarts from 'echarts'

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

onMounted(async () => {
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
  if (chartInstance) {
    chartInstance.dispose()
    chartInstance = null
  }
  
  try {
    const sessionId = `data-analysis-${Date.now()}`
    let graphId = ''
    let input: any = {}
    
    // 如果开启知识库，先获取 RAG 上下文
    if (useKnowledgeBase.value && selectedKb.value) {
      // TODO: 调用 RAG API 并增强 query
    }
    
    if (dataSource.value === 'db') {
      graphId = 'db_chart'
      input = {
        query: query.value,
        session_id: sessionId,
        db_name: dbName.value
      }
    } else {
      // Excel 模式
      // 这里简化处理：假设文件已通过其他接口上传，实际应先上传文件获取路径
      // 为了演示，我们假设 Agent 可以直接访问挂载目录的示例文件
      graphId = 'excel_chart'
      input = {
        session_id: sessionId,
        query: query.value
      }
    }
    
    // 1. 创建线程
    const threadRes = await fetch('/api/agents/data/threads', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({})
    })
    
    if (!threadRes.ok) throw new Error('创建线程失败')
    const thread = await threadRes.json()
    
    // 2. 运行 Agent
    const runRes = await fetch(`/api/agents/data/threads/${thread.thread_id}/runs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        assistant_id: graphId,
        input: input,
        stream_mode: ["values"]
      })
    })
    
    if (!runRes.ok) throw new Error('运行分析失败')
    
    // 3. 处理流式响应
    const reader = runRes.body?.getReader()
    const decoder = new TextDecoder()
    
    while (reader) {
      const { done, value } = await reader.read()
      if (done) break
      
      const chunk = decoder.decode(value)
      const lines = chunk.split('\n')
      
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6))
            // 检查是否有图表配置
            // 注意：具体字段需根据 agent-langchain 返回结构调整
            if (data.values && data.values.chart_spec) {
              chartConfig.value = JSON.parse(data.values.chart_spec)
              renderChart()
            }
            if (data.values && data.values.summary) {
              analysisResult.value = data.values.summary
            }
          } catch {}
        }
      }
    }
    
    ElMessage.success('分析完成')
    
  } catch (err: any) {
    ElMessage.error(err.message || '分析失败')
    console.error(err)
  } finally {
    loading.value = false
  }
}

const renderChart = () => {
  if (!chartContainer.value || !chartConfig.value) return
  
  chartInstance = echarts.init(chartContainer.value, 'dark')
  chartInstance.setOption(chartConfig.value)
  
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

      <!-- 右侧展示区 -->
      <div class="result-panel">
        <div class="result-container">
          <!-- 图表区域 -->
          <div class="chart-wrapper">
            <div ref="chartContainer" class="chart-box"></div>
            <div v-if="!chartConfig && !loading" class="empty-chart">
              图表将在此显示
            </div>
          </div>

          <!-- 结论区域 -->
          <div class="analysis-text" v-if="analysisResult">
            <div class="text-title">分析结论</div>
            <div class="text-content">{{ analysisResult }}</div>
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
  color: #a6e3a1;
}

.header-title {
  font-size: 18px;
  font-weight: 600;
}

.page-body {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.control-panel {
  width: 360px;
  padding: 24px;
  background: #1e1e2e;
  border-right: 1px solid #313244;
  overflow-y: auto;
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: #cdd6f4;
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
  width: 100%;
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

.config-section {
  background: rgba(30, 30, 46, 0.5);
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
  height: 80px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.3s;
}

.file-upload-area:hover {
  border-color: #89b4fa;
  background: rgba(137, 180, 250, 0.1);
}

.file-info, .upload-placeholder {
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
}

.result-panel {
  flex: 1;
  padding: 24px;
  background: #11111b;
  overflow-y: auto;
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
  padding: 20px;
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
}

.analysis-text {
  background: #1e1e2e;
  border-radius: 12px;
  padding: 20px;
  border: 1px solid #313244;
}

.text-title {
  font-weight: 600;
  color: #a6e3a1;
  margin-bottom: 12px;
}

.text-content {
  color: #cdd6f4;
  line-height: 1.6;
  white-space: pre-wrap;
}
</style>
