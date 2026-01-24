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
                <h2 class="page-title">Audit Logs</h2>
            </div>
            <div class="header-right">
                 <el-input 
                    v-model="searchQuery"
                    class="search-input-el"
                    placeholder="Search logs..." 
                    :prefix-icon="Search"
                    clearable
                 />
                 <el-button class="export-btn-el">Export</el-button>
            </div>
        </el-header>
        
        <el-main class="audit-main">
            <div class="audit-content">
                <el-card class="audit-card-el" shadow="hover" :body-style="{ padding: '0px' }">
                     <!-- Filter Bar -->
                     <div class="filter-bar">
                        <div class="filter-group">
                            <el-date-picker
                                v-model="dateRange"
                                type="daterange"
                                range-separator="To"
                                start-placeholder="Start date"
                                end-placeholder="End date"
                                size="default"
                                class="filter-date"
                            />
                            <el-select v-model="selectedType" placeholder="Event Type" clearable class="filter-select">
                                <el-option v-for="type in eventTypes" :key="type" :label="type" :value="type" />
                            </el-select>
                            <el-select v-model="selectedSeverity" placeholder="Severity" clearable class="filter-select">
                                <el-option v-for="sev in severities" :key="sev" :label="sev" :value="sev" />
                            </el-select>
                        </div>
                        <el-button link type="primary" @click="clearFilters">Clear Filters</el-button>
                     </div>

                     <el-table 
                        :data="filteredLogs" 
                        style="width: 100%" 
                        class="premium-table"
                        :header-cell-style="{ background: 'transparent', color: 'var(--text-secondary)', fontWeight: '600', textTransform: 'uppercase', fontSize: '12px', letterSpacing: '0.05em' }"
                        :row-class-name="tableRowClassName"
                     >
                        <el-table-column prop="time" label="Time" width="180">
                            <template #default="scope">
                                <span class="text-secondary">{{ scope.row.time }}</span>
                            </template>
                        </el-table-column>
                        
                        <el-table-column prop="type" label="Event Type" width="150" />
                        
                        <el-table-column prop="severity" label="Severity" width="120">
                            <template #default="scope">
                                <el-tag 
                                    :type="getSeverityType(scope.row.severity)" 
                                    effect="light" 
                                    round 
                                    size="small"
                                    class="font-bold border-none"
                                >
                                    {{ scope.row.severity }}
                                </el-tag>
                            </template>
                        </el-table-column>
                        
                        <el-table-column prop="description" label="Description" min-width="300" show-overflow-tooltip />
                        
                        <el-table-column prop="initiator" label="User/Agent" width="180">
                            <template #default="scope">
                                <div class="user-cell">
                                    <div class="user-avatar">
                                        {{ scope.row.initiator.substring(0,2).toUpperCase() }}
                                    </div>
                                    <span>{{ scope.row.initiator }}</span>
                                </div>
                            </template>
                        </el-table-column>
                     </el-table>
                     
                     <!-- Pagination -->
                     <div class="pagination-container">
                         <el-pagination
                            background
                            layout="prev, pager, next"
                            :total="100"
                            class="premium-pagination"
                         />
                     </div>
                </el-card>
            </div>
        </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { Search } from '@element-plus/icons-vue'
import AppSidebar from '@/components/layout/AppSidebar.vue'

const searchQuery = ref('')
const dateRange = ref([])
const selectedType = ref('')
const selectedSeverity = ref('')

// Filter Options
const eventTypes = ['Connection', 'Batch Job', 'Performance', 'Deployment', 'Security', 'Auth', 'System']
const severities = ['Success', 'Info', 'Warning', 'Error']

const logs = ref([
    { time: '2023-10-24 10:42:05', type: 'Connection', severity: 'Error', description: 'Agent-007 failed to handshake with VectorDB cluster. Retrying in 5s...', initiator: 'System' },
    { time: '2023-10-24 10:40:12', type: 'Batch Job', severity: 'Info', description: 'Successfully processed 1,200 documents for ingest.', initiator: 'DataAgent' },
    { time: '2023-10-24 10:38:55', type: 'Performance', severity: 'Warning', description: 'Vector DB query latency > 500ms detected in eu-west-1 region.', initiator: 'Monitor' },
    { time: '2023-10-24 10:15:20', type: 'Deployment', severity: 'Success', description: 'Agent-009 "CreativeWriter" deployed to production successfully.', initiator: 'Alex Morgan' },
    { time: '2023-10-24 09:55:00', type: 'Security', severity: 'Info', description: 'Scheduled rotation of internal service keys completed.', initiator: 'KeyManager' },
    { time: '2023-10-24 09:30:11', type: 'Auth', severity: 'Success', description: 'User login from IP 192.168.1.1', initiator: 'Alex Morgan' },
    { time: '2023-10-24 08:00:00', type: 'System', severity: 'Info', description: 'Daily backup verification completed.', initiator: 'BackupSvc' },
])

import { computed } from 'vue'

const filteredLogs = computed(() => {
    return logs.value.filter(log => {
        // Search Query
        if (searchQuery.value && !log.description.toLowerCase().includes(searchQuery.value.toLowerCase()) && !log.initiator.toLowerCase().includes(searchQuery.value.toLowerCase())) {
            return false
        }
        // Event Type
        if (selectedType.value && log.type !== selectedType.value) {
            return false
        }
        // Severity
        if (selectedSeverity.value && log.severity !== selectedSeverity.value) {
            return false
        }
        // Date Range (Simple string comparison for demo, ideally parse Dates)
        if (dateRange.value && dateRange.value.length === 2) {
            const logDate = new Date(log.time)
            const startDate = dateRange.value[0]
            const endDate = dateRange.value[1]
            if (logDate < startDate || logDate > endDate) {
                return false
            }
        }
        return true
    })
})

