<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import apiClient, { DEV_USER_ROLE } from '@/api/client'
import { useTheme } from '@/composables/useTheme'
import {
  ArrowDown,
  Download,
  InfoFilled,
  MoreFilled,
  Refresh,
  Search,
  Star,
  Bell,
} from '@element-plus/icons-vue'
import MarkdownRenderer from '@/components/chat/MarkdownRenderer.vue'

type Mode = 'vector' | 'graph'

type KB = {
  id: number
  name: string
  description?: string
}

type ResultRow = {
  id: string
  rank: number
  score: number
  source: string
  snippet: string
  fullSnippet: string
  documentId?: number
  label: number // 0..3
}

type EvalCase = {
  id: number
  query: string
  expected_sources: string[]
  notes?: string | null
  tags: string[]
  created_at?: string | null
  updated_at?: string | null
}

const router = useRouter()
const route = useRoute()

const { toggleTheme } = useTheme()

const isAdmin = DEV_USER_ROLE === 'admin'

const kbList = ref<KB[]>([])
const selectedKbId = ref<number | null>(null)
const labDatasetId = ref<number | null>(null)

const mode = ref<Mode>('vector')
const topK = ref(12)

const headerSearch = ref('')
const query = ref("What are the liability limitations in Section 4.2?")

const loading = ref(false)
const evaluating = ref(false)

const savedCases = ref<EvalCase[]>([])
const selectedCaseId = ref<number | null>(null)
const selectedCase = ref<EvalCase | null>(null)

const results = ref<ResultRow[]>([])

const snippetDialogOpen = ref(false)
const snippetDialogTitle = ref('')
const snippetDialogText = ref('')

const expectedSources = ref<string[]>([])

const judgeAnswer = ref(
  ''
)
const judgeMetrics = ref<any>(null)

function _tagValue(tags: string[], key: string): string | null {
  const prefix = `${key}=`
  for (const t of tags || []) {
    if (typeof t === 'string' && t.startsWith(prefix)) return t.slice(prefix.length)
    if (typeof t === 'string' && t.startsWith(`lab:${prefix}`)) return t.slice(`lab:`.length + prefix.length)
  }
  return null
}

function caseMeta(c: EvalCase): { mode: Mode; topK: number } {
  const m = (_tagValue(c.tags || [], 'mode') || '').toLowerCase()
  const k = Number.parseInt(_tagValue(c.tags || [], 'topk') || '', 10)
  const modeVal: Mode = m === 'graph' ? 'graph' : 'vector'
  const topKVal = Number.isFinite(k) && k > 0 ? k : 12
  return { mode: modeVal, topK: topKVal }
}

function caseTitle(c: EvalCase): string {
  const q = String(c.query || '').trim()
  if (!q) return `Case #${c.id}`
  return q.length > 36 ? q.slice(0, 36).trimEnd() + '…' : q
}

function formatCaseMeta(c: EvalCase): string {
  const { mode: m, topK: k } = caseMeta(c)
  const dt = c.created_at ? new Date(c.created_at) : null
  const d = dt && !Number.isNaN(dt.getTime()) ? dt.toLocaleDateString() : ''
  return `TopK: ${k} • ${m.toUpperCase()}${d ? ` • ${d}` : ''}`
}

function formatScore(v: number) {
  if (!Number.isFinite(v)) return '—'
  return v.toFixed(3)
}

function formatSnippet(s: string, max = 220) {
  const oneLine = String(s || '').replace(/\s+/g, ' ').trim()
  if (oneLine.length <= max) return oneLine
  return oneLine.slice(0, max).trimEnd() + '…'
}

function openSnippet(row: ResultRow) {
  snippetDialogTitle.value = row.source
  snippetDialogText.value = row.fullSnippet || row.snippet || ''
  snippetDialogOpen.value = true
}

async function copySnippet() {
  const text = snippetDialogText.value || ''
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('Copied')
  } catch {
    ElMessage.warning('Copy failed')
  }
}

const selectedKbName = computed(() => {
  const kb = kbList.value.find((k) => k.id === selectedKbId.value)
  return kb?.name || 'Select Knowledge Base'
})

const chunksFoundLabel = computed(() => {
  const n = results.value.length
  return n ? `${n} CHUNKS FOUND` : ''
})

const labelCount = computed(() => results.value.filter((r) => r.label > 0).length)

const heatCells = computed(() => results.value.slice(0, 12).map((r) => r.label))

const judgeFaithfulness = computed(() => {
  const v = Number((judgeMetrics.value as any)?.faithfulness)
  return Number.isFinite(v) ? v : null
})
const judgeRelevance = computed(() => {
  const v = Number((judgeMetrics.value as any)?.answer_relevance)
  return Number.isFinite(v) ? v : null
})
const judgeReasoningText = computed(() => {
  const a = String((judgeMetrics.value as any)?.reasoning_faithfulness || '').trim()
  const b = String((judgeMetrics.value as any)?.reasoning_relevance || '').trim()
  if (!a && !b) return '—'
  return [a && `Faithfulness: ${a}`, b && `Relevance: ${b}`].filter(Boolean).join('\n\n')
})

