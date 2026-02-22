<template>
  <div class="audit-security" v-loading="security.loading">
    <section class="head">
      <h1>Security Audit</h1>
      <el-select v-model="eventType" placeholder="Event Type" clearable style="width: 240px" @change="load">
        <el-option label="All" value="" />
        <el-option label="Login Success" value="login_success" />
        <el-option label="Login Failed" value="login_failed" />
        <el-option label="API Key" value="api_key" />
        <el-option label="Secret" value="secret" />
      </el-select>
    </section>

    <el-card style="margin-bottom: 16px;">
      <div class="overview">
        <div>Total: {{ security.authAuditOverview?.total_events ?? 0 }}</div>
        <div>Login Success: {{ security.authAuditOverview?.login_success ?? 0 }}</div>
        <div>Login Failed: {{ security.authAuditOverview?.login_failed ?? 0 }}</div>
        <div>Unique Users: {{ security.authAuditOverview?.unique_user_count ?? 0 }}</div>
      </div>
    </el-card>

    <el-table :data="security.authAudit?.items || []" stripe>
      <el-table-column prop="event_time" label="Time" width="220" />
      <el-table-column prop="event_type" label="Event" width="220" />
      <el-table-column prop="user_id" label="User" width="180" />
      <el-table-column prop="result" label="Result" width="120" />
      <el-table-column prop="reason_code" label="Reason" />
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useSecurityStore } from '@/stores/security'

const security = useSecurityStore()
const eventType = ref('')

async function load() {
  const params: Record<string, any> = { limit: 50 }
  if (eventType.value) params.event_type = eventType.value
  await security.loadSecurityAudit(params)
}

onMounted(load)
</script>

<style scoped>
.audit-security { padding: 24px; }
.head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.overview { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }
</style>
