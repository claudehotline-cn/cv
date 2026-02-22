<template>
  <div class="settings-page" v-loading="loading">
    <div class="head">
      <h1>Tenant & Members</h1>
      <el-button plain @click="loadTenantsAndMembers">Refresh</el-button>
    </div>
    <el-card>
      <template #header>Current Tenant</template>
      <p>ID: {{ auth.activeTenantId || '-' }}</p>
      <p>Role: {{ auth.activeTenantRole || auth.user?.tenant_role || '-' }}</p>
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

    <el-card style="margin-top: 16px;">
      <template #header>
        <div class="members-head">
          <span>Members (Current Tenant)</span>
          <div class="member-actions">
            <el-button
              size="small"
              type="primary"
              :disabled="!auth.canManageTenantSecurity"
              @click="openInvite"
            >
              Invite Member
            </el-button>
          </div>
        </div>
      </template>
      <el-alert v-if="error" :title="error" type="error" :closable="false" style="margin-bottom: 12px;" />
      <el-table :data="members" stripe>
        <el-table-column prop="name" label="Name" />
        <el-table-column prop="email" label="Email" />
        <el-table-column prop="role" label="Role" width="120" />
        <el-table-column prop="status" label="Status" width="120" />
        <el-table-column label="Actions" width="220">
          <template #default="{ row }">
            <el-dropdown
              trigger="click"
              :disabled="!auth.canManageTenantSecurity || row.status !== 'active'"
              @command="(role: string) => onChangeRole(row, role)"
            >
              <el-button size="small">Change Role</el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="owner">Owner</el-dropdown-item>
                  <el-dropdown-item command="admin">Admin</el-dropdown-item>
                  <el-dropdown-item command="member">Member</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <el-button
              size="small"
              type="danger"
              :disabled="!auth.canManageTenantSecurity || row.status !== 'active'"
              @click="onRemove(row)"
            >
              Remove
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="inviteDialogVisible" title="Invite Member" width="480px">
      <el-form label-position="top">
        <el-form-item label="User ID">
          <el-input v-model="inviteForm.user_id" placeholder="u-xxxx (optional)" />
        </el-form-item>
        <el-form-item label="Email">
          <el-input v-model="inviteForm.email" placeholder="user@example.com (optional)" />
        </el-form-item>
        <el-form-item label="Role">
          <el-select v-model="inviteForm.role" style="width: 100%;">
            <el-option label="Member" value="member" />
            <el-option label="Admin" value="admin" />
            <el-option label="Owner" value="owner" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="inviteDialogVisible = false">Cancel</el-button>
        <el-button type="primary" :loading="inviting" @click="onInvite">Invite</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import apiClient from '@/api/client'

const auth = useAuthStore()
const loading = ref(false)
const inviting = ref(false)
const error = ref('')
const tenants = ref<Array<{ id: string; name: string; role: string; status?: string }>>([])
const members = ref<Array<{ tenant_id?: string; user_id: string; name: string; email?: string | null; role: string; status: string }>>([])
const inviteDialogVisible = ref(false)
const inviteForm = ref<{ user_id: string; email: string; role: 'owner' | 'admin' | 'member' }>({
  user_id: '',
  email: '',
  role: 'member',
})

const tenantName = computed(() => {
  const id = auth.activeTenantId
  return tenants.value.find((t) => t.id === id)?.name || ''
})

function resetInviteForm() {
  inviteForm.value = { user_id: '', email: '', role: 'member' }
}

async function loadMembers() {
  const tenantId = auth.activeTenantId
  if (!tenantId) {
    members.value = []
    return
  }
  const data = await apiClient.listTenantMembers(tenantId)
  members.value = data.items || []
}

async function loadTenantsAndMembers() {
  loading.value = true
  error.value = ''
  try {
    const data = await apiClient.listMyTenants()
    tenants.value = data?.items || []
    await loadMembers()
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || 'Failed to load tenant members'
  } finally {
    loading.value = false
  }
}

function openInvite() {
  resetInviteForm()
  inviteDialogVisible.value = true
}

async function onInvite() {
  const tenantId = auth.activeTenantId
  if (!tenantId) return
  const userId = inviteForm.value.user_id.trim()
  const email = inviteForm.value.email.trim()
  if (!userId && !email) {
    ElMessage.error('Please provide user id or email')
    return
  }
  inviting.value = true
  try {
    await apiClient.inviteTenantMember(tenantId, {
      user_id: userId || undefined,
      email: email || undefined,
      role: inviteForm.value.role,
    })
    inviteDialogVisible.value = false
    await loadMembers()
    ElMessage.success('Member invited')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || 'Invite failed')
  } finally {
    inviting.value = false
  }
}

async function onChangeRole(row: { user_id: string }, role: string) {
  const tenantId = auth.activeTenantId
  if (!tenantId) return
  try {
    await apiClient.updateTenantMemberRole(tenantId, row.user_id, role as 'owner' | 'admin' | 'member')
    await loadMembers()
    ElMessage.success('Role updated')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || 'Role update failed')
  }
}

async function onRemove(row: { user_id: string; name: string }) {
  const tenantId = auth.activeTenantId
  if (!tenantId) return
  try {
    await ElMessageBox.confirm(`Remove ${row.name}?`, 'Confirm', { type: 'warning' })
  } catch {
    return
  }
  try {
    await apiClient.removeTenantMember(tenantId, row.user_id)
    await loadMembers()
    ElMessage.success('Member removed')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || 'Remove failed')
  }
}

watch(
  () => auth.activeTenantId,
  async () => {
    await loadTenantsAndMembers()
  }
)

onMounted(async () => {
  await loadTenantsAndMembers()
})
</script>

<style scoped>
.settings-page { padding: 24px; }
.head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.members-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.member-actions { display: flex; gap: 8px; }
</style>
