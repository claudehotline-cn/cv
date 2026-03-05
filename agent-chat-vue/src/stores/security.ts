import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import apiClient, {
  type AuthAuditOverview,
  type CacheEntryItem,
  type CacheStatsResponse,
  type LimitsResponse,
  type PaginatedAuthAuditResponse,
  type QuotaResponse,
  type SecretItem,
} from '@/api/client'
import { useAuthStore } from '@/stores/auth'


export const useSecurityStore = defineStore('security', () => {
  const loading = ref(false)
  const error = ref<string>('')
  const limits = ref<LimitsResponse | null>(null)
  const quota = ref<QuotaResponse | null>(null)
  const secrets = ref<SecretItem[]>([])
  const authAudit = ref<PaginatedAuthAuditResponse | null>(null)
  const authAuditOverview = ref<AuthAuditOverview | null>(null)
  const cacheStats = ref<CacheStatsResponse | null>(null)
  const cacheEntries = ref<CacheEntryItem[]>([])
  const cacheLoading = ref(false)
  const cacheError = ref<string>('')

  const hasQuotaPressure = computed(() => {
    if (!quota.value || quota.value.monthly_token_quota <= 0) return false
    return quota.value.used_tokens / quota.value.monthly_token_quota >= 0.8
  })

  async function loadLimitsAndQuota() {
    loading.value = true
    error.value = ''
    try {
      limits.value = await apiClient.getMyLimits()
      quota.value = await apiClient.getMyQuota()
    } catch (e: any) {
      error.value = e?.response?.data?.detail || e?.message || 'Failed to load limits/quota'
      throw e
    } finally {
      loading.value = false
    }
  }

  async function saveLimits(patch: Record<string, any>) {
    const auth = useAuthStore()
    const tenantId = auth.activeTenantId
    if (!tenantId) throw new Error('No active tenant')
    limits.value = await apiClient.updateTenantLimits(tenantId, patch)
  }

  async function saveQuota(patch: { monthly_token_quota?: number; enabled?: boolean }) {
    const auth = useAuthStore()
    const tenantId = auth.activeTenantId
    if (!tenantId) throw new Error('No active tenant')
    quota.value = await apiClient.updateTenantQuota(tenantId, patch)
  }

  async function loadSecrets(scope?: 'user' | 'tenant') {
    loading.value = true
    error.value = ''
    try {
      const res = await apiClient.listSecrets(scope)
      secrets.value = res.items || []
    } catch (e: any) {
      error.value = e?.response?.data?.detail || e?.message || 'Failed to load secrets'
      throw e
    } finally {
      loading.value = false
    }
  }

  async function createSecret(input: { name: string; value: string; scope: 'user' | 'tenant'; provider?: string }) {
    await apiClient.createSecret(input)
    await loadSecrets()
  }

  async function rotateSecret(secretId: string, value: string) {
    await apiClient.rotateSecret(secretId, value)
    await loadSecrets()
  }

  async function disableSecret(secretId: string) {
    await apiClient.disableSecret(secretId)
    await loadSecrets()
  }

  async function enableSecret(secretId: string) {
    await apiClient.enableSecret(secretId)
    await loadSecrets()
  }

  async function deleteSecret(secretId: string) {
    await apiClient.deleteSecret(secretId)
    await loadSecrets()
  }

  async function reencryptTenantSecrets() {
    const auth = useAuthStore()
    const tenantId = auth.activeTenantId
    if (!tenantId) throw new Error('No active tenant')
    return apiClient.reencryptTenantSecrets(tenantId)
  }

  async function loadSecurityAudit(params: Record<string, any> = {}) {
    loading.value = true
    error.value = ''
    try {
      authAudit.value = await apiClient.listAuthAuditEvents(params)
      authAuditOverview.value = await apiClient.getAuthAuditOverview({ window_hours: 24 })
    } catch (e: any) {
      error.value = e?.response?.data?.detail || e?.message || 'Failed to load security audit'
      throw e
    } finally {
      loading.value = false
    }
  }

  async function loadCacheStats() {
    cacheLoading.value = true
    cacheError.value = ''
    try {
      cacheStats.value = await apiClient.getCacheStatsMe()
    } catch (e: any) {
      cacheError.value = e?.response?.data?.detail || e?.message || 'Failed to load cache stats'
      throw e
    } finally {
      cacheLoading.value = false
    }
  }

  async function loadCacheEntries(params: { limit?: number; offset?: number; namespace?: string } = {}) {
    const auth = useAuthStore()
    const tenantId = auth.activeTenantId
    if (!tenantId) throw new Error('No active tenant')

    cacheLoading.value = true
    cacheError.value = ''
    try {
      const res = await apiClient.listTenantCacheEntries(tenantId, params)
      cacheEntries.value = res.items || []
    } catch (e: any) {
      cacheError.value = e?.response?.data?.detail || e?.message || 'Failed to load cache entries'
      throw e
    } finally {
      cacheLoading.value = false
    }
  }

  async function invalidateCache(namespace?: string) {
    const auth = useAuthStore()
    const tenantId = auth.activeTenantId
    if (!tenantId) throw new Error('No active tenant')

    cacheLoading.value = true
    cacheError.value = ''
    try {
      const payload = namespace ? { namespace } : undefined
      await apiClient.invalidateTenantCache(tenantId, payload)
      await Promise.all([loadCacheStats(), loadCacheEntries({ namespace })])
    } catch (e: any) {
      cacheError.value = e?.response?.data?.detail || e?.message || 'Failed to invalidate cache'
      throw e
    } finally {
      cacheLoading.value = false
    }
  }

  return {
    loading,
    error,
    limits,
    quota,
    secrets,
    authAudit,
    authAuditOverview,
    cacheStats,
    cacheEntries,
    cacheLoading,
    cacheError,
    hasQuotaPressure,
    loadLimitsAndQuota,
    saveLimits,
    saveQuota,
    loadSecrets,
    createSecret,
    rotateSecret,
    disableSecret,
    enableSecret,
    deleteSecret,
    reencryptTenantSecrets,
    loadSecurityAudit,
    loadCacheStats,
    loadCacheEntries,
    invalidateCache,
  }
})
