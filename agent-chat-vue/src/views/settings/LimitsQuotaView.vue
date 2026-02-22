<template>
  <div class="settings-page" v-loading="security.loading">
    <div class="head">
      <h1>Limits & Quota</h1>
      <el-button type="primary" plain @click="refresh">Refresh</el-button>
    </div>

    <el-alert v-if="security.error" :title="security.error" type="error" :closable="false" style="margin-bottom: 16px;" />

    <el-card style="margin-bottom: 16px;">
      <template #header>Rate Limits</template>
      <div class="kv">
        <div>Tenant Read: {{ security.limits?.rate_limits.read }}</div>
        <div>Tenant Write: {{ security.limits?.rate_limits.write }}</div>
        <div>Tenant Execute: {{ security.limits?.rate_limits.execute }}</div>
        <div>User Read: {{ security.limits?.rate_limits.user_read }}</div>
        <div>User Write: {{ security.limits?.rate_limits.user_write }}</div>
        <div>User Execute: {{ security.limits?.rate_limits.user_execute }}</div>
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

      <div class="quota-actions" v-if="auth.isAdmin" style="margin-top: 12px; display: flex; gap: 8px;">
        <el-input-number v-model="quotaForm.monthly_token_quota" :min="0" :step="100000" />
        <el-switch v-model="quotaForm.enabled" active-text="Enabled" inactive-text="Disabled" />
        <el-button type="primary" @click="saveQuota">Save Quota</el-button>
      </div>
    </el-card>

    <el-card v-if="auth.isAdmin" style="margin-top: 16px;">
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
import { onMounted, reactive } from 'vue'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { useSecurityStore } from '@/stores/security'

const auth = useAuthStore()
const security = useSecurityStore()

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
  await security.loadLimitsAndQuota()
  quotaForm.monthly_token_quota = security.quota?.monthly_token_quota ?? 0
  quotaForm.enabled = security.quota?.enabled ?? true
  limitForm.execute_limit = security.limits?.rate_limits.execute || ''
  limitForm.user_execute_limit = security.limits?.rate_limits.user_execute || ''
  limitForm.tenant_concurrency_limit = security.limits?.rate_limits.tenant_concurrency_limit || 1
  limitForm.user_concurrency_limit = security.limits?.rate_limits.user_concurrency_limit || 1
}

async function saveQuota() {
  await security.saveQuota({
    monthly_token_quota: quotaForm.monthly_token_quota,
    enabled: quotaForm.enabled,
  })
  ElMessage.success('Quota updated')
}

async function saveLimits() {
  await security.saveLimits({
    execute_limit: limitForm.execute_limit,
    user_execute_limit: limitForm.user_execute_limit,
    tenant_concurrency_limit: limitForm.tenant_concurrency_limit,
    user_concurrency_limit: limitForm.user_concurrency_limit,
  })
  ElMessage.success('Limits updated')
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
