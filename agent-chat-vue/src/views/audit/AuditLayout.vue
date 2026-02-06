<template>
  <el-container class="audit-shell">
    <el-aside width="auto">
      <AppSidebar />
    </el-aside>

    <el-container direction="vertical" class="audit-main">
      <el-main class="audit-main-content">
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
.audit-shell {
  height: 100vh;
  width: 100vw;
  overflow: hidden;
  background: var(--bg-primary);
}

.audit-main {
  min-width: 0;
  height: 100%;
}

.audit-main-content {
  padding: 0;
  height: 100%;
  overflow: hidden;
}
</style>
