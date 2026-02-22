<template>
  <div class="settings-page" v-loading="security.loading">
    <h1>Limits & Quota</h1>

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
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useSecurityStore } from '@/stores/security'

const security = useSecurityStore()

onMounted(async () => {
  await security.loadLimitsAndQuota()
})
</script>

<style scoped>
.settings-page { padding: 24px; }
.kv { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 16px; }
</style>
