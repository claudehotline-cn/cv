<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import apiClient, { DEV_USER_ROLE } from '@/api/client'
import {
  Setting,
  Folder,
  Search,
  Bell,
  Upload,
  Files,
  Monitor,
  HomeFilled,
  CircleCheck,
  DataAnalysis,
  Link as IconLink,
  Document,
  MoreFilled,
  Refresh,
  View,
  Grid
} from '@element-plus/icons-vue'

const router = useRouter()

const isAdmin = DEV_USER_ROLE === 'admin'

type KB = {
  id: number
  name: string
  description?: string
  document_count?: number
  chunk_size?: number
  chunk_overlap?: number
  cleaning_rules?: Record<string, any> | null
}

type Doc = {
  id: number
  knowledge_base_id: number
  filename: string
  file_type: string
  file_size?: number
  source_url?: string
  chunk_count?: number
  status: string
  error_message?: string
  created_at?: string
}

const knowledgeBases = ref<KB[]>([])
const selectedKbId = ref<number | null>(null)
const selectedKb = computed(() => knowledgeBases.value.find(k => k.id === selectedKbId.value) || null)

const kbStats = ref<any | null>(null)

const activeFilter = ref('All Types')
const filters = ['All Types', 'PDF', 'Spreadsheets', 'Word', 'Images', 'Audio', 'Video', 'Web']

const documents = ref<Doc[]>([])

