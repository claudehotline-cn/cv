<template>
  <div class="settings-page" v-loading="loading">
    <h1>Tenant & Members</h1>
    <el-card>
      <template #header>Current Tenant</template>
      <p>ID: {{ auth.activeTenantId || '-' }}</p>
      <p>Role: {{ auth.user?.tenant_role || '-' }}</p>
      <p>Name: {{ tenantName || '-' }}</p>
    </el-card>

    <el-card style="margin-top: 16px;">
      <template #header>My Tenants</template>
      <el-table :data="tenants" stripe>
        <el-table-column prop="name" label="Tenant" />
        <el-table-column prop="id" label="Tenant ID" />
        <el-table-column prop="role" label="Role" width="120" />
        <el-table-column prop="status" label="Status" width="120" />
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useAuthStore } from '@/stores/auth'
import apiClient from '@/api/client'

const auth = useAuthStore()
const loading = ref(false)
const tenants = ref<Array<{ id: string; name: string; role: string; status?: string }>>([])

const tenantName = computed(() => {
  const id = auth.activeTenantId
  return tenants.value.find((t) => t.id === id)?.name || ''
})

onMounted(async () => {
  loading.value = true
  try {
    const data = await apiClient.listMyTenants()
    tenants.value = data?.items || []
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.settings-page { padding: 24px; }
</style>
