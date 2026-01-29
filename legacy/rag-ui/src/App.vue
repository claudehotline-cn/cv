<script setup lang="ts">
import { RouterView } from 'vue-router'
import MainLayout from './components/MainLayout.vue'
</script>

<template>
  <div v-if="route.meta.layout === 'full'">
    <RouterView />
  </div>
  <MainLayout v-else>
    <RouterView />
  </MainLayout>
</template>

<style scoped>
</style>
