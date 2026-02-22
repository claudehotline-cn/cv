<template>
  <div class="settings-page" v-loading="security.loading">
    <div class="page-header">
      <div class="header-content">
        <h1 class="page-title">Limits & Quota</h1>
        <p class="page-description">Manage API rate limits and token usage quotas for the tenant.</p>
      </div>
      <el-button :icon="RefreshIcon" circle title="Refresh" @click="refresh" />
    </div>

    <transition-group name="el-fade-in-linear">
      <el-alert v-if="security.error" :title="security.error" type="error" :closable="false" show-icon class="alert-box" key="error" />
      <el-alert
        v-if="limitErrorDetail"
        :title="limitErrorDetail"
        type="warning"
        :closable="false"
        show-icon
        class="alert-box"
        key="warning"
      />
    </transition-group>

    <el-row :gutter="20" class="panel-row">
      <!-- Rate Limits -->
      <el-col :xs="24" :lg="12" class="stretch-col">
        <el-card shadow="never" class="system-card h-full">
          <template #header>
            <div class="card-header">
              <span>Rate Limits</span>
              <el-tag size="small" type="info">{{ security.limits?.rate_limits.fail_mode || 'standard' }} mode</el-tag>
            </div>
          </template>
          
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="Tenant Read">{{ security.limits?.rate_limits.read ?? '-' }}</el-descriptions-item>
            <el-descriptions-item label="Tenant Write">{{ security.limits?.rate_limits.write ?? '-' }}</el-descriptions-item>
            <el-descriptions-item label="Tenant Execute">{{ security.limits?.rate_limits.execute ?? '-' }}</el-descriptions-item>
            <el-descriptions-item label="User Read">{{ security.limits?.rate_limits.user_read ?? '-' }}</el-descriptions-item>
            <el-descriptions-item label="User Write">{{ security.limits?.rate_limits.user_write ?? '-' }}</el-descriptions-item>
            <el-descriptions-item label="User Execute">{{ security.limits?.rate_limits.user_execute ?? '-' }}</el-descriptions-item>
            <el-descriptions-item label="Tenant Concurrency">{{ security.limits?.rate_limits.tenant_concurrency_limit ?? '-' }}</el-descriptions-item>
            <el-descriptions-item label="User Concurrency">{{ security.limits?.rate_limits.user_concurrency_limit ?? '-' }}</el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>

      <!-- Quota -->
      <el-col :xs="24" :lg="12" class="stretch-col">
        <el-card shadow="never" class="system-card h-full">
          <template #header>
            <div class="card-header">
              <span>Quota Usage</span>
              <el-tag size="small" :type="security.quota?.enabled ? 'success' : 'info'">
                {{ security.quota?.enabled ? 'Enabled' : 'Disabled' }}
              </el-tag>
            </div>
          </template>

          <div class="quota-stats">
            <el-row :gutter="16">
              <el-col :span="12">
                <el-statistic title="Monthly Quota" :value="security.quota?.monthly_token_quota ?? 0" />
              </el-col>
              <el-col :span="12">
                <el-statistic title="Used Tokens" :value="security.quota?.used_tokens ?? 0" />
              </el-col>
            </el-row>
            <el-divider />
            <el-row :gutter="16">
              <el-col :span="12">
                <el-statistic title="Remaining" :value="security.quota?.remaining_tokens ?? 0" value-style="color: var(--el-color-primary)" />
              </el-col>
              <el-col :span="12">
                <el-statistic title="Period" :value="security.quota?.period || '-'" group-separator="" />
              </el-col>
            </el-row>
          </div>

          <div class="quota-actions" v-if="auth.canManageTenantSecurity">
            <el-divider content-position="left">Manage Quota</el-divider>
            <div class="action-form">
               <el-input-number v-model="quotaForm.monthly_token_quota" :min="0" :step="10000" class="flex-grow" />
               <el-switch v-model="quotaForm.enabled" active-text="Enabled" inactive-text="Disabled" />
               <el-button type="primary" @click="saveQuota">Apply</el-button>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- Update Execute Limits -->
    <el-card shadow="never" class="system-card mt-20" v-if="auth.canManageTenantSecurity">
      <template #header>
        <div class="card-header">
          <span>Concurrency & API Limits Configuration</span>
        </div>
      </template>
      <el-form :model="limitForm" label-position="top">
        <el-row :gutter="20">
          <el-col :xs="24" :md="6">
            <el-form-item label="Execute Limit (Tenant)">
              <el-input v-model="limitForm.execute_limit" placeholder="e.g. 60/min" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="6">
            <el-form-item label="Execute Limit (User)">
              <el-input v-model="limitForm.user_execute_limit" placeholder="e.g. 20/min" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="6">
            <el-form-item label="Concurrency Limit (Tenant)">
              <el-input-number v-model="limitForm.tenant_concurrency_limit" :min="1" class="w-full" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="6">
            <el-form-item label="Concurrency Limit (User)">
              <el-input-number v-model="limitForm.user_concurrency_limit" :min="1" class="w-full" />
            </el-form-item>
          </el-col>
        </el-row>
        <div class="form-footer">
          <el-button type="primary" @click="saveLimits">Save Limits Configuration</el-button>
        </div>
      </el-form>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh as RefreshIcon } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { useSecurityStore } from '@/stores/security'

