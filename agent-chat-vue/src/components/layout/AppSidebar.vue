<template>
  <aside class="sidebar-container" :class="{ collapsed: ui.sidebarCollapsed }">
    <!-- Header -->
    <div class="sidebar-header">
      <div class="brand-row">
        <div class="logo-wrapper">
          <span class="material-symbols-outlined text-primary icon-xl-24">all_inclusive</span>
        </div>
        <h1 class="brand-title">AI Nexus</h1>
      </div>

      <el-tooltip content="Toggle sidebar" placement="right">
        <el-button text class="collapse-btn" @click="ui.toggleSidebarCollapsed">
          <span class="material-symbols-outlined icon-lg-20">{{ ui.sidebarCollapsed ? 'chevron_right' : 'chevron_left' }}</span>
        </el-button>
      </el-tooltip>
    </div>

    <!-- Scrollable Menu -->
    <div class="menu-scroll-area">
      <!-- We wrap el-menu to make it behave like the original nav list -->
      <el-menu
        :default-active="activeRoute"
        class="custom-menu"
        :router="true"
        :ellipsis="false" 
      >
        <el-menu-item index="/">
          <template #title>
             <div class="menu-item-content">
                <span class="material-symbols-outlined filled" :class="{ 'text-primary': activeRoute === '/', 'text-text-secondary': activeRoute !== '/' }">dashboard</span>
                <span class="font-medium">Dashboard</span>
             </div>
          </template>
        </el-menu-item>
        
        <el-menu-item index="/chat">
          <template #title>
             <div class="menu-item-content">
                <span class="material-symbols-outlined">chat</span>
                <span class="font-medium">Chat Space</span>
             </div>
          </template>
        </el-menu-item>

        <el-menu-item index="/agents">
           <template #title>
              <div class="menu-item-content">
                 <span class="material-symbols-outlined">smart_toy</span>
                 <span class="font-medium">Agents</span>
              </div>
           </template>
        </el-menu-item>

         <el-menu-item index="/audit">
            <template #title>
              <div class="menu-item-content">
                 <span class="material-symbols-outlined" :class="{ 'filled': activeRoute === '/audit' }">article</span>
                 <span class="font-medium">Audit</span>
              </div>
           </template>
         </el-menu-item>
 
         <el-menu-item index="/finance-docs">
           <template #title>
             <div class="menu-item-content">
               <span class="material-symbols-outlined" :class="{ 'filled': activeRoute === '/finance-docs' }">monitor</span>
               <span class="font-medium">Knowledge Base</span>
             </div>
           </template>
         </el-menu-item>

         <el-menu-item index="/analytics" disabled>
           <template #title>
             <div class="menu-item-content opacity-60">
               <span class="material-symbols-outlined">analytics</span>
               <span class="font-medium">Analytics</span>
             </div>
           </template>
         </el-menu-item>

        <!-- Divider & Subheader -->
        <div class="menu-divider"></div>
        <p class="menu-section-title">Settings</p>

        <el-menu-item index="/settings/general" disabled>
            <template #title>
             <div class="menu-item-content opacity-60">
                <span class="material-symbols-outlined">settings</span>
                <span class="font-medium">General</span>
             </div>
           </template>
        </el-menu-item>

        <el-menu-item index="/settings/api" disabled>
            <template #title>
             <div class="menu-item-content opacity-60">
                <span class="material-symbols-outlined">api</span>
                <span class="font-medium">API Keys</span>
             </div>
           </template>
        </el-menu-item>
      </el-menu>
    </div>

    <!-- Footer -->
    <div class="sidebar-footer">
      <div class="user-card">
        <div class="user-avatar"></div>
        <div class="user-info">
          <p class="user-name">Alex Morgan</p>
          <p class="user-email">alex@nexus.ai</p>
        </div>
        <span class="material-symbols-outlined text-text-secondary icon-lg-20">unfold_more</span>
      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useUiStore } from '@/stores/ui'

const route = useRoute()
const ui = useUiStore()
const activeRoute = computed(() => {
  const p = route.path
  if (p.startsWith('/agents')) return '/agents'
  return p
})
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

.sidebar-container {
    width: 256px; /* w-64 */
    height: 100%;
    background-color: var(--bg-primary); /* bg-surface-light */
    display: flex;
    flex-direction: column;
    border-right: 1px solid var(--border-color);
    z-index: 20;
    flex-shrink: 0;
    transition: background-color 0.3s, border-color 0.3s;
}

