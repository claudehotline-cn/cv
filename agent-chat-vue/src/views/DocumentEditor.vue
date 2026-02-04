<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import apiClient, { DEV_USER_ROLE } from '@/api/client'
import MarkdownRenderer from '@/components/chat/MarkdownRenderer.vue'
import {
  ArrowRight,
  Refresh,
  Search,
  View,
  Coin,
  Setting,
  Document,
  Connection
} from '@element-plus/icons-vue'

// Custom icons or Material Symbols aliases if needed
// For now using Element Plus Icons

const route = useRoute()
const router = useRouter()
const isAdmin = DEV_USER_ROLE === 'admin'

type KB = {
  id: number
  name: string
  description?: string
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
  chunk_count?: number
  status: string
  error_message?: string
  created_at?: string
}

type ChunkRow = {
  id: number
  chunk_index: number
  content: string
  metadata?: Record<string, any>
  parent_id?: number | null
  is_parent: boolean
  created_at?: string | null
  tokens_estimate?: number
}

type ChunkView = {
  id: number
  displayId: string
  globalDisplayId: string
  tag: string
  tokens: number
  content: string
  isParent: boolean
  parentId: number | null
  chunkIndex: number
}

const kbId = computed(() => {
  const raw = String(route.query.kbId || '')
  const n = Number.parseInt(raw, 10)
  return Number.isFinite(n) ? n : null
})

const docId = computed(() => {
  const raw = String(route.query.docId || '')
  const n = Number.parseInt(raw, 10)
  return Number.isFinite(n) ? n : null
})

const kb = ref<KB | null>(null)
const doc = ref<Doc | null>(null)

const loading = ref(false)
const loadingMore = ref(false)
const saving = ref(false)

const offset = ref(0)
const pageSize = 50
const hasMore = ref(true)

const activeChunkId = ref<number | null>(null)
const activeParentId = ref<number | null>(null)
const searchText = ref('')

const expandedParents = ref<Record<string, boolean>>({})

type OutlineNode = {
  id: string
  title: string
  level: number
  parent_chunk_index: number
  children?: OutlineNode[]
}

const outlineItems = ref<OutlineNode[]>([])
const outlineExtraction = ref<string | null>(null)

const chunks = ref<ChunkView[]>([])

const cleaningRules = ref({
  removeWhitespace: true,
  stripHtml: true,
  fixEncoding: false,
  consolidateShortParagraphs: true,
})

const chunkingStrategy = ref({
  maxTokenLimit: 500,
  chunkOverlap: 50,
})

const previewDialogOpen = ref(false)
const previewData = ref<any | null>(null)

function truncate(text: string, max = 260) {
  const s = (text || '').trim()
  if (s.length <= max) return s
  return s.slice(0, max).trimEnd() + '…'
}


