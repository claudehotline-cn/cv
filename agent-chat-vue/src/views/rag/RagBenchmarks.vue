<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import RagModuleShell from '@/components/rag/RagModuleShell.vue'
import apiClient from '@/api/client'

type DatasetItem = { id: number; name: string }
type RunItem = {
  id: number
  knowledge_base_id: number
  dataset_id: number
  mode: 'vector' | 'graph' | 'qa'
  top_k: number
  status: string
  created_at?: string
  metrics?: any
}

type QaResult = {
  id: number
  run_id: number
  case_id: number
  expected_answer?: string | null
  answer?: string | null
  score?: number | null
  judge?: any
  sources?: any
}

type ResultItem = {
  id: number
  run_id: number
  case_id: number
  hit_rank?: number | null
  mrr: number
  ndcg: number
  retrieved: any
  qa?: QaResult | null
}

const route = useRoute()
const router = useRouter()

const search = ref('')
const loading = ref(false)
const datasets = ref<DatasetItem[]>([])
const runs = ref<RunItem[]>([])
const results = ref<ResultItem[]>([])

const runDialogOpen = ref(false)
const runSaving = ref(false)
const runForm = ref<{ datasetId: number | null; mode: 'vector' | 'graph' | 'qa'; top_k: number }>({
  datasetId: null,
  mode: 'vector',
  top_k: 5,
})

const selectedRunId = ref<number | null>(null)

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
      await router.replace({ path: '/rag/benchmarks', query: { kbId: String(id) } })
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

function runTitle(r: RunItem) {
  return `Run #${r.id}`
}

function runMeta(r: RunItem) {
  return `${r.mode} • dataset ${r.dataset_id} • top_k=${r.top_k}`
}

function runStatusLabel(r: RunItem) {
  const s = (r.status || '').toLowerCase()
  if (s === 'succeeded') return 'Completed'
  if (s === 'running') return 'Running'
  if (s === 'failed') return 'Failed'
  return 'Queued'
}

async function refreshDatasets() {
  if (!kbId.value) return
  try {
    const res = await apiClient.listEvalDatasets(kbId.value)
    datasets.value = (res.items || []).map((d: any) => ({ id: Number(d.id), name: String(d.name || '') }))
  } catch {
    datasets.value = []
  }
}

async function refreshRuns() {
  if (!kbId.value) return
  loading.value = true
  try {
    const res = await apiClient.listBenchmarkRuns(kbId.value)
    runs.value = (res.items || []) as RunItem[]
    if (!selectedRunId.value && runs.value.length) {
      selectedRunId.value = runs.value[0].id
    }
  } catch {
    ElMessage.error('Failed to load runs')
    runs.value = []
  } finally {
    loading.value = false
  }
}

async function refreshResults(runId: number) {
  if (!kbId.value) return
  try {
    const res = await apiClient.listBenchmarkResults(kbId.value, runId)
    results.value = (res.items || []) as ResultItem[]
  } catch {
    results.value = []
  }
}

const filteredRuns = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return runs.value
  return runs.value.filter((r) => {
    return (
      runTitle(r).toLowerCase().includes(q) ||
      runMeta(r).toLowerCase().includes(q) ||
      runStatusLabel(r).toLowerCase().includes(q)
    )
  })
})

const selected = computed(() => {
  const id = selectedRunId.value
  return runs.value.find((r) => r.id === id) || null
})

function pick(id: string) {
  selectedRunId.value = Number(id)
}

async function onNewRun() {
  if (!kbId.value) {
    ElMessage.warning('Missing kbId')
    return
  }
  await refreshDatasets()
  if (!datasets.value.length) {
    ElMessage.warning('Create a dataset first')
    return
  }
  runForm.value = {
    datasetId: datasets.value[0].id,
    mode: 'vector',
    top_k: 5,
  }
  runDialogOpen.value = true
}

