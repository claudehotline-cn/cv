<template>
  <div class="audit-security" v-loading="security.loading">
    <section class="head">
      <h1>Security Audit</h1>
      <div class="filters">
        <el-input v-model="query" clearable placeholder="Search user/reason/payload" style="width: 300px" />
        <el-select v-model="eventType" placeholder="Event Type" clearable style="width: 220px">
          <el-option label="All" value="" />
          <el-option label="Login Success" value="login_success" />
          <el-option label="Login Failed" value="login_failed" />
          <el-option label="API Key" value="api_key" />
          <el-option label="Secret" value="secret" />
        </el-select>
        <el-select v-model="result" placeholder="Result" clearable style="width: 160px">
          <el-option label="All" value="" />
          <el-option label="Success" value="success" />
          <el-option label="Failed" value="failed" />
        </el-select>
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
      <el-table-column prop="event_type" label="Event" width="220" />
      <el-table-column prop="user_id" label="User" width="180" />
      <el-table-column prop="result" label="Result" width="120" />
      <el-table-column prop="reason_code" label="Reason" />
    </el-table>

    <el-drawer v-model="detailVisible" title="Security Event Detail" size="50%">
      <el-descriptions :column="1" border v-if="selectedEvent">
        <el-descriptions-item label="Event ID">{{ selectedEvent.event_id }}</el-descriptions-item>
        <el-descriptions-item label="Event Time">{{ selectedEvent.event_time }}</el-descriptions-item>
        <el-descriptions-item label="Event Type">{{ selectedEvent.event_type }}</el-descriptions-item>
        <el-descriptions-item label="User">{{ selectedEvent.user_id || '-' }}</el-descriptions-item>
        <el-descriptions-item label="Result">{{ selectedEvent.result || '-' }}</el-descriptions-item>
        <el-descriptions-item label="Reason">{{ selectedEvent.reason_code || '-' }}</el-descriptions-item>
        <el-descriptions-item label="Payload">
          <pre class="payload">{{ JSON.stringify(selectedEvent.payload || {}, null, 2) }}</pre>
        </el-descriptions-item>
      </el-descriptions>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useSecurityStore } from '@/stores/security'

const security = useSecurityStore()
const eventType = ref('')
const result = ref('')
const query = ref('')
const detailVisible = ref(false)
const selectedEvent = ref<any>(null)

async function load() {
  const params: Record<string, any> = { limit: 50 }
  if (eventType.value) params.event_type = eventType.value
  if (result.value) params.result = result.value
  if (query.value) params.q = query.value
  await security.loadSecurityAudit(params)
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
