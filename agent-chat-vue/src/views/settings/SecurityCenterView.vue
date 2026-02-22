<template>
  <div class="settings-page" v-loading="security.loading">
    <h1>Security Center</h1>
    <div class="grid">
      <el-card>
        <template #header>Tenant</template>
        <p>{{ auth.activeTenantId || '-' }}</p>
        <p>Role: {{ auth.user?.tenant_role || '-' }}</p>
      </el-card>
      <el-card>
        <template #header>Quota</template>
        <p>Used: {{ security.quota?.used_tokens ?? 0 }}</p>
        <p>Remaining: {{ security.quota?.remaining_tokens ?? 0 }}</p>
      </el-card>
      <el-card>
        <template #header>Secrets</template>
        <p>Count: {{ security.secrets.length }}</p>
      </el-card>
      <el-card>
        <template #header>Security Events (24h)</template>
        <p>Total: {{ security.authAuditOverview?.total_events ?? 0 }}</p>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useSecurityStore } from '@/stores/security'

const auth = useAuthStore()
const security = useSecurityStore()

onMounted(async () => {
  await Promise.all([
    security.loadLimitsAndQuota(),
    security.loadSecrets(),
    security.loadSecurityAudit(),
  ])
})
</script>

<style scoped>
.settings-page { padding: 24px; }
.grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
</style>
