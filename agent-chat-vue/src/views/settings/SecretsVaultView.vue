<template>
  <div class="settings-page" v-loading="security.loading">
    <div class="page-header">
      <div class="header-content">
        <h1 class="page-title">Secrets Vault</h1>
        <p class="page-description">Securely manage credentials and secrets for third-party providers.</p>
      </div>
      <div class="actions flex-actions">
        <el-select v-model="scopeFilter" style="width: 140px" @change="load" placeholder="Filter by Scope">
          <el-option label="All Scopes" value="" />
          <el-option label="User" value="user" />
          <el-option label="Tenant" value="tenant" />
        </el-select>
        <el-button v-if="auth.canManageTenantSecurity" type="warning" @click="onReencrypt">Re-encrypt Tenant Secrets</el-button>
        <el-button type="primary" @click="onClickCreate">Create Secret</el-button>
      </div>
    </div>

    <transition name="el-fade-in-linear">
      <el-alert v-if="security.error" :title="security.error" type="error" :closable="false" show-icon class="alert-box" />
    </transition>

    <el-card shadow="never" class="table-card">
      <el-table :data="security.secrets" stripe style="width: 100%">
        <template #empty>
          <el-empty description="No Secrets Found" />
        </template>
        <el-table-column prop="name" label="Name" min-width="150" />
        <el-table-column prop="scope" label="Scope" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="row.scope === 'tenant' ? 'warning' : 'info'">{{ row.scope }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="provider" label="Provider" width="140" />
        <el-table-column prop="status" label="Status" width="120">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 'active' ? 'success' : 'info'">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="current_version" label="Version" width="100" />
        <el-table-column prop="updated_at" label="Updated At" width="180" />
        <el-table-column label="Actions" width="300" fixed="right">
          <template #default="{ row }">
            <div class="action-buttons">
              <template v-if="auth.canManageTenantSecurity || row.scope === 'user'">
                <el-button size="small" @click="openRotate(row.id)">Rotate</el-button>
                <el-button v-if="row.status === 'active'" size="small" plain type="warning" @click="security.disableSecret(row.id)">Disable</el-button>
                <el-button v-else size="small" plain type="success" @click="security.enableSecret(row.id)">Enable</el-button>
                <el-button size="small" type="danger" plain @click="security.deleteSecret(row.id)">Delete</el-button>
              </template>
              <el-tag v-else size="small" type="info">Read only</el-tag>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="createDialog" title="Create Secret" width="520px" destroy-on-close>
      <el-form label-position="top">
        <el-form-item label="Name"><el-input v-model="createForm.name" placeholder="Secret name identifier" /></el-form-item>
        <el-form-item label="Provider"><el-input v-model="createForm.provider" placeholder="e.g. openai, aws" /></el-form-item>
        <el-form-item label="Scope">
          <el-select v-model="createForm.scope" style="width: 100%">
            <el-option label="User" value="user" />
            <el-option label="Tenant" value="tenant" />
          </el-select>
        </el-form-item>
        <el-form-item label="Value"><el-input v-model="createForm.value" type="password" show-password placeholder="Secret value or API key" /></el-form-item>
      </el-form>
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="createDialog = false">Cancel</el-button>
          <el-button type="primary" @click="onCreate" :disabled="!createForm.name || !createForm.provider || !createForm.value">Create</el-button>
        </span>
      </template>
    </el-dialog>

    <el-dialog v-model="rotateDialog" title="Rotate Secret" width="480px" destroy-on-close>
      <el-form label-position="top">
        <el-form-item label="New Value"><el-input v-model="rotateValue" type="password" show-password placeholder="Enter new secret value" /></el-form-item>
      </el-form>
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="rotateDialog = false">Cancel</el-button>
          <el-button type="primary" @click="onRotate" :disabled="!rotateValue">Rotate</el-button>
        </span>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useSecurityStore } from '@/stores/security'
import { useAuthStore } from '@/stores/auth'

const security = useSecurityStore()
const auth = useAuthStore()
const scopeFilter = ref('')

const createDialog = ref(false)
const rotateDialog = ref(false)
const rotateId = ref('')
const rotateValue = ref('')

const createForm = reactive({
  name: '',
  provider: '',
  scope: 'user' as 'user' | 'tenant',
  value: '',
})

async function onCreate() {
  if (createForm.scope === 'tenant' && !auth.canManageTenantSecurity) {
    ElMessage.error('Only tenant admin/owner can create tenant scope secrets')
    return
  }
  await security.createSecret({ ...createForm })
  createDialog.value = false
  createForm.name = ''
  createForm.provider = ''
  createForm.scope = 'user'
  createForm.value = ''
}

function openRotate(secretId: string) {
  rotateId.value = secretId
  rotateValue.value = ''
  rotateDialog.value = true
}

async function onRotate() {
  await security.rotateSecret(rotateId.value, rotateValue.value)
  rotateDialog.value = false
}

async function onReencrypt() {
  const result = await security.reencryptTenantSecrets()
  ElMessage.success(`Re-encrypt queued: ${result.job_id || 'ok'}`)
}

function onClickCreate() {
  if (!auth.canManageTenantSecurity) {
    createForm.scope = 'user'
  }
  createDialog.value = true
}

async function load() {
  await security.loadSecrets((scopeFilter.value || undefined) as 'user' | 'tenant' | undefined)
}

onMounted(async () => {
  try {
    await load()
  } catch {
    // error state is already tracked by store
  }
})
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

.flex-actions {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.alert-box {
  margin-bottom: 20px;
}

.table-card {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
}

.table-card :deep(.el-card__body) {
  padding: 0;
}

.action-buttons {
  display: flex;
  gap: 6px;
  flex-wrap: nowrap;
}

@media (max-width: 768px) {
  .settings-page {
    padding: 16px;
  }
  
  .page-header {
    flex-direction: column;
  }

  .flex-actions {
    width: 100%;
    flex-direction: column;
    align-items: stretch;
  }
  
  .flex-actions .el-select,
  .flex-actions .el-button {
    width: 100%;
    margin-left: 0 !important;
  }
}
</style>
