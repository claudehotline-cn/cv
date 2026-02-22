<template>
  <div class="settings-page" v-loading="security.loading">
    <div class="head">
      <div>
        <h1>Security Center</h1>
        <p class="subtitle">Central place for tenant security, limits, secrets and security audit.</p>
      </div>
      <el-button type="primary" plain @click="refresh">Refresh</el-button>
    </div>

    <el-alert v-if="security.error" :title="security.error" type="error" :closable="false" style="margin-bottom: 16px;" />

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
        <el-tag v-if="security.hasQuotaPressure" type="warning" size="small">Usage > 80%</el-tag>
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

    <el-card style="margin-top: 16px;">
      <template #header>Quick Actions</template>
      <div class="actions">
        <el-button @click="go('/settings/tenant')">Tenant & Members</el-button>
        <el-button @click="go('/settings/limits')">Limits & Quota</el-button>
        <el-button @click="go('/settings/secrets')">Secrets Vault</el-button>
        <el-button @click="go('/audit/security')">Security Audit</el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
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
.settings-page { padding: 24px; }
.head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; gap: 12px; }
.subtitle { color: var(--text-secondary); margin: 0; }
.grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; }
</style>
