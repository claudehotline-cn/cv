import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import apiClient, { type AuthUser, type TenantOption } from '@/api/client'


export const useAuthStore = defineStore('auth', () => {
  const user = ref<AuthUser | null>(apiClient.getStoredUser())
  const initialized = ref(false)
  const loading = ref(false)

  const isAuthenticated = computed(() => !!user.value && apiClient.isAuthenticated())
  const isAdmin = computed(() => user.value?.role === 'admin')
  const activeTenantId = ref(apiClient.getActiveTenantId())
  const tenantOptions = computed<TenantOption[]>(() => {
    if (!user.value?.tenant_id) return []
    return [{
      id: user.value.tenant_id,
      name: 'Default Tenant',
      role: (user.value.tenant_role || 'member') as 'owner' | 'admin' | 'member',
    }]
  })

  async function bootstrap() {
    if (initialized.value) return
    loading.value = true
    try {
      user.value = await apiClient.bootstrapAuth()
      if (user.value?.tenant_id && !activeTenantId.value) {
        activeTenantId.value = user.value.tenant_id
        apiClient.setActiveTenantId(user.value.tenant_id)
      }
    } finally {
      initialized.value = true
      loading.value = false
    }
  }

  async function login(email: string, password: string) {
    loading.value = true
    try {
      user.value = await apiClient.login(email, password)
      if (user.value?.tenant_id) {
        activeTenantId.value = user.value.tenant_id
        apiClient.setActiveTenantId(user.value.tenant_id)
      }
      return user.value
    } finally {
      loading.value = false
    }
  }

  async function logout() {
    loading.value = true
    try {
      await apiClient.logout()
      user.value = null
      activeTenantId.value = ''
    } finally {
      loading.value = false
    }
  }

  function switchTenant(tenantId: string) {
    activeTenantId.value = tenantId
    apiClient.setActiveTenantId(tenantId)
  }

  return {
    user,
    initialized,
    loading,
    isAuthenticated,
    isAdmin,
    activeTenantId,
    tenantOptions,
    bootstrap,
    login,
    logout,
    switchTenant,
  }
})
