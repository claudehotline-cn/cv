<template>
  <router-view v-if="authReady" />
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useTheme } from '@/composables/useTheme'
import { useAuthStore } from '@/stores/auth'

const { initTheme } = useTheme()
const authStore = useAuthStore()
const authReady = computed(() => authStore.initialized)

onMounted(() => {
  initTheme()
})
</script>

<style>
/* Global Layout */
#app {
  height: 100vh;
  width: 100vw;
  overflow: hidden;
  background: radial-gradient(circle at top right, #1e1b4b 0%, #0f172a 40%);
  transition: background 0.3s ease;
}

/* Light Mode Background */
:root.light #app {
  background: radial-gradient(circle at top right, #e0e7ff 0%, #f8fafc 40%);
}
</style>