function setLabel(rowId: string, next: number) {
  const n = Math.max(0, Math.min(3, next))
  results.value = results.value.map((r) => (r.id === rowId ? { ...r, label: n } : r))
}

function onLabelClick(row: ResultRow, idx: number) {
  // idx: 1..3
  // Toggle off if user clicks the already-selected level.
  if (row.label === idx) setLabel(row.id, 0)
  else setLabel(row.id, idx)
  syncExpectedSourcesFromLabels()
}

function openDoc(row: ResultRow) {
  if (!row.documentId || !selectedKbId.value) return
  router.push({ path: '/document-editor', query: { kbId: String(selectedKbId.value), docId: String(row.documentId) } })
}

function resetLabels() {
  results.value = results.value.map((r) => ({ ...r, label: 0 }))
  expectedSources.value = []
}

function exportJson() {
  const payload = {
    kb_id: selectedKbId.value,
    kb_name: selectedKbName.value,
    mode: mode.value,
    top_k: topK.value,
    query: query.value,
    results: results.value,
    expected_sources: expectedSources.value,
    judge: {
      answer: judgeAnswer.value,
      metrics: judgeMetrics.value,
    },
    exported_at: new Date().toISOString(),
  }
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `rag-eval-${Date.now()}.json`
  a.click()
  URL.revokeObjectURL(a.href)
}

async function runRetrieve() {
  if (!query.value.trim()) {
    ElMessage.warning('请输入 Query')
    return
  }

  // Keep the UI alive even if API is missing.
  loading.value = true
  try {
    const payload = {
      query: query.value.trim(),
      knowledge_base_id: selectedKbId.value || undefined,
      top_k: topK.value,
    }

    const res = mode.value === 'graph'
      ? await apiClient.ragGraphRetrieve(payload)
      : await apiClient.ragRetrieve(payload)

    const rows = Array.isArray((res as any)?.results) ? (res as any).results : []
    if (!rows.length) {
      results.value = []
      ElMessage.warning('检索接口返回空结果')
      return
    }

    const expected = new Set((expectedSources.value || []).map((s) => String(s || '').trim().toLowerCase()).filter(Boolean))

    results.value = rows.slice(0, topK.value).map((r: any, i: number) => {
      const source = String(r?.metadata?.source || `doc:${r.document_id}`)
      const isExpected = expected.has(source.trim().toLowerCase())
      const full = String(r.content || r.content_preview || '').trim()
      return {
        id: `api_${i}_${String(r.document_id || '')}_${String(r.chunk_index || '')}`,
        rank: i + 1,
        score: Number(r.score || 0),
        source,
        snippet: formatSnippet(full, 220),
        fullSnippet: full,
        documentId: Number(r.document_id || 0) || undefined,
        label: isExpected ? 3 : 0,
      }
    })
  } catch {
    ElMessage.error('检索接口暂不可用')
  } finally {
    loading.value = false
  }
}

async function evaluate() {
  if (!isAdmin) {
    ElMessage.warning('需要 admin 才能调用 Evaluate')
    return
  }
  evaluating.value = true
  try {
    const res = await apiClient.ragEvaluate({
      question: query.value.trim(),
      answer: judgeAnswer.value.trim(),
      contexts: results.value.map((r) => r.fullSnippet || r.snippet),
    })
    judgeMetrics.value = res
    ElMessage.success('Evaluate completed')
  } catch {
    judgeMetrics.value = null
    ElMessage.warning('Evaluate 接口暂不可用')
  } finally {
    evaluating.value = false
  }
}

async function loadCase(c: EvalCase) {
  selectedCaseId.value = c.id
  selectedCase.value = c
  const meta = caseMeta(c)
  mode.value = meta.mode
  topK.value = meta.topK
  query.value = c.query
  expectedSources.value = Array.isArray(c.expected_sources) ? c.expected_sources : []
  await runRetrieve()
}

async function ensureLabDataset() {
  const kbId = selectedKbId.value
  if (!kbId) return
  const res = await apiClient.listEvalDatasets(kbId)
  const items = (res.items || []) as any[]
  const hit = items.find((d) => String(d.name || '').trim() === 'Retrieval Lab')
  if (hit?.id) {
    labDatasetId.value = Number(hit.id)
    return
  }
  const created = await apiClient.createEvalDataset(kbId, { name: 'Retrieval Lab', description: 'Saved cases from /rag-eval' })
  labDatasetId.value = Number(created?.id)
}

