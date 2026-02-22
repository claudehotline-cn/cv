<template>
  <div class="settings-page" v-loading="security.loading">
    <div class="head">
      <h1>Limits & Quota</h1>
      <el-button type="primary" plain @click="refresh">Refresh</el-button>
    </div>

    <el-alert v-if="security.error" :title="security.error" type="error" :closable="false" style="margin-bottom: 16px;" />
    <el-alert
      v-if="limitErrorDetail"
      :title="limitErrorDetail"
      type="warning"
      :closable="false"
      style="margin-bottom: 16px;"
    />

    <el-card style="margin-bottom: 16px;">
      <template #header>Rate Limits</template>
      <div class="kv">
        <div>Tenant Read: {{ security.limits?.rate_limits.read }}</div>
        <div>Tenant Write: {{ security.limits?.rate_limits.write }}</div>
        <div>Tenant Execute: {{ security.limits?.rate_limits.execute }}</div>
        <div>User Read: {{ security.limits?.rate_limits.user_read }}</div>
        <div>User Write: {{ security.limits?.rate_limits.user_write }}</div>
        <div>User Execute: {{ security.limits?.rate_limits.user_execute }}</div>
        <div>Tenant Concurrency: {{ security.limits?.rate_limits.tenant_concurrency_limit }}</div>
        <div>User Concurrency: {{ security.limits?.rate_limits.user_concurrency_limit }}</div>
        <div>Fail Mode: {{ security.limits?.rate_limits.fail_mode || '-' }}</div>
      </div>
    </el-card>

    <el-card>
      <template #header>Quota</template>
      <div class="kv">
        <div>Period: {{ security.quota?.period }}</div>
        <div>Monthly Quota: {{ security.quota?.monthly_token_quota }}</div>
        <div>Used: {{ security.quota?.used_tokens }}</div>
        <div>Remaining: {{ security.quota?.remaining_tokens }}</div>
      </div>

      <div class="quota-actions" v-if="auth.canManageTenantSecurity" style="margin-top: 12px; display: flex; gap: 8px;">
        <el-input-number v-model="quotaForm.monthly_token_quota" :min="0" :step="100000" />
        <el-switch v-model="quotaForm.enabled" active-text="Enabled" inactive-text="Disabled" />
        <el-button type="primary" @click="saveQuota">Save Quota</el-button>
      </div>
    </el-card>

    <el-card v-if="auth.canManageTenantSecurity" style="margin-top: 16px;">
      <template #header>Update Execute Limits</template>
      <div class="limits-form">
        <el-input v-model="limitForm.execute_limit" placeholder="tenant execute, e.g. 60/min" />
        <el-input v-model="limitForm.user_execute_limit" placeholder="user execute, e.g. 20/min" />
        <el-input-number v-model="limitForm.tenant_concurrency_limit" :min="1" />
        <el-input-number v-model="limitForm.user_concurrency_limit" :min="1" />
        <el-button type="primary" @click="saveLimits">Save Limits</el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
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
.settings-page { padding: 24px; }
.kv { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 16px; }
.head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.limits-form { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; align-items: center; }
</style>
