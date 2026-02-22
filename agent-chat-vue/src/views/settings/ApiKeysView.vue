<template>
  <div class="settings-page" v-loading="loading">
    <div class="page-header">
      <div class="header-content">
        <h1 class="page-title">API Keys</h1>
        <p class="page-description">Manage API keys used to authenticate requests to the platform.</p>
      </div>
      <el-button type="primary" @click="createDialog = true">Create API Key</el-button>
    </div>

    <transition name="el-fade-in-linear">
      <el-alert
        v-if="newSecretValue"
        title="Save this key now. It will not be shown again."
        type="warning"
        :closable="true"
        show-icon
        @close="newSecretValue = ''"
        class="secret-alert"
      >
        <template #default>
          <div class="new-key-row">
            <el-input :model-value="newSecretValue" readonly>
              <template #append>
                <el-button @click="copyNewKey">Copy</el-button>
              </template>
            </el-input>
          </div>
        </template>
      </el-alert>
    </transition>

    <el-card shadow="never" class="table-card">
      <el-table :data="keys" stripe style="width: 100%">
        <template #empty>
          <el-empty description="No API Keys found" />
        </template>
        <el-table-column prop="id" label="Key ID" min-width="120" />
        <el-table-column prop="name" label="Name" min-width="150" />
        <el-table-column prop="created_at" label="Created At" min-width="180" />
        <el-table-column label="Actions" width="100" fixed="right" align="center">
          <template #default="{ row }">
            <el-button size="small" type="danger" plain @click="onRevoke(row.id)">Revoke</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="createDialog" title="Create API Key" width="400px" destroy-on-close>
      <el-form label-position="top">
        <el-form-item label="Name">
          <el-input v-model="keyName" placeholder="e.g. Production Key" @keyup.enter="onCreate" />
        </el-form-item>
      </el-form>
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="createDialog = false">Cancel</el-button>
          <el-button type="primary" @click="onCreate" :disabled="!keyName">Create</el-button>
        </span>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import apiClient from '@/api/client'

const loading = ref(false)
const keys = ref<any[]>([])
const createDialog = ref(false)
const keyName = ref('')
const newSecretValue = ref('')

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
  const created = await apiClient.createApiKey(keyName.value)
  newSecretValue.value = created?.secret || created?.key || ''
  createDialog.value = false
  keyName.value = ''
  await load()
}

async function onRevoke(keyId: string) {
  await apiClient.revokeApiKey(keyId)
  await load()
}

async function copyNewKey() {
  if (!newSecretValue.value) return
  await navigator.clipboard.writeText(newSecretValue.value)
  ElMessage.success('Copied')
}

onMounted(load)
</script>

<style scoped>
.settings-page {
  padding: 32px;
  max-width: 1200px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 24px;
  gap: 16px;
  flex-wrap: wrap;
}

.header-content {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.page-title {
  margin: 0;
  font-size: 24px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.page-description {
  margin: 0;
  font-size: 14px;
  color: var(--el-text-color-regular);
}

.secret-alert {
  margin-bottom: 24px;
}

.new-key-row {
  margin-top: 12px;
}

.table-card {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
}

.table-card :deep(.el-card__body) {
  padding: 0;
}

@media (max-width: 768px) {
  .settings-page {
    padding: 16px;
  }
  
  .page-header {
    flex-direction: column;
  }
  
  .page-header .el-button {
    width: 100%;
  }
}
</style>
