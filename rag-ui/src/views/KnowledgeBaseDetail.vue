<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { knowledgeBaseApi, documentApi } from '../api'
import { Link, Upload, Document, Grid, UploadFilled, Connection } from '@element-plus/icons-vue'

const route = useRoute()
const kbId = computed(() => Number(route.params.id))

interface Document {
  id: number
  filename: string
  file_type: string
  file_size: number
  source_url?: string
  chunk_count: number
  status: string
  error_message?: string
  created_at: string
}

interface KnowledgeBase {
  id: number
  name: string
  description: string
  document_count: number
}

const loading = ref(false)
const kb = ref<KnowledgeBase | null>(null)
const documents = ref<Document[]>([])
const uploadDialogVisible = ref(false)
const urlDialogVisible = ref(false)
const urlInput = ref('')
const fileList = ref<any[]>([])

// 统计信息
interface KbStats {
  knowledge_base: any
  documents: { total: number; completed: number; processing: number; failed: number }
  vectors: { total: number; parents: number; children: number; parent_child_ratio: string; avg_chunk_size: number }
  chunk_distribution: Record<string, number>
}
const stats = ref<KbStats | null>(null)
const showStats = ref(false)

const loadData = async () => {
  loading.value = true
  try {
    const [kbRes, docsRes] = await Promise.all([
      knowledgeBaseApi.get(kbId.value),
      knowledgeBaseApi.getDocuments(kbId.value)
    ])
    kb.value = kbRes.data
    documents.value = docsRes.data.items
  } catch (err) {
    ElMessage.error('加载数据失败')
  } finally {
    loading.value = false
  }
}

const loadStats = async () => {
  try {
    const res = await knowledgeBaseApi.getStats(kbId.value)
    stats.value = res.data
    showStats.value = true
  } catch (err) {
    ElMessage.error('加载统计信息失败')
  }
}

const handleUpload = async (options: any) => {
  try {
    await documentApi.upload(kbId.value, options.file)
    ElMessage.success('上传成功，正在处理...')
    uploadDialogVisible.value = false
    fileList.value = []
    setTimeout(loadData, 1000)
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || '上传失败')
  }
}

const handleBuildGraph = async () => {
  try {
    await knowledgeBaseApi.buildGraph(kbId.value)
    ElMessage.success('已触发知识图谱构建任务')
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || '触发构建失败')
  }
}

const handleImportUrl = async () => {
  if (!urlInput.value.trim()) {
    ElMessage.warning('请输入URL')
    return
  }
  try {
    await documentApi.importUrl(kbId.value, urlInput.value)
    ElMessage.success('导入成功，正在处理...')
    urlDialogVisible.value = false
    urlInput.value = ''
    setTimeout(loadData, 1000)
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || '导入失败')
  }
}

const handleDeleteDoc = async (doc: Document) => {
  try {
    await ElMessageBox.confirm(`确定删除文档 "${doc.filename}" 吗？`, '确认删除', {
      type: 'warning'
    })
    await documentApi.delete(doc.id)
    ElMessage.success('删除成功')
    loadData()
  } catch (err) {
    // 用户取消
  }
}

const formatSize = (bytes: number) => {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(1) + ' MB'
}

const getStatusType = (status: string) => {
  switch (status) {
    case 'completed': return 'success'
    case 'processing': return 'warning'
    case 'failed': return 'danger'
    default: return 'info'
  }
}

const getStatusText = (status: string) => {
  switch (status) {
    case 'completed': return '已完成'
    case 'processing': return '处理中'
    case 'failed': return '失败'
    default: return '待处理'
  }
}

// ----------------- 查看分块逻辑 -----------------
interface Chunk {
  index: number
  content: string
  metadata: any
  char_count: number
}

const chunksDrawerVisible = ref(false)
const currentDocChunks = ref<Chunk[]>([])
const currentDocName = ref('')
const chunksLoading = ref(false)

const handleViewChunks = async (doc: Document) => {
  currentDocName.value = doc.filename
  chunksDrawerVisible.value = true
  chunksLoading.value = true
  currentDocChunks.value = []
  
  try {
    const res = await documentApi.getChunks(doc.id)
    currentDocChunks.value = res.data.chunks
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || '获取分块失败')
  } finally {
    chunksLoading.value = false
  }
}

