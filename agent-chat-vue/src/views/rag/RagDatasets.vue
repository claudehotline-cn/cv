<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import RagModuleShell from '@/components/rag/RagModuleShell.vue'
import apiClient from '@/api/client'

type DatasetItem = {
  id: number
  knowledge_base_id: number
  name: string
  description?: string
  is_active: boolean
  cases_count?: number
  updated_at?: string
}

type CaseItem = {
  id: number
  dataset_id: number
  query: string
  expected_sources: string[]
  notes?: string
  tags: string[]
}

const route = useRoute()
const router = useRouter()

const search = ref('')
const loading = ref(false)
const datasets = ref<DatasetItem[]>([])
const selectedDatasetId = ref<number | null>(null)
const cases = ref<CaseItem[]>([])

const kbId = computed(() => {
  const raw = String(route.query.kbId || '')
  const n = Number.parseInt(raw, 10)
  return Number.isFinite(n) ? n : null
})

async function ensureKbSelected() {
  if (kbId.value) return
  try {
    const res = await apiClient.listKnowledgeBases()
    const first = res.items?.[0]
    const id = Number(first?.id)
    if (Number.isFinite(id)) {
      await router.replace({ path: '/rag/datasets', query: { kbId: String(id) } })
    }
  } catch {
    // ignore
  }
}

function formatUpdatedLabel(iso?: string) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleDateString(undefined, { month: 'short', day: '2-digit' })
}

async function refreshDatasets() {
  if (!kbId.value) return
  loading.value = true
  try {
    const res = await apiClient.listEvalDatasets(kbId.value)
    datasets.value = (res.items || []) as DatasetItem[]
    if (!selectedDatasetId.value && datasets.value.length) {
      selectedDatasetId.value = datasets.value[0].id
    }
  } catch (e) {
    ElMessage.error('Failed to load datasets')
  } finally {
    loading.value = false
  }
}

async function refreshCases(datasetId: number) {
  if (!kbId.value) return
  try {
    const res = await apiClient.listEvalCases(kbId.value, datasetId)
    cases.value = (res.items || []) as CaseItem[]
  } catch {
    cases.value = []
    ElMessage.error('Failed to load cases')
  }
}

const filteredDatasets = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return datasets.value
  return datasets.value.filter((d) => {
    return (
      d.name.toLowerCase().includes(q) ||
      (d.description || '').toLowerCase().includes(q)
    )
  })
})

const selected = computed(() => {
  const id = selectedDatasetId.value
  return datasets.value.find((d) => d.id === id) || null
})

async function pick(id: number) {
  selectedDatasetId.value = id
  await refreshCases(id)
}

async function onNewDataset() {
  if (!kbId.value) {
    ElMessage.warning('Missing kbId')
    return
  }
  try {
    const { value } = await ElMessageBox.prompt('Dataset name', 'New Dataset', {
      confirmButtonText: 'Create',
      cancelButtonText: 'Cancel',
      inputPlaceholder: 'e.g. Finance_Facts_v1',
      inputPattern: /\S+/, 
      inputErrorMessage: 'Name is required',
    })
    const created = await apiClient.createEvalDataset(kbId.value, { name: String(value).trim() })
    ElMessage.success('Dataset created')
    await refreshDatasets()
    if (created?.id) await pick(Number(created.id))
  } catch {
    // cancelled
  }
}

async function onExport() {
  if (!kbId.value || !selectedDatasetId.value) {
    ElMessage.warning('Select a dataset first')
    return
  }
  try {
    const payload = await apiClient.exportEvalDataset(kbId.value, selectedDatasetId.value)
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `rag-dataset-${selectedDatasetId.value}.json`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  } catch {
    ElMessage.error('Export failed')
  }
}

