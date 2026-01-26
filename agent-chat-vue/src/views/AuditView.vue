<template>
  <el-container class="audit-layout el-premium">
    <!-- Sidebar -->
    <el-aside width="auto">
      <AppSidebar />
    </el-aside>

    <!-- Main Audit Content -->
    <el-container direction="vertical" class="audit-container">
        <el-header class="audit-header">
            <div class="header-left">
                <h2 class="page-title">Run History</h2>
            </div>
            <div class="header-right">
                 <el-button @click="refresh" :icon="Refresh" :loading="loading" circle />
            </div>
        </el-header>
        
        <el-main class="audit-main">
            <div class="audit-content">
                <el-card class="audit-card-el" shadow="never" :body-style="{ padding: '0px' }">
                     <!-- Filter Bar (Consolidated) -->
                     <div class="filter-bar">
                        <!-- Left: Filters -->
                        <div class="filter-group">
                             <el-input 
                                v-model="searchQuery"
                                class="filter-input-search"
                                placeholder="Search ID / User..." 
                                :prefix-icon="Search"
                                clearable
                                @keyup.enter="refresh"
                             />
                             <el-date-picker
                                v-model="dateRange"
                                type="datetimerange"
                                range-separator="-"
                                start-placeholder="Start"
                                end-placeholder="End"
                                :shortcuts="shortcuts"
                                class="filter-date"
                                :prefix-icon="Calendar"
                            />
                            <el-select v-model="selectedStatus" placeholder="Status" clearable class="filter-select">
                                <template #prefix><el-icon><InfoFilled /></el-icon></template>
                                <el-option label="Succeeded" value="succeeded" />
                                <el-option label="Failed" value="failed" />
                                <el-option label="Running" value="running" />
                            </el-select>
                            <el-select v-model="selectedAgent" placeholder="All Agents" clearable class="filter-select">
                                <template #prefix><el-icon><User /></el-icon></template>
                                <el-option v-for="agent in agentOptions" :key="agent" :label="agent" :value="agent" />
                            </el-select>
                        </div>
                        
                        <!-- Right: Actions -->
                        <div class="filter-actions">
                            <el-button v-if="hasFilters" link type="info" @click="clearFilters">Reset</el-button>
                            <el-button type="primary" @click="refresh">Query</el-button>
                        </div>
                     </div>

                     <!-- Table -->
                     <el-table 
                        v-loading="loading"
                        :data="runs" 
                        style="width: 100%" 
                        class="premium-table"
                        :header-cell-style="{ 
                            background: 'var(--bg-secondary)', 
                            color: 'var(--text-secondary)', 
                            fontWeight: '600', 
                            fontSize: '12px', 
                            textTransform: 'uppercase',
                            borderBottom: '1px solid var(--border-color)'
                        }"
                     >
                        <el-table-column label="Request ID" width="120" fixed="left">
                            <template #default="scope">
                                <el-tooltip :content="scope.row.request_id" placement="top" :show-after="500">
                                    <span class="font-mono text-xs text-secondary cursor-pointer hover:text-primary transition-colors">
                                        #{{ scope.row.request_id.substring(0, 8) }}
                                    </span>
                                </el-tooltip>
                            </template>
                        </el-table-column>

                        <el-table-column label="Session ID" width="120">
                            <template #default="scope">
                                <el-tooltip :content="scope.row.session_id" placement="top" :show-after="500">
                                     <span class="font-mono text-xs text-secondary cursor-pointer hover:text-primary transition-colors">
                                        {{ scope.row.session_id ? scope.row.session_id.substring(0, 8) : '-' }}
                                     </span>
                                </el-tooltip>
                            </template>
                        </el-table-column>

                        <el-table-column prop="time" label="Started" width="180">
                            <template #default="scope">
                                <div class="flex flex-col">
                                    <span class="text-sm font-medium">{{ formatDate(scope.row.time).split(' ')[0] }}</span>
                                    <span class="text-xs text-secondary">{{ formatDate(scope.row.time).split(' ')[1] }}</span>
                                </div>
                            </template>
                        </el-table-column>

                        <el-table-column prop="root_agent_name" label="Agent" width="160">
                             <template #default="scope">
                                <span class="font-bold text-primary">{{ scope.row.root_agent_name }}</span>
                            </template>
                        </el-table-column>

                        <el-table-column prop="status" label="Status" width="120">
                            <template #default="scope">
                                <el-tag 
                                    :type="getStatusType(scope.row.status)" 
                                    effect="light" 
                                    round 
                                    size="small"
                                    class="border-none font-medium"
                                >
                                    {{ scope.row.status }}
                                </el-tag>
                            </template>
                        </el-table-column>
                        
                        <el-table-column label="Latency" width="100">
                             <template #default="scope">
                                <span class="text-sm font-mono">{{ formatDuration(scope.row.duration_seconds) }}</span>
                            </template>
                        </el-table-column>

                        <el-table-column label="Statistics" min-width="280">
                             <template #default="scope">
                                <div class="flex items-center gap-3">
                                    <el-tooltip content="LLM Calls" placement="top" :show-after="300" v-if="scope.row.llm_calls_count > 0">
                                        <div class="flex items-center gap-1 text-xs text-secondary cursor-help">
                                            <el-icon><ChatDotRound /></el-icon> {{ scope.row.llm_calls_count }}
                                        </div>
                                    </el-tooltip>

                                    <el-tooltip content="Tool Calls" placement="top" :show-after="300" v-if="scope.row.tool_calls_count > 0">
                                        <div class="flex items-center gap-1 text-xs text-secondary cursor-help">
                                            <el-icon><Tools /></el-icon> {{ scope.row.tool_calls_count }}
                                        </div>
                                    </el-tooltip>

                                    <el-tooltip content="Interrupts (HITL)" placement="top" :show-after="300" v-if="scope.row.interrupts_count > 0">
                                        <div class="flex items-center gap-1 text-xs text-warning cursor-help">
                                            <el-icon><VideoPause /></el-icon> {{ scope.row.interrupts_count }}
                                        </div>
                                    </el-tooltip>

                                    <el-tooltip v-if="scope.row.failures_count > 0" content="Errors" placement="top" :show-after="300">
                                        <el-tag size="small" type="danger" effect="dark" class="ml-auto cursor-help">
                                            {{ scope.row.failures_count }} Errors
                                        </el-tag>
                                    </el-tooltip>
                                </div>
                            </template>
                        </el-table-column>

                        <el-table-column prop="initiator" label="Initiator" width="140" show-overflow-tooltip>
                            <template #default="scope">
                                <div class="flex items-center gap-2">
                                    <div class="w-6 h-6 rounded bg-gray-100 flex items-center justify-center text-xs font-bold text-gray-500">
                                        {{ scope.row.initiator.charAt(0).toUpperCase() }}
                                    </div>
                                    <span class="text-xs truncate">{{ scope.row.initiator }}</span>
                                </div>
                            </template>
                        </el-table-column>

                      <el-table-column width="80" align="right" fixed="right">
                            <template #default="scope">
                                <el-button link type="primary" :icon="ArrowRight" @click="viewRunDetails(scope.row)" />
                            </template>
                        </el-table-column>
                     </el-table>

                     <div class="p-4 border-t border-gray-200 dark:border-gray-700 flex justify-end">
                        <el-pagination
                            v-model:current-page="currentPage"
                            v-model:page-size="pageSize"
                            :page-sizes="[20, 50, 100]"
                            layout="total, sizes, prev, pager, next, jumper"
                            :total="total"
                            @size-change="refresh"
                            @current-change="refresh"
                        />
                     </div>
                </el-card>

                <!-- Run Details Drawer -->
                <el-drawer
                    v-model="drawerVisible"
                    title="Run Execution Details"
                    direction="rtl"
                    size="50%"
                    class="premium-drawer"
                    :destroy-on-close="true"
                    :with-header="false" 
                >
                     <div v-if="runDetail" class="h-full flex flex-col bg-white dark:bg-gray-900">
                        <!-- Custom Header -->
                        <div class="px-6 py-4 border-b border-gray-200 dark:border-gray-700 flex justify-between items-center bg-gray-50 dark:bg-gray-800">
                            <div>
                                <div class="flex items-center gap-3">
                                    <h3 class="text-lg font-bold text-gray-900 dark:text-gray-100">{{ runDetail.run?.root_agent_name }}</h3>
                                    <el-tag :type="getStatusType(runDetail.run?.status)" effect="dark" size="small">{{ runDetail.run?.status }}</el-tag>
                                </div>
                                <div class="text-xs text-gray-500 mt-1 font-mono">ID: {{ runDetail.run?.request_id }}</div>
                            </div>
                            <el-button @click="drawerVisible = false" circle :icon="Close" size="small" />
                        </div>

                        <!-- Content Stats -->
                        <div class="grid grid-cols-6 gap-4 p-6 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900">
                             <div class="stat-item">
                                <div class="text-xs text-gray-500 uppercase">Duration</div>
                                <div class="text-xl font-bold mt-1">{{ formatDuration(runDetail.run?.duration_seconds) }}</div>
                             </div>
                             <div class="stat-item">
                                <div class="text-xs text-gray-500 uppercase">LLM Calls</div>
                                <div class="text-xl font-bold mt-1">{{ runDetail.run?.llm_calls_count }}</div>
                             </div>
                             <div class="stat-item">
                                <div class="text-xs text-gray-500 uppercase">Tool Calls</div>
                                <div class="text-xl font-bold mt-1">{{ runDetail.run?.tool_calls_count }}</div>
                             </div>
                             <div class="stat-item">
                                <div class="text-xs text-gray-500 uppercase text-yellow-600">Interrupts</div>
                                <div class="text-xl font-bold mt-1 text-yellow-600">{{ runDetail.run?.interrupts_count }}</div>
                             </div>
                             <div class="stat-item">
                                <div class="text-xs text-gray-500 uppercase text-red-600">Errors</div>
                                <div class="text-xl font-bold mt-1 text-red-600">{{ runDetail.run?.failures_count }}</div>
                             </div>
                             <div class="stat-item">
                                <div class="text-xs text-gray-500 uppercase">Start Time</div>
                                <div class="text-sm font-medium mt-1">{{ formatDate(runDetail.run?.time) }}</div>
                             </div>
                        </div>

                        <!-- Tabs -->
                        <div class="flex-1 overflow-hidden flex flex-col">
                            <el-tabs v-model="activeTab" class="h-full flex flex-col px-6">
                                <el-tab-pane label="Event" name="timeline" class="h-full overflow-y-auto pb-6">
                                    <el-timeline class="mt-4 pl-2">
                                        <el-timeline-item
                                          v-for="(activity, index) in runDetail.recent_events"
                                          :key="index"
                                          :ref="(el: any) => setTimelineItemRef(el, activity.span_id)"
                                          :timestamp="formatTime(activity.time)"
                                          :type="getSeverityType(activity.severity)"
                                          :color="getActivityColor(activity.severity)"
                                          :hollow="activity.severity === 'Info'"
                                          placement="top"
                                          :class="{ 'highlight-event': activity.span_id === highlightedSpanId }"
                                        >
                                          <div class="timeline-content pb-4">
                                              <!-- ... existing content ... -->
                                              <div class="flex items-start justify-between">
                                                  <div>
                                                      <div class="font-bold text-sm text-gray-800 dark:text-gray-200">{{ activity.type }}</div>
                                                      <div class="text-xs text-gray-500 mt-0.5">{{ activity.component }}</div>
                                                  </div>
                                                  <el-tag v-if="activity.severity === 'Error'" type="danger" size="small" effect="plain">Failed</el-tag>
                                              </div>
                                              
                                              <div v-if="activity.message && activity.message !== activity.type" class="mt-2 text-sm text-gray-600 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 p-2 rounded border border-gray-100 dark:border-gray-700">
                                                  {{ activity.message }}
                                              </div>

                                              <!-- Payload Viewer -->
                                              <div v-if="activity.payload && Object.keys(activity.payload).length > 0" class="mt-2">
                                                  <details class="group">
                                                      <summary class="text-xs text-primary cursor-pointer hover:underline list-none font-medium flex items-center gap-1 select-none">
                                                          <el-icon class="group-open:rotate-90 transition-transform"><ArrowRight /></el-icon>
                                                          Payload
                                                      </summary>
                                                  <pre class="json-viewer mt-2">{{ formatPayload(activity.payload) }}</pre>
                                                  </details>
                                              </div>
                                          </div>
                                        </el-timeline-item>
                                    </el-timeline>
                                </el-tab-pane>
                                
                                <el-tab-pane label="Timeline" name="trace" class="h-full overflow-y-auto pb-6">
                                     <div v-if="!traceData.length" class="text-center text-gray-400 py-10">
                                         No timeline data available
                                     </div>
                                     <el-tree 
                                        v-else
                                        :data="traceData" 
                                        node-key="span_id"
                                        default-expand-all
                                        :expand-on-click-node="false"
                                        class="bg-transparent"
                                        @node-click="handleNodeClick"
                                     >
                                        <template #default="{ data }">
                                            <div class="flex-1 flex items-center justify-between py-2 pr-4 border-b border-gray-100 dark:border-gray-800">
                                                <div class="flex items-center gap-2">
                                                    <el-tag size="small" :type="getSpanTypeColor(data.type)">{{ data.type }}</el-tag>
                                                    <span class="text-sm font-medium text-gray-800 dark:text-gray-200">{{ data.name }}</span>
                                                    <el-icon v-if="['interrupted', 'paused'].includes(data.status?.toLowerCase())" class="text-yellow-500 ml-1">
                                                        <VideoPause />
                                                    </el-icon>
                                                    <span v-if="data.duration" class="text-xs text-gray-400 ml-2">{{ formatDuration(data.duration) }}</span>
                                                </div>
                                                <div class="flex items-center gap-2">
                                                     <el-tag size="small" :type="getStatusType(data.status)" effect="plain">{{ data.status }}</el-tag>
                                                </div>
                                            </div>
                                        </template>
                                     </el-tree>
                                </el-tab-pane>

                                <el-tab-pane label="Failures" name="failures" class="h-full overflow-y-auto pb-6">
                                    <div v-if="!runDetail.failures.length" class="flex flex-col items-center justify-center py-12 text-gray-400">
                                        <el-icon :size="48"><CircleCheck /></el-icon>
                                        <div class="mt-4">No failures recorded</div>
                                    </div>
                                    <div v-else class="space-y-4 mt-4">
                                        <div v-for="fail in runDetail.failures" :key="fail.event_id" class="border border-red-200 bg-red-50 dark:bg-red-900/10 rounded-lg p-4">
                                            <div class="flex items-center gap-2 text-red-700 font-bold mb-2">
                                                <el-icon><Warning /></el-icon>
                                                {{ fail.type }}
                                            </div>
                                            <div class="text-sm text-gray-800 dark:text-gray-200 mb-3">{{ fail.message }}</div>
                                            <pre class="json-viewer border-red-100">{{ JSON.stringify(fail.payload, null, 2) }}</pre>
                                            <div class="text-xs text-gray-500 mt-2 text-right">{{ formatTime(fail.time) }}</div>
                                        </div>
                                    </div>
                                </el-tab-pane>
                            </el-tabs>
                        </div>
                     </div>
                </el-drawer>
            </div>
        </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { ref, onMounted, watch, computed, nextTick, type ComponentPublicInstance } from 'vue'
