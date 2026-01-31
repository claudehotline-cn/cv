<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import RagModuleShell from '@/components/rag/RagModuleShell.vue'

type Dataset = {
  id: string
  name: string
  description: string
  casesCount: number
  updatedLabel: string
  status: 'Active' | 'Draft'
  cases: { id: string; title: string; meta: string }[]
}

const search = ref('')

const datasets = ref<Dataset[]>([
  {
    id: 'ds_contract_ca',
    name: 'Contract_CA_Set',
    description: 'Contracts and agreements: liability cap',
    casesCount: 2,
    updatedLabel: 'Oct 24',
    status: 'Active',
    cases: [
      {
        id: 'c1',
        title: 'What are the liability limitations in Section 4.2?',
        meta: 'output_source_1 • 2 KBs selected (within)',
      },
    ],
  },
  {
    id: 'ds_gdpr',
    name: 'GDPR_Compliance',
    description: 'Privacy controls: retention and consent',
    casesCount: 1,
    updatedLabel: 'Oct 22',
    status: 'Draft',
    cases: [
      {
        id: 'c2',
        title: 'List retention requirements and permitted exceptions.',
        meta: 'output_source_2 • 1 KB selected (within)',
      },
    ],
  },
])

const selectedDatasetId = ref(datasets.value[0]?.id || null)

const filteredDatasets = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return datasets.value
  return datasets.value.filter((d) => {
    return (
      d.name.toLowerCase().includes(q) ||
      d.description.toLowerCase().includes(q) ||
      d.status.toLowerCase().includes(q)
    )
  })
})

const selected = computed(() => {
  const id = selectedDatasetId.value
  return datasets.value.find((d) => d.id === id) || null
})

function pick(id: string) {
  selectedDatasetId.value = id
}

function onNewDataset() {
  ElMessage.info('New Dataset: UI only (no backend wired)')
}

function onImport() {
  ElMessage.info('Import: UI only')
}

function onExport() {
  ElMessage.info('Export: UI only')
}

function onAddCase() {
  ElMessage.info('Add Case: UI only')
}
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
          <button class="head-action" type="button" @click="onExport">Full export</button>
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
              <div class="row-updated">{{ d.updatedLabel }}</div>
              <div class="chip" :class="d.status === 'Active' ? 'chip-active' : 'chip-draft'">{{ d.status }}</div>
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
              <div v-for="c in selected.cases" :key="c.id" class="case">
                <div class="case-title">{{ c.title }}</div>
                <div class="case-meta">{{ c.meta }}</div>
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
