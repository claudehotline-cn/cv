import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import apiClient, { type AuthUser } from '@/api/client'


export const useAuthStore = defineStore('auth', () => {
  const user = ref<AuthUser | null>(apiClient.getStoredUser())
  const initialized = ref(false)
  const loading = ref(false)

  const isAuthenticated = computed(() => !!user.value && apiClient.isAuthenticated())
  const isAdmin = computed(() => user.value?.role === 'admin')

  async function bootstrap() {
    if (initialized.value) return
    loading.value = true
    try {
      user.value = await apiClient.bootstrapAuth()
    } finally {
      initialized.value = true
      loading.value = false
    }
  }

  async function login(email: string, password: string) {
    loading.value = true
    try {
      user.value = await apiClient.login(email, password)
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
    } finally {
      loading.value = false
    }
  }

  return {
    user,
    initialized,
    loading,
    isAuthenticated,
    isAdmin,
    bootstrap,
    login,
    logout,
  }
})