import { Refresh, Search, Calendar, ChatDotRound, Tools, ArrowRight, Close, CircleCheck, Warning, InfoFilled, User, VideoPause } from '@element-plus/icons-vue'
import apiClient from '@/api/client'
import AppSidebar from '@/components/layout/AppSidebar.vue'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
dayjs.extend(relativeTime)

const loading = ref(false)
const drawerLoading = ref(false)
const runs = ref<any[]>([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(50)
const selectedStatus = ref('')
const selectedAgent = ref('')
const searchQuery = ref('')
const dateRange = ref<[Date, Date] | null>(null)
const agentOptions = ref<string[]>([])

// Drawer
const drawerVisible = ref(false)
const runDetail = ref<any>(null)
const activeTab = ref('timeline')

// Shortcuts for date picker
const shortcuts = [
  { text: 'Last Hour', value: () => [new Date(Date.now() - 3600 * 1000), new Date()] },
  { text: 'Last 24h', value: () => [new Date(Date.now() - 3600 * 1000 * 24), new Date()] },
  { text: 'Last 7 Days', value: () => [new Date(Date.now() - 3600 * 1000 * 24 * 7), new Date()] },
]

const hasFilters = computed(() => !!(selectedStatus.value || selectedAgent.value || searchQuery.value || dateRange.value))

const traceData = computed(() => {
    if (!runDetail.value?.spans) return []
    const spans = JSON.parse(JSON.stringify(runDetail.value.spans)) // deep copy
    const map: Record<string, any> = {}
    const roots: any[] = []
    
    // 1. Initialize map
    spans.forEach((s: any) => {
        s.children = []
        s.label = s.name // for el-tree default
        map[s.span_id] = s
    })
    
    // 2. Build Tree
    spans.forEach((s: any) => {
        if (s.parent_span_id && map[s.parent_span_id]) {
            map[s.parent_span_id].children.push(s)
        } else {
            roots.push(s)
        }
    })
    
    return roots
})

const refresh = async () => {
    loading.value = true
    try {
        const offset = (currentPage.value - 1) * pageSize.value
        const res = await apiClient.listAuditRuns({
            status: selectedStatus.value,
            agent: selectedAgent.value,
            q: searchQuery.value,
            start_date: dateRange.value?.[0]?.toISOString(),
            end_date: dateRange.value?.[1]?.toISOString(),
            limit: pageSize.value,
            offset: offset
        })
        runs.value = res.items
        total.value = res.total
    } catch (e) {
        console.error('Failed to fetch runs', e)
    } finally {
        loading.value = false
    }
}

const clearFilters = () => {
    selectedStatus.value = ''
    selectedAgent.value = ''
    searchQuery.value = ''
    dateRange.value = null
    currentPage.value = 1
    refresh()
}

watch([selectedStatus, selectedAgent, dateRange, searchQuery], () => {
    currentPage.value = 1
    refresh()
})

const highlightedSpanId = ref<string | null>(null)
const timelineItemRefs = ref<Record<string, HTMLElement | ComponentPublicInstance>>({})

const setTimelineItemRef = (el: HTMLElement | ComponentPublicInstance | null, spanId?: string) => {
    if (el && spanId) {
        timelineItemRefs.value[spanId] = el
    }
}

const handleNodeClick = async (data: any) => {
    if (!data.span_id) return
    
    // 1. Switch Tab
    activeTab.value = 'timeline' // This is the Event tab now
    highlightedSpanId.value = data.span_id
    
    // 2. Scroll to Element
    await nextTick()
    const target = timelineItemRefs.value[data.span_id]
    if (target) {
        // Element-plus timeline item might need $el access if it's a component
        const domEl = '$el' in target ? (target as any).$el : target
        domEl.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
}

const viewRunDetails = async (run: any) => {
    drawerVisible.value = true
    runDetail.value = null 
    drawerLoading.value = true
    activeTab.value = 'timeline'
    
    try {
        const detail = await apiClient.getAuditRunSummary(run.request_id)
        console.log("[DEBUG] Audit Run Summary Response:", detail)
        console.log("[DEBUG] Spans:", detail.spans)
        runDetail.value = detail
    } catch (e) {
        console.error("Failed to load details", e)
    } finally {
        drawerLoading.value = false
    }
}

const formatPayload = (payload: any) => {
    try {
        return JSON.stringify(payload, null, 2)
    } catch (e) {
        return String(payload)
    }
}

// Helpers
const formatDate = (val: string) => dayjs(val).format('YYYY-MM-DD HH:mm:ss')
const formatTime = (val: string) => dayjs(val).format('HH:mm:ss.SSS')

const formatDuration = (val?: number) => {
    if (val === undefined || val === null) return '-'
    if (val < 1) return '< 1s'
    if (val < 60) return `${val.toFixed(1)}ms` 
    if (val < 1) return `${(val * 1000).toFixed(0)}ms`
    return `${val.toFixed(2)}s`
}

const getStatusType = (status?: string) => {
    switch(status?.toLowerCase()) {
        case 'succeeded': return 'success'
        case 'failed': return 'danger'
        case 'running': return 'primary'
        case 'cancelled': return 'warning'
        case 'interrupted': return 'warning'
        default: return 'info'
    }
}

const getSeverityType = (sev: string) => {
    switch(sev?.toLowerCase()) {
        case 'error': return 'danger'
        case 'success': return 'success'
        case 'warning': return 'warning'
        case 'interrupt': return 'warning'
        default: return 'info'
    }
}

const getActivityColor = (sev: string) => {
    switch(sev?.toLowerCase()) {
        case 'error': return '#f56c6c'
        case 'success': return '#67c23a'
        case 'warning': return '#e6a23c'
        case 'interrupt': return '#e6a23c'
        default: return '#909399'
    }
}

const getSpanTypeColor = (type: string) => {
    switch(type) {
        case 'agent': return 'primary'
        case 'chain': return 'info'
        case 'tool': return 'warning'
        case 'llm': return 'success'
        default: return 'info'
    }
}




onMounted(async () => {
    try {
        const agents = await apiClient.listAgents()
        agentOptions.value = agents.map((a: any) => a.name)
    } catch(e) {}
    refresh()
})
</script>

<style scoped>
.audit-layout {
    height: 100vh;
    display: flex;
    background-color: var(--el-bg-color-page);
    font-family: 'Inter', sans-serif;
}

.audit-header {
    background-color: var(--bg-primary);
    border-bottom: 1px solid var(--border-color);
    height: 64px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 32px;
}

.page-title {
    font-size: 18px;
    font-weight: 700;
    color: var(--text-primary);
}

.audit-content {
    padding: 24px;
    height: 100%;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
}

.audit-card-el {
    border: 1px solid var(--border-color);
    background-color: var(--bg-primary);
    border-radius: 8px;
    display: flex;
    flex-direction: column;
    flex: 1;
    overflow: hidden; 
}

/* Filter Bar Styling */
.filter-bar {
    padding: 16px 24px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid var(--border-color);
    background-color: var(--bg-primary);
    flex-wrap: wrap;
    gap: 16px;
}

.filter-group {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
}

.filter-actions {
    display: flex;
    align-items: center;
    gap: 8px;
}

/* Input Customization */
.filter-input-search {
    width: 240px;
}
.filter-date {
    width: 320px !important;
}
.filter-select {
    width: 140px;
}

/* Make elements blend */
:deep(.el-input__wrapper), :deep(.el-range-editor.el-input__wrapper) {
    box-shadow: 0 0 0 1px var(--border-color) inset;
    background-color: transparent;
}
:deep(.el-input__wrapper:hover) {
    box-shadow: 0 0 0 1px var(--el-color-primary) inset;
}

.json-viewer {
    background: #1e1e1e;
    color: #ce9178;
    padding: 12px;
    border-radius: 6px;
    font-family: 'Fira Code', monospace;
    font-size: 11px;
    overflow-x: auto;
    font-size: 11px;
    overflow-x: auto;
    line-height: 1.4;
    white-space: pre-wrap;
    word-break: break-all;
}

.text-secondary { color: var(--text-secondary); }

/* Premium Drawer Override */
:deep(.premium-drawer .el-drawer__body) {
    padding: 0;
}

.highlight-event :deep(.el-timeline-item__node) {
    box-shadow: 0 0 0 4px rgba(64, 158, 255, 0.4);
    transform: scale(1.2);
    transition: all 0.3s ease;
}
.highlight-event :deep(.timeline-content) {
    background-color: var(--el-color-primary-light-9);
    border-radius: 4px;
    padding: 8px;
    margin: -8px; /* Offset padding */
    border-left: 3px solid var(--el-color-primary);
}
</style>
