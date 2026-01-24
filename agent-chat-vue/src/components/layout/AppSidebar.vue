<template>
  <aside class="w-64 bg-surface-light dark:bg-surface-dark flex flex-col border-r border-border-color dark:border-gray-800 z-20 flex-shrink-0 transition-colors">
    <!-- Header -->
    <div class="p-6 flex items-center gap-3">
      <div class="bg-primary/10 rounded-lg p-2 flex items-center justify-center">
        <span class="material-symbols-outlined text-primary" style="font-size: 24px;">all_inclusive</span>
      </div>
      <h1 class="text-text-main dark:text-white text-lg font-bold tracking-tight">AI Nexus</h1>
    </div>

    <!-- Scrollable Menu -->
    <div class="flex-1 overflow-y-auto px-4 flex flex-col gap-2">
      <!-- We wrap el-menu to make it behave like the original nav list -->
      <el-menu
        :default-active="activeRoute"
        class="custom-menu border-none bg-transparent w-full"
        :router="true"
        :ellipsis="false" 
      >
        <el-menu-item index="/">
          <template #title>
             <div class="flex items-center gap-3 w-full">
                <span class="material-symbols-outlined filled" :class="{ 'text-primary': activeRoute === '/', 'text-text-secondary': activeRoute !== '/' }">dashboard</span>
                <span class="font-medium">Dashboard</span>
             </div>
          </template>
        </el-menu-item>
        
        <el-menu-item index="/chat">
          <template #title>
             <div class="flex items-center gap-3 w-full">
                <span class="material-symbols-outlined">chat</span>
                <span class="font-medium">Chat Space</span>
             </div>
          </template>
        </el-menu-item>

        <el-menu-item index="/agents" disabled>
           <template #title>
             <div class="flex items-center gap-3 w-full opacity-60">
                <span class="material-symbols-outlined">smart_toy</span>
                <span class="font-medium">Agents</span>
             </div>
          </template>
        </el-menu-item>

        <el-menu-item index="/audit">
           <template #title>
             <div class="flex items-center gap-3 w-full">
                <span class="material-symbols-outlined" :class="{ 'filled': activeRoute === '/audit' }">article</span>
                <span class="font-medium">Audit</span>
             </div>
          </template>
        </el-menu-item>

        <el-menu-item index="/analytics" disabled>
           <template #title>
             <div class="flex items-center gap-3 w-full opacity-60">
                <span class="material-symbols-outlined">analytics</span>
                <span class="font-medium">Analytics</span>
             </div>
           </template>
        </el-menu-item>

        <!-- Divider & Subheader -->
        <div class="my-2 border-t border-border-color dark:border-gray-800 pointer-events-none"></div>
        <p class="px-3 text-xs font-semibold text-text-secondary dark:text-gray-500 uppercase tracking-wider mb-1 mt-2 pointer-events-none">Settings</p>

        <el-menu-item index="/settings/general" disabled>
            <template #title>
             <div class="flex items-center gap-3 w-full opacity-60">
                <span class="material-symbols-outlined">settings</span>
                <span class="font-medium">General</span>
             </div>
           </template>
        </el-menu-item>

        <el-menu-item index="/settings/api" disabled>
            <template #title>
             <div class="flex items-center gap-3 w-full opacity-60">
                <span class="material-symbols-outlined">api</span>
                <span class="font-medium">API Keys</span>
             </div>
           </template>
        </el-menu-item>
      </el-menu>
    </div>

    <!-- Footer -->
    <div class="p-4 border-t border-border-color dark:border-gray-800">
      <div class="flex items-center gap-3 p-2 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800/50 cursor-pointer transition-colors user-card">
        <div class="size-8 rounded-full bg-gradient-to-tr from-blue-400 to-indigo-500"></div>
        <div class="flex-1 min-w-0">
          <p class="text-sm font-medium text-text-main dark:text-white truncate">Alex Morgan</p>
          <p class="text-xs text-text-secondary dark:text-gray-400 truncate">alex@nexus.ai</p>
        </div>
        <span class="material-symbols-outlined text-text-secondary" style="font-size: 20px;">unfold_more</span>
      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const activeRoute = computed(() => route.path)
</script>

<style scoped>
/* Reset Element Menu Defaults */
:deep(.custom-menu) {
    border-right: none !important;
    background-color: transparent !important;
    padding: 0 !important;
    display: flex;
    flex-direction: column;
    gap: 4px; /* gap-1 equivalent */
}

/* Item Styling */
:deep(.el-menu-item) {
    height: auto !important; /* Allow flex height */
    line-height: normal !important;
    padding: 10px 12px !important; /* px-3 py-2.5 equivalent */
    margin: 0 !important;
    border-radius: 0.5rem; /* rounded-lg */
    color: var(--text-secondary);
    background-color: transparent;
    transition: all 0.2s ease;
}

:deep(.dark .el-menu-item) {
    color: #9ca3af; /* gray-400 */
}

/* Hover State */
:deep(.el-menu-item:hover) {
    background-color: #f9fafb !important; /* bg-gray-50 */
    color: var(--text-secondary) !important; /* Keep secondary on hover unless active */
}
:deep(.dark .el-menu-item:hover) {
    background-color: rgba(31, 41, 55, 0.5) !important; /* gray-800/50 */
    color: #9ca3af !important;
}

/* Active State - Primary Light Background */
:deep(.el-menu-item.is-active) {
    background-color: rgba(59, 130, 246, 0.1) !important; /* primary/10 */
    color: var(--primary-color) !important; /* text-primary */
}
:deep(.dark .el-menu-item.is-active) {
    color: #93c5fd !important; /* blue-300 */
}

/* Fix Icon Styles inside template */
:deep(.material-symbols-outlined) {
    font-size: 24px;
    /* transition: color 0.2s; */
}
:deep(.el-menu-item.is-active .material-symbols-outlined.filled) {
    font-variation-settings: 'FILL' 1;
}

/* User Card */
.user-card:hover {
    background-color: #f9fafb;
}
:deep(.dark .user-card:hover) {
    background-color: rgba(31, 41, 55, 0.5);
}
</style>
