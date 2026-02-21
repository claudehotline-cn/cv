<template>
  <div class="audit-runs-page">
    <div class="audit-runs-scroll">
      <section class="audit-page-head">
        <div class="head-left">
          <div class="breadcrumbs">
            <span>Projects</span>
            <el-icon><ArrowRight /></el-icon>
            <span>{{ selectedAgent || 'All Agents' }}</span>
          </div>
          <h1>Audit Logs</h1>
          <p>Monitor agent executions, latency, and token consumption across all environments.</p>
        </div>

        <div class="head-right">
          <el-segmented
            v-model="mode"
            :options="[
              { label: 'Real-time', value: 'realtime' },
              { label: 'Historical', value: 'historical' }
            ]"
            class="mode-toggle"
          />
          <el-button class="export-btn" :icon="Download" @click="exportRuns">Export</el-button>
        </div>
      </section>

      <section class="kpi-grid" v-loading="overviewLoading">
        <el-card shadow="never" class="kpi-card">
          <div class="kpi-icon cyan"><span class="material-symbols-outlined">bolt</span></div>
          <div class="kpi-body">
            <div class="kpi-label">TOTAL REQUESTS ({{ overviewWindowLabel }})</div>
            <div class="kpi-value-row">
              <div class="kpi-value">{{ formatNumber(overview?.total_requests ?? 0) }}</div>
              <div class="kpi-delta up" v-if="overview">{{ successRateText }}</div>
            </div>
          </div>
        </el-card>

        <el-card shadow="never" class="kpi-card">
          <div class="kpi-icon amber"><span class="material-symbols-outlined">timer</span></div>
          <div class="kpi-body">
            <div class="kpi-label">AVG LATENCY</div>
            <div class="kpi-value-row">
              <div class="kpi-value">{{ formatLatencyMs(overview?.avg_latency_ms ?? 0) }}</div>
              <div class="kpi-delta" :class="(overview?.avg_latency_ms ?? 0) > 1200 ? 'down' : 'up'">
                {{ latencyHealthText }}
              </div>
            </div>
          </div>
        </el-card>

        <el-card shadow="never" class="kpi-card">
          <div class="kpi-icon violet"><span class="material-symbols-outlined">toll</span></div>
          <div class="kpi-body">
            <div class="kpi-label">TOTAL TOKENS USED</div>
            <div class="kpi-value-row">
              <div class="kpi-value">{{ formatCompact(overview?.total_tokens ?? 0) }}</div>
               <div class="kpi-delta up">{{ overviewWindowLabel }}</div>
            </div>
          </div>
        </el-card>
      </section>

      <section class="filter-wrap">
        <el-card shadow="never" class="filter-card">
          <div class="filter-row" :class="mode">
            <el-input
              v-model="searchQuery"
              class="search-input"
              clearable
              placeholder="Filter by Request ID, Session ID or Keyword..."
              :prefix-icon="Search"
              @keyup.enter="handleQuery"
            />

            <el-select v-model="selectedStatus" clearable placeholder="Status: All" class="filter-select">
              <el-option label="Succeeded" value="succeeded" />
              <el-option label="Failed" value="failed" />
              <el-option label="Interrupted" value="interrupted" />
              <el-option label="Running" value="running" />
            </el-select>

            <el-select v-model="selectedAction" clearable placeholder="Action: All" class="filter-select">
              <el-option label="LLM" value="llm" />
              <el-option label="Tool" value="tool" />
              <el-option label="Chain" value="chain" />
              <el-option label="Interrupt" value="interrupt" />
              <el-option label="Job" value="job" />
            </el-select>

            <el-select v-model="selectedAgent" clearable placeholder="Agent: All" class="filter-select wide">
              <el-option v-for="agent in agentOptions" :key="agent" :label="agent" :value="agent" />
            </el-select>

            <el-select v-if="mode === 'realtime'" v-model="quickWindow" class="filter-select time-select" :prefix-icon="Calendar">
              <el-option label="Last 24 Hours" value="24h" />
              <el-option label="Last 72 Hours" value="72h" />
              <el-option label="Last 7 Days" value="7d" />
            </el-select>

            <el-date-picker
              v-else
              v-model="dateRange"
              type="datetimerange"
              range-separator="-"
              start-placeholder="Start"
              end-placeholder="End"
              class="filter-date"
            />

            <el-button text class="reset-btn" :icon="Filter" @click="clearFilters" />
            <el-button type="primary" class="query-btn" @click="handleQuery">Query</el-button>
          </div>
        </el-card>
      </section>

      <section class="table-wrap">
        <el-card shadow="never" class="table-card">
          <el-table
            :data="runs"
            v-loading="loading"
            class="audit-table"
            :row-class-name="getRowClassName"
            @row-click="openRun"
          >
            <el-table-column label="TIMESTAMP" width="190">
              <template #default="{ row }">
                <div class="ts-cell">
                  <div class="ts-main">{{ formatDate(row.time) }}</div>
                  <div class="ts-sub">{{ formatRelative(row.time) }}</div>
                </div>
              </template>
            </el-table-column>

            <el-table-column label="REQUEST ID" width="170">
              <template #default="{ row }">
                <button class="id-link" @click.stop="openRun(row)">
                  {{ shortenId(row.request_id) }}
                </button>
              </template>
            </el-table-column>

            <el-table-column label="SESSION ID" width="160">
              <template #default="{ row }">
                <div class="session-cell">
                  <span class="session-strip" />
                  <span>{{ row.session_id ? shortenId(row.session_id) : '-' }}</span>
                </div>
              </template>
            </el-table-column>

            <el-table-column label="AGENT NAME" width="180">
              <template #default="{ row }">
                <div class="agent-cell">
                  <span class="agent-icon material-symbols-outlined">smart_toy</span>
                  <span class="agent-name">{{ row.root_agent_name || 'Unknown' }}</span>
                </div>
              </template>
            </el-table-column>

            <el-table-column label="ACTION TYPE" width="140">
              <template #default="{ row }">
                <span class="action-pill" :class="`action-${row.action_type}`">{{ actionLabel(row.action_type) }}</span>
              </template>
            </el-table-column>

            <el-table-column label="LATENCY" width="140">
              <template #default="{ row }">
                <div class="latency-cell">
                  <div class="latency-text">{{ formatDurationSeconds(row.duration_seconds) }}</div>
                  <div class="latency-track">
                    <div
                      class="latency-fill"
                      :class="latencyClass(row)"
                      :style="{ width: `${latencyWidth(row)}%` }"
                    />
                  </div>
                </div>
              </template>
            </el-table-column>

            <el-table-column label="TOKENS" width="120" align="right">
              <template #default="{ row }">
                <span class="token-text">{{ row.total_tokens > 0 ? formatNumber(row.total_tokens) : '--' }}</span>
              </template>
            </el-table-column>

            <el-table-column label="STATUS" min-width="140">
              <template #default="{ row }">
                <div class="status-cell" :class="`status-${row.status}`">
                  <span class="material-symbols-outlined">{{ statusIcon(row.status) }}</span>
                  <span>{{ statusLabel(row.status) }}</span>
                </div>
              </template>
            </el-table-column>
          </el-table>

          <div class="table-footer">
            <div class="footer-left">
              <span>Showing <b>{{ rangeStart }}</b> - <b>{{ rangeEnd }}</b> of {{ formatNumber(total) }} results</span>
              <span class="divider" />
              <span class="rows-select-wrap">
                Rows per page:
                <el-select v-model="pageSize" class="rows-select" @change="handlePageSizeChange">
                  <el-option :value="20" label="20" />
                  <el-option :value="50" label="50" />
                  <el-option :value="100" label="100" />
                </el-select>
              </span>
            </div>
            <el-pagination
              v-model:current-page="currentPage"
              :page-size="pageSize"
              :total="total"
              layout="prev, pager, next"
              @current-change="refresh"
            />
          </div>
        </el-card>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowRight, Calendar, Download, Filter, Search } from '@element-plus/icons-vue'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import apiClient, { type AuditOverview, type AuditRunItem } from '@/api/client'

