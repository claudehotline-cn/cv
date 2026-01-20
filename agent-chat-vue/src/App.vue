<template>
  <router-view />
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useTheme } from '@/composables/useTheme'

const { initTheme } = useTheme()

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