.sidebar-container.collapsed {
    width: 76px;
}
:deep(.dark .sidebar-container) {
    background-color: var(--bg-secondary); /* bg-surface-dark */
    border-right-color: #1f2937; /* border-gray-800 */
}

.sidebar-header {
    padding: 24px; /* p-6 */
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px; /* gap-3 */
}

.brand-row {
    display: flex;
    align-items: center;
    gap: 12px;
    min-width: 0;
}

.collapse-btn {
    border-radius: 10px;
    padding: 6px 8px;
    color: var(--text-secondary);
}

:deep(.collapse-btn:hover) {
    background: rgba(0, 0, 0, 0.04);
}

:deep(.dark .collapse-btn:hover) {
    background: rgba(255, 255, 255, 0.08);
}

.sidebar-container.collapsed .brand-title {
    display: none;
}

.logo-wrapper {
    background-color: rgba(99, 102, 241, 0.1); /* primary/10 */
    border-radius: 8px; /* rounded-lg */
    padding: 8px; /* p-2 */
    display: flex;
    align-items: center;
    justify-content: center;
}

.brand-title {
    color: var(--text-primary);
    font-size: 18px; /* text-lg */
    font-weight: 700; /* font-bold */
    letter-spacing: -0.025em; /* tracking-tight */
    margin: 0;
}
:deep(.dark .brand-title) {
    color: white;
}

.menu-scroll-area {
    flex: 1;
    overflow-y: auto;
    padding: 0 16px; /* px-4 */
    display: flex;
    flex-direction: column;
    gap: 8px; /* gap-2 */
}

.sidebar-container.collapsed .menu-scroll-area {
    padding: 0 10px;
}

.sidebar-container.collapsed .menu-divider,
.sidebar-container.collapsed .menu-section-title {
    display: none;
}

.sidebar-container.collapsed .menu-item-content {
    justify-content: center;
    gap: 0;
}

.sidebar-container.collapsed .menu-item-content .font-medium {
    display: none;
}

.sidebar-container.collapsed :deep(.el-menu-item) {
    padding: 12px 10px !important;
}

.custom-menu {
    border: none !important;
    background-color: transparent !important;
    width: 100%;
}

.menu-item-content {
    display: flex;
    align-items: center;
    gap: 12px; /* gap-3 */
    width: 100%;
}

.menu-item-content.opacity-60 {
    opacity: 0.6;
}

.menu-divider {
    margin: 8px 0; /* my-2 */
    border-top: 1px solid var(--border-color);
    pointer-events: none;
}
:deep(.dark .menu-divider) {
    border-top-color: #1f2937; /* gray-800 */
}

.menu-section-title {
    padding: 0 12px; /* px-3 */
    font-size: 12px; /* text-xs */
    font-weight: 600; /* font-semibold */
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.05em; /* tracking-wider */
    margin-bottom: 4px; /* mb-1 */
    margin-top: 8px; /* mt-2 */
    pointer-events: none;
}
:deep(.dark .menu-section-title) {
    color: #6b7280; /* gray-500 */
}

.sidebar-footer {
    padding: 16px; /* p-4 */
    border-top: 1px solid var(--border-color);
}

.sidebar-container.collapsed .sidebar-footer {
    padding: 12px;
}

.sidebar-container.collapsed .user-info,
.sidebar-container.collapsed .icon-lg-20 {
    display: none;
}

.sidebar-container.collapsed .user-card {
    justify-content: center;
    padding: 10px;
}
:deep(.dark .sidebar-footer) {
    border-top-color: #1f2937; /* gray-800 */
}

.user-card {
    display: flex;
    align-items: center;
    gap: 12px; /* gap-3 */
    padding: 8px; /* p-2 */
    border-radius: 8px; /* rounded-lg */
    cursor: pointer;
    transition: background-color 0.15s;
}

.user-avatar {
    width: 32px; /* size-8 */
    height: 32px;
    border-radius: 9999px; /* rounded-full */
    background: linear-gradient(to top right, #60a5fa, #6366f1); /* from-blue-400 to-indigo-500 */
}

.user-info {
    flex: 1;
    min-width: 0;
}

.user-name {
    font-size: 14px; /* text-sm */
    font-weight: 500;
    color: var(--text-primary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    margin: 0;
}
:deep(.dark .user-name) {
    color: white;
}

.user-email {
    font-size: 12px; /* text-xs */
    color: var(--text-secondary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    margin: 0;
}
:deep(.dark .user-email) {
    color: #9ca3af; /* gray-400 */
}

.icon-xl-24 {
    font-size: 24px !important;
}

.icon-lg-20 {
    font-size: 20px !important;
}

</style>