const clearFilters = () => {
    searchQuery.value = ''
    dateRange.value = []
    selectedType.value = ''
    selectedSeverity.value = ''
}

const getSeverityType = (severity: string) => {
    switch (severity.toLowerCase()) {
        case 'success': return 'success'
        case 'warning': return 'warning'
        case 'error': return 'danger'
        case 'info': return 'info'
        default: return 'info'
    }
}

const tableRowClassName = () => {
    return 'custom-row'
}
</script>

<style scoped>
.audit-layout {
    height: 100vh;
    overflow: hidden;
    display: flex;
    background-color: var(--el-bg-color-page);
    font-family: 'Inter', sans-serif;
    color: var(--text-primary);
    -webkit-font-smoothing: antialiased;
}
:deep(.dark .audit-layout) {
    background-color: var(--el-bg-color-page);
}

.audit-main {
    flex: 1;
    display: flex;
    flex-direction: column;
    height: 100%;
    position: relative;
    overflow: hidden;
}

.audit-header {
    background-color: var(--bg-primary);
    border-bottom: 1px solid var(--border-color);
    height: 64px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 32px;
    flex-shrink: 0;
    z-index: 10;
}

.header-left, .header-right {
    display: flex;
    align-items: center;
    gap: 24px;
}

.header-right {
    gap: 12px;
}

.page-title {
    font-size: 18px;
    font-weight: 700;
    color: var(--text-primary);
}

/* Element Plus Overrides */
.search-input-el {
    width: 260px;
}

:deep(.search-input-el .el-input__wrapper) {
    background-color: var(--bg-secondary); /* or #f3f4f6 */
    box-shadow: none;
    border-radius: 8px;
}
:deep(.search-input-el .el-input__inner) {
    color: var(--text-primary);
}
:deep(.search-input-el .el-input__wrapper.is-focus) {
    box-shadow: 0 0 0 1px var(--accent-primary);
    background-color: var(--bg-primary);
}

.export-btn-el {
    border-radius: 8px;
    font-weight: 500;
    /* Use default styling but ensure it matches theme */
}

.audit-content {
    flex: 1;
    overflow-y: auto;
    padding: 32px;
}

.audit-card-el {
    max-width: 1400px;
    margin: 0 auto;
    border-radius: 12px;
    background-color: var(--bg-primary);
    border: 1px solid var(--border-color);
    --el-card-border-color: var(--border-color);
    --el-card-bg-color: var(--bg-primary);
}

.filter-bar {
    padding: 16px 24px;
    border-bottom: 1px solid var(--border-color);
    display: flex;
    justify-content: space-between;
    align-items: center;
    background-color: transparent;
}

.filter-group {
    display: flex;
    gap: 12px;
    align-items: center;
}

.filter-select {
    width: 160px;
}

:deep(.filter-date.el-date-editor) {
    --el-date-editor-width: 240px;
    box-shadow: none;
    background-color: var(--bg-secondary);
    border-radius: 8px;
}
:deep(.filter-date .el-range-input) {
    color: var(--text-primary);
    background: transparent;
}
:deep(.filter-date .el-range-separator) {
    color: var(--text-secondary);
}

:deep(.filter-select .el-input__wrapper) {
    background-color: var(--bg-secondary);
    box-shadow: none;
    border-radius: 8px;
}
:deep(.filter-select .el-input__inner) {
    color: var(--text-primary);
}

/* Table Styling */
:deep(.el-table) {
    --el-table-bg-color: transparent;
    --el-table-tr-bg-color: transparent;
    --el-table-header-bg-color: transparent;
    --el-table-row-hover-bg-color: var(--bg-tertiary); /* #f9fafb or dark eq */
    --el-table-border-color: var(--border-color);
    --el-table-text-color: var(--text-primary);
    --el-table-header-text-color: var(--text-secondary);
}

:deep(.el-table th.el-table__cell) {
    background-color: rgba(0,0,0,0.02); /* Slight header bg */
}
:deep(.dark .el-table th.el-table__cell) {
    background-color: rgba(255,255,255,0.02);
}

.user-cell {
    display: flex;
    align-items: center;
    gap: 8px;
}

.user-avatar {
    width: 24px;
    height: 24px;
    border-radius: 4px;
    background-color: var(--bg-tertiary);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 10px;
    font-weight: 700;
    color: var(--text-secondary);
}

.text-secondary {
    color: var(--text-secondary);
}

/* Pagination */
.pagination-container {
    padding: 16px;
    display: flex;
    justify-content: flex-end;
    border-top: 1px solid var(--border-color);
}

/* Premium Overrides */
:deep(.premium-table .el-table__cell) {
    padding: 16px 0;
}

:deep(.premium-table .cell) {
    padding: 0 24px;
}

/* Pagination Customization */
:deep(.premium-pagination .el-pagination.is-background .el-pager li:not(.is-disabled).is-active) {
    background-color: var(--accent-primary) !important;
}

:deep(.premium-pagination .el-pagination.is-background .el-pager li) {
    background-color: transparent !important;
    border: 1px solid var(--border-color);
    color: var(--text-secondary);
}

:deep(.premium-pagination .el-pagination.is-background .btn-prev),
:deep(.premium-pagination .el-pagination.is-background .btn-next) {
    background-color: transparent !important;
    border: 1px solid var(--border-color);
    color: var(--text-secondary);
}

:deep(.premium-pagination .el-pagination.is-background .el-pager li:hover) {
    color: var(--accent-primary);
    border-color: var(--accent-primary);
}
</style>