const auth = useAuthStore()
const security = useSecurityStore()
const limitErrorDetail = ref('')

const quotaForm = reactive({
  monthly_token_quota: 0,
  enabled: true,
})

const limitForm = reactive({
  execute_limit: '',
  user_execute_limit: '',
  tenant_concurrency_limit: 1,
  user_concurrency_limit: 1,
})

async function refresh() {
  limitErrorDetail.value = ''
  await security.loadLimitsAndQuota()
  quotaForm.monthly_token_quota = security.quota?.monthly_token_quota ?? 0
  quotaForm.enabled = security.quota?.enabled ?? true
  limitForm.execute_limit = security.limits?.rate_limits.execute || ''
  limitForm.user_execute_limit = security.limits?.rate_limits.user_execute || ''
  limitForm.tenant_concurrency_limit = security.limits?.rate_limits.tenant_concurrency_limit || 1
  limitForm.user_concurrency_limit = security.limits?.rate_limits.user_concurrency_limit || 1
}

async function saveQuota() {
  try {
    await security.saveQuota({
      monthly_token_quota: quotaForm.monthly_token_quota,
      enabled: quotaForm.enabled,
    })
    limitErrorDetail.value = ''
    ElMessage.success('Quota updated')
  } catch (e: any) {
    limitErrorDetail.value = formatLimitError(e)
  }
}

async function saveLimits() {
  try {
    await security.saveLimits({
      execute_limit: limitForm.execute_limit,
      user_execute_limit: limitForm.user_execute_limit,
      tenant_concurrency_limit: limitForm.tenant_concurrency_limit,
      user_concurrency_limit: limitForm.user_concurrency_limit,
    })
    limitErrorDetail.value = ''
    ElMessage.success('Limits updated')
  } catch (e: any) {
    limitErrorDetail.value = formatLimitError(e)
  }
}

function formatLimitError(e: any): string {
  const status = e?.response?.status
  const detail = e?.response?.data?.detail
  if (status !== 429) return ''

  if (detail?.detail === 'rate_limit_exceeded' || detail?.bucket || detail?.scope) {
    const bucket = detail?.bucket || '-'
    const scope = detail?.scope || '-'
    const retry = detail?.retry_after ?? '-'
    return `Rate limit exceeded: scope=${scope}, bucket=${bucket}, retry_after=${retry}s`
  }

  if (detail?.detail === 'quota_exceeded') {
    const quotaType = detail?.quota_type || 'monthly_token_quota'
    const remaining = detail?.remaining_tokens ?? detail?.remaining ?? '-'
    return `Quota exceeded: type=${quotaType}, remaining=${remaining}`
  }

  if (typeof detail === 'string') return detail
  return 'Request was throttled (429)'
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

.panel-row {
  margin-bottom: 20px;
  display: flex;
  align-items: stretch;
}

.stretch-col {
  display: flex;
  flex-direction: column;
}

.h-full {
  height: 100%;
  flex: 1;
}

.system-card {
  border-radius: 8px;
  border: 1px solid var(--el-border-color-lighter);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 500;
}

.quota-stats {
  padding: 8px 0;
}

.action-form {
  display: flex;
  gap: 16px;
  align-items: center;
  flex-wrap: wrap;
}

.flex-grow {
  flex-grow: 1;
}

.w-full {
  width: 100%;
}

.mt-20 {
  margin-top: 20px;
}

.form-footer {
  display: flex;
  justify-content: flex-end;
  margin-top: 8px;
}

@media (max-width: 992px) {
  .panel-row {
    flex-direction: column;
    gap: 20px;
  }
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

  .action-form {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
