<template>
  <div class="audit-security" v-loading="security.loading">
    <section class="head">
      <h1>Security Audit</h1>
      <div class="filters">
        <el-date-picker
          v-model="timeRange"
          type="datetimerange"
          range-separator="to"
          start-placeholder="Start time"
          end-placeholder="End time"
          style="width: 360px"
        />
        <el-select v-model="eventType" placeholder="Event Type" clearable style="width: 220px">
          <el-option label="All" value="" />
          <el-option label="Auth Login Success" value="auth_login_succeeded" />
          <el-option label="Auth Login Failed" value="auth_login_failed" />
          <el-option label="API Key Created" value="api_key_created" />
          <el-option label="API Key Revoked" value="api_key_revoked" />
          <el-option label="API Key Used" value="api_key_used" />
          <el-option label="Secret Created" value="secret_created" />
          <el-option label="Secret Rotated" value="secret_rotated" />
          <el-option label="Secret Enabled" value="secret_enabled" />
          <el-option label="Secret Disabled" value="secret_disabled" />
          <el-option label="Secret Deleted" value="secret_deleted" />
          <el-option label="Secret Reencrypt" value="secret_reencrypt" />
          <el-option label="Rate Limit Exceeded" value="rate_limit_exceeded" />
          <el-option label="Quota Exceeded" value="quota_exceeded" />
        </el-select>
        <el-select v-model="result" placeholder="Result" clearable style="width: 160px">
          <el-option label="All" value="" />
          <el-option label="Success" value="success" />
          <el-option label="Failed" value="failed" />
        </el-select>
        <el-input v-model="email" clearable placeholder="User email" style="width: 200px" />
        <el-input v-model="userId" clearable placeholder="User ID" style="width: 180px" />
        <el-input v-model="ipAddr" clearable placeholder="IP" style="width: 140px" />
        <el-input :model-value="auth.activeTenantId || '-'" readonly placeholder="Tenant" style="width: 220px" />
        <el-button type="primary" @click="load">Query</el-button>
      </div>
    </section>

    <el-alert v-if="security.error" :title="security.error" type="error" :closable="false" style="margin-bottom: 12px;" />

    <el-card style="margin-bottom: 16px;">
      <div class="overview">
        <div>Total: {{ security.authAuditOverview?.total_events ?? 0 }}</div>
        <div>Login Success: {{ security.authAuditOverview?.login_success ?? 0 }}</div>
        <div>Login Failed: {{ security.authAuditOverview?.login_failed ?? 0 }}</div>
        <div>Unique Users: {{ security.authAuditOverview?.unique_user_count ?? 0 }}</div>
      </div>
    </el-card>

    <el-table :data="security.authAudit?.items || []" stripe @row-click="openEvent">
      <el-table-column prop="event_time" label="Time" width="220" />
      <el-table-column label="Actor" width="220">
        <template #default="{ row }">
          {{ row.actor_id || row.user_id || '-' }}
        </template>
      </el-table-column>
      <el-table-column prop="event_type" label="Event" width="220" />
      <el-table-column prop="result" label="Result" width="120" />
      <el-table-column prop="reason_code" label="Reason" width="180" />
      <el-table-column label="Request ID">
        <template #default="{ row }">
          {{ eventRequestId(row) || '-' }}
        </template>
      </el-table-column>
    </el-table>

    <el-drawer v-model="detailVisible" title="Security Event Detail" size="50%">
      <el-descriptions :column="1" border v-if="selectedEvent">
        <el-descriptions-item label="Event ID">{{ selectedEvent.event_id }}</el-descriptions-item>
        <el-descriptions-item label="Event Time">{{ selectedEvent.event_time }}</el-descriptions-item>
        <el-descriptions-item label="Event Type">{{ selectedEvent.event_type }}</el-descriptions-item>
        <el-descriptions-item label="User">{{ selectedEvent.user_id || '-' }}</el-descriptions-item>
        <el-descriptions-item label="Actor">{{ selectedEvent.actor_id || '-' }}</el-descriptions-item>
        <el-descriptions-item label="Tenant">{{ auth.activeTenantId || '-' }}</el-descriptions-item>
        <el-descriptions-item label="Result">{{ selectedEvent.result || '-' }}</el-descriptions-item>
        <el-descriptions-item label="Reason">{{ selectedEvent.reason_code || '-' }}</el-descriptions-item>
        <el-descriptions-item label="IP">{{ selectedEvent.ip_addr || '-' }}</el-descriptions-item>
        <el-descriptions-item label="User Agent">{{ selectedEvent.user_agent || '-' }}</el-descriptions-item>
        <el-descriptions-item label="Request ID">{{ eventRequestId(selectedEvent) || '-' }}</el-descriptions-item>
        <el-descriptions-item label="Trace Link">
          <el-button v-if="eventRequestId(selectedEvent)" link type="primary" @click="goAuditRun(eventRequestId(selectedEvent)!)">
            Open Run Trace
          </el-button>
          <span v-else>-</span>
        </el-descriptions-item>
        <el-descriptions-item label="Payload">
          <pre class="payload">{{ JSON.stringify(selectedEvent.payload || {}, null, 2) }}</pre>
        </el-descriptions-item>
      </el-descriptions>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useSecurityStore } from '@/stores/security'

const auth = useAuthStore()
const security = useSecurityStore()
const router = useRouter()
const eventType = ref('')
const result = ref('')
const userId = ref('')
const email = ref('')
const ipAddr = ref('')
const timeRange = ref<[Date, Date] | null>(null)
const detailVisible = ref(false)
const selectedEvent = ref<any>(null)

async function load() {
  const params: Record<string, any> = { limit: 50 }
  if (eventType.value) params.event_type = eventType.value
  if (result.value) params.result = result.value
  if (userId.value) params.user_id = userId.value
  if (email.value) params.email = email.value
  if (ipAddr.value) params.ip_addr = ipAddr.value
  if (timeRange.value?.[0]) params.start_date = timeRange.value[0].toISOString()
  if (timeRange.value?.[1]) params.end_date = timeRange.value[1].toISOString()
  await security.loadSecurityAudit(params)
}

function eventRequestId(row: any): string | null {
  if (!row) return null
  return row.request_id || row?.payload?.request_id || row?.payload?.audit_run_id || null
}

function goAuditRun(requestId: string) {
  if (!requestId) return
  router.push(`/audit/${requestId}`)
}

function openEvent(row: any) {
  selectedEvent.value = row
  detailVisible.value = true
}

onMounted(load)
</script>

<style scoped>
.audit-security { padding: 24px; }
.head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; gap: 12px; }
.filters { display: flex; align-items: center; gap: 8px; }
.overview { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }
.payload { white-space: pre-wrap; word-break: break-word; margin: 0; }
</style>