onMounted(loadData)
</script>

<template>
  <div class="page-container" v-loading="loading">
    <!-- 面包屑和标题 -->
    <div class="page-nav">
      <el-breadcrumb separator="/">
        <el-breadcrumb-item :to="{ path: '/knowledge-bases' }">知识库管理</el-breadcrumb-item>
        <el-breadcrumb-item>{{ kb?.name }}</el-breadcrumb-item>
      </el-breadcrumb>
    </div>

    <div class="page-header">
      <div class="header-info">
        <h1 class="page-title">{{ kb?.name }}</h1>
        <p class="page-desc">{{ kb?.description || '暂无描述' }}</p>
      </div>
      <div class="header-actions">
        <el-button @click="loadStats">
          <el-icon><Grid /></el-icon>
          统计信息
        </el-button>
        <el-button type="success" @click="handleBuildGraph">
          <el-icon><Connection /></el-icon>
          构建图谱
        </el-button>
        <el-button @click="urlDialogVisible = true">
          <el-icon><Link /></el-icon>
          导入网页
        </el-button>
        <el-button type="primary" @click="uploadDialogVisible = true">
          <el-icon><Upload /></el-icon>
          上传文档
        </el-button>
      </div>
    </div>

    <!-- 统计信息面板 -->
    <el-dialog v-model="showStats" title="知识库统计" width="600px">
      <div v-if="stats" class="stats-panel">
        <div class="stats-grid">
          <div class="stat-card">
            <div class="stat-label">文档总数</div>
            <div class="stat-value">{{ stats.documents.total }}</div>
            <div class="stat-detail">
              <span class="stat-success">完成: {{ stats.documents.completed }}</span>
              <span class="stat-warning">处理中: {{ stats.documents.processing }}</span>
              <span class="stat-danger">失败: {{ stats.documents.failed }}</span>
            </div>
          </div>
          <div class="stat-card">
            <div class="stat-label">向量总数</div>
            <div class="stat-value">{{ stats.vectors.total }}</div>
            <div class="stat-detail">
              父块: {{ stats.vectors.parents }} | 子块: {{ stats.vectors.children }}
            </div>
          </div>
          <div class="stat-card">
            <div class="stat-label">父子比例</div>
            <div class="stat-value">{{ stats.vectors.parent_child_ratio }}</div>
            <div class="stat-detail">每个父块平均包含的子块数</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">平均块大小</div>
            <div class="stat-value">{{ stats.vectors.avg_chunk_size }}</div>
            <div class="stat-detail">字符</div>
          </div>
        </div>
        <div class="chunk-distribution">
          <h4>分块数量分布</h4>
          <div class="distribution-bars">
            <div v-for="(count, bucket) in stats.chunk_distribution" :key="bucket" class="dist-item">
              <span class="dist-label">{{ bucket }}</span>
              <div class="dist-bar" :style="{ width: (count / stats.documents.total * 100) + '%' }"></div>
              <span class="dist-count">{{ count }}</span>
            </div>
          </div>
        </div>
      </div>
    </el-dialog>

    <!-- 文档列表 -->
    <div class="doc-section">
      <h2 class="section-title">
        文档列表
        <span class="doc-count">{{ documents.length }} 个文档</span>
      </h2>
      
      <el-table :data="documents" style="width: 100%" class="doc-table">
        <el-table-column prop="filename" label="文件名" min-width="200">
          <template #default="{ row }">
            <div class="doc-name">
              <el-icon v-if="row.file_type === 'pdf'" color="#f38ba8"><Document /></el-icon>
              <el-icon v-else-if="row.file_type === 'word'" color="#89b4fa"><Document /></el-icon>
              <el-icon v-else-if="row.file_type === 'excel'" color="#a6e3a1"><Grid /></el-icon>
              <el-icon v-else-if="row.file_type === 'webpage'" color="#f9e2af"><Link /></el-icon>
              <el-icon v-else color="#cdd6f4"><Document /></el-icon>
              <span>{{ row.filename }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="file_type" label="类型" width="100" />
        <el-table-column prop="file_size" label="大小" width="100">
          <template #default="{ row }">{{ formatSize(row.file_size) }}</template>
        </el-table-column>
        <el-table-column prop="chunk_count" label="分块数" width="80" />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row.status)" size="small">
              {{ getStatusText(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="handleViewChunks(row)">
              查看
            </el-button>
            <el-button text type="danger" size="small" @click="handleDeleteDoc(row)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-if="documents.length === 0" description="暂无文档，请上传或导入" />
    </div>

    <!-- 上传对话框 -->
    <el-dialog v-model="uploadDialogVisible" title="上传文档" width="500px">
      <el-upload
        v-model:file-list="fileList"
        drag
        :auto-upload="false"
        :http-request="handleUpload"
        accept=".pdf,.docx,.doc,.xlsx,.xls,.md,.txt"
        :limit="1"
      >
        <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
        <div class="el-upload__text">拖拽文件到此处，或<em>点击上传</em></div>
        <template #tip>
          <div class="el-upload__tip">
            支持 PDF、Word、Excel、Markdown、TXT 格式
          </div>
        </template>
      </el-upload>
      <template #footer>
        <el-button @click="uploadDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="fileList[0] && handleUpload({ file: fileList[0].raw })">
          上传
        </el-button>
      </template>
    </el-dialog>

    <!-- URL导入对话框 -->
    <el-dialog v-model="urlDialogVisible" title="导入网页" width="500px">
      <el-form>
        <el-form-item label="网页URL">
          <el-input v-model="urlInput" placeholder="https://example.com/article" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="urlDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleImportUrl">导入</el-button>
      </template>
    </el-dialog>

    <!-- 分块查看抽屉 -->
    <el-drawer
      v-model="chunksDrawerVisible"
      :title="currentDocName"
      size="50%"
      direction="rtl"
      class="chunks-drawer"
    >
      <div v-loading="chunksLoading" class="chunks-container">
        <div v-if="currentDocChunks.length > 0">
          <div class="chunks-header">
            共 {{ currentDocChunks.length }} 个分块
          </div>
          <div class="chunks-list">
            <div v-for="chunk in currentDocChunks" :key="chunk.index" class="chunk-item">
              <div class="chunk-header">
                <span class="chunk-index">#{{ chunk.index + 1 }}</span>
                <span class="chunk-meta">{{ chunk.char_count }} chars</span>
              </div>
              <div class="chunk-content">{{ chunk.content }}</div>
            </div>
          </div>
        </div>
        <el-empty v-else-if="!chunksLoading" description="该文档没有分块数据" />
      </div>
    </el-drawer>

  </div>
</template>

<style scoped>
.page-container {
  max-width: 1200px;
  margin: 0 auto;
}

.page-nav {
  margin-bottom: 16px;
}

.page-nav :deep(.el-breadcrumb__item) {
  color: #6c7086;
}

.page-nav :deep(.el-breadcrumb__inner a) {
  color: #89b4fa;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 32px;
  padding: 32px;
  background: rgba(30, 30, 46, 0.6);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(137, 180, 250, 0.1);
  border-radius: 16px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
}

.page-title {
  color: #cdd6f4;
  font-size: 32px;
  font-weight: 700;
  margin: 0 0 12px 0;
  letter-spacing: -0.5px;
  background: linear-gradient(135deg, #cdd6f4 0%, #a6adc8 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.page-desc {
  color: #bac2de;
  font-size: 15px;
  margin: 0;
  line-height: 1.6;
  max-width: 600px;
}

.header-actions {
  display: flex;
  gap: 16px;
}

.doc-section {
  background: rgba(30, 30, 46, 0.4);
  backdrop-filter: blur(8px);
  border: 1px solid rgba(49, 50, 68, 0.8);
  border-radius: 16px;
  padding: 24px;
}

.section-title {
  color: #cdd6f4;
  font-size: 20px;
  font-weight: 600;
  margin: 0 0 24px 0;
  display: flex;
  align-items: center;
  gap: 12px;
  padding-bottom: 16px;
  border-bottom: 1px solid rgba(49, 50, 68, 0.5);
}

.doc-count {
  font-size: 13px;
  color: #89b4fa;
  background: rgba(137, 180, 250, 0.1);
  padding: 4px 10px;
  border-radius: 12px;
  font-weight: 500;
}

.doc-table {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: rgba(24, 24, 37, 0.6);
  --el-table-border-color: rgba(49, 50, 68, 0.5);
  --el-table-text-color: #cdd6f4;
  --el-table-header-text-color: #a6adc8;
  --el-table-row-hover-bg-color: rgba(137, 180, 250, 0.1);
}

.doc-name {
  display: flex;
  align-items: center;
  gap: 12px;
  font-weight: 500;
}

/* Drawer Styles moved to global style.css */

.chunks-container {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.chunks-header {
  margin-bottom: 20px;
  color: #a6adc8;
  font-size: 14px;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 8px;
}

.chunks-header::before {
  content: '';
  display: block;
  width: 4px;
  height: 14px;
  background: #89b4fa;
  border-radius: 2px;
}

.chunks-list {
  display: flex;
  flex-direction: column;
  gap: 20px;
  padding-bottom: 24px;
}

.chunk-item {
  background: rgba(30, 30, 46, 0.6);
  border: 1px solid rgba(137, 180, 250, 0.1);
  border-radius: 16px;
  padding: 20px;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  overflow: hidden;
}

.chunk-item:hover {
  border-color: rgba(137, 180, 250, 0.4);
  background: rgba(30, 30, 46, 0.8);
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.2);
}

.chunk-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.chunk-index {
  background: linear-gradient(135deg, #89b4fa 0%, #b4befe 100%);
  color: #1e1e2e;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.5px;
}

.chunk-meta {
  color: #6c7086;
  font-size: 12px;
  font-family: 'JetBrains Mono', monospace;
  background: rgba(0, 0, 0, 0.2);
  padding: 4px 8px;
  border-radius: 4px;
}

.chunk-content {
  color: #cdd6f4;
  font-size: 14px;
  line-height: 1.7;
  white-space: pre-wrap;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  max-height: 400px;
  overflow-y: auto;
  padding: 16px;
  background: rgba(17, 17, 27, 0.5);
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.02);
}

/* Custom Scrollbar for Drawer */
.chunk-content::-webkit-scrollbar,
:deep(.el-drawer__body)::-webkit-scrollbar {
  width: 6px;
}

.chunk-content::-webkit-scrollbar-thumb,
:deep(.el-drawer__body)::-webkit-scrollbar-thumb {
  background: #45475a;
  border-radius: 3px;
}

.chunk-content::-webkit-scrollbar-thumb:hover,
:deep(.el-drawer__body)::-webkit-scrollbar-thumb:hover {
  background: #585b70;
}

/* Stats Panel Styles */
.stats-panel {
  padding: 16px;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}

.stat-card {
  background: #313244;
  border-radius: 12px;
  padding: 16px;
  text-align: center;
}

.stat-label {
  color: #a6adc8;
  font-size: 13px;
  margin-bottom: 8px;
}

.stat-value {
  color: #89b4fa;
  font-size: 28px;
  font-weight: 700;
  margin-bottom: 4px;
}

.stat-detail {
  color: #6c7086;
  font-size: 12px;
}

.stat-success { color: #a6e3a1; margin-right: 8px; }
.stat-warning { color: #f9e2af; margin-right: 8px; }
.stat-danger { color: #f38ba8; }

.chunk-distribution h4 {
  color: #cdd6f4;
  margin-bottom: 12px;
}

.distribution-bars {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.dist-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.dist-label {
  width: 60px;
  color: #a6adc8;
  font-size: 12px;
}

.dist-bar {
  height: 20px;
  background: linear-gradient(90deg, #89b4fa, #cba6f7);
  border-radius: 4px;
  min-width: 4px;
  max-width: calc(100% - 100px);
}

.dist-count {
  color: #cdd6f4;
  font-size: 12px;
  min-width: 30px;
}

</style>