function extractFirstHeading(content: string): { level: number; title: string } | null {
  const lines = String(content || '').split('\n')
  let inCode = false
  let fence: string | null = null

  for (const line of lines) {
    const trimmed = line.trim()
    if (trimmed.startsWith('```') || trimmed.startsWith('~~~')) {
      const f = trimmed.slice(0, 3)
      if (!inCode) {
        inCode = true
        fence = f
      } else if (fence === f) {
        inCode = false
        fence = null
      }
      continue
    }

    if (inCode) continue

    const m = line.match(/^\s*(?:>\s*)?(#{1,6})\s+(.+?)\s*$/)
    if (m) {
      const level = m[1].length
      const title = m[2].trim()
      if (title) return { level, title }
    }
  }

  return null
}

function extractSectionTitle(content: string) {
  const h = extractFirstHeading(content)
  if (h) return h.title

  const lines = String(content || '')
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)

  const page = lines.find((l) => /^\[Page\s+\d+\]/i.test(l))
  if (page) return page.replace(/^\[(.+?)\].*$/, '$1').trim()

  return lines[0] ? truncate(lines[0], 60) : ''
}

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

function normalizeCleaningRules(input: any) {
  const base = {
    removeWhitespace: true,
    stripHtml: true,
    fixEncoding: false,
    consolidateShortParagraphs: true,
  }
  if (!input || typeof input !== 'object') return base
  return {
    removeWhitespace: Boolean((input as any).removeWhitespace ?? base.removeWhitespace),
    stripHtml: Boolean((input as any).stripHtml ?? base.stripHtml),
    fixEncoding: Boolean((input as any).fixEncoding ?? base.fixEncoding),
    consolidateShortParagraphs: Boolean((input as any).consolidateShortParagraphs ?? base.consolidateShortParagraphs),
  }
}

function mapChunkRow(r: ChunkRow): ChunkView {
  const idx = Number.isFinite(r.chunk_index) ? r.chunk_index : 0
  const globalDisplayId = `#${String(idx).padStart(3, '0')}`
  const meta = (r.metadata || {}) as any

  const parentIndexRaw = meta?.parent_index
  const childLocalIndexRaw = meta?.child_local_index
  const parentIndex = Number.isFinite(Number(parentIndexRaw)) ? Number(parentIndexRaw) : null
  const childLocalIndex = Number.isFinite(Number(childLocalIndexRaw)) ? Number(childLocalIndexRaw) : null

  let displayId = globalDisplayId
  if (r.is_parent) {
    const p = parentIndex ?? idx
    displayId = `P${String(p + 1).padStart(3, '0')}`
  } else if (parentIndex !== null && childLocalIndex !== null) {
    displayId = `P${String(parentIndex + 1).padStart(3, '0')}.${String(childLocalIndex + 1).padStart(2, '0')}`
  }
  const tokens = Math.max(1, Number(r.tokens_estimate || 0) || Math.floor((r.content || '').length / 4) || 1)
  return {
    id: r.id,
    displayId,
    globalDisplayId,
    tag: r.is_parent ? 'Parent' : 'Child',
    tokens,
    content: r.content || '',
    isParent: Boolean(r.is_parent),
    parentId: r.parent_id ?? null,
    chunkIndex: idx,
  }
}

const parentChunks = computed(() => chunks.value.filter((c) => c.isParent))
const childChunks = computed(() => chunks.value.filter((c) => !c.isParent))

const childrenByParentId = computed<Record<string, ChunkView[]>>(() => {
  const out: Record<string, ChunkView[]> = {}
  for (const c of childChunks.value) {
    if (!c.parentId) continue
    const key = String(c.parentId)
    if (!out[key]) out[key] = []
    out[key].push(c)
  }
  for (const key of Object.keys(out)) {
    out[key].sort((a, b) => a.chunkIndex - b.chunkIndex)
  }
  return out
})

const searchActive = computed(() => searchText.value.trim().length > 0)

function isExpanded(parentId: number) {
  return Boolean(expandedParents.value[String(parentId)])
}

function toggleExpanded(parentId: number) {
  const key = String(parentId)
  expandedParents.value[key] = !expandedParents.value[key]
}

function scrollToParent(parentId: number) {
  activeParentId.value = parentId
  expandedParents.value[String(parentId)] = true
  const el = document.getElementById(`parent-${parentId}`)
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function scrollToOutlineNode(node: any) {
  const idxRaw = node?.parent_chunk_index
  const idx = Number.parseInt(String(idxRaw ?? ''), 10)
  if (!Number.isFinite(idx)) return

  const p = parentChunks.value.find((x) => x.chunkIndex === idx)
  if (p) {
    scrollToParent(p.id)
    return
  }

  if (hasMore.value) {
    ElMessage.info('该章节对应的 chunk 还没加载，先点 “Load More Chunks”')
  } else {
    ElMessage.warning('未找到该章节对应的 parent chunk')
  }
}

function childrenForParent(parentId: number) {
  const kids = childrenByParentId.value[String(parentId)] || []
  const q = searchText.value.trim().toLowerCase()
  if (!q) return kids
  return kids.filter((c) => (c.content || '').toLowerCase().includes(q))
}

const parentLabelById = computed<Record<string, string>>(() => {
  const out: Record<string, string> = {}
  for (const p of parentChunks.value) {
    out[String(p.id)] = extractSectionTitle(p.content) || p.displayId
  }
  return out
})

const filteredParents = computed(() => {
  const q = searchText.value.trim().toLowerCase()
  if (!q) return parentChunks.value

  return parentChunks.value.filter((p) => {
    if ((p.content || '').toLowerCase().includes(q)) return true
    const kids = childrenByParentId.value[String(p.id)] || []
    return kids.some((c) => (c.content || '').toLowerCase().includes(q))
  })
})

const outlineTree = computed<OutlineNode[]>(() => {
  return outlineItems.value || []
})

// outlineTree is used for the left outline panel.

const activeParentChunkIndex = computed<number | null>(() => {
  const id = activeParentId.value
  if (!id) return null
  const hit = parentChunks.value.find((p) => p.id === id)
  return hit ? hit.chunkIndex : null
})

const chunkCountLabel = computed(() => {
  const count = doc.value?.chunk_count ?? chunks.value.length
  return `${count} Chunks Generated`
})

const totalTokensEstimate = computed(() => chunks.value.reduce((sum, c) => sum + (c.tokens || 0), 0))

const docMetaLabel = computed(() => {
  const d = doc.value
  if (!d) return '—'
  const parts = [formatBytes(d.file_size), (d.file_type || 'document').toUpperCase()]
  return parts.filter(Boolean).join(' • ')
})

function setActiveChunk(id: number) {
  activeChunkId.value = id
  const hit = chunks.value.find((c) => c.id === id)
  if (hit?.parentId) activeParentId.value = hit.parentId
}

async function loadInitial() {
  if (!kbId.value || !docId.value) {
    ElMessage.error('Missing kbId/docId in URL')
    return
  }
  loading.value = true
  try {
    const [kbRes, chunkRes, outlineRes] = await Promise.all([
      apiClient.getKnowledgeBase(kbId.value),
      apiClient.listDocumentChunks(kbId.value, docId.value, { offset: 0, limit: pageSize, include_parents: true }),
      apiClient.getDocumentOutline(kbId.value, docId.value).catch(() => null),
    ])

    kb.value = kbRes as KB
    doc.value = (chunkRes.document || null) as Doc | null

    cleaningRules.value = normalizeCleaningRules((kbRes as any)?.cleaning_rules)
    chunkingStrategy.value = {
      maxTokenLimit: Number((kbRes as any)?.chunk_size ?? 500) || 500,
      chunkOverlap: Number((kbRes as any)?.chunk_overlap ?? 50) || 50,
    }

    const rows = (chunkRes.items || []) as ChunkRow[]
    chunks.value = rows.map(mapChunkRow)
    offset.value = rows.length
    hasMore.value = rows.length >= pageSize

    outlineItems.value = ((outlineRes as any)?.items || []) as OutlineNode[]
    outlineExtraction.value = (outlineRes as any)?.extraction ?? null

    // Default: select the first section (collapsed).
    if (parentChunks.value.length) {
      const candidate =
        parentChunks.value.find((p) => childChunks.value.some((c) => c.parentId === p.id)) || parentChunks.value[0]
      activeParentId.value = candidate.id
    }

    if (!activeChunkId.value) {
      activeChunkId.value = childChunks.value[0]?.id ?? chunks.value[0]?.id ?? null
    }
  } catch (e: any) {
    ElMessage.error('Failed to load document')
    kb.value = null
    doc.value = null
    chunks.value = []
    hasMore.value = false
  } finally {
    loading.value = false
  }
}

async function loadMore() {
  if (!kbId.value || !docId.value) return
  if (!hasMore.value || loadingMore.value) return
  loadingMore.value = true
  try {
    const res = await apiClient.listDocumentChunks(kbId.value, docId.value, {
      offset: offset.value,
      limit: pageSize,
      include_parents: true,
    })
    const rows = (res.items || []) as ChunkRow[]
    const existing = new Set(chunks.value.map((c) => c.id))
    for (const r of rows) {
      const mapped = mapChunkRow(r)
      if (!existing.has(mapped.id)) {
        chunks.value.push(mapped)
        existing.add(mapped.id)
      }
    }
    offset.value += rows.length
    hasMore.value = rows.length >= pageSize
  } catch {
    ElMessage.error('Failed to load more chunks')
  } finally {
    loadingMore.value = false
  }
}

async function saveKbSettings() {
  if (!kbId.value) return
  if (!isAdmin) {
    ElMessage.warning('Admin role required')
    return
  }
  saving.value = true
  try {
    const patch = {
      chunk_size: Number(chunkingStrategy.value.maxTokenLimit) || 500,
      chunk_overlap: Number(chunkingStrategy.value.chunkOverlap) || 0,
      cleaning_rules: { ...cleaningRules.value },
    }
    const updated = await apiClient.updateKnowledgeBase(kbId.value, patch)
    kb.value = updated as KB
    ElMessage.success('Saved')
  } catch (e: any) {
    ElMessage.error('Save failed')
  } finally {
    saving.value = false
  }
}

async function previewChunks() {
  if (!kbId.value || !docId.value) return
  if (!isAdmin) {
    ElMessage.warning('Admin role required')
    return
  }
  try {
    const res = await apiClient.previewDocumentChunks(kbId.value, docId.value, {
      chunk_size: Number(chunkingStrategy.value.maxTokenLimit) || 500,
      chunk_overlap: Number(chunkingStrategy.value.chunkOverlap) || 0,
      cleaning_rules: { ...cleaningRules.value },
      limit: 80,
    })
    previewData.value = res
    previewDialogOpen.value = true
  } catch (e: any) {
    ElMessage.error('Preview failed')
  }
}

async function regenerateDocument() {
  if (!kbId.value || !docId.value) return
  if (!isAdmin) {
    ElMessage.warning('Admin role required')
    return
  }
  try {
    await apiClient.reindexDocument(kbId.value, docId.value)
    ElMessage.success('Reindex queued')
  } catch {
    ElMessage.error('Failed to queue reindex')
  }
}

function exitEditor() {
  router.push('/finance-docs')
}

onMounted(loadInitial)

watch(
  () => [kbId.value, docId.value],
  () => {
    chunks.value = []
    outlineItems.value = []
    outlineExtraction.value = null
    offset.value = 0
    hasMore.value = true
    activeChunkId.value = null
    activeParentId.value = null
    loadInitial()
  }
)
</script>

<template>
  <el-container class="editor-layout">
    <!-- Top Header -->
    <el-header class="editor-header">
      <div class="header-left">
        <div class="brand">
          <el-icon class="brand-icon"><Connection /></el-icon>
          <span class="brand-name">Knowledge Base Agent</span>
        </div>
        <div class="divider"></div>
        <el-breadcrumb :separator-icon="ArrowRight">
          <el-breadcrumb-item>Documents</el-breadcrumb-item>
          <el-breadcrumb-item class="active-crumb">{{ doc?.filename || 'Document' }}</el-breadcrumb-item>
        </el-breadcrumb>
      </div>
      <div class="header-right">
        <el-button plain class="btn-secondary" @click="exitEditor">Exit Editor</el-button>
        <el-button type="primary" class="btn-primary" disabled>Deploy Agent</el-button>
        <el-avatar :size="36" class="user-avatar">AM</el-avatar>
      </div>
    </el-header>

    <el-container class="main-body">
      <!-- Left Sidebar: Outline -->
      <el-aside width="320px" class="outline-sidebar">
        <div class="doc-meta">
          <div class="doc-info-card">
            <div class="doc-icon">
              <el-icon><Document /></el-icon>
            </div>
            <div class="doc-details">
              <div class="doc-title">{{ doc?.filename || '—' }}</div>
              <div class="doc-sub">{{ docMetaLabel }}</div>
            </div>
          </div>
          <div class="doc-stats">
            <div class="stat-box">
              <span class="stat-label">Total Tokens</span>
              <span class="stat-value">{{ totalTokensEstimate.toLocaleString() }}</span>
            </div>
            <div class="stat-box">
              <span class="stat-label">Chunks</span>
              <span class="stat-value">{{ (doc?.chunk_count ?? chunks.length).toLocaleString() }}</span>
            </div>
          </div>
        </div>

         <div class="outline-nav">
           <div class="nav-title">DOCUMENT OUTLINE</div>
           <el-scrollbar>
             <el-tree
               class="outline-tree"
               :data="outlineTree"
               node-key="id"
               :expand-on-click-node="false"
               :default-expand-all="false"
               @node-click="scrollToOutlineNode"
             >
               <template #default="{ data }">
                  <div class="tree-row" :class="{ active: Number(data.parent_chunk_index) === activeParentChunkIndex }">
                   <span class="tree-dot" />
                   <span class="tree-label">{{ data.title }}</span>
                 </div>
               </template>
             </el-tree>
           </el-scrollbar>
         </div>
        
        <div class="sidebar-footer">
          Last synced: Today, 10:23 AM
        </div>
      </el-aside>

      <!-- Center: Editor -->
      <el-main class="editor-main">
        <div class="toolbar-sticky">
          <div class="toolbar-left">
            <span class="chunk-count">{{ chunkCountLabel }}</span>
            <div class="v-divider"></div>
            <el-button
              link
              type="primary"
              :icon="Refresh"
              class="regenerate-btn"
              :disabled="!isAdmin"
              @click="regenerateDocument"
            >
              Regenerate Document
            </el-button>
          </div>
          <div class="toolbar-right">
            <el-input
              placeholder="Find in chunks..."
              :prefix-icon="Search"
              class="chunk-search"
              v-model="searchText"
            />
          </div>
        </div>

        <div class="chunk-list">
          <div v-if="!filteredParents.length" class="empty-chunks">
            <div class="empty-title">No sections to show</div>
            <div class="empty-sub">
              <span v-if="searchText.trim()">Try a different search query.</span>
              <span v-else-if="hasMore">Load more to fetch chunks.</span>
              <span v-else>Document has no hierarchical chunks.</span>
            </div>
          </div>

          <div
            v-for="p in filteredParents"
            :id="`parent-${p.id}`"
            :key="p.id"
            class="parent-card"
          >
            <div class="parent-head" @click="activeParentId = p.id">
            <div class="parent-head-left">
              <span class="chunk-id">{{ p.displayId }}</span>
              <span class="chunk-id chunk-id-secondary">{{ p.globalDisplayId }}</span>
              <el-tag size="small" effect="light" class="chunk-tag">Section</el-tag>
              <span class="parent-title">{{ parentLabelById[String(p.id)] || p.displayId }}</span>
            </div>
              <div class="parent-head-right">
                <div class="token-badge">
                  <el-icon><Coin /></el-icon>
                  {{ p.tokens }} Tokens
                </div>
                <el-button link type="primary" @click.stop="toggleExpanded(p.id)">
                  {{ isExpanded(p.id) ? 'Collapse' : 'Expand' }}
                </el-button>
              </div>
            </div>

            <div class="parent-content">
              <div class="content-md" :class="{ collapsed: !isExpanded(p.id) }">
                <MarkdownRenderer :content="p.content" :auto-math="true" />
              </div>
            </div>

            <div v-if="isExpanded(p.id) || searchActive" class="children-block">
              <div class="children-title">
                Child Chunks ({{ childrenForParent(p.id).length }})
              </div>
              <div v-if="!childrenForParent(p.id).length" class="children-empty">
                No child chunks loaded. <span v-if="hasMore">Use "Load More Chunks" to fetch more.</span>
              </div>

              <div
                v-for="chunk in childrenForParent(p.id)"
                :key="chunk.id"
                class="chunk-card child-card"
                :class="{ active: chunk.id === activeChunkId }"
                @click="setActiveChunk(chunk.id)"
              >
                <div class="chunk-header">
                  <div class="header-info">
                    <span class="chunk-id">{{ chunk.displayId }}</span>
                    <span class="chunk-id chunk-id-secondary">{{ chunk.globalDisplayId }}</span>
                    <el-tag size="small" effect="light" class="chunk-tag">{{ chunk.tag }}</el-tag>
                  </div>
                  <div class="header-actions">
                    <div class="token-badge">
                      <el-icon><Coin /></el-icon>
                      {{ chunk.tokens }} Tokens
                    </div>
                  </div>
              </div>
              <div class="chunk-content">
                  <div class="content-md" :class="{ collapsed: chunk.id !== activeChunkId }">
                    <MarkdownRenderer :content="chunk.content" :auto-math="true" />
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div class="load-more" v-if="hasMore">
            <el-button round class="load-more-btn" :loading="loadingMore" @click="loadMore">
              Load More Chunks
              <el-icon class="el-icon--right"><ArrowRight /></el-icon>
            </el-button>
          </div>
        </div>
      </el-main>

      <!-- Right Sidebar: Rules -->
      <el-aside width="320px" class="rules-sidebar">
        <div class="sidebar-header-title">
          <el-icon color="#0d776e"><Setting /></el-icon>
          <span>Cleaning Rules</span>
        </div>

        <el-scrollbar class="rules-content">
          <div class="rule-section">
            <div class="section-title">TEXT FORMATTING</div>
            <div class="rule-item">
              <div class="rule-label">
                <div class="title">Remove Whitespace</div>
                <div class="desc">Trims excessive spaces and line breaks.</div>
              </div>
              <el-switch v-model="cleaningRules.removeWhitespace" />
            </div>
            <div class="rule-item">
              <div class="rule-label">
                <div class="title">Strip HTML Tags</div>
                <div class="desc">Removes all HTML markup tags.</div>
              </div>
              <el-switch v-model="cleaningRules.stripHtml" />
            </div>
            <div class="rule-item">
              <div class="rule-label">
                <div class="title">Fix Encoding</div>
                <div class="desc">Corrects garbled characters.</div>
              </div>
              <el-switch v-model="cleaningRules.fixEncoding" />
            </div>
          </div>

          <div class="h-divider"></div>

          <div class="rule-section">
            <div class="section-title">CHUNKING STRATEGY</div>
            <div class="slider-item">
              <div class="slider-label">
                <span>Chunk Size</span>
                <el-tag size="small" type="primary" class="slider-value">{{ chunkingStrategy.maxTokenLimit }}</el-tag>
              </div>
              <el-slider v-model="chunkingStrategy.maxTokenLimit" :min="128" :max="4096" />
              <div class="slider-range">
                <span>128</span>
                <span>4096</span>
              </div>
            </div>
            <div class="slider-item">
              <div class="slider-label">
                <span>Chunk Overlap</span>
                <el-tag size="small" type="primary" class="slider-value">{{ chunkingStrategy.chunkOverlap }}</el-tag>
              </div>
              <el-slider v-model="chunkingStrategy.chunkOverlap" :min="0" :max="512" />
              <div class="slider-range">
                <span>0</span>
                <span>512</span>
              </div>
            </div>
          </div>

          <div class="h-divider"></div>

          <div class="rule-section">
            <div class="section-title">ADVANCED</div>
            <div class="rule-item">
              <div class="rule-label">
                <div class="title">Consolidate Short Paragraphs</div>
              </div>
              <el-switch v-model="cleaningRules.consolidateShortParagraphs" />
            </div>
          </div>
        </el-scrollbar>

        <div class="rules-footer">
          <el-button type="primary" class="btn-save" :loading="saving" :disabled="!isAdmin" @click="saveKbSettings">Save Changes</el-button>
          <el-button plain class="btn-preview" :disabled="!isAdmin" @click="previewChunks">
            <el-icon><View /></el-icon> Preview Result
          </el-button>
          <el-button plain class="btn-preview" :disabled="!isAdmin" @click="regenerateDocument">
            <el-icon><Refresh /></el-icon> Reindex Document
          </el-button>
          <p class="reindex-note">Changes will require re-indexing.</p>
        </div>
      </el-aside>
    </el-container>
  </el-container>

  <el-dialog v-model="previewDialogOpen" title="Preview Chunks" width="900px">
    <div v-if="!previewData">No preview data.</div>
    <div v-else>
      <div style="display:flex; justify-content: space-between; margin-bottom: 12px; gap: 12px; flex-wrap: wrap;">
        <div>
          <div style="font-weight: 600;">Effective Settings</div>
          <div style="font-size: 12px; color: #6b7280;">
            chunk_size={{ previewData.effective?.chunk_size }} • chunk_overlap={{ previewData.effective?.chunk_overlap }}
          </div>
        </div>
        <div style="font-size: 12px; color: #6b7280;">
          parents={{ previewData.counts?.parents }} • children={{ previewData.counts?.children }}
        </div>
      </div>
      <el-scrollbar height="520px">
        <div style="display:flex; flex-direction: column; gap: 12px;">
          <div v-for="(it, i) in (previewData.items || [])" :key="i" style="border: 1px solid #e5e7eb; border-radius: 6px; padding: 12px; background: #fff;">
            <div style="display:flex; justify-content: space-between; gap: 12px; margin-bottom: 6px;">
              <div style="font-size: 12px; color: #6b7280; font-family: monospace;">
                #{{ String(it.chunk_index).padStart(3, '0') }}
              </div>
              <div style="font-size: 12px; color: #6b7280;">
                {{ it.is_parent ? 'Parent' : 'Chunk' }} • {{ it.tokens_estimate }} tokens
              </div>
            </div>
            <div class="preview-md">
              <MarkdownRenderer :content="String(it.content || '')" :auto-math="true" />
            </div>
          </div>
        </div>
      </el-scrollbar>
    </div>
  </el-dialog>
</template>

<style scoped>
.editor-layout {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background-color: #f7f7f8;
  color: #2e3136;
  font-family: 'Inter', sans-serif;
}

/* Header */
.editor-header {
  height: 64px;
  background-color: #f8fcfb;
  border-bottom: 3px solid #dce2e5;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  flex-shrink: 0;
  z-index: 100;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #0e1b1a;
}

.brand-icon {
  font-size: 24px;
  color: #0d776e;
}

.brand-name {
  font-size: 18px;
  font-weight: 700;
  letter-spacing: -0.015em;
}

.divider {
  width: 1px;
  height: 24px;
  background-color: #dce2e5;
  margin: 0 8px;
}

.active-crumb {
  font-weight: 500;
  color: #2e3136;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.btn-primary {
  background-color: #0d776e;
  border-color: #0d776e;
  font-weight: 700;
}

.btn-primary:hover {
  background-color: #0a5f58;
  border-color: #0a5f58;
}

.btn-secondary {
  border-color: #dce2e5;
  color: #2e3136;
  font-weight: 500;
}

.user-avatar {
  background-color: #0d776e;
  color: white;
  font-weight: 600;
}

/* Main Body */
.main-body {
  flex: 1;
  overflow: hidden;
}

/* Left Sidebar */
.outline-sidebar {
  background-color: #edf0f1;
  border-right: 1px solid #dce2e5;
  display: flex;
  flex-direction: column;
}

.doc-meta {
  padding: 20px;
  border-bottom: 2px solid #dce2e5;
  background: rgba(237, 240, 241, 0.5);
}

.doc-info-card {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}

.doc-icon {
  width: 40px;
  height: 40px;
  background: white;
  border: 1px solid #dce2e5;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #ef4444;
  box-shadow: 0 1px 2px rgba(0,0,0,0.05);
}

.doc-title {
  font-size: 14px;
  font-weight: 700;
  color: #2e3136;
  margin-bottom: 4px;
}

.doc-sub {
  font-size: 12px;
  color: #6b7280;
}

.doc-stats {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.stat-box {
  background: white;
  padding: 10px;
  border-radius: 4px;
  border: 1px solid #dce2e5;
}

.stat-label {
  display: block;
  font-size: 11px;
  color: #9ca3af;
  margin-bottom: 4px;
}

.stat-value {
  font-size: 14px;
  font-weight: 600;
  color: #2e3136;
}

.outline-nav {
  flex: 1;
  padding: 16px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.outline-tree {
  background: transparent;
}

:deep(.outline-tree .el-tree-node__content) {
  height: 34px;
  padding: 0 6px;
  border-radius: 6px;
}

:deep(.outline-tree .el-tree-node__content:hover) {
  background: rgba(13, 119, 110, 0.06);
}

.tree-row {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  min-width: 0;
  color: #2e3136;
  font-weight: 600;
}

.tree-row.active {
  color: #0d776e;
}

.tree-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: rgba(13, 119, 110, 0.35);
  flex-shrink: 0;
}

.tree-row.active .tree-dot {
  background: #0d776e;
}

.tree-label {
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.nav-title {
  font-size: 11px;
  font-weight: 700;
  color: #9ca3af;
  letter-spacing: 0.05em;
  margin-bottom: 12px;
  padding: 0 8px;
}

.nav-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px;
  font-size: 14px;
  color: #4b5563;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}

.nav-item:hover {
  background-color: white;
  color: #2e3136;
  box-shadow: 0 1px 2px rgba(0,0,0,0.05);
}

.nav-item.active {
  background-color: white;
  color: #0d776e;
  font-weight: 500;
  border: 1px solid #dce2e5;
  box-shadow: 0 1px 2px rgba(0,0,0,0.05);
}

.nav-item.indent {
  padding-left: 20px;
}

.nav-icon {
  font-size: 18px;
}

.nav-item.indent .nav-icon {
  font-size: 16px;
  opacity: 0.5;
}

.sidebar-footer {
  padding: 16px;
  border-top: 1px solid #dce2e5;
  background: white;
  font-size: 11px;
  color: #9ca3af;
  text-align: center;
}

/* Editor Main */
.editor-main {
  flex: 1;
  padding: 0;
  background-color: #f7f7f8;
  display: flex;
  flex-direction: column;
}

.toolbar-sticky {
  position: sticky;
  top: 0;
  z-index: 10;
  background: rgba(247, 247, 248, 0.95);
  backdrop-filter: blur(4px);
  padding: 12px 24px;
  border-bottom: 1px solid #dce2e5;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.chunk-count {
  font-size: 14px;
  font-weight: 600;
  color: #374151;
}

.v-divider {
  width: 1px;
  height: 16px;
  background-color: #dce2e5;
}

.regenerate-btn {
  font-size: 12px;
  font-weight: 500;
  color: #0d776e;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.chunk-search {
  width: 180px;
}

:deep(.chunk-search .el-input__wrapper) {
  border-radius: 6px;
  box-shadow: 0 0 0 1px #dce2e5 inset;
}

/* Chunk List */
.chunk-list {
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: 900px;
  margin: 0 auto;
  width: 100%;
}


.parent-card {
  border: 1px solid rgba(220, 226, 229, 0.9);
  background: #ffffff;
  border-radius: 10px;
  overflow: hidden;
}

.parent-head {
  padding: 10px 14px;
  background: rgba(249, 250, 251, 0.7);
  border-bottom: 1px solid #f3f4f6;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.parent-head-left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.parent-title {
  font-size: 13px;
  font-weight: 900;
  color: #0f181a;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.parent-head-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.parent-content {
  padding: 12px 14px;
}

.children-block {
  padding: 10px 14px 14px;
  border-top: 1px solid rgba(220, 226, 229, 0.7);
  background: rgba(248, 250, 252, 0.7);
}

.children-title {
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #6b7280;
  margin-bottom: 10px;
}

.children-empty {
  padding: 10px 12px;
  border: 1px dashed #cbd5e1;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.9);
  font-size: 12px;
  font-weight: 700;
  color: #6b7280;
}

.child-card {
  margin-top: 10px;
}

.empty-chunks {
  border: 1px dashed #cbd5e1;
  background: rgba(248, 250, 252, 0.7);
  border-radius: 10px;
  padding: 18px;
}

.empty-title {
  font-weight: 700;
  color: #0f181a;
}

.empty-sub {
  margin-top: 6px;
  font-size: 13px;
  color: #538893;
}

.chunk-card {
  background: white;
  border: 1px solid #dce2e5;
  border-radius: 6px;
  transition: all 0.2s;
  overflow: hidden;
}

.chunk-card:hover {
  border-color: rgba(13, 119, 110, 0.5);
  box-shadow: 0 2px 4px rgba(0,0,0,0.05);
}

.chunk-card.active {
  border-color: #0d776e;
  box-shadow: 0 4px 12px rgba(13, 119, 110, 0.08), 0 0 0 1px rgba(13, 119, 110, 0.2);
}

.chunk-header {
  padding: 8px 16px;
  background: rgba(249, 250, 251, 0.5);
  border-bottom: 1px solid #f3f4f6;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.chunk-card.active .chunk-header {
  background: rgba(13, 119, 110, 0.05);
  border-bottom-color: rgba(13, 119, 110, 0.1);
}

.chunk-id {
  font-family: monospace;
  font-size: 12px;
  font-weight: 700;
  color: #9ca3af;
  margin-right: 12px;
}

.chunk-id-secondary {
  font-size: 11px;
  font-weight: 600;
  color: rgba(156, 163, 175, 0.8);
  margin-right: 10px;
}

.chunk-card.active .chunk-id {
  color: #0d776e;
}

.chunk-tag {
  background-color: #f3f4f6;
  border: 1px solid #e5e7eb;
  color: #6b7280;
  font-weight: 700;
  font-size: 10px;
  padding: 0 8px;
}

.chunk-card.active .chunk-tag {
  background-color: rgba(13, 119, 110, 0.1);
  border-color: rgba(13, 119, 110, 0.2);
  color: #0d776e;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.token-badge {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  font-weight: 500;
  color: #6b7280;
  background: white;
  padding: 2px 8px;
  border-radius: 4px;
  border: 1px solid #dce2e5;
}

.chunk-content {
  padding: 16px;
}

.content-text {
  font-size: 14px;
  line-height: 1.6;
  color: #2e3136;
  margin: 0;
  white-space: pre-wrap;
}

.content-md {
  font-size: 14px;
  line-height: 1.6;
}

.content-md.collapsed {
  max-height: 220px;
  overflow: hidden;
  position: relative;
}

.content-md.collapsed::after {
  content: "";
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 56px;
  background: linear-gradient(to bottom, rgba(255, 255, 255, 0), rgba(255, 255, 255, 1));
  pointer-events: none;
}

.content-md :deep(.markdown-body) {
  padding: 0;
  background: transparent;
}

.preview-md :deep(.markdown-body) {
  padding: 0;
  background: transparent;
}

:deep(.content-editor .el-textarea__inner) {
  border: none;
  padding: 0;
  font-size: 14px;
  line-height: 1.6;
  color: #2e3136;
  background: transparent;
}

:deep(.content-editor .el-textarea__inner:focus) {
  box-shadow: none;
}

.delete-btn:hover {
  color: #ef4444 !important;
}

.load-more {
  display: flex;
  justify-content: center;
  margin-top: 16px;
  padding-bottom: 40px;
}

.load-more-btn {
  font-size: 12px;
  font-weight: 500;
  padding: 8px 20px;
  color: #6b7280;
  box-shadow: 0 1px 2px rgba(0,0,0,0.05);
}

/* Right Sidebar */
.rules-sidebar {
  background-color: #edf0f1;
  border-left: 1px solid #dce2e5;
  display: flex;
  flex-direction: column;
}

.sidebar-header-title {
  padding: 20px;
  background: #edf0f1;
  border-bottom: 1px solid #dce2e5;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 700;
}

.rules-content {
  flex: 1;
  padding: 20px;
}

.rule-section {
  margin-bottom: 24px;
}

.section-title {
  font-size: 11px;
  font-weight: 700;
  color: #9ca3af;
  letter-spacing: 0.05em;
  margin-bottom: 16px;
}

.rule-item {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
}

.rule-label .title {
  font-size: 14px;
  font-weight: 500;
  color: #2e3136;
  margin-bottom: 4px;
}

.rule-label .desc {
  font-size: 12px;
  color: #6b7280;
}

.h-divider {
  height: 1px;
  background-color: #dce2e5;
  margin: 24px 0;
}

.slider-item {
  margin-bottom: 24px;
}

.slider-label {
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
  font-size: 14px;
  font-weight: 500;
}

.slider-value {
  background-color: rgba(13, 119, 110, 0.1);
  color: #0d776e;
  border: none;
  font-weight: 700;
}

:deep(.el-slider__bar) {
  background-color: #0d776e;
}

:deep(.el-slider__button) {
  border-color: #0d776e;
}

.slider-range {
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  color: #9ca3af;
  margin-top: 4px;
}

.rules-footer {
  padding: 20px;
  background: white;
  border-top: 1px solid #dce2e5;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.btn-save {
  width: 100%;
  height: 40px;
  background-color: #0d776e;
  border-color: #0d776e;
  font-weight: 700;
  box-shadow: 0 4px 6px -1px rgba(13, 119, 110, 0.2);
}

.btn-preview {
  width: 100%;
  height: 40px;
  font-weight: 700;
  color: #2e3136;
}

.reindex-note {
  font-size: 10px;
  color: #9ca3af;
  text-align: center;
  margin: 0;
}

/* Switches color */
:deep(.el-switch.is-checked .el-switch__core) {
  background-color: #0d776e;
}
</style>
