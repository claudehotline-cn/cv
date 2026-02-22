<template>
  <div class="settings-page" v-loading="loading">
    <div class="head">
      <h1>API Keys</h1>
      <el-button type="primary" @click="createDialog = true">Create API Key</el-button>
    </div>

    <el-table :data="keys" stripe>
      <el-table-column prop="id" label="Key ID" />
      <el-table-column prop="name" label="Name" />
      <el-table-column prop="created_at" label="Created At" />
      <el-table-column label="Actions" width="120">
        <template #default="{ row }">
          <el-button size="small" type="danger" @click="onRevoke(row.id)">Revoke</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="createDialog" title="Create API Key" width="480px">
      <el-form label-position="top">
        <el-form-item label="Name"><el-input v-model="keyName" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialog = false">Cancel</el-button>
        <el-button type="primary" @click="onCreate">Create</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import apiClient from '@/api/client'

const loading = ref(false)
const keys = ref<any[]>([])
const createDialog = ref(false)
const keyName = ref('')

async function load() {
  loading.value = true
  try {
    const data = await apiClient.listApiKeys()
    keys.value = data?.items || data || []
  } finally {
    loading.value = false
  }
}

async function onCreate() {
  await apiClient.createApiKey(keyName.value)
  createDialog.value = false
  keyName.value = ''
  await load()
}

async function onRevoke(keyId: string) {
  await apiClient.revokeApiKey(keyId)
  await load()
}

onMounted(load)
</script>

<style scoped>
.settings-page { padding: 24px; }
.head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
</style>
