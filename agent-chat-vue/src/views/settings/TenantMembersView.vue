<template>
  <div class="settings-page" v-loading="loading">
    <div class="page-header">
      <div class="header-content">
        <h1 class="page-title">Tenant & Members</h1>
        <p class="page-description">Manage your organization tenants and control member access roles.</p>
      </div>
      <el-button :icon="RefreshIcon" circle title="Refresh" @click="loadTenantsAndMembers" />
    </div>

    <transition name="el-fade-in-linear">
      <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="alert-box" />
    </transition>

    <el-row :gutter="20">
      <el-col :xs="24" :lg="8" class="tenant-info-col">
        <el-card shadow="never" class="system-card h-full">
          <template #header>
            <div class="card-header">
              <span>Current Tenant</span>
            </div>
          </template>
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="Tenant ID">{{ auth.activeTenantId || '-' }}</el-descriptions-item>
            <el-descriptions-item label="Tenant Name">{{ tenantName || '-' }}</el-descriptions-item>
            <el-descriptions-item label="Your Role">
              <el-tag size="small" type="success" disable-transitions>{{ auth.activeTenantRole || auth.user?.tenant_role || '-' }}</el-tag>
            </el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>

      <el-col :xs="24" :lg="16" class="tenant-list-col">
        <el-card shadow="never" class="system-card h-full">
          <template #header>
            <div class="card-header">
              <span>My Tenants</span>
            </div>
          </template>
          <el-table :data="tenants" stripe style="width: 100%">
            <template #empty>
              <el-empty description="No Tenants Found" :image-size="60" />
            </template>
            <el-table-column prop="name" label="Tenant Name" min-width="150" />
            <el-table-column prop="id" label="Tenant ID" min-width="150" />
            <el-table-column prop="role" label="Role" width="120">
              <template #default="{ row }">
                <el-tag size="small" type="info">{{ row.role }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="status" label="Status" width="100">
              <template #default="{ row }">
                <el-tag size="small" :type="row.status === 'active' ? 'success' : 'info'">{{ row.status || 'unknown' }}</el-tag>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never" class="system-card mt-20">
      <template #header>
        <div class="card-header">
          <span>Members (Current Tenant)</span>
          <el-button
            type="primary"
            :disabled="!auth.canManageTenantSecurity"
            @click="openInvite"
          >
            Invite Member
          </el-button>
        </div>
      </template>
      <el-table :data="members" stripe style="width: 100%">
        <template #empty>
          <el-empty description="No Members Found" />
        </template>
        <el-table-column prop="name" label="Name" min-width="150" />
        <el-table-column prop="email" label="Email" min-width="180" />
        <el-table-column prop="role" label="Role" width="120">
          <template #default="{ row }">
            <el-tag size="small" :type="row.role === 'owner' ? 'danger' : row.role === 'admin' ? 'warning' : 'primary'">{{ row.role }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="Status" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 'active' ? 'success' : 'info'">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="Actions" width="220" fixed="right">
          <template #default="{ row }">
            <div class="action-buttons">
              <el-dropdown
                trigger="click"
                :disabled="!auth.canManageTenantSecurity || row.status !== 'active'"
                @command="(role: string) => onChangeRole(row, role)"
              >
                <el-button size="small" plain>Change Role</el-button>
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
                plain
                :disabled="!auth.canManageTenantSecurity || row.status !== 'active'"
                @click="onRemove(row)"
              >
                Remove
              </el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="inviteDialogVisible" title="Invite Member" width="440px" destroy-on-close>
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
        <span class="dialog-footer">
          <el-button @click="inviteDialogVisible = false">Cancel</el-button>
          <el-button type="primary" :loading="inviting" @click="onInvite">Invite</el-button>
        </span>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh as RefreshIcon } from '@element-plus/icons-vue'
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

.alert-box {
  margin-bottom: 20px;
}

.h-full {
  height: 100%;
}

.system-card {
  border-radius: 8px;
  border: 1px solid var(--el-border-color-lighter);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 500;
}

.mt-20 {
  margin-top: 20px;
}

.action-buttons {
  display: flex;
  gap: 8px;
  align-items: center;
}

@media (max-width: 992px) {
  .tenant-info-col {
    margin-bottom: 20px;
  }
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

  .card-header {
    flex-direction: column;
    align-items: stretch;
    gap: 12px;
  }
}
</style>
