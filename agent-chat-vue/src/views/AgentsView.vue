<template>
  <el-container class="agents-page">
    <el-aside width="auto">
      <AppSidebar />
    </el-aside>

    <el-container direction="vertical" class="agents-main">
      <el-main class="agents-main-content">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import AppSidebar from '@/components/layout/AppSidebar.vue'
</script>

<style scoped>
.agents-page {
  height: 100vh;
  width: 100vw;
  overflow: hidden;
  background: var(--bg-primary);
}

.agents-main {
  min-width: 0;
  height: 100%;
}

.agents-main-content {
  padding: 0;
  height: 100%;
  overflow: hidden;
}
</style>