async function refreshCases() {
  const kbId = selectedKbId.value
  const dsId = labDatasetId.value
  if (!kbId || !dsId) {
    savedCases.value = []
    return
  }
  const res = await apiClient.listEvalCases(kbId, dsId)
  savedCases.value = (res.items || []) as any
}

function syncExpectedSourcesFromLabels() {
  const picked = results.value
    .filter((r) => r.label >= 2)
    .map((r) => String(r.source || '').trim())
    .filter(Boolean)
  expectedSources.value = Array.from(new Set(picked))
}

async function saveCurrentCase() {
  if (!selectedKbId.value) {
    ElMessage.warning('请选择 Knowledge Base')
    return
  }
  await ensureLabDataset()
  if (!labDatasetId.value) {
    ElMessage.error('Failed to init Retrieval Lab dataset')
    return
  }
  const q = query.value.trim()
  if (!q) {
    ElMessage.warning('请输入 Query')
    return
  }

  syncExpectedSourcesFromLabels()

  const created = await apiClient.createEvalCase(selectedKbId.value, labDatasetId.value, {
    query: q,
    expected_sources: expectedSources.value,
    notes: undefined,
    tags: ['lab', `lab:mode=${mode.value}`, `lab:topk=${topK.value}`],
  })
  await refreshCases()
  selectedCaseId.value = Number(created?.id)
  selectedCase.value = created as any
  ElMessage.success('Case saved')
}

async function saveLabelsToCase() {
  if (!selectedCaseId.value) {
    ElMessage.warning('先选择一个 Saved Case')
    return
  }
  syncExpectedSourcesFromLabels()
  await apiClient.updateEvalCase(selectedCaseId.value, { expected_sources: expectedSources.value, tags: ['lab', `lab:mode=${mode.value}`, `lab:topk=${topK.value}`] })
  await refreshCases()
  ElMessage.success('Labels saved')
}

async function deleteCase(c: EvalCase) {
  if (!isAdmin) {
    ElMessage.warning('需要 admin')
    return
  }
  await ElMessageBox.confirm('删除这个 Saved Case？', 'Confirm', { type: 'warning' })
  await apiClient.deleteEvalCase(c.id)
  if (selectedCaseId.value === c.id) {
    selectedCaseId.value = null
    selectedCase.value = null
    expectedSources.value = []
  }
  await refreshCases()
  ElMessage.success('Deleted')
}

async function loadKbs() {
  try {
    const res = await apiClient.listKnowledgeBases()
    kbList.value = (res.items || []) as KB[]
  } catch {
    kbList.value = []
  }
}

const filteredCases = computed(() => {
  const q = headerSearch.value.trim().toLowerCase()
  if (!q) return (savedCases.value as any as EvalCase[])
  return (savedCases.value as any as EvalCase[]).filter((c) => {
    const s = `${c.query || ''} ${(c.tags || []).join(' ')} ${c.notes || ''}`.toLowerCase()
    return s.includes(q)
  })
})

function computeRetrievalMetrics(expected: string[], retrieved: string[]) {
  const exp = new Set((expected || []).map((s) => String(s || '').trim().toLowerCase()).filter(Boolean))
  if (!exp.size) {
    return { precision: null as number | null, mrr: null as number | null, ndcg: null as number | null, hitRank: null as number | null, hit: 0 }
  }
  const rels: number[] = []
  let hitRank: number | null = null
  for (let i = 0; i < retrieved.length; i++) {
    const src = String(retrieved[i] || '').trim().toLowerCase()
    const rel = exp.has(src) ? 1 : 0
    rels.push(rel)
    if (hitRank === null && rel) hitRank = i + 1
  }
  const mrr = hitRank ? 1 / hitRank : 0
  let dcg = 0
  for (let i = 0; i < rels.length; i++) {
    if (!rels[i]) continue
    dcg += 1 / Math.log2(i + 2)
  }
  const idealCount = Math.min(exp.size, rels.length)
  let idcg = 0
  for (let i = 0; i < idealCount; i++) {
    idcg += 1 / Math.log2(i + 2)
  }
  const ndcg = idcg > 0 ? dcg / idcg : 0
  const hit = hitRank ? 1 : 0
  const precision = retrieved.length ? (rels.reduce((a, b) => a + b, 0) / retrieved.length) : 0
  return { precision, mrr, ndcg, hitRank, hit }
}

const retrievalMetrics = computed(() => {
  const retrieved = results.value.map((r) => r.source).slice(0, topK.value)
  return computeRetrievalMetrics(expectedSources.value, retrieved)
})