dayjs.extend(relativeTime)

const router = useRouter()
const route = useRoute()

const mode = ref<'realtime' | 'historical'>('realtime')
const loading = ref(false)
const overviewLoading = ref(false)

const runs = ref<AuditRunItem[]>([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(50)

const searchQuery = ref('')
const selectedStatus = ref('')
const selectedAction = ref('')
const selectedAgent = ref('')
const dateRange = ref<[Date, Date] | null>(null)
const quickWindow = ref<'24h' | '72h' | '7d'>('24h')

const overview = ref<AuditOverview | null>(null)
const agentOptions = ref<string[]>([])
let realtimeTimer: ReturnType<typeof setInterval> | null = null

const maxLatencyMs = computed(() => {
  const values = runs.value
    .map((r) => (r.duration_seconds || 0) * 1000)
    .filter((v) => v > 0)
  return values.length ? Math.max(...values) : 1
})

const successRateText = computed(() => {
  if (!overview.value || overview.value.total_requests <= 0) return '0%'
  const rate = (overview.value.succeeded_requests / overview.value.total_requests) * 100
  return `${rate.toFixed(1)}%`
})

const latencyHealthText = computed(() => {
  const ms = overview.value?.avg_latency_ms ?? 0
  if (ms >= 3000) return 'Slow'
  if (ms >= 1200) return 'Medium'
  return 'Healthy'
})

function quickWindowToHours() {
  if (quickWindow.value === '72h') return 72
  if (quickWindow.value === '7d') return 24 * 7
  return 24
}

function resolveOverviewWindowHours() {
  if (mode.value === 'realtime') return quickWindowToHours()
  if (dateRange.value?.[0] && dateRange.value?.[1]) {
    const diff = Math.abs(dayjs(dateRange.value[1]).diff(dayjs(dateRange.value[0]), 'hour'))
    return Math.max(1, Math.min(24 * 7, diff || 24))
  }
  return 24 * 7
}

function resolveQueryBounds() {
  if (mode.value === 'historical') {
    return {
      start: dateRange.value?.[0]?.toISOString(),
      end: dateRange.value?.[1]?.toISOString(),
    }
  }

  const now = dayjs()
  const start = now.subtract(quickWindowToHours(), 'hour')
  return {
    start: start.toISOString(),
    end: now.toISOString(),
  }
}

const overviewWindowLabel = computed(() => {
  const hours = resolveOverviewWindowHours()
  if (hours >= 24 * 7) return '7D'
  if (hours >= 72) return '72H'
  return '24H'
})

const rangeStart = computed(() => {
  if (!total.value) return 0
  return (currentPage.value - 1) * pageSize.value + 1
})

const rangeEnd = computed(() => {
  if (!total.value) return 0
  return Math.min(currentPage.value * pageSize.value, total.value)
})

function shortenId(id: string) {
  if (!id) return '-'
  return id.length <= 12 ? id : `${id.slice(0, 8)}...`
}

function formatDate(value: string) {
  return dayjs(value).format('MMM D, HH:mm:ss')
}

function formatRelative(value: string) {
  return dayjs(value).fromNow()
}

function formatNumber(value: number) {
  return new Intl.NumberFormat('en-US').format(value || 0)
}

function formatCompact(value: number) {
  return new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(value || 0)
}

function formatLatencyMs(ms: number) {
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(2)}s`
}

function formatDurationSeconds(seconds?: number | null) {
  if (seconds == null) return '--'
  if (seconds < 1) return `${Math.max(1, Math.round(seconds * 1000))}ms`
  if (seconds < 10) return `${seconds.toFixed(2)}s`
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  return `${Math.round(seconds)}s`
}

function latencyWidth(run: AuditRunItem) {
  const ms = Math.max((run.duration_seconds || 0) * 1000, 0)
  if (ms <= 0) return 6
  return Math.max(8, Math.min(100, (ms / maxLatencyMs.value) * 100))
}

function latencyClass(run: AuditRunItem) {
  const ms = (run.duration_seconds || 0) * 1000
  if (ms >= 3000) return 'latency-danger'
  if (ms >= 1200) return 'latency-warn'
  return 'latency-good'
}

function statusIcon(status: string) {
  const s = (status || '').toLowerCase()
  if (s === 'succeeded') return 'check_circle'
  if (s === 'failed') return 'error'
  if (s === 'interrupted' || s === 'cancelled') return 'pause_circle'
  if (s === 'running') return 'progress_activity'
  return 'help'
}

function statusLabel(status: string) {
  const s = (status || '').toLowerCase()
  if (s === 'succeeded') return 'SUCCESS'
  if (s === 'failed') return 'FAILED'
  if (s === 'interrupted') return 'INTERRUPTED'
  if (s === 'cancelled') return 'CANCELLED'
  if (s === 'running') return 'RUNNING'
  return (status || 'UNKNOWN').toUpperCase()
}

function actionLabel(action: string) {
  const a = (action || '').toLowerCase()
  if (a === 'llm') return 'LLM CALL'
  if (a === 'tool') return 'TOOL USE'
  if (a === 'interrupt') return 'INTERRUPT'
  if (a === 'job') return 'JOB'
  return 'CHAIN'
}

function getRowClassName({ row }: { row: AuditRunItem }) {
  return row.status?.toLowerCase() === 'failed' ? 'audit-row-failed' : ''
}

function openRun(run: AuditRunItem) {
  if (!run?.request_id) return
  router.push({ path: `/audit/${run.request_id}` })
}

function clearFilters() {
  searchQuery.value = ''
  selectedStatus.value = ''
  selectedAction.value = ''
  selectedAgent.value = ''
  quickWindow.value = '24h'
  dateRange.value = null
  currentPage.value = 1
  refresh()
  refreshOverview()
}

function handleQuery() {
  currentPage.value = 1
  refresh()
  refreshOverview()
}

function handlePageSizeChange() {
  currentPage.value = 1
  refresh()
}

function stopRealtimePolling() {
  if (!realtimeTimer) return
  clearInterval(realtimeTimer)
  realtimeTimer = null
}

function startRealtimePolling() {
  stopRealtimePolling()
  if (mode.value !== 'realtime') return
  realtimeTimer = setInterval(() => {
    refreshOverview()
    refresh()
  }, 15000)
}

function exportRuns() {
  const bounds = resolveQueryBounds()
  const snapshot = {
    exported_at: new Date().toISOString(),
    mode: mode.value,
    filters: {
      status: selectedStatus.value || null,
      action: selectedAction.value || null,
      agent: selectedAgent.value || null,
      quick_window: mode.value === 'realtime' ? quickWindow.value : null,
      q: searchQuery.value || null,
      start_date: bounds.start || null,
      end_date: bounds.end || null,
    },
    pagination: {
      current_page: currentPage.value,
      page_size: pageSize.value,
      total: total.value,
    },
    overview: overview.value,
    runs: runs.value,
  }

  const ts = dayjs().format('YYYYMMDD-HHmmss')
  const blob = new Blob([JSON.stringify(snapshot, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `audit-runs-${ts}.json`
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

async function refreshOverview() {
  overviewLoading.value = true
  try {
    overview.value = await apiClient.getAuditOverview({
      window_hours: resolveOverviewWindowHours(),
      agent: selectedAgent.value || undefined,
    })
  } catch (error) {
    console.error('Failed to load audit overview', error)
  } finally {
    overviewLoading.value = false
  }
}

async function refresh() {
  loading.value = true
  try {
    const offset = (currentPage.value - 1) * pageSize.value
    const bounds = resolveQueryBounds()
    const response = await apiClient.listAuditRuns({
      limit: pageSize.value,
      offset,
      status: selectedStatus.value || undefined,
      action: selectedAction.value || undefined,
      agent: selectedAgent.value || undefined,
      q: searchQuery.value || undefined,
      start_date: bounds.start,
      end_date: bounds.end,
    })
    runs.value = response.items
    total.value = response.total
  } catch (error) {
    console.error('Failed to load audit runs', error)
  } finally {
    loading.value = false
  }
}

watch(mode, async () => {
  startRealtimePolling()
  await Promise.all([refreshOverview(), refresh()])
})

watch(quickWindow, async () => {
  if (mode.value !== 'realtime') return
  currentPage.value = 1
  await Promise.all([refreshOverview(), refresh()])
})

onMounted(async () => {
  const q = route.query.q
  if (typeof q === 'string' && q) searchQuery.value = q

  const agent = route.query.agent
  if (typeof agent === 'string' && agent) selectedAgent.value = agent

  try {
    const agents = await apiClient.listAgents()
    agentOptions.value = agents.map((a: any) => a.name)
  } catch (error) {
    console.error('Failed to load agents for audit filter', error)
  }

  startRealtimePolling()
  await Promise.all([refreshOverview(), refresh()])
})

onBeforeUnmount(() => {
  stopRealtimePolling()
})
</script>

<style scoped>
.audit-runs-page {
  height: 100%;
  min-height: 100%;
  background: #fbfdff;
  color: #0f181a;
}

.audit-runs-scroll {
  height: 100%;
  overflow-y: auto;
  padding: 24px 24px 20px;
  font-family: 'Noto Sans', var(--font-sans);
}

.audit-page-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 16px;
}

.head-left h1 {
  margin: 6px 0 4px;
  font-family: 'Space Grotesk', var(--font-sans);
  font-size: 54px;
  font-weight: 800;
  letter-spacing: -0.02em;
  line-height: 1.03;
  color: #0c1930;
}

.head-left p {
  margin: 0;
  color: #5e7590;
  font-size: 14px;
}

.breadcrumbs {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: #6c8195;
  font-size: 13px;
  font-weight: 600;
}

.head-right {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-top: 10px;
}

.mode-toggle {
  --el-segmented-item-selected-bg-color: #25d1f4;
  --el-segmented-item-selected-color: #ffffff;
  border: 1px solid #d7e5ef;
  border-radius: 12px;
  padding: 3px;
  background: #ffffff;
}

.export-btn {
  border: 1px solid #d7e5ef;
  border-radius: 12px;
  height: 40px;
  font-weight: 700;
  color: #162a42;
  background: #ffffff;
}

.kpi-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 14px;
}

.kpi-card {
  border-radius: 16px;
  border: 1px solid #deebf3;
  box-shadow: 0 4px 14px rgba(18, 44, 72, 0.04);
}

.kpi-card :deep(.el-card__body) {
  padding: 18px;
  display: flex;
  align-items: center;
  gap: 12px;
}

.kpi-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.kpi-icon .material-symbols-outlined {
  font-size: 24px;
  font-variation-settings: 'FILL' 1;
}

.kpi-icon.cyan {
  background: #e6f9ff;
  color: #1bbde3;
}

.kpi-icon.amber {
  background: #fff5e2;
  color: #eea400;
}

.kpi-icon.violet {
  background: #f1ebff;
  color: #8f6bf5;
}

.kpi-label {
  font-size: 13px;
  font-weight: 800;
  letter-spacing: 0.08em;
  color: #67809a;
}

.kpi-value-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.kpi-value {
  font-family: 'Space Grotesk', var(--font-sans);
  font-size: 48px;
  font-weight: 800;
  line-height: 1;
  color: #0f172a;
}

.kpi-delta {
  font-size: 13px;
  font-weight: 800;
}

.kpi-delta.up {
  color: #00b87c;
}

.kpi-delta.down {
  color: #ea3f65;
}

.filter-wrap {
  margin-bottom: 14px;
}

.filter-card {
  border-radius: 16px;
  border: 1px solid #deebf3;
  box-shadow: 0 4px 14px rgba(18, 44, 72, 0.04);
}

.filter-card :deep(.el-card__body) {
  padding: 12px;
}

.filter-row {
  display: grid;
  grid-template-columns: minmax(300px, 1fr) 148px 148px 176px 280px 42px 92px;
  gap: 8px;
  align-items: center;
}

.filter-row.historical {
  grid-template-columns: minmax(240px, 1fr) 148px 148px 176px minmax(360px, 1.45fr) 42px 92px;
}

.search-input :deep(.el-input__wrapper),
.filter-select :deep(.el-input__wrapper),
.filter-date :deep(.el-input__wrapper) {
  background: #ffffff;
  border: 1px solid #d9e7f0;
  border-radius: 10px;
  box-shadow: none;
  min-height: 40px;
}

.search-input :deep(.el-input__wrapper.is-focus),
.filter-select :deep(.el-input__wrapper.is-focus),
.filter-date :deep(.el-input__wrapper.is-focus) {
  border-color: #25d1f4;
  box-shadow: 0 0 0 3px rgba(37, 209, 244, 0.12);
}

.time-select :deep(.el-input__inner) {
  color: #00b5e5;
  font-weight: 700;
}

.filter-select.wide {
  width: 100%;
}

.filter-date {
  width: 100%;
  min-width: 0;
}

.filter-date :deep(.el-date-editor--datetimerange) {
  width: 100%;
  min-width: 0;
}

.filter-date :deep(.el-range-input) {
  width: auto;
  flex: 1 1 auto;
  min-width: 118px;
}

.filter-date :deep(.el-range-separator) {
  color: #7b90a5;
  padding: 0 6px;
}

.reset-btn {
  width: 42px;
  height: 42px;
  border: 1px solid #d9e7f0;
  border-radius: 10px;
  color: #7a91a6;
}

.query-btn {
  height: 42px;
  border-radius: 10px;
  font-weight: 800;
  border: none;
  background: #25d1f4;
  color: #ffffff;
}

.query-btn:hover {
  transform: none;
  box-shadow: none;
  opacity: 0.96;
}

.table-wrap {
  padding-bottom: 8px;
}

.table-card {
  border-radius: 16px;
  border: 1px solid #deebf3;
  overflow: hidden;
  box-shadow: 0 4px 14px rgba(18, 44, 72, 0.04);
}

.table-card :deep(.el-card__body) {
  padding: 0;
}

.audit-table {
  --el-table-header-bg-color: #ffffff;
  --el-table-tr-bg-color: #ffffff;
  --el-table-row-hover-bg-color: rgba(37, 209, 244, 0.05);
}

.audit-table :deep(th.el-table__cell) {
  height: 52px;
  font-size: 12px;
  font-weight: 800;
  color: #4f6d8d;
  letter-spacing: 0.08em;
  border-bottom-color: #e7f1f5;
}

.audit-table :deep(td.el-table__cell) {
  height: 82px;
  border-bottom-color: #eef5f8;
  cursor: pointer;
}

.audit-table :deep(.audit-row-failed > td.el-table__cell:first-child) {
  border-left: 4px solid #ff446e;
}

.ts-main {
  font-size: 16px;
  font-weight: 700;
  color: #0f172a;
  line-height: 1.2;
}

.ts-sub {
  margin-top: 4px;
  font-size: 12px;
  color: #8aa1b1;
}

.id-link {
  border: none;
  background: transparent;
  padding: 0;
  color: #25c6ee;
  font-family: 'JetBrains Mono', monospace;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
}

.id-link:hover {
  text-decoration: underline;
}

.session-cell {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: #3f6079;
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
  font-weight: 600;
}

.session-strip {
  width: 4px;
  height: 18px;
  border-radius: 999px;
  background: #7de7ff;
}

.agent-cell {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.agent-icon {
  font-size: 18px;
  color: #20c5ea;
  background: #e8fbff;
  border-radius: 8px;
  padding: 4px;
}

.agent-name {
  font-size: 16px;
  font-weight: 700;
  color: #152538;
}

.action-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 4px 9px;
  border-radius: 7px;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.06em;
}

.action-llm {
  color: #5f55e8;
  background: #ebe8ff;
}

.action-tool {
  color: #d98b00;
  background: #fff5d9;
}

.action-chain {
  color: #0f8cd4;
  background: #e8f7ff;
}

.action-interrupt {
  color: #c47a00;
  background: #fff0d6;
}

.action-job {
  color: #50708a;
  background: #edf3f7;
}

.latency-cell {
  min-width: 88px;
}

.latency-text {
  font-family: 'JetBrains Mono', monospace;
  font-size: 14px;
  color: #17283b;
}

.latency-track {
  margin-top: 6px;
  width: 56px;
  height: 4px;
  background: #edf3f7;
  border-radius: 99px;
  overflow: hidden;
}

.latency-fill {
  height: 100%;
  border-radius: 99px;
}

.latency-good {
  background: #1dd7a0;
}

.latency-warn {
  background: #f9b41a;
}

.latency-danger {
  background: #ff4770;
}

.token-text {
  font-family: 'JetBrains Mono', monospace;
  font-size: 15px;
  font-weight: 700;
  color: #0e1a2d;
}

.status-cell {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.06em;
}

.status-cell .material-symbols-outlined {
  font-size: 14px;
  font-variation-settings: 'FILL' 1;
}

.status-succeeded {
  color: #00b87c;
}

.status-failed {
  color: #ff446e;
}

.status-interrupted,
.status-cancelled {
  color: #e09100;
}

.status-running {
  color: #169ad3;
}

.table-footer {
  border-top: 1px solid #e7f1f5;
  background: #ffffff;
  padding: 12px 14px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.footer-left {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  color: #5f7488;
  font-size: 14px;
}

.divider {
  width: 1px;
  height: 20px;
  background: #d8e6ed;
}

.rows-select-wrap {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.rows-select {
  width: 84px;
}

.rows-select :deep(.el-input__wrapper) {
  border-radius: 8px;
  background: #ffffff;
  border: 1px solid #dbe8ee;
  box-shadow: none;
}

.table-footer :deep(.el-pagination .btn-prev),
.table-footer :deep(.el-pagination .btn-next),
.table-footer :deep(.el-pager li) {
  border-radius: 8px;
  min-width: 30px;
  height: 30px;
  line-height: 30px;
  border: 1px solid transparent;
}

.table-footer :deep(.el-pager li.is-active) {
  background: #25d1f4;
  color: #ffffff;
  border-color: #25d1f4;
}

@media (max-width: 1600px) {
  .filter-row {
    grid-template-columns: minmax(220px, 1fr) 140px 140px 160px 240px 42px 92px;
  }

  .filter-row.historical {
    grid-template-columns: minmax(200px, 1fr) 140px 140px 160px minmax(320px, 1.35fr) 42px 92px;
  }

  .kpi-value {
    font-size: 40px;
  }
}

@media (max-width: 1280px) {
  .audit-page-head {
    flex-direction: column;
    align-items: flex-start;
  }

  .head-right {
    margin-top: 0;
  }

  .kpi-grid {
    grid-template-columns: 1fr;
  }

  .filter-row {
    grid-template-columns: 1fr 1fr;
  }

  .search-input,
  .filter-date {
    grid-column: 1 / -1;
  }
}

@media (max-width: 768px) {
  .audit-runs-scroll {
    padding: 16px 12px;
  }

  .head-left h1 {
    font-size: 34px;
  }

  .filter-row {
    grid-template-columns: 1fr;
  }

  .table-footer {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