async function createRun() {
  if (!kbId.value) return
  if (!runForm.value.datasetId) {
    ElMessage.warning('Select a dataset')
    return
  }
  const top_k = Number(runForm.value.top_k)
  if (!Number.isFinite(top_k) || top_k <= 0 || top_k > 50) {
    ElMessage.warning('top_k must be 1-50')
    return
  }
  runSaving.value = true
  try {
    const created = await apiClient.createBenchmarkRun(kbId.value, {
      dataset_id: runForm.value.datasetId,
      mode: runForm.value.mode,
      top_k,
    })
    ElMessage.success('Run created')
    runDialogOpen.value = false
    await refreshRuns()
    if (created?.id) {
      selectedRunId.value = Number(created.id)
      await refreshResults(selectedRunId.value)
    }
  } catch {
    ElMessage.error('Create run failed')
  } finally {
    runSaving.value = false
  }
}

async function onRun() {
  if (!kbId.value || !selectedRunId.value) {
    ElMessage.warning('Select a run first')
    return
  }
  try {
    await apiClient.executeBenchmarkRun(kbId.value, selectedRunId.value)
    ElMessage.success('Benchmark queued')
    await refreshRuns()
  } catch {
    ElMessage.error('Failed to execute run')
  }
}

async function onExportReport() {
  if (!kbId.value || !selectedRunId.value) {
    ElMessage.warning('Select a run first')
    return
  }
  try {
    const payload = await apiClient.exportBenchmarkRun(kbId.value, selectedRunId.value)
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `rag-benchmark-run-${selectedRunId.value}.json`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  } catch {
    ElMessage.error('Export failed')
  }
}

onMounted(async () => {
  await ensureKbSelected()
  await refreshDatasets()
  await refreshRuns()
  if (selectedRunId.value) await refreshResults(selectedRunId.value)
})

watch(
  () => kbId.value,
  async (id) => {
    if (!id) return
    selectedRunId.value = null
    results.value = []
    await refreshDatasets()
    await refreshRuns()
    if (selectedRunId.value) await refreshResults(selectedRunId.value)
  }
)

watch(
  () => selectedRunId.value,
  async (id) => {
    if (!kbId.value || !id) return
    await refreshResults(id)
  }
)
</script>