async function onImport() {
  if (!kbId.value || !selectedDatasetId.value) {
    ElMessage.warning('Select a dataset first')
    return
  }

  const input = document.createElement('input')
  input.type = 'file'
  input.accept = 'application/json'
  input.onchange = async () => {
    const file = input.files?.[0]
    if (!file) return
    try {
      const text = await file.text()
      const parsed = JSON.parse(text)
      const rawCases = Array.isArray(parsed?.cases) ? parsed.cases : []
      const normalized = rawCases
        .map((c: any) => ({
          query: String(c?.query || '').trim(),
          expected_sources: Array.isArray(c?.expected_sources) ? c.expected_sources.map((x: any) => String(x)) : [],
          notes: c?.notes ? String(c.notes) : undefined,
          tags: Array.isArray(c?.tags) ? c.tags.map((x: any) => String(x)) : [],
        }))
        .filter((c: any) => c.query)
      await apiClient.importEvalDataset(kbId.value!, selectedDatasetId.value!, { replace: true, cases: normalized })
      ElMessage.success('Imported')
      await refreshCases(selectedDatasetId.value!)
      await refreshDatasets()
    } catch (e) {
      ElMessage.error('Import failed')
    }
  }
  input.click()
}

async function onAddCase() {
  if (!kbId.value || !selectedDatasetId.value) {
    ElMessage.warning('Select a dataset first')
    return
  }
  try {
    const { value } = await ElMessageBox.prompt('Case query', 'Add Case', {
      confirmButtonText: 'Add',
      cancelButtonText: 'Cancel',
      inputPlaceholder: 'Ask a question you expect the KB to answer',
      inputType: 'textarea',
      inputPattern: /\S+/,
      inputErrorMessage: 'Query is required',
    })

    const { value: sources } = await ElMessageBox.prompt(
      'Expected sources (comma-separated, match metadata.source)',
      'Add Case',
      {
        confirmButtonText: 'Save',
        cancelButtonText: 'Cancel',
        inputPlaceholder: 'e.g. contract.pdf, policy.md',
      }
    )

    const expected_sources = String(sources)
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)

    await apiClient.createEvalCase(kbId.value, selectedDatasetId.value, { query: String(value).trim(), expected_sources })
    ElMessage.success('Case added')
    await refreshCases(selectedDatasetId.value)
    await refreshDatasets()
  } catch {
    // cancelled
  }
}

onMounted(async () => {
  await ensureKbSelected()
  await refreshDatasets()
  if (selectedDatasetId.value) {
    await refreshCases(selectedDatasetId.value)
  }
})

watch(
  () => kbId.value,
  async (id) => {
    if (!id) return
    selectedDatasetId.value = null
    cases.value = []
    await refreshDatasets()
    if (selectedDatasetId.value) await refreshCases(selectedDatasetId.value)
  }
)
</script>

<template>
  <RagModuleShell
    v-model:search="search"
    breadcrumb="RAG  /  Datasets"
    title="Datasets"
    search-placeholder="Search datasets..."
    primary-action-label="New Dataset"
    @primary="onNewDataset"
  >
    <div class="page">
      <section class="card list">
        <div class="card-head">
          <div class="head-left">
            <div class="kicker">All Datasets</div>
            <div class="sub">{{ filteredDatasets.length }} total</div>
          </div>
          <button class="head-action" type="button" :disabled="loading" @click="onExport">Full export</button>
        </div>

        <div class="rows">
          <button
            v-for="d in filteredDatasets"
            :key="d.id"
            class="row"
            :class="{ active: d.id === selectedDatasetId }"
            type="button"
            @click="pick(d.id)"
          >
            <div class="row-main">
              <div class="row-title">{{ d.name }}</div>
              <div class="row-desc">{{ d.description }}</div>
            </div>
            <div class="row-meta">
              <div class="row-updated">{{ formatUpdatedLabel(d.updated_at) }}</div>
              <div class="chip" :class="d.is_active ? 'chip-active' : 'chip-draft'">{{ d.is_active ? 'Active' : 'Draft' }}</div>
            </div>
          </button>
        </div>
      </section>

      <section class="card detail">
        <div class="detail-head">
          <div>
            <div class="detail-title">{{ selected?.name || 'Select a dataset' }}</div>
            <div class="detail-sub">
              Oversees eval cases and exports for consistency across datasets.
            </div>
          </div>
          <div class="detail-actions">
            <button class="ghost" type="button" @click="onImport">Import</button>
            <button class="ghost" type="button" @click="onExport">Export</button>
          </div>
        </div>

        <div class="detail-body">
          <div class="section-title">Cases</div>
          <div class="cases">
            <div v-if="!selected" class="empty">Pick a dataset from the left.</div>
            <div v-else>
              <div v-for="c in cases" :key="c.id" class="case">
                <div class="case-title">{{ c.query }}</div>
                <div class="case-meta">
                  {{ (c.expected_sources || []).slice(0, 3).join(', ') || 'No expected sources' }}
                </div>
              </div>
              <button class="add" type="button" @click="onAddCase">Add Case</button>
            </div>
          </div>
        </div>
      </section>
    </div>
  </RagModuleShell>
