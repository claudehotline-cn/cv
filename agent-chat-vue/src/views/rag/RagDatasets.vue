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
  expected_answer?: string | null
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
const selectedCaseIds = ref<number[]>([])

const datasetDialogOpen = ref(false)
const datasetSaving = ref(false)
const datasetForm = ref({ name: '', description: '' })

const caseDialogOpen = ref(false)
const caseDialogMode = ref<'create' | 'edit'>('create')
const caseSaving = ref(false)
const caseEditingId = ref<number | null>(null)
const caseForm = ref({
  query: '',
  expectedSourcesText: '',
  expectedAnswer: '',
  notes: '',
})

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

function onSelectionChange(rows: any[]) {
  selectedCaseIds.value = (rows || []).map((r) => Number(r.id)).filter((n) => Number.isFinite(n))
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

function openEditDatasetDialog() {
  if (!selected.value) return
  datasetForm.value = {
    name: selected.value.name || '',
    description: selected.value.description || '',
  }
  datasetDialogOpen.value = true
}

async function saveDataset() {
  if (!kbId.value || !selectedDatasetId.value) return
  const name = String(datasetForm.value.name || '').trim()
  const description = String(datasetForm.value.description || '').trim()
  if (!name) {
    ElMessage.warning('Name is required')
    return
  }
  datasetSaving.value = true
  try {
    await apiClient.updateEvalDataset(kbId.value, selectedDatasetId.value, {
      name,
      description: description || undefined,
    })
    ElMessage.success('Updated')
    datasetDialogOpen.value = false
    await refreshDatasets()
  } catch {
    ElMessage.error('Update failed')
  } finally {
    datasetSaving.value = false
  }
}

async function onDeleteDataset() {
  if (!kbId.value || !selectedDatasetId.value || !selected.value) {
    ElMessage.warning('Select a dataset first')
    return
  }
  try {
    await ElMessageBox.confirm(
      `Delete dataset "${selected.value.name}"? This hides it (soft delete).`,
      'Delete Dataset',
      { confirmButtonText: 'Delete', cancelButtonText: 'Cancel', type: 'warning' }
    )
    await apiClient.deleteEvalDataset(kbId.value, selectedDatasetId.value)
    ElMessage.success('Deleted')
    selectedDatasetId.value = null
    cases.value = []
    await refreshDatasets()
    if (datasets.value.length) {
      await pick(datasets.value[0].id)
    }
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
          expected_answer: c?.expected_answer ? String(c.expected_answer) : undefined,
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

function openNewCaseDialog() {
  if (!selectedDatasetId.value) return
  caseDialogMode.value = 'create'
  caseEditingId.value = null
  caseForm.value = {
    query: '',
    expectedSourcesText: '',
    expectedAnswer: '',
    notes: '',
  }
  caseDialogOpen.value = true
}

function openEditCaseDialog(c: CaseItem) {
  caseDialogMode.value = 'edit'
  caseEditingId.value = c.id
  caseForm.value = {
    query: c.query || '',
    expectedSourcesText: (c.expected_sources || []).join(', '),
    expectedAnswer: (c.expected_answer as any) || '',
    notes: c.notes || '',
  }
  caseDialogOpen.value = true
}

async function saveCase() {
  if (!kbId.value || !selectedDatasetId.value) return
  const query = String(caseForm.value.query || '').trim()
  if (!query) {
    ElMessage.warning('Query is required')
    return
  }
  const expected_sources = String(caseForm.value.expectedSourcesText || '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
  const expected_answer = String(caseForm.value.expectedAnswer || '').trim()
  const notes = String(caseForm.value.notes || '').trim()

  caseSaving.value = true
  try {
    if (caseDialogMode.value === 'create') {
      await apiClient.createEvalCase(kbId.value, selectedDatasetId.value, {
        query,
        expected_sources,
        expected_answer: expected_answer || undefined,
        notes: notes || undefined,
      })
      ElMessage.success('Case created')
    } else {
      if (!caseEditingId.value) return
      await apiClient.updateEvalCase(caseEditingId.value, {
        query,
        expected_sources,
        expected_answer: expected_answer || '',
        notes: notes || undefined,
      })
      ElMessage.success('Case updated')
    }
    caseDialogOpen.value = false
    await refreshCases(selectedDatasetId.value)
    await refreshDatasets()
  } catch {
    ElMessage.error('Save failed')
  } finally {
    caseSaving.value = false
  }
}

async function deleteCase(c: CaseItem) {
  if (!kbId.value || !selectedDatasetId.value) return
  try {
    await ElMessageBox.confirm('Delete this case?', 'Delete Case', {
      confirmButtonText: 'Delete',
      cancelButtonText: 'Cancel',
      type: 'warning',
    })
    await apiClient.deleteEvalCase(c.id)
    ElMessage.success('Deleted')
    await refreshCases(selectedDatasetId.value)
    await refreshDatasets()
  } catch {
    // cancelled
  }
}

async function bulkDeleteSelectedCases() {
  if (!kbId.value || !selectedDatasetId.value) return
  if (!selectedCaseIds.value.length) {
    ElMessage.warning('Select cases first')
    return
  }
  try {
    await ElMessageBox.confirm(`Delete ${selectedCaseIds.value.length} cases?`, 'Bulk Delete', {
      confirmButtonText: 'Delete',
      cancelButtonText: 'Cancel',
      type: 'warning',
    })
    await apiClient.bulkDeleteEvalCases(kbId.value, selectedDatasetId.value, selectedCaseIds.value)
    selectedCaseIds.value = []
    ElMessage.success('Deleted')
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
            <button class="ghost" type="button" :disabled="!selected" @click="openEditDatasetDialog">Edit</button>
            <button class="danger" type="button" :disabled="!selected" @click="onDeleteDataset">Delete</button>
          </div>
        </div>

        <div class="detail-body">
          <div class="section-title">Cases</div>
          <div class="cases">
            <div v-if="!selected" class="empty">Pick a dataset from the left.</div>
            <div v-else>
              <div class="case-actions">
                <button class="ghost" type="button" :disabled="!selectedCaseIds.length" @click="bulkDeleteSelectedCases">
                  Delete Selected
                </button>
                <button class="add" type="button" @click="openNewCaseDialog">Add Case</button>
              </div>

              <el-table
                :data="cases"
                class="case-table"
                style="width: 100%"
                @selection-change="onSelectionChange"
              >
                <el-table-column type="selection" width="44" />
                <el-table-column label="Query" min-width="260">
                  <template #default="{ row }">
                    <div class="cell-title">{{ row.query }}</div>
                    <div class="cell-sub">
                      {{ (row.expected_sources || []).slice(0, 3).join(', ') || 'No expected sources' }}
                    </div>
                  </template>
                </el-table-column>
                <el-table-column label="Expected Answer" min-width="220">
                  <template #default="{ row }">
                    <div class="cell-sub">
                      {{ (row.expected_answer || '').slice(0, 120) || '—' }}
                    </div>
                  </template>
                </el-table-column>
                <el-table-column label="Actions" width="170" align="right">
                  <template #default="{ row }">
                    <div class="row-actions">
                      <button class="ghost" type="button" @click="openEditCaseDialog(row)">Edit</button>
                      <button class="ghost" type="button" @click="deleteCase(row)">Delete</button>
                    </div>
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </div>
        </div>
      </section>
    </div>

    <el-dialog
      v-model="caseDialogOpen"
      :title="caseDialogMode === 'create' ? 'New Case' : 'Edit Case'"
      width="720px"
    >
      <el-form label-position="top">
        <el-form-item label="Query">
          <el-input v-model="caseForm.query" type="textarea" :rows="3" placeholder="Ask a question" />
        </el-form-item>
        <el-form-item label="Expected sources (comma-separated, match filename)">
          <el-input v-model="caseForm.expectedSourcesText" placeholder="e.g. contract.pdf, policy.md" />
        </el-form-item>
        <el-form-item label="Expected answer (for QA scoring)">
          <el-input v-model="caseForm.expectedAnswer" type="textarea" :rows="5" placeholder="What a correct answer should say" />
        </el-form-item>
        <el-form-item label="Notes (optional)">
          <el-input v-model="caseForm.notes" type="textarea" :rows="2" placeholder="Additional notes" />
        </el-form-item>
      </el-form>
      <template #footer>
        <div class="dialog-footer">
          <button class="ghost" type="button" @click="caseDialogOpen = false">Cancel</button>
          <button class="add" type="button" :disabled="caseSaving" @click="saveCase">
            {{ caseSaving ? 'Saving...' : 'Save' }}
          </button>
        </div>
      </template>
    </el-dialog>

    <el-dialog v-model="datasetDialogOpen" title="Edit Dataset" width="560px">
      <el-form label-position="top">
        <el-form-item label="Name">
          <el-input v-model="datasetForm.name" placeholder="Dataset name" />
        </el-form-item>
        <el-form-item label="Description">
          <el-input v-model="datasetForm.description" type="textarea" :rows="3" placeholder="Optional description" />
        </el-form-item>
      </el-form>
      <template #footer>
        <div class="dialog-footer">
          <button class="ghost" type="button" @click="datasetDialogOpen = false">Cancel</button>
          <button class="add" type="button" :disabled="datasetSaving" @click="saveDataset">
            {{ datasetSaving ? 'Saving...' : 'Save' }}
          </button>
        </div>
      </template>
    </el-dialog>
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

.danger {
  height: 32px;
  padding: 0 12px;
  border-radius: 10px;
  border: 1px solid rgba(239, 68, 68, 0.35);
  background: rgba(239, 68, 68, 0.08);
  color: #b91c1c;
  font-family: inherit;
  font-size: 12px;
  font-weight: 900;
  cursor: pointer;
}

.danger:hover {
  border-color: rgba(239, 68, 68, 0.55);
  background: rgba(239, 68, 68, 0.12);
}

.ghost:disabled,
.danger:disabled {
  opacity: 0.55;
  cursor: not-allowed;
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

.case-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 12px;
}

.case-table :deep(.el-table__header-wrapper th) {
  background: #f8fafc;
}

.cell-title {
  font-size: 13px;
  font-weight: 900;
  color: #0f172a;
}

.cell-sub {
  margin-top: 6px;
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
  line-height: 1.35;
}

.row-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
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
  height: 36px;
  padding: 0 16px;
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

.add:disabled {
  opacity: 0.65;
  cursor: not-allowed;
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
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
