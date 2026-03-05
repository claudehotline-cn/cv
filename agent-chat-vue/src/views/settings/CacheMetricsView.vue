<template>
  <div class="settings-page" v-loading="security.cacheLoading">
    <div class="page-header">
      <div class="header-content">
        <h1 class="page-title">Cache Metrics</h1>
        <p class="page-description">Observe semantic cache hits and invalidate tenant cache entries.</p>
      </div>
      <el-button :icon="RefreshIcon" circle title="Refresh" @click="refresh" />
    </div>

    <transition name="el-fade-in-linear">
      <el-alert v-if="security.cacheError" :title="security.cacheError" type="error" :closable="false" show-icon class="alert-box" />
    </transition>

    <el-row :gutter="20" class="metrics-grid">
      <el-col :xs="24" :sm="12" :lg="6" class="metric-col">
        <el-card shadow="hover" class="metric-card">
          <div class="card-title">Total Entries</div>
          <div class="metric-value">{{ security.cacheStats?.total_entries?.toLocaleString() ?? 0 }}</div>
          <div class="metric-extra">Tenant scoped cache records</div>
        </el-card>
      </el-col>

      <el-col :xs="24" :sm="12" :lg="6" class="metric-col">
        <el-card shadow="hover" class="metric-card">
          <div class="card-title">Total Hits</div>
          <div class="metric-value">{{ security.cacheStats?.total_hits?.toLocaleString() ?? 0 }}</div>
          <div class="metric-extra">Accumulated metadata hit_count</div>
        </el-card>
      </el-col>

      <el-col :xs="24" :sm="12" :lg="12" class="metric-col">
        <el-card shadow="hover" class="metric-card">
          <div class="card-title">Tenant</div>
          <div class="metric-value tenant-id">{{ security.cacheStats?.tenant_id || auth.activeTenantId || '-' }}</div>
          <div class="metric-extra">Current active tenant context</div>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never" class="list-card">
      <template #header>
        <div class="list-header">
          <span>Recent Cache Entries</span>
          <div class="header-actions" v-if="auth.isAdmin">
            <el-input
              v-model="namespaceFilter"
              size="small"
              clearable
              placeholder="Namespace (optional)"
              class="namespace-input"
              @clear="onReloadEntries"
              @keyup.enter="onReloadEntries"
            />
            <el-button size="small" @click="onReloadEntries">Load</el-button>
            <el-button type="danger" size="small" @click="onInvalidate">Invalidate</el-button>
          </div>
        </div>
      </template>

      <el-table :data="security.cacheEntries" stripe>
        <el-table-column prop="namespace" label="Namespace" min-width="160" />
        <el-table-column prop="prompt_hash" label="Prompt Hash" min-width="220" show-overflow-tooltip />
        <el-table-column label="Updated" min-width="200">
          <template #default="scope">
            {{ formatTime(scope.row.updated_at || scope.row.created_at) }}
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh as RefreshIcon } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { useSecurityStore } from '@/stores/security'

const auth = useAuthStore()
const security = useSecurityStore()

const namespaceFilter = ref('')

function buildFilter() {
  const namespace = namespaceFilter.value.trim()
  return namespace ? namespace : undefined
}

async function refresh() {
  await security.loadCacheStats().catch(() => undefined)
  if (auth.isAdmin) {
    await security.loadCacheEntries({ limit: 50, namespace: buildFilter() }).catch(() => undefined)
  } else {
    security.cacheEntries = []
  }
}

async function onReloadEntries() {
  if (!auth.isAdmin) return
  await security.loadCacheEntries({ limit: 50, namespace: buildFilter() })
}

async function onInvalidate() {
  if (!auth.isAdmin) {
    ElMessage.warning('Admin role required')
    return
  }
  await security.invalidateCache(buildFilter())
  ElMessage.success('Cache invalidated')
}

function formatTime(raw?: string) {
  if (!raw) return '-'
  const date = new Date(raw)
  if (Number.isNaN(date.getTime())) return raw
  return date.toLocaleString()
}

onMounted(async () => {
  await refresh()
})
</script>

<style scoped>
.settings-page {
  padding: 32px;
  max-width: 1200px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 24px;
  gap: 16px;
  flex-wrap: wrap;
}

.header-content {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.page-title {
  margin: 0;
  font-size: 24px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.page-description {
  margin: 0;
  font-size: 14px;
  color: var(--el-text-color-regular);
}

.alert-box {
  margin-bottom: 20px;
}

.metrics-grid {
  margin-bottom: 24px;
}

.metric-col {
  margin-bottom: 20px;
}

.metric-card {
  height: 100%;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
}

.metric-card :deep(.el-card__body) {
  padding: 20px;
  display: flex;
  flex-direction: column;
  height: 100%;
}

.card-title {
  font-size: 14px;
  color: var(--el-text-color-regular);
  font-weight: 500;
  margin-bottom: 12px;
}

.metric-value {
  font-size: 28px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  line-height: 1.2;
  margin-bottom: 8px;
}

.metric-extra {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: auto;
}

.tenant-id {
  font-size: 16px;
  word-break: break-all;
}

.list-card {
  border-radius: 8px;
  border: 1px solid var(--el-border-color-lighter);
}

.list-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.namespace-input {
  width: 220px;
}

@media (max-width: 768px) {
  .settings-page {
    padding: 16px;
  }

  .page-header {
    flex-direction: column;
  }

  .page-header .el-button {
    width: 100%;
  }

  .namespace-input {
    width: 100%;
  }
}
</style>
