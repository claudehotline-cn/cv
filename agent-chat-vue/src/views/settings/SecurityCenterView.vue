<template>
  <div class="settings-page" v-loading="security.loading">
    <div class="page-header">
      <div class="header-content">
        <h1 class="page-title">Security Center</h1>
        <p class="page-description">Central place for tenant security, limits, secrets and security audit.</p>
      </div>
      <el-button :icon="RefreshIcon" circle title="Refresh" @click="refresh" />
    </div>

    <transition name="el-fade-in-linear">
      <el-alert v-if="security.error" :title="security.error" type="error" :closable="false" show-icon class="alert-box" />
    </transition>

    <el-row :gutter="20" class="metrics-grid">
      <el-col :xs="24" :sm="12" :lg="6" class="metric-col">
        <el-card shadow="hover" class="metric-card">
          <div class="card-title">Tenant Active</div>
          <el-tooltip :content="auth.activeTenantId || ''" placement="top">
            <div class="metric-value truncate">{{ auth.activeTenantId || '-' }}</div>
          </el-tooltip>
          <div class="metric-extra">Role: <el-tag size="small" type="info" style="margin-left: 6px;">{{ auth.user?.tenant_role || '-' }}</el-tag></div>
        </el-card>
      </el-col>
      
      <el-col :xs="24" :sm="12" :lg="6" class="metric-col">
        <el-card shadow="hover" class="metric-card">
          <div class="card-title">Quota Usage</div>
          <div class="metric-value">{{ security.quota?.used_tokens?.toLocaleString() ?? 0 }}</div>
          <div class="metric-extra">
            <span>Remaining: {{ security.quota?.remaining_tokens?.toLocaleString() ?? 0 }}</span>
            <el-tag v-if="security.hasQuotaPressure" type="warning" size="small" style="margin-left: 8px;">Usage > 80%</el-tag>
          </div>
        </el-card>
      </el-col>

      <el-col :xs="24" :sm="12" :lg="6" class="metric-col">
        <el-card shadow="hover" class="metric-card">
          <div class="card-title">Secrets</div>
          <div class="metric-value">{{ security.secrets.length }}</div>
          <div class="metric-extra">Active secret entries</div>
        </el-card>
      </el-col>

      <el-col :xs="24" :sm="12" :lg="6" class="metric-col">
        <el-card shadow="hover" class="metric-card">
          <div class="card-title">Security Events (24h)</div>
          <div class="metric-value">{{ security.authAuditOverview?.total_events?.toLocaleString() ?? 0 }}</div>
          <div class="metric-extra">Observed in recent window</div>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never" class="actions-card">
      <template #header>
        <div class="actions-header">Quick Actions</div>
      </template>
      <div class="quick-actions">
        <el-button size="large" @click="go('/settings/tenant')" class="action-btn">
          <span class="action-btn-text">Tenant & Members</span>
        </el-button>
        <el-button size="large" @click="go('/settings/limits')" class="action-btn">
          <span class="action-btn-text">Limits & Quota</span>
        </el-button>
        <el-button size="large" @click="go('/settings/secrets')" class="action-btn">
          <span class="action-btn-text">Secrets Vault</span>
        </el-button>
        <el-button size="large" @click="go('/settings/cache-metrics')" class="action-btn">
          <span class="action-btn-text">Cache Metrics</span>
        </el-button>
        <el-button size="large" @click="go('/audit/security')" class="action-btn">
          <span class="action-btn-text">Security Audit</span>
        </el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Refresh as RefreshIcon } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { useSecurityStore } from '@/stores/security'

const auth = useAuthStore()
const security = useSecurityStore()
const router = useRouter()

async function refresh() {
  await Promise.allSettled([
    security.loadLimitsAndQuota(),
    security.loadSecrets(),
    security.loadSecurityAudit(),
  ])
}

function go(path: string) {
  router.push(path)
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
  margin-bottom: 32px;
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
  margin-bottom: 24px;
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

.truncate {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.metric-extra {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  display: flex;
  align-items: center;
  margin-top: auto;
}

.actions-card {
  border-radius: 8px;
  border: 1px solid var(--el-border-color-lighter);
}

.actions-header {
  font-weight: 500;
  font-size: 16px;
}

.quick-actions {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 16px;
}

.action-btn {
  width: 100%;
  height: 60px;
  justify-content: flex-start;
  padding: 0 20px;
  border-radius: 8px;
}

.action-btn-text {
  font-weight: 500;
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

  .quick-actions {
    grid-template-columns: 1fr;
  }
}
</style>