onMounted(async () => {
  const rawKbId = String(route.query.kbId || '')
  const kbId = Number.parseInt(rawKbId, 10)
  if (Number.isFinite(kbId)) selectedKbId.value = kbId

  await loadKbs()
  if (!selectedKbId.value && kbList.value.length) selectedKbId.value = kbList.value[0].id

  try {
    await ensureLabDataset()
    await refreshCases()
  } catch {
    // ignore
  }
})

watch(
  () => route.query.kbId,
  async (v) => {
    const kbId = Number.parseInt(String(v || ''), 10)
    if (!Number.isFinite(kbId)) return
    selectedKbId.value = kbId
  }
)

watch(
  () => selectedKbId.value,
  async (kbId) => {
    if (!kbId) return
    selectedCaseId.value = null
    selectedCase.value = null
    expectedSources.value = []
    results.value = []
    judgeMetrics.value = null
    judgeAnswer.value = ''
    await ensureLabDataset()
    await refreshCases()
    router.replace({ path: '/rag-eval', query: { ...route.query, kbId: String(kbId) } })
  }
)
</script>

<template>
  <div class="rag-eval">
    <div class="page">
      <header class="header">
        <div class="header-left">
          <div class="brand">
            <div class="brand-icon">
              <span class="ms">biotech</span>
            </div>
            <div class="brand-title">Retrieval Quality Lab</div>
          </div>
          <div class="sep" />
          <nav class="nav">
            <router-link class="nav-link" :class="{ active: route.path === '/' }" to="/">Dashboard</router-link>
            <router-link class="nav-link" :class="{ active: route.path === '/finance-docs' }" to="/finance-docs">Knowledge Base</router-link>
            <router-link
              class="nav-link"
              :class="{ active: route.path === '/rag-eval' }"
              :to="selectedKbId ? { path: '/rag-eval', query: { kbId: String(selectedKbId) } } : { path: '/rag-eval' }"
            >
              Retrieval Lab
            </router-link>
            <router-link
              class="nav-link"
              :class="{ active: route.path === '/rag/datasets' }"
              :to="selectedKbId ? { path: '/rag/datasets', query: { kbId: String(selectedKbId) } } : { path: '/rag/datasets' }"
            >
              Datasets
            </router-link>
            <router-link
              class="nav-link"
              :class="{ active: route.path === '/rag/benchmarks' }"
              :to="selectedKbId ? { path: '/rag/benchmarks', query: { kbId: String(selectedKbId) } } : { path: '/rag/benchmarks' }"
            >
              Benchmarks
            </router-link>
          </nav>
        </div>

        <div class="header-right">
          <el-input v-model="headerSearch" class="header-search" :prefix-icon="Search" placeholder="Search benchmarks..." clearable />
          <el-button class="icon-button" circle :icon="Bell" />
          <el-button class="icon-button" circle :icon="MoreFilled" @click="toggleTheme" />
          <el-avatar :size="40" class="avatar" src="https://lh3.googleusercontent.com/aida-public/AB6AXuA5FL-nB-IA5tIut7DpxuCLF-OImVaJQWmRDYr_fmptoIFbyhVtKWV0Jf1ly_PoPSIHgtUSgPMgJh_UeZX7vexUkRvQTXl2YL4rEq-Agq6Pzpl2_dTz7Bx4Fr0AQVFsYfkHKZYxEypo1tUOluSDJSwaDPbSvqIVJXw7pbWJ3K124o-BpRmkoC7F6GAmE5A1MYwli5fWsVu0BnoVoywK17ZbxnY4goAF74LYT7kmPkw3jF0NlFXrNuVD7akbkhg73xIa_1rcFo_9TbE" />
        </div>
      </header>

      <div class="body">
        <aside class="left no-scrollbar">
          <div class="left-inner">
            <div class="block">
              <div class="label">Knowledge Base</div>
              <el-dropdown trigger="click" class="kb-dd" :hide-on-click="true">
                <el-button class="kb-btn" plain>
                  <span class="kb-name">{{ selectedKbName }}</span>
                  <el-icon class="kb-caret"><ArrowDown /></el-icon>
                </el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item v-for="kb in kbList" :key="kb.id" @click="selectedKbId = kb.id">
                      {{ kb.name }}
                    </el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>

            <div class="block">
              <div class="label">Retriever Type</div>
              <div class="seg">
                <button class="seg-btn" :class="{ on: mode === 'vector' }" @click="mode = 'vector'">VECTOR</button>
                <button class="seg-btn" :class="{ on: mode === 'graph' }" @click="mode = 'graph'">GRAPH</button>
              </div>
            </div>

            <div class="block">
              <div class="row">
                <div class="label">TopK Results</div>
                <div class="topk">{{ topK }}</div>
              </div>
              <el-slider v-model="topK" :min="1" :max="20" :show-tooltip="false" />
            </div>

            <el-button class="run" type="primary" :loading="loading" @click="runRetrieve">Run Retrieve</el-button>

            <div class="block">
              <h3 class="saved-title">Saved Cases</h3>
              <div class="saved-list">
                <div
                  v-for="c in filteredCases"
                  :key="c.id"
                  class="case"
                  :class="{ active: c.id === selectedCaseId }"
                  @click="loadCase(c)"
                >
                  <p class="case-title">{{ caseTitle(c) }}</p>
                  <p class="case-meta">{{ formatCaseMeta(c) }}</p>
                  <div style="display:flex; gap: 8px; align-items: center;">
                    <el-button class="case-load" plain size="small" @click.stop="loadCase(c)">Load</el-button>
                    <el-button
                      v-if="isAdmin"
                      class="case-load"
                      plain
                      size="small"
                      type="danger"
                      @click.stop="deleteCase(c)"
                    >
                      Delete
                    </el-button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </aside>

        <main class="main">
          <div class="main-inner">
            <section class="card query">
              <div class="card-head">
                <h3 class="card-title">Query Context</h3>
                <div class="actions">
                  <el-button class="ghost" text :icon="Refresh" @click="resetLabels">Reset</el-button>
                  <el-button class="ghost" text :icon="Download" @click="exportJson">Export</el-button>
                  <el-button class="ghost" text :disabled="!selectedCaseId" @click="saveLabelsToCase">Save Labels</el-button>
                  <el-button class="save" type="primary" :icon="Star" @click="saveCurrentCase">Save Case</el-button>
                </div>
              </div>
              <el-input v-model="query" type="textarea" :rows="3" class="query-input" placeholder="Enter your evaluation query here..." />
            </section>

            <section class="card table">
              <div class="card-head row-head">
                <h3 class="card-title">Retrieved Chunks</h3>
                <div v-if="chunksFoundLabel" class="pill">{{ chunksFoundLabel }}</div>
              </div>

              <div class="table-wrap">
                <table class="t">
                  <thead>
                    <tr>
                      <th>Rank</th>
                      <th>Score</th>
                      <th>Source/Path</th>
                      <th>Snippet</th>
                      <th class="center">Relevance</th>
                      <th class="col-open"><span class="sr-only">Open</span></th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="row in results" :key="row.id">
                      <td class="rank">#{{ row.rank }}</td>
                      <td>
                        <span class="score">{{ formatScore(row.score) }}</span>
                      </td>
                      <td class="source">{{ row.source }}</td>
                      <td class="snippet">
                        <button class="snippet-btn" type="button" @click="openSnippet(row)">{{ row.snippet }}</button>
                      </td>
                      <td class="center">
                        <div class="rel">
                          <button
                            class="dot"
                            :class="{ teal: row.label >= 1, orange: row.label === 1 }"
                            @click="onLabelClick(row, 1)"
                            aria-label="relevance 1"
                          />
                          <button
                            class="dot"
                            :class="{ teal: row.label >= 2 }"
                            @click="onLabelClick(row, 2)"
                            aria-label="relevance 2"
                          />
                          <button
                            class="dot"
                            :class="{ teal: row.label >= 3 }"
                            @click="onLabelClick(row, 3)"
                            aria-label="relevance 3"
                          />
                        </div>
                      </td>
                      <td class="right col-open">
                        <button
                          class="open"
                          :disabled="!row.documentId || !selectedKbId"
                          @click="openDoc(row)"
                          aria-label="Open in editor"
                        >
                          <span class="material-symbols-outlined">open_in_new</span>
                        </button>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>

            <el-dialog v-model="snippetDialogOpen" :title="snippetDialogTitle" width="720px">
              <div style="display:flex; justify-content: flex-end; margin-bottom: 10px;">
                <el-button size="small" plain @click="copySnippet">Copy</el-button>
              </div>
              <div class="snippet-md">
                <MarkdownRenderer :content="snippetDialogText" />
              </div>
            </el-dialog>

            <section class="card judge">
              <div class="judge-head">
                <div class="judge-title">
                  <span class="ms teal">auto_awesome</span>
                  <h3>LLM-as-a-Judge</h3>
                </div>
                <el-button type="primary" :loading="evaluating" @click="evaluate">Evaluate Results</el-button>
              </div>
              <div class="judge-grid">
                <div>
                  <div class="label">Answer (Paste / Generate)</div>
                  <el-input v-model="judgeAnswer" type="textarea" :autosize="{ minRows: 6, maxRows: 10 }" class="judge-answer" />
                </div>
                <div>
                  <div class="label">Judge Output</div>
                  <div class="chips">
                    <span class="chip teal"><span class="ms">verified</span> Faithfulness: {{ judgeFaithfulness === null ? '—' : judgeFaithfulness.toFixed(2) }}</span>
                    <span class="chip blue"><span class="ms">target</span> Relevance: {{ judgeRelevance === null ? '—' : judgeRelevance.toFixed(2) }}</span>
                  </div>
                  <div class="reason">
                    <div class="reason-title">Reasoning:</div>
                    <div class="reason-text" style="white-space: pre-wrap;">{{ judgeReasoningText }}</div>
                  </div>
                </div>
              </div>
            </section>
          </div>
        </main>

        <aside class="right no-scrollbar">
          <div class="right-inner">
            <div class="right-head">
              <div class="right-title">Retrieval Metrics</div>
              <el-button text class="info" :icon="InfoFilled" />
            </div>

            <div class="metric">
              <div class="metric-row">
                <div class="metric-name">Precision@K</div>
                <div class="metric-value">{{ retrievalMetrics.precision === null ? '—' : retrievalMetrics.precision.toFixed(2) }}</div>
              </div>
              <div class="bar"><div class="bar-fill" :style="{ width: `${Math.round(((retrievalMetrics.precision || 0) as number) * 100)}%` }"></div></div>
              <div class="metric-note">expected_sources={{ expectedSources.length }} • labeled={{ labelCount }} / {{ results.length }}</div>
            </div>

            <div class="metric">
              <div class="metric-row">
                <div class="metric-name">MRR</div>
                <div class="metric-value">{{ retrievalMetrics.mrr === null ? '—' : retrievalMetrics.mrr.toFixed(2) }}</div>
              </div>
              <div class="bar"><div class="bar-fill" :style="{ width: `${Math.round(((retrievalMetrics.mrr || 0) as number) * 100)}%` }"></div></div>
            </div>

            <div class="metric">
              <div class="metric-row">
                <div class="metric-name">nDCG</div>
                <div class="metric-value">{{ retrievalMetrics.ndcg === null ? '—' : retrievalMetrics.ndcg.toFixed(2) }}</div>
              </div>
              <div class="bar"><div class="bar-fill" :style="{ width: `${Math.round(((retrievalMetrics.ndcg || 0) as number) * 100)}%` }"></div></div>
            </div>

            <div class="sample">
              <div class="sample-row">
                <div class="label">Expected Sources</div>
                <div class="sample-value">{{ expectedSources.length }}</div>
              </div>
              <el-button class="export" plain :icon="Download" @click="exportJson">Export Full Report</el-button>
            </div>

            <div class="heat">
              <div class="heat-title">Retrieval Density</div>
              <div class="heat-grid">
                <span
                  v-for="(v, i) in heatCells"
                  :key="i"
                  class="h"
                  :class="{ teal: v >= 2, orange: v === 1, gray: v === 0, faint: v === 1 }"
                />
              </div>
            </div>
          </div>
        </aside>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* Match Stitch HTML structure and tone (Element Plus + custom CSS) */

