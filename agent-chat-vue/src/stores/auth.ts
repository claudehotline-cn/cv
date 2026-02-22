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
  const tenantList = ref<TenantOption[]>([])
  const tenantOptions = computed<TenantOption[]>(() => tenantList.value)
  const activeTenantRole = computed<'owner' | 'admin' | 'member' | null>(() => {
    const active = tenantList.value.find((t) => t.id === activeTenantId.value)
    return (active?.role as 'owner' | 'admin' | 'member' | undefined) || user.value?.tenant_role || null
  })
  const canManageTenantSecurity = computed(() => {
    return isAdmin.value || activeTenantRole.value === 'owner' || activeTenantRole.value === 'admin'
  })

  function ensureActiveTenant() {
    if (tenantList.value.length === 0) {
      activeTenantId.value = ''
      return
    }
    if (!activeTenantId.value || !tenantList.value.some((t) => t.id === activeTenantId.value)) {
      const fallback = tenantList.value[0].id
      activeTenantId.value = fallback
      apiClient.setActiveTenantId(fallback)
    }
  }

  async function loadTenants() {
    if (!isAuthenticated.value) {
      tenantList.value = []
      activeTenantId.value = ''
      return
    }
    const res = await apiClient.listMyTenants()
    tenantList.value = (res?.items || []).map((t) => ({ id: t.id, name: t.name, role: t.role }))
    if (res?.active_tenant_id) {
      activeTenantId.value = res.active_tenant_id
      apiClient.setActiveTenantId(res.active_tenant_id)
    }
    ensureActiveTenant()
  }

  async function bootstrap() {
    if (initialized.value) return
    loading.value = true
    try {
      user.value = await apiClient.bootstrapAuth()
      if (user.value?.tenant_id && !activeTenantId.value) {
        activeTenantId.value = user.value.tenant_id
        apiClient.setActiveTenantId(user.value.tenant_id)
      }
      await loadTenants()
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
      await loadTenants()
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
      tenantList.value = []
      activeTenantId.value = ''
    } finally {
      loading.value = false
    }
  }

  function switchTenant(tenantId: string) {
    if (!tenantList.value.some((t) => t.id === tenantId)) return
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
    activeTenantRole,
    canManageTenantSecurity,
    tenantOptions,
    loadTenants,
    bootstrap,
    login,
    logout,
    switchTenant,
  }
})