<template>
  <RagModuleShell
    v-model:search="search"
    breadcrumb="RAG  /  Benchmarks"
    title="Benchmarks"
    search-placeholder="Search runs..."
    primary-action-label="New Run"
    @primary="onNewRun"
  >
    <div class="page">
      <section class="card list">
        <div class="card-head">
          <div class="head-left">
            <div class="kicker">All Runs</div>
            <div class="sub">{{ filteredRuns.length }} total</div>
          </div>
          <div class="pill">Vector / Graph / QA</div>
        </div>

        <div class="rows">
          <button
            v-for="r in filteredRuns"
            :key="r.id"
            class="row"
            :class="{ active: r.id === selectedRunId }"
            type="button"
            @click="pick(String(r.id))"
          >
            <div class="row-main">
              <div class="row-title">{{ runTitle(r) }}</div>
              <div class="row-desc">{{ runMeta(r) }}</div>
            </div>
            <div class="row-meta">
              <div class="row-updated">{{ formatUpdatedLabel(r.created_at) }}</div>
              <div class="chip" :class="runStatusLabel(r) === 'Completed' ? 'chip-ok' : 'chip-run'">{{ runStatusLabel(r) }}</div>
            </div>
          </button>
        </div>
      </section>

      <section class="card detail">
        <div class="detail-head">
          <div>
            <div class="detail-title">{{ selected ? runTitle(selected) : 'Select a run' }}</div>
            <div class="detail-sub">
              Benchmarks run datasets in batch and track metrics over time.
            </div>
          </div>
          <div class="detail-actions">
            <button class="primary" type="button" @click="onRun">Run</button>
            <button class="ghost" type="button" @click="onExportReport">Export Report</button>
          </div>
        </div>

        <div class="detail-body">
          <div class="section-title">Case Results</div>
          <div class="cases">
            <div v-if="!selected" class="empty">Pick a run from the left.</div>
            <div v-else>
              <div v-if="selected?.metrics" class="case" style="margin-bottom: 10px;">
                <div class="case-title">Metrics</div>
                <div class="case-meta">
                  hit_rate={{ selected.metrics?.hit_rate ?? '—' }}, mrr={{ selected.metrics?.mrr ?? '—' }}, ndcg={{ selected.metrics?.ndcg ?? '—' }}
                  <span v-if="selected.metrics?.qa">
                    , qa_avg={{ selected.metrics?.qa?.avg_score ?? '—' }}, qa_pass={{ selected.metrics?.qa?.pass_rate ?? '—' }}
                  </span>
                </div>
              </div>

              <div v-for="c in results" :key="c.id" class="case">
                <div class="case-title">Case #{{ c.case_id }}</div>
                <div class="case-meta">
                  hit_rank={{ c.hit_rank ?? '-' }} • mrr={{ c.mrr.toFixed(3) }} • ndcg={{ c.ndcg.toFixed(3) }}
                </div>

                <div v-if="c.qa" class="case-meta" style="margin-top: 8px;">
                  qa_score={{ c.qa.score ?? '—' }}
                </div>
                <div v-if="c.qa?.answer" class="case-meta" style="margin-top: 8px; white-space: pre-wrap;">
                  {{ String(c.qa.answer).slice(0, 260) }}
                </div>
              </div>
              <button class="ghost full" type="button" @click="onExportReport">Export Full Report</button>
            </div>
          </div>
        </div>
      </section>
    </div>

    <el-dialog v-model="runDialogOpen" title="New Run" width="560px">
      <el-form label-position="top">
        <el-form-item label="Dataset">
          <el-select v-model="runForm.datasetId" placeholder="Select dataset" style="width: 100%">
            <el-option v-for="d in datasets" :key="d.id" :label="`${d.id}: ${d.name}`" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="Mode">
          <el-radio-group v-model="runForm.mode">
            <el-radio label="vector">vector</el-radio>
            <el-radio label="graph">graph</el-radio>
            <el-radio label="qa">qa</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="top_k">
          <el-input-number v-model="runForm.top_k" :min="1" :max="50" />
        </el-form-item>
        <div style="font-size: 12px; color: #64748b; line-height: 1.5;">
          qa mode generates answers via RAG and scores them against the case's expected answer.
        </div>
      </el-form>
      <template #footer>
        <div class="dialog-footer">
          <button class="ghost" type="button" @click="runDialogOpen = false">Cancel</button>
          <button class="primary" type="button" :disabled="runSaving" @click="createRun">
            {{ runSaving ? 'Creating...' : 'Create' }}
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

.pill {
  border-radius: 999px;
  padding: 6px 10px;
  background: rgba(20, 108, 240, 0.08);
  color: #146cf0;
  font-size: 11px;
  font-weight: 900;
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
  color: #64748b;
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
  font-weight: 900;
  border: 1px solid rgba(226, 232, 240, 0.9);
}

.chip-ok {
  color: #146cf0;
  background: rgba(20, 108, 240, 0.08);
}

.chip-run {
  color: #0f172a;
  background: rgba(45, 212, 191, 0.16);
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
  flex-shrink: 0;
}

.primary {
  height: 32px;
  padding: 0 12px;
  border-radius: 999px;
  border: 0;
  background: #146cf0;
  color: #ffffff;
  font-family: inherit;
  font-size: 12px;
  font-weight: 900;
  cursor: pointer;
}

.primary:hover {
  filter: brightness(0.97);
}

.ghost {
  height: 32px;
  padding: 0 12px;
  border-radius: 999px;
  border: 1px solid #e2e8f0;
  background: #ffffff;
  font-family: inherit;
  font-size: 12px;
  font-weight: 900;
  color: #0f172a;
  cursor: pointer;
}

.ghost:hover {
  border-color: rgba(20, 108, 240, 0.35);
  color: #146cf0;
}

.ghost.full {
  margin-top: 12px;
  width: 100%;
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
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