.no-scrollbar {
  scrollbar-width: none;
  -ms-overflow-style: none;
}
.no-scrollbar::-webkit-scrollbar {
  display: none;
}

.rag-eval {
  --primary: #137fec;
  --teal: #2dd4bf;
  --bg: #f8fafc;
  --surface: #ffffff;
  --surface-2: #f1f5f9;
  --border: #e2e8f0;
  --text: #0f172a;
  --muted: #64748b;
  --muted-2: #94a3b8;
  --shadow: 0 1px 0 rgba(15, 23, 42, 0.03), 0 10px 22px rgba(2, 6, 23, 0.06);

  background: var(--bg);
  color: var(--text);
  min-height: 100vh;

  /* page-local Element Plus colors */
  --el-color-primary: var(--primary);
}

:root.dark .rag-eval {
  --bg: #101922;
  --surface: #101922;
  --surface-2: #0f172a;
  --border: #1f2937;
  --text: #e5e7eb;
  --muted: #94a3b8;
  --muted-2: #64748b;
  --shadow: 0 1px 0 rgba(255, 255, 255, 0.04), 0 16px 26px rgba(0, 0, 0, 0.35);
}

.page {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
}

.header {
  position: sticky;
  top: 0;
  z-index: 30;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 32px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 18px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
}

