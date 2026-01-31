<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import RagModuleShell from '@/components/rag/RagModuleShell.vue'

type Run = {
  id: string
  title: string
  meta: string
  updatedLabel: string
  status: 'Completed' | 'Running'
  results: { id: string; title: string; meta: string }[]
}

const search = ref('')

const runs = ref<Run[]>([
  {
    id: 'run_2026_02_01',
    title: 'Run 2026-02-01 12:45',
    meta: 'vector + graph • 2 KBs • 2 datasets • 10 cases',
    updatedLabel: 'Yesterday',
    status: 'Completed',
    results: [
      {
        id: 'r1',
        title: 'Case liability limitation in Section 4.2',
        meta: 'F1=0.92 (VLM) • nDCG 0.82',
      },
    ],
  },
  {
    id: 'run_2026_01_28',
    title: 'Run 2026-01-28 09:48',
    meta: 'vector • 1 KB • 1 dataset • 6 cases',
    updatedLabel: 'Oct 24',
    status: 'Completed',
    results: [
      {
        id: 'r2',
        title: 'Case retention requirements and exceptions',
        meta: 'Faithfulness: High • Relevance: Med',
      },
    ],
  },
])

const selectedRunId = ref(runs.value[0]?.id || null)

const filteredRuns = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return runs.value
  return runs.value.filter((r) => {
    return (
      r.title.toLowerCase().includes(q) ||
      r.meta.toLowerCase().includes(q) ||
      r.status.toLowerCase().includes(q)
    )
  })
})

const selected = computed(() => {
  const id = selectedRunId.value
  return runs.value.find((r) => r.id === id) || null
})

function pick(id: string) {
  selectedRunId.value = id
}

function onNewRun() {
  ElMessage.info('New Run: UI only (no backend wired)')
}

function onRun() {
  ElMessage.info('Run: UI only')
}

function onExportReport() {
  ElMessage.info('Export report: UI only')
}
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
          <div class="pill">Vector + Graph</div>
        </div>

        <div class="rows">
          <button
            v-for="r in filteredRuns"
            :key="r.id"
            class="row"
            :class="{ active: r.id === selectedRunId }"
            type="button"
            @click="pick(r.id)"
          >
            <div class="row-main">
              <div class="row-title">{{ r.title }}</div>
              <div class="row-desc">{{ r.meta }}</div>
            </div>
            <div class="row-meta">
              <div class="row-updated">{{ r.updatedLabel }}</div>
              <div class="chip" :class="r.status === 'Completed' ? 'chip-ok' : 'chip-run'">{{ r.status }}</div>
            </div>
          </button>
        </div>
      </section>

      <section class="card detail">
        <div class="detail-head">
          <div>
            <div class="detail-title">{{ selected?.title || 'Select a run' }}</div>
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
              <div v-for="c in selected.results" :key="c.id" class="case">
                <div class="case-title">{{ c.title }}</div>
                <div class="case-meta">{{ c.meta }}</div>
              </div>
              <button class="ghost full" type="button" @click="onExportReport">Export Full Report</button>
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