</template>

<style scoped>
.page {
  display: grid;
  grid-template-columns: minmax(520px, 1fr) 520px;
  gap: 20px;
  min-height: 0;
}

.card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  overflow: hidden;
  min-height: 0;
}

.list {
  display: flex;
  flex-direction: column;
}

.card-head {
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
}

.head-left {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.kicker {
  font-size: 12px;
  font-weight: 800;
  color: #0f172a;
}

.sub {
  font-size: 12px;
  font-weight: 700;
  color: #94a3b8;
}

.head-action {
  border: 0;
  background: transparent;
  color: #64748b;
  font-family: inherit;
  font-size: 12px;
  font-weight: 800;
  cursor: pointer;
}

.head-action:hover {
  color: #146cf0;
}

.rows {
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  border: 0;
  border-top: 1px solid rgba(226, 232, 240, 0.7);
  background: #ffffff;
  text-align: left;
  font-family: inherit;
  cursor: pointer;
}

.row:hover {
  background: rgba(248, 250, 252, 0.75);
}

.row.active {
  outline: 2px solid rgba(20, 108, 240, 0.18);
  outline-offset: -2px;
}

.row-main {
  min-width: 0;
}

.row-title {
  font-size: 13px;
  font-weight: 800;
  color: #0f172a;
}

.row-desc {
  margin-top: 4px;
  font-size: 12px;
  font-weight: 600;
  color: #94a3b8;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 520px;
}

.row-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.row-updated {
  font-size: 12px;
  font-weight: 800;
  color: #94a3b8;
}

.chip {
  border-radius: 999px;
  padding: 4px 10px;
  font-size: 11px;
  font-weight: 800;
  border: 1px solid rgba(226, 232, 240, 0.9);
}

.chip-active {
  color: #146cf0;
  background: rgba(20, 108, 240, 0.08);
}

.chip-draft {
  color: #64748b;
  background: rgba(148, 163, 184, 0.12);
}

.detail {
  display: flex;
  flex-direction: column;
}

.detail-head {
  padding: 16px;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
}

.detail-title {
  font-size: 14px;
  font-weight: 900;
  color: #0f172a;
}

.detail-sub {
  margin-top: 6px;
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
  line-height: 1.45;
}

.detail-actions {
  display: flex;
  gap: 8px;
}

.ghost {
  height: 32px;
  padding: 0 12px;
  border-radius: 10px;
  border: 1px solid #e2e8f0;
  background: #ffffff;
  font-family: inherit;
  font-size: 12px;
  font-weight: 800;
  color: #0f172a;
  cursor: pointer;
}

.ghost:hover {
  border-color: rgba(20, 108, 240, 0.35);
  color: #146cf0;
}

.detail-body {
  padding: 16px;
  overflow: auto;
}

.section-title {
  font-size: 12px;
  font-weight: 900;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #94a3b8;
}

.cases {
  margin-top: 12px;
}

.case {
  padding: 12px;
  border: 1px solid rgba(226, 232, 240, 0.9);
  border-radius: 12px;
  background: rgba(248, 250, 252, 0.75);
}

.case + .case {
  margin-top: 10px;
}

.case-title {
  font-size: 13px;
  font-weight: 900;
  color: #0f172a;
}

.case-meta {
  margin-top: 6px;
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
}

.add {
  margin-top: 12px;
  width: 100%;
  height: 36px;
  border-radius: 999px;
  border: 0;
  background: #146cf0;
  color: #ffffff;
  font-family: inherit;
  font-size: 12px;
  font-weight: 900;
  cursor: pointer;
}

.add:hover {
  filter: brightness(0.97);
}

.empty {
  padding: 14px;
  border-radius: 12px;
  border: 1px dashed rgba(148, 163, 184, 0.7);
  color: #64748b;
  font-weight: 700;
}

@media (max-width: 1120px) {
  .page {
    grid-template-columns: 1fr;
  }
}
</style>