.brand-icon {
  color: var(--primary);
}

.brand-title {
  font-size: 16px;
  font-weight: 800;
  color: var(--text);
  letter-spacing: -0.01em;
}

.sep {
  width: 1px;
  height: 22px;
  background: var(--border);
}

.nav {
  display: flex;
  align-items: center;
  gap: 18px;
}

.nav-link {
  font-size: 13px;
  font-weight: 600;
  color: var(--muted);
  text-decoration: none;
}

.nav-link:hover {
  color: var(--text);
}

.nav-link.active {
  color: var(--primary);
}

.header-right {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  flex: 1;
}

.header-search {
  width: 380px;
}

.icon-button {
  background: #f1f5f9;
  border: 1px solid transparent;
  color: #475569;
}

:root.dark .icon-button {
  background: rgba(255, 255, 255, 0.06);
  color: rgba(255, 255, 255, 0.7);
}

.avatar {
  border: 1px solid var(--border);
}

.body {
  flex: 1;
  display: flex;
  min-height: 0;
  overflow: hidden;
}

.left {
  width: 320px;
  border-right: 1px solid var(--border);
  background: var(--surface);
  padding: 24px;
  min-height: 0;
  overflow: auto;
}

.left-inner {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.right {
  width: 288px;
  border-left: 1px solid var(--border);
  background: var(--surface);
  padding: 24px;
  min-height: 0;
  overflow: auto;
}

.main {
  flex: 1;
  padding: 32px;
  min-height: 0;
  overflow: auto;
  background: var(--bg);
}

.main-inner {
  max-width: 1024px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 28px;
}

.block {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.label {
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--muted-2);
}

.kb-btn {
  width: 100%;
  justify-content: space-between;
  border: 1px solid var(--border);
}

.kb-name {
  max-width: 230px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.seg {
  display: flex;
  gap: 6px;
  background: #f1f5f9;
  padding: 6px;
  border-radius: 10px;
}

:root.dark .seg {
  background: rgba(255, 255, 255, 0.06);
}

.seg-btn {
  flex: 1;
  border: 0;
  background: transparent;
  padding: 8px 10px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 800;
  color: var(--muted);
  cursor: pointer;
}

.seg-btn.on {
  background: var(--surface);
  box-shadow: var(--shadow);
  color: var(--text);
}

.row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.topk {
  color: var(--primary);
  font-weight: 900;
}

.run {
  width: 100%;
  border-radius: 10px;
  height: 44px;
  font-weight: 800;
  box-shadow: 0 14px 22px rgba(19, 127, 236, 0.20);
}

.saved-title {
  font-size: 14px;
  font-weight: 900;
  color: var(--text);
  margin: 0;
}

.saved-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.case {
  border: 1px solid rgba(226, 232, 240, 0.9);
  background: rgba(241, 245, 249, 0.55);
  border-radius: 16px;
  padding: 14px;
  cursor: pointer;
}

:root.dark .case {
  border-color: rgba(31, 41, 55, 0.9);
  background: rgba(148, 163, 184, 0.06);
}

.case.active {
  border-color: rgba(19, 127, 236, 0.35);
}

.case-title {
  margin: 0;
  font-size: 14px;
  font-weight: 900;
  color: var(--text);
}

.case-meta {
  margin: 6px 0 12px;
  font-size: 12px;
  color: var(--muted);
}

.case-load {
  width: 100%;
  font-weight: 800;
}

.card {
  background: var(--surface);
  border: 1px solid rgba(226, 232, 240, 0.7);
  border-radius: 12px;
  box-shadow: 0 1px 0 rgba(15, 23, 42, 0.03);
}

:root.dark .card {
  border-color: rgba(31, 41, 55, 0.8);
}

.card-head {
  padding: 24px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.card-title {
  margin: 0;
  font-size: 14px;
  font-weight: 900;
  color: var(--text);
}

.query {
  padding-bottom: 0;
}

.query-input {
  padding: 0 24px 24px;
}

.actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.ghost {
  color: var(--muted);
  font-weight: 800;
}

.save {
  font-weight: 900;
}

.table .row-head {
  border-bottom: 1px solid rgba(226, 232, 240, 0.7);
}

.pill {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 6px 10px;
  background: rgba(45, 212, 191, 0.12);
  color: rgba(6, 95, 70, 1);
  font-size: 10px;
  letter-spacing: 0.12em;
  font-weight: 900;
}

:root.dark .pill {
  color: var(--teal);
}

.table-wrap {
  overflow-x: auto;
}

.table {
  overflow: hidden;
}

.t {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.t thead th {
  background: rgba(241, 245, 249, 0.9);
  color: var(--muted-2);
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  padding: 16px 24px;
}

:root.dark .t thead th {
  background: rgba(148, 163, 184, 0.08);
}

.t tbody td {
  padding: 16px 24px;
  border-top: 1px solid rgba(226, 232, 240, 0.7);
  color: var(--muted);
}

:root.dark .t tbody td {
  border-top-color: rgba(31, 41, 55, 0.8);
}

.t tbody tr:hover {
  background: rgba(241, 245, 249, 0.55);
}

:root.dark .t tbody tr:hover {
  background: rgba(148, 163, 184, 0.06);
}

.rank {
  font-weight: 900;
  color: var(--muted-2);
}

.score {
  display: inline-block;
  border-radius: 8px;
  padding: 4px 8px;
  background: rgba(19, 127, 236, 0.10);
  color: var(--primary);
  font-weight: 900;
  font-size: 12px;
}

.source {
  font-weight: 600;
  color: var(--muted);
}

.snippet {
  max-width: 320px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.snippet-btn {
  display: inline-block;
  width: 100%;
  text-align: left;
  padding: 0;
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  cursor: pointer;
}

.snippet-btn:hover {
  color: var(--primary);
}

.snippet-md {
  max-height: 60vh;
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px 16px;
  background: var(--surface-2);
}

.center {
  text-align: center;
}

.right {
  text-align: right;
}

.col-open {
  width: 48px;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

.rel {
  display: inline-flex;
  gap: 4px;
}

.dot {
  width: 16px;
  height: 16px;
  border-radius: 3px;
  border: 0;
  background: rgba(226, 232, 240, 1);
  cursor: pointer;
}

:root.dark .dot {
  background: rgba(51, 65, 85, 1);
}

.dot.teal {
  background: var(--teal);
}

.dot.orange {
  background: #fb923c;
}

.open {
  border: 0;
  background: transparent;
  font-family: inherit;
  cursor: pointer;
  color: var(--muted-2);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 6px;
  border-radius: 10px;
}

.open:hover {
  color: var(--primary);
  background: rgba(15, 23, 42, 0.04);
}

:root.dark .open:hover {
  background: rgba(255, 255, 255, 0.06);
}

.open:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.open :deep(.material-symbols-outlined) {
  font-size: 20px;
}

.ms {
  font-family: 'Material Symbols Outlined', sans-serif;
  font-variation-settings: 'FILL' 1;
  font-size: 24px;
  color: var(--primary);
}

.ms.teal {
  color: var(--teal);
}

.judge {
  border: 2px solid rgba(19, 127, 236, 0.08);
}

.judge-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 18px 22px;
}

.judge-title {
  display: flex;
  align-items: center;
  gap: 10px;
}

.judge-title h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 900;
  color: var(--text);
}

.judge-grid {
  padding: 0 22px 22px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px;
}

.judge-answer :deep(textarea) {
  color: var(--muted);
}

.chips {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border-radius: 999px;
  padding: 6px 12px;
  font-size: 12px;
  font-weight: 900;
}

.chip.teal {
  background: rgba(45, 212, 191, 0.12);
  color: #059669;
}

.chip.blue {
  background: rgba(19, 127, 236, 0.10);
  color: var(--primary);
}

.reason {
  border-radius: 12px;
  background: rgba(241, 245, 249, 0.9);
  padding: 14px;
}

:root.dark .reason {
  background: rgba(148, 163, 184, 0.08);
}

.reason-title {
  font-weight: 900;
  color: var(--text);
}

.reason-text {
  margin-top: 8px;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.6;
}

.right-inner {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.right-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.right-title {
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--muted-2);
}

.metric {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.metric-row {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
}

.metric-name {
  font-size: 14px;
  font-weight: 700;
  color: var(--text);
}

.metric-value {
  font-size: 18px;
  font-weight: 900;
  color: var(--text);
}

.bar {
  height: 6px;
  border-radius: 999px;
  background: rgba(241, 245, 249, 0.9);
  overflow: hidden;
}

:root.dark .bar {
  background: rgba(148, 163, 184, 0.08);
}

.bar-fill {
  height: 100%;
  background: var(--teal);
}

.metric-note {
  font-size: 10px;
  color: var(--muted-2);
}

.sample {
  border-top: 1px solid rgba(226, 232, 240, 0.7);
  padding-top: 18px;
}

:root.dark .sample {
  border-top-color: rgba(31, 41, 55, 0.8);
}

.sample-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.sample-value {
  font-weight: 900;
  color: var(--text);
}

.export {
  width: 100%;
  font-weight: 800;
}

.heat {
  background: rgba(241, 245, 249, 0.9);
  padding: 14px;
  border-radius: 16px;
}

:root.dark .heat {
  background: rgba(148, 163, 184, 0.08);
}

.heat-title {
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--muted-2);
  margin-bottom: 10px;
}

.heat-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.h {
  width: 16px;
  height: 16px;
  border-radius: 3px;
  background: rgba(226, 232, 240, 1);
}

.h.teal {
  background: var(--teal);
}

.h.orange {
  background: #fb923c;
}

.h.gray {
  background: rgba(226, 232, 240, 1);
}

:root.dark .h.gray {
  background: rgba(51, 65, 85, 1);
}

.faint {
  opacity: 0.5;
}

@media (max-width: 1180px) {
  .right { display: none; }
}

@media (max-width: 980px) {
  .left { display: none; }
  .header { padding: 12px 18px; }
  .header-search { width: 240px; }
  .main { padding: 18px; }
}

@media (max-width: 720px) {
  .nav { display: none; }
  .sep { display: none; }
  .header-search { display: none; }
  .judge-grid { grid-template-columns: 1fr; }
}
</style>
