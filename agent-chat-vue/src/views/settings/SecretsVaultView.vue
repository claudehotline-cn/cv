<template>
  <div class="settings-page" v-loading="security.loading">
    <div class="head">
      <h1>Secrets Vault</h1>
      <div class="actions">
        <el-select v-model="scopeFilter" style="width: 140px" @change="load">
          <el-option label="All" value="" />
          <el-option label="User" value="user" />
          <el-option label="Tenant" value="tenant" />
        </el-select>
        <el-button type="warning" @click="onReencrypt">Re-encrypt Tenant Secrets</el-button>
        <el-button type="primary" @click="createDialog = true">Create Secret</el-button>
      </div>
    </div>

    <el-alert v-if="security.error" :title="security.error" type="error" :closable="false" style="margin-bottom: 12px;" />

    <el-table :data="security.secrets" stripe>
      <el-table-column prop="name" label="Name" />
      <el-table-column prop="scope" label="Scope" width="100" />
      <el-table-column prop="provider" label="Provider" width="140" />
      <el-table-column prop="status" label="Status" width="120" />
      <el-table-column prop="current_version" label="Version" width="100" />
      <el-table-column label="Actions" width="320">
        <template #default="{ row }">
          <el-button size="small" @click="openRotate(row.id)">Rotate</el-button>
          <el-button v-if="row.status === 'active'" size="small" @click="security.disableSecret(row.id)">Disable</el-button>
          <el-button v-else size="small" @click="security.enableSecret(row.id)">Enable</el-button>
          <el-button size="small" type="danger" @click="security.deleteSecret(row.id)">Delete</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="createDialog" title="Create Secret" width="520px">
      <el-form label-position="top">
        <el-form-item label="Name"><el-input v-model="createForm.name" /></el-form-item>
        <el-form-item label="Provider"><el-input v-model="createForm.provider" /></el-form-item>
        <el-form-item label="Scope">
          <el-select v-model="createForm.scope" style="width: 100%">
            <el-option label="User" value="user" />
            <el-option label="Tenant" value="tenant" />
          </el-select>
        </el-form-item>
        <el-form-item label="Value"><el-input v-model="createForm.value" type="password" show-password /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialog = false">Cancel</el-button>
        <el-button type="primary" @click="onCreate">Create</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="rotateDialog" title="Rotate Secret" width="480px">
      <el-form label-position="top">
        <el-form-item label="New Value"><el-input v-model="rotateValue" type="password" show-password /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="rotateDialog = false">Cancel</el-button>
        <el-button type="primary" @click="onRotate">Rotate</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useSecurityStore } from '@/stores/security'

const security = useSecurityStore()
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

async function load() {
  await security.loadSecrets((scopeFilter.value || undefined) as 'user' | 'tenant' | undefined)
}

onMounted(async () => {
  await load()
})
</script>

<style scoped>
.settings-page { padding: 24px; }
.head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.actions { display: flex; gap: 8px; }
</style>