function formatBytes(bytes?: number) {
  if (!bytes || bytes <= 0) return '—'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  let n = bytes
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024
    i++
  }
  return `${n.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}

function formatDate(iso?: string) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString()
}

function iconForType(fileType: string) {
  const t = (fileType || '').toLowerCase()
  if (t === 'pdf') return { icon: Document, iconClass: 'icon-pdf' }
  if (t === 'word') return { icon: Document, iconClass: 'icon-word' }
  if (t === 'excel' || t === 'csv') return { icon: DataAnalysis, iconClass: 'icon-csv' }
  if (t === 'webpage') return { icon: IconLink, iconClass: 'icon-link' }
  return { icon: Document, iconClass: 'icon-link' }
}

function statusFor(doc: Doc) {
  const s = (doc.status || '').toLowerCase()
  if (s === 'completed') return { status: 'Ready', statusType: 'success' }
  if (s === 'failed') return { status: 'Failed', statusType: 'danger' }
  if (s === 'processing' || s === 'queued' || s === 'pending') return { status: 'Processing', statusType: 'warning' }
  return { status: doc.status || 'Unknown', statusType: 'info' }
}

const tableData = computed(() => {
  const filter = activeFilter.value
  const rows = documents.value
    .filter((d) => {
      if (filter === 'All Types') return true
      const ft = (d.file_type || '').toLowerCase()
      if (filter === 'PDF') return ft === 'pdf'
      if (filter === 'Spreadsheets') return ft === 'excel' || ft === 'csv'
      if (filter === 'Word') return ft === 'word'
      if (filter === 'Images') return ft === 'image'
      if (filter === 'Audio') return ft === 'audio'
      if (filter === 'Video') return ft === 'video'
      if (filter === 'Web') return ft === 'webpage'
      return true
    })
    .map((d) => {
      const { icon, iconClass } = iconForType(d.file_type)
      const { status, statusType } = statusFor(d)
      const meta = `${formatBytes(d.file_size)} • ${(d.file_type || 'Document').toUpperCase()}`
      return {
        docId: d.id,
        kbId: d.knowledge_base_id,
        icon,
        iconClass,
        name: d.filename,
        meta,
        date: formatDate(d.created_at),
        status,
        statusType,
        raw: d,
      }
    })
  return rows
})

const totalItemsLabel = computed(() => {
  const total = kbStats.value?.documents?.total ?? documents.value.length
  return Number.isFinite(total) ? String(total) : String(documents.value.length)
})

const showingItemsLabel = computed(() => String(tableData.value.length))

const stats = computed(() => {
  const docCount = kbStats.value?.documents?.total ?? selectedKb.value?.document_count ?? documents.value.length
  const totalVectors = kbStats.value?.vectors?.total
  const avgSize = kbStats.value?.vectors?.avg_chunk_size
  return [
    { label: 'Total Documents', value: String(docCount ?? 0) },
    { label: 'Total Vectors', value: totalVectors !== undefined ? String(totalVectors) : '—' },
    { label: 'Avg Chunk Size', value: avgSize !== undefined ? String(avgSize) : '—' },
  ]
})

async function refreshKb(kbId: number) {
  selectedKbId.value = kbId
  try {
    const [docRes, statsRes] = await Promise.all([
      apiClient.listKnowledgeBaseDocuments(kbId),
      apiClient.getKnowledgeBaseStats(kbId),
    ])
    documents.value = (docRes.items || []) as Doc[]
    kbStats.value = statsRes
  } catch (e: any) {
    ElMessage.error('Failed to load knowledge base')
    documents.value = []
    kbStats.value = null
  }
}

async function loadKbs() {
  const res = await apiClient.listKnowledgeBases()
  knowledgeBases.value = (res.items || []) as KB[]
  if (!knowledgeBases.value.length) {
    selectedKbId.value = null
    documents.value = []
    kbStats.value = null
    return
  }

  const preferred = knowledgeBases.value.find(k => k.name.toLowerCase() === 'finance docs')
  await refreshKb((preferred || knowledgeBases.value[0]).id)
}

const createKbDialogOpen = ref(false)
const creatingKb = ref(false)
const createKbForm = ref({
  name: '',
  description: '',
})

function openCreateKbDialog() {
  if (!isAdmin) {
    ElMessage.warning('Admin role required')
    return
  }
  createKbForm.value = { name: '', description: '' }
  createKbDialogOpen.value = true
}

async function submitCreateKb() {
  if (!isAdmin) {
    ElMessage.warning('Admin role required')
    return
  }
  const name = createKbForm.value.name.trim()
  const description = createKbForm.value.description.trim()
  if (!name) {
    ElMessage.warning('Please enter a name')
    return
  }
  creatingKb.value = true
  try {
    const created = await apiClient.createKnowledgeBase({ name, description: description || undefined })
    const kbId = Number((created as any)?.id)
    ElMessage.success('Knowledge base created')
    createKbDialogOpen.value = false
    await loadKbs()
    if (Number.isFinite(kbId)) {
      await refreshKb(kbId)
    }
  } catch {
    ElMessage.error('Failed to create knowledge base')
  } finally {
    creatingKb.value = false
  }
}

const fileInputRef = ref<HTMLInputElement | null>(null)
function openFilePicker() {
  if (!isAdmin) {
    ElMessage.warning('Admin role required')
    return
  }
  if (!selectedKbId.value) {
    ElMessage.warning('Select a knowledge base first')
    return
  }
  fileInputRef.value?.click()
}

async function onFileSelected(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  if (!selectedKbId.value) return
  try {
    await apiClient.uploadKnowledgeBaseDocument(selectedKbId.value, file)
    ElMessage.success('Upload queued')
    await refreshKb(selectedKbId.value)
  } catch (err: any) {
    ElMessage.error('Upload failed')
  } finally {
    input.value = ''
  }
}

const importUrlDialogOpen = ref(false)
const importUrlValue = ref('')
const importingUrl = ref(false)

function openImportUrlDialog() {
  if (!isAdmin) {
    ElMessage.warning('Admin role required')
    return
  }
  if (!selectedKbId.value) {
    ElMessage.warning('Select a knowledge base first')
    return
  }
  importUrlValue.value = ''
  importUrlDialogOpen.value = true
}

async function submitImportUrl() {
  if (!selectedKbId.value) return
  const url = importUrlValue.value.trim()
  if (!url) {
    ElMessage.warning('Please enter a URL')
    return
  }
  importingUrl.value = true
  try {
    const res = await apiClient.importKnowledgeBaseUrl(selectedKbId.value, url)
    const jobId = (res as any)?.job_id
    ElMessage.success(jobId ? `Import queued (job_id=${jobId})` : 'Import queued')
    importUrlDialogOpen.value = false
    await refreshKb(selectedKbId.value)
  } catch {
    ElMessage.error('Import failed')
  } finally {
    importingUrl.value = false
  }
}

const queueingKbJob = ref(false)

async function rebuildVectors() {
  if (!selectedKbId.value) return
  if (!isAdmin) {
    ElMessage.warning('Admin role required')
    return
  }
  queueingKbJob.value = true
  try {
    const res = await apiClient.rebuildKnowledgeBaseVectors(selectedKbId.value)
    const jobId = (res as any)?.job_id
    ElMessage.success(jobId ? `Rebuild queued (job_id=${jobId})` : 'Rebuild queued')
  } catch {
    ElMessage.error('Failed to queue rebuild')
  } finally {
    queueingKbJob.value = false
  }
}

async function buildGraph() {
  if (!selectedKbId.value) return
  if (!isAdmin) {
    ElMessage.warning('Admin role required')
    return
  }
  queueingKbJob.value = true
  try {
    const res = await apiClient.buildKnowledgeBaseGraph(selectedKbId.value)
    const jobId = (res as any)?.job_id
    ElMessage.success(jobId ? `Build graph queued (job_id=${jobId})` : 'Build graph queued')
  } catch {
    ElMessage.error('Failed to queue build graph')
  } finally {
    queueingKbJob.value = false
  }
}

const handleRowClick = (row: any) => {
  const kbId = row.kbId
  const docId = row.docId
  router.push({ path: '/document-editor', query: { kbId: String(kbId), docId: String(docId) } })
}

onMounted(async () => {
  try {
    await loadKbs()
  } catch {
    // handled in loadKbs
  }
})
</script>

<template>
  <el-container class="layout-container">
    <!-- Sidebar -->
    <el-aside width="280px" class="aside">
      <div class="brand">
        <div class="logo-box">
          <el-icon :size="20"><Monitor /></el-icon>
        </div>
        <span class="brand-text">Agent OS</span>
      </div>

      <div class="scroll-area">
        <el-menu class="custom-menu" default-active="2">
          <router-link to="/" style="text-decoration: none;">
            <el-menu-item index="1">
              <el-icon><HomeFilled /></el-icon>
              <span>Dashboard</span>
            </el-menu-item>
          </router-link>
          
          <router-link to="/finance-docs" style="text-decoration: none;">
            <el-menu-item index="2">
              <el-icon><Files /></el-icon>
              <span>Knowledge Base</span>
            </el-menu-item>
          </router-link>


          <el-menu-item index="4">
            <el-icon><Setting /></el-icon>
            <span>Settings</span>
          </el-menu-item>
        </el-menu>

          <div class="collections">
            <div class="section-header">
              <span>COLLECTIONS</span>
              <el-button v-if="isAdmin" link type="primary" size="small" @click="openCreateKbDialog">+</el-button>
            </div>
           <el-menu
             class="custom-menu collections-menu"
             :default-active="selectedKbId ? String(selectedKbId) : ''"
           >
             <el-menu-item
               v-for="kb in knowledgeBases"
               :key="kb.id"
               :index="String(kb.id)"
               :class="{ 'collection-active': kb.id === selectedKbId }"
               @click="refreshKb(kb.id)"
             >
               <el-icon><Folder /></el-icon>
               <span class="flex-1">{{ kb.name }}</span>
               <span class="badge">{{ kb.document_count ?? 0 }}</span>
             </el-menu-item>
           </el-menu>
         </div>
      </div>

      <div class="storage-widget">
        <el-card shadow="never" class="storage-card">
          <div class="storage-info">
             <div class="storage-icon">
               <el-icon><Upload /></el-icon>
             </div>
             <div>
               <div class="storage-title">Vector Storage</div>
               <div class="storage-sub">4.5GB of 10GB used</div>
             </div>
          </div>
          <el-progress :percentage="45" :show-text="false" class="storage-progress" />
        </el-card>
      </div>
    </el-aside>

    <el-container>
      <!-- Header -->
      <el-header class="header">
        <div class="breadcrumbs">
          <el-breadcrumb separator="/">
            <el-breadcrumb-item>Knowledge Base</el-breadcrumb-item>
            <el-breadcrumb-item>Collections</el-breadcrumb-item>
             <el-breadcrumb-item>
               <span class="active-crumb">
                 <el-icon><Folder /></el-icon> {{ selectedKb?.name || '—' }}
               </span>
             </el-breadcrumb-item>
           </el-breadcrumb>
         </div>
        
        <div class="header-actions">
           <el-input 
             class="search-input" 
             placeholder="Search files..." 
             :prefix-icon="Search"
           />
           <div class="notification-btn">
             <el-badge is-dot class="item">
               <el-icon :size="20"><Bell /></el-icon>
             </el-badge>
           </div>
           <el-avatar :size="36" src="https://cube.elemecdn.com/0/88/03b0d39583f48206768a7534e55bcpng.png" />
        </div>
      </el-header>

      <!-- Main -->
      <el-main class="main-content">
        <div class="main-inner">
          <!-- Page Title -->
          <div class="page-title-row">
            <div>
               <h1>{{ selectedKb?.name || 'Knowledge Base' }}</h1>
               <p class="subtitle">{{ selectedKb?.description || 'Manage documents and vectors for agent context.' }}</p>
             </div>
              <div class="actions">
                <el-button-group>
                  <el-button :icon="View" />
                  <el-button :icon="Grid" />
                </el-button-group>
                <el-button v-if="isAdmin" type="primary" :icon="Upload" :disabled="!selectedKbId" @click="openFilePicker">Upload Data</el-button>
                <el-dropdown
                  v-if="isAdmin"
                  trigger="click"
                  @command="(cmd: string) => { if (cmd === 'import_url') openImportUrlDialog(); if (cmd === 'rebuild_vectors') rebuildVectors(); if (cmd === 'build_graph') buildGraph(); }"
                >
                  <el-button :icon="MoreFilled" :disabled="!selectedKbId" :loading="queueingKbJob" />
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item command="import_url">Import URL</el-dropdown-item>
                      <el-dropdown-item command="rebuild_vectors">Rebuild Vectors</el-dropdown-item>
                      <el-dropdown-item command="build_graph">Build Graph</el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
              </div>
           </div>

          <!-- Stats -->
          <el-row :gutter="16" class="stats-row">
            <el-col :span="6" v-for="stat in stats" :key="stat.label">
              <el-card shadow="never" class="stat-card">
                <div class="stat-label">{{ stat.label }}</div>
                <div class="stat-value">{{ stat.value }}</div>
              </el-card>
            </el-col>
            <el-col :span="6">
              <el-card shadow="never" class="stat-card health-card">
                 <div class="health-bg"></div>
                 <div class="health-content">
                   <div class="health-label">
                     AGENT HEALTH <el-icon><CircleCheck /></el-icon>
                   </div>
                   <div class="health-desc">Data is vectorized & ready for queries.</div>
                 </div>
              </el-card>
            </el-col>
          </el-row>

          <!-- Main Table Card -->
          <el-card shadow="never" class="table-card" :body-style="{ padding: '0' }">
             <!-- Filter Bar -->
             <div class="filter-bar">
               <div class="filters">
                 <span>Filter by:</span>
                 <el-check-tag 
                   v-for="f in filters" 
                   :key="f" 
                   :checked="activeFilter === f" 
                   @change="activeFilter = f" 
                   class="custom-tag"
                 >
                   {{ f }}
                 </el-check-tag>
               </div>
                <span class="count">Showing {{ showingItemsLabel }} of {{ totalItemsLabel }} items</span>
              </div>

             <!-- Table -->
             <el-table 
               :data="tableData" 
               style="width: 100%" 
               class="custom-table" 
               header-row-class-name="table-header"
               @row-click="handleRowClick"
               row-class-name="clickable-row"
             >
                <el-table-column label="DOCUMENT NAME" min-width="300">
                  <template #default="{ row }">
                     <div class="doc-cell">
                       <div class="icon-box" :class="row.iconClass">
                         <el-icon><component :is="row.icon" /></el-icon>
                       </div>
                       <div>
                         <div class="doc-name">{{ row.name }}</div>
                         <div class="doc-meta">{{ row.meta }}</div>
                       </div>
                     </div>
                  </template>
                </el-table-column>
                <el-table-column prop="date" label="DATE UPLOADED" width="150" />
                <el-table-column label="VECTOR STATUS" width="180">
                  <template #default="{ row }">
                    <el-tag :type="row.statusType" effect="light" round class="status-tag">
                      <el-icon v-if="row.status === 'Processing'" class="is-loading"><Refresh /></el-icon>
                      <el-icon v-else-if="row.status === 'Failed'"><DataAnalysis /></el-icon>
                      <el-icon v-else><CircleCheck /></el-icon>
                      {{ row.status }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="ACTIONS" width="200" align="right">
                  <template #default="{ row }">
                    <div class="action-buttons">
                      <el-button v-if="row.status === 'Failed'" size="small" type="danger" plain :icon="Refresh">Retry</el-button>
                      <el-button v-else size="small" plain>Segments</el-button>
                      <el-button size="small" text :icon="MoreFilled" />
                    </div>
                  </template>
                </el-table-column>
             </el-table>
          </el-card>

          <!-- Footer Banner -->
          <div class="footer-banner">
             <div class="banner-content">
               <div class="banner-icon"><el-icon><DataAnalysis /></el-icon></div>
               <div>
                 <h3>Need help structuring your data?</h3>
                 <p>Read our guide on optimal chunking strategies.</p>
               </div>
             </div>
             <el-button class="banner-btn">Read Guide</el-button>
          </div>

        </div>
      </el-main>
    </el-container>
  </el-container>

  <input ref="fileInputRef" type="file" style="display:none" @change="onFileSelected" />

  <el-dialog v-model="importUrlDialogOpen" title="Import URL" width="640px">
    <el-input
      v-model="importUrlValue"
      placeholder="https://example.com/page"
      clearable
      :disabled="importingUrl"
    />
    <template #footer>
      <el-button @click="importUrlDialogOpen = false" :disabled="importingUrl">Cancel</el-button>
      <el-button type="primary" :loading="importingUrl" @click="submitImportUrl">Import</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="createKbDialogOpen" title="Create Knowledge Base" width="640px">
    <el-form label-position="top">
      <el-form-item label="Name">
        <el-input v-model="createKbForm.name" placeholder="e.g. Finance Docs" :disabled="creatingKb" />
      </el-form-item>
      <el-form-item label="Description">
        <el-input v-model="createKbForm.description" placeholder="Optional" :disabled="creatingKb" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="createKbDialogOpen = false" :disabled="creatingKb">Cancel</el-button>
      <el-button type="primary" :loading="creatingKb" @click="submitCreateKb">Create</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@200..800&display=swap');

/* Global Variables Override */
.layout-container {
  height: 100vh;
  font-family: 'Manrope', sans-serif;
  color: #0f172a;
  background-color: #fafafa;
}

/* Sidebar */
.aside {
  background: #ffffff;
  border-right: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
}
.brand {
  height: 64px;
  display: flex;
  align-items: center;
  padding: 0 24px;
  gap: 12px;
  border-bottom: 1px solid #f1f5f9;
}
.logo-box {
  width: 32px;
  height: 32px;
  background: #146cf0;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
}
.brand-text {
  font-weight: 700;
  font-size: 18px;
  letter-spacing: -0.02em;
}

.scroll-area {
  flex: 1;
  overflow-y: auto;
  padding: 24px 16px;
  display: flex;
  flex-direction: column;
  gap: 32px;
}

/* Menu Customization */
:deep(.el-menu) {
  border-right: none;
  background: transparent;
}
:deep(.el-menu-item) {
  height: 44px;
  line-height: 44px;
  border-radius: 8px;
  margin-bottom: 4px;
  color: #64748b;
  font-weight: 500;
}
:deep(.el-menu-item:hover) {
  background-color: #f8fafc;
  color: #0f172a;
}
:deep(.el-menu-item.is-active) {
  background-color: rgba(20, 108, 240, 0.05);
  color: #146cf0;
  font-weight: 700;
}
:deep(.el-sub-menu__title:hover) {
  background-color: #f8fafc;
}

.collections .section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 12px;
  font-size: 12px;
  font-weight: 700;
  color: #94a3b8;
  margin-bottom: 8px;
}

.collection-active {
  background-color: #f1f5f9 !important;
  color: #0f172a !important; 
  border-left: 3px solid #146cf0;
  border-radius: 0 8px 8px 0;
  margin-left: -16px; /* Breakout left */
  padding-left: 29px !important;
}

.badge {
  background: white;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 11px;
  border: 1px solid #e2e8f0;
  color: #64748b;
}

/* Storage Widget */
.storage-widget {
  padding: 16px;
  background: #f8fafc;
  border-top: 1px solid #e2e8f0;
}
.storage-card {
  border-radius: 12px;
  border: 1px solid #e2e8f0;
}
.storage-info {
  display: flex;
  gap: 12px;
  margin-bottom: 12px;
}
.storage-icon {
  background: #e0e7ff;
  color: #4f46e5;
  padding: 8px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.storage-title {font-size: 14px; font-weight: 700;}
.storage-sub {font-size: 12px; color: #64748b;}
:deep(.el-progress-bar__inner) { background-color: #146cf0; }

/* Header */
.header {
  background: #ffffff;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 32px;
}
.active-crumb {
  display: flex;
  align-items: center;
  gap: 6px;
  background: #f1f5f9;
  padding: 4px 8px;
  border-radius: 4px;
  font-weight: 600;
  color: #0f172a;
}
.header-actions {
  display: flex;
  align-items: center;
  gap: 16px;
}
.search-input { width: 250px; }
:deep(.el-input__wrapper) {
  background: #f8fafc;
  box-shadow: none;
  border: 1px solid transparent;
}
:deep(.el-input__wrapper:hover) { border-color: #e2e8f0; }
:deep(.el-input__wrapper.is-focus) { 
  background: white; 
  box-shadow: 0 0 0 1px #146cf0; 
}

/* Main Content */
.main-content {
  padding: 32px;
  background: #fafafa;
}
.main-inner {
  max-width: 1200px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.page-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
h1 { font-size: 30px; font-weight: 800; margin: 0 0 4px 0; letter-spacing: -0.02em; }
.subtitle { color: #64748b; font-size: 16px; margin: 0; }

/* Stats */
.stat-card {
  border-radius: 12px;
  border: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  justify-content: center;
  height: 100%;
}
.stat-label { font-size: 12px; font-weight: 600; text-transform: uppercase; color: #64748b; margin-bottom: 4px; }
.stat-value { font-size: 24px; font-weight: 700; color: #0f172a; }

.health-card {
  background: #eef2ff;
  border: 1px solid #e0e7ff;
  position: relative;
  overflow: hidden;
}
.health-bg {
  position: absolute;
  top: -20px; right: -20px;
  width: 80px; height: 80px;
  background: #e0e7ff;
  opacity: 0.5;
  border-radius: 50%;
}
.health-label {
  color: #4f46e5;
  font-weight: 700;
  font-size: 12px;
  display: flex; align-items: center; gap: 4px;
}
.health-desc { font-size: 14px; font-weight: 500; color: #0f172a; }

/* Table Card */
.table-card {
  border-radius: 12px;
  border: 1px solid #e2e8f0;
  overflow: hidden;
}
.filter-bar {
  padding: 16px 24px;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.filters {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 14px;
  font-weight: 600;
  color: #64748b;
}
.custom-tag {
  background: white;
  border: 1px solid #e2e8f0;
  font-weight: 500;
  color: #0f172a;
  padding: 4px 12px;
}
.custom-tag.is-checked {
  background-color: white;
  border-color: #146cf0;
  color: #146cf0;
}
.count { font-size: 12px; color: #94a3b8; }

:deep(th.table-header) {
  background-color: #f8fafc !important;
  color: #64748b;
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 12px 0;
}
.doc-cell { display: flex; align-items: center; gap: 16px; }
.icon-box {
  width: 40px; height: 40px;
  border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  font-size: 20px;
}
.icon-pdf { background: #fef2f2; color: #ef4444; border: 1px solid #fee2e2; }
.icon-word { background: #eff6ff; color: #3b82f6; border: 1px solid #dbeafe; }
.icon-link { background: #f1f5f9; color: #64748b; border: 1px solid #e2e8f0; }
.icon-csv { background: #f0fdf4; color: #16a34a; border: 1px solid #dcfce7; }

.doc-name { font-weight: 700; color: #0f172a; font-size: 14px; }
.doc-meta { font-size: 12px; color: #64748b; }

.status-tag { 
  font-weight: 700; 
  display: inline-flex; 
  align-items: center; 
  gap: 6px; 
  border: none;
}
:deep(.el-tag--success) { background: #ecfdf5; color: #047857; }
:deep(.el-tag--warning) { background: #fffbeb; color: #b45309; }
:deep(.el-tag--danger) { background: #fff1f2; color: #be123c; }

/* Banner */
.footer-banner {
  background: linear-gradient(to right, #146cf0, #6366f1);
  border-radius: 12px;
  padding: 24px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  color: white;
  box-shadow: 0 10px 15px -3px rgba(99, 102, 241, 0.2);
}
.banner-content { display: flex; align-items: center; gap: 16px; }
.banner-icon {
  background: rgba(255,255,255,0.2);
  padding: 12px;
  border-radius: 8px;
}
.banner-content h3 { font-size: 18px; font-weight: 700; margin: 0; }
.banner-content p { color: #e0e7ff; margin: 0; font-size: 14px; }
.banner-btn {
  background: white;
  color: #146cf0;
  font-weight: 700;
  border: none;
}

.custom-table :deep(.clickable-row) {
  cursor: pointer;
  transition: background-color 0.2s;
}

.custom-table :deep(.clickable-row:hover) > td {
  background-color: #f0fdfa !important;
}
</style>
