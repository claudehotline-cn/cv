<template>
  <div class="settings-page">
    <h1>Tenant & Members</h1>
    <el-card>
      <template #header>Current Tenant</template>
      <p>ID: {{ auth.activeTenantId || '-' }}</p>
      <p>Role: {{ auth.user?.tenant_role || '-' }}</p>
    </el-card>
    <el-alert
      style="margin-top: 16px"
      title="成员管理 API 尚未完整开放，当前页面先提供租户上下文与占位信息。"
      type="info"
      :closable="false"
    />
  </div>
</template>

<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
</script>

<style scoped>
.settings-page { padding: 24px; }
</style>
