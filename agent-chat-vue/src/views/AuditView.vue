<template>
  <div class="h-screen overflow-hidden flex bg-background-light dark:bg-background-dark font-display text-text-main antialiased">
    <!-- Use same Sidebar as Dashboard for consistency or MainLayout if preferred, but for now copying Dashboard Sidebar structure for standalone view or re-using MainLayout? 
         Better: Route /audit to use MainLayout or standalone?
         Let's stick to the requested separate page. I'll include the sidebar to keep it looking integrated like Dashboard.
    -->
    <aside class="w-64 bg-surface-light dark:bg-surface-dark flex flex-col border-r border-border-color dark:border-gray-800 z-20 flex-shrink-0">
      <div class="p-6 flex items-center gap-3">
        <div class="bg-primary/10 rounded-lg p-2 flex items-center justify-center">
          <span class="material-symbols-outlined text-primary" style="font-size: 24px;">all_inclusive</span>
        </div>
        <h1 class="text-text-main dark:text-white text-lg font-bold tracking-tight">AI Nexus</h1>
      </div>
      <nav class="flex-1 px-4 flex flex-col gap-2 overflow-y-auto">
        <router-link to="/" class="flex items-center gap-3 px-3 py-2.5 rounded-lg text-text-secondary hover:bg-gray-50 dark:text-gray-400 dark:hover:bg-gray-800/50 transition-colors">
          <span class="material-symbols-outlined">dashboard</span>
          <span class="text-sm font-medium">Dashboard</span>
        </router-link>
        <router-link to="/chat" class="flex items-center gap-3 px-3 py-2.5 rounded-lg text-text-secondary hover:bg-gray-50 dark:text-gray-400 dark:hover:bg-gray-800/50 transition-colors">
          <span class="material-symbols-outlined">chat</span>
          <span class="text-sm font-medium">Chat Space</span>
        </router-link>
        <a href="#" class="flex items-center gap-3 px-3 py-2.5 rounded-lg text-text-secondary hover:bg-gray-50 dark:text-gray-400 dark:hover:bg-gray-800/50 transition-colors">
          <span class="material-symbols-outlined">smart_toy</span>
          <span class="text-sm font-medium">Agents</span>
        </a>
        <router-link to="/audit" class="flex items-center gap-3 px-3 py-2.5 rounded-lg bg-primary/10 text-primary dark:text-blue-300">
           <span class="material-symbols-outlined filled" style="font-variation-settings: 'FILL' 1;">article</span>
           <span class="text-sm font-semibold">Audit</span>
        </router-link>
        <a href="#" class="flex items-center gap-3 px-3 py-2.5 rounded-lg text-text-secondary hover:bg-gray-50 dark:text-gray-400 dark:hover:bg-gray-800/50 transition-colors">
          <span class="material-symbols-outlined">analytics</span>
          <span class="text-sm font-medium">Analytics</span>
        </a>
      </nav>
      <!-- Footer user profile -->
      <div class="p-4 border-t border-border-color dark:border-gray-800">
        <div class="flex items-center gap-3 p-2 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800/50 cursor-pointer transition-colors">
          <div class="size-8 rounded-full bg-gradient-to-tr from-blue-400 to-indigo-500"></div>
          <div class="flex-1 min-w-0">
            <p class="text-sm font-medium text-text-main dark:text-white truncate">Alex Morgan</p>
            <p class="text-xs text-text-secondary dark:text-gray-400 truncate">alex@nexus.ai</p>
          </div>
        </div>
      </div>
    </aside>

    <!-- Main Audit Content -->
    <main class="flex-1 flex flex-col h-full relative overflow-hidden">
        <header class="bg-surface-light dark:bg-surface-dark border-b border-border-color dark:border-gray-800 h-16 flex items-center justify-between px-8 flex-shrink-0 z-10">
            <div class="flex items-center gap-6">
                <h2 class="text-lg font-bold text-text-main dark:text-white">Audit Logs</h2>
            </div>
            <div class="flex items-center gap-4">
                 <input class="block w-64 pl-4 pr-3 py-2 border-none rounded-lg bg-gray-100 dark:bg-gray-800 text-sm placeholder-text-secondary focus:ring-2 focus:ring-primary/20 focus:bg-white dark:focus:bg-gray-700 transition-all" placeholder="Search logs..." type="text"/>
                 <button class="px-4 py-2 bg-white border border-border-color text-text-main text-sm font-medium rounded-lg hover:bg-gray-50 transition-colors">Export</button>
            </div>
        </header>
        
        <div class="flex-1 overflow-y-auto p-8">
            <div class="max-w-[1400px] mx-auto bg-surface-light dark:bg-surface-dark rounded-xl border border-border-color dark:border-gray-800 shadow-card">
                 <!-- Table Header -->
                 <div class="grid grid-cols-12 gap-4 p-4 border-b border-border-color dark:border-gray-800 text-xs font-semibold text-text-secondary uppercase tracking-wider bg-gray-50/50 dark:bg-gray-800/50">
                     <div class="col-span-2">Time</div>
                     <div class="col-span-2">Event Type</div>
                     <div class="col-span-2">Severity</div>
                     <div class="col-span-4">Description</div>
                     <div class="col-span-2">User/Agent</div>
                 </div>
                 
                 <!-- Table Body -->
                 <div class="divide-y divide-border-color dark:divide-gray-800">
                     <div v-for="(log, idx) in logs" :key="idx" class="grid grid-cols-12 gap-4 p-4 hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors items-center text-sm text-text-main dark:text-white">
                         <div class="col-span-2 text-text-secondary">{{ log.time }}</div>
                         <div class="col-span-2 font-medium">{{ log.type }}</div>
                         <div class="col-span-2">
                             <span 
                               :class="{
                                   'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400': log.severity === 'Success' || log.severity === 'Info',
                                   'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400': log.severity === 'Warning',
                                   'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400': log.severity === 'Error'
                               }"
                               class="px-2 py-0.5 rounded text-xs font-bold"
                             >{{ log.severity }}</span>
                         </div>
                         <div class="col-span-4 truncate" :title="log.description">{{ log.description }}</div>
                         <div class="col-span-2 flex items-center gap-2">
                             <div class="size-6 rounded bg-gray-200 dark:bg-gray-700 flex items-center justify-center text-[10px] font-bold">
                                 {{ log.initiator.substring(0,2).toUpperCase() }}
                             </div>
                             <span>{{ log.initiator }}</span>
                         </div>
                     </div>
                 </div>
            </div>
            
             <!-- Pagination Mock -->
             <div class="mt-6 flex justify-end gap-2">
                 <button class="px-3 py-1 border border-border-color rounded hover:bg-gray-50 dark:border-gray-700 dark:hover:bg-gray-800 text-sm">Previous</button>
                 <button class="px-3 py-1 bg-primary text-white rounded text-sm">1</button>
                 <button class="px-3 py-1 border border-border-color rounded hover:bg-gray-50 dark:border-gray-700 dark:hover:bg-gray-800 text-sm">2</button>
                 <button class="px-3 py-1 border border-border-color rounded hover:bg-gray-50 dark:border-gray-700 dark:hover:bg-gray-800 text-sm">Next</button>
             </div>
        </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const logs = ref([
    { time: '2023-10-24 10:42:05', type: 'Connection', severity: 'Error', description: 'Agent-007 failed to handshake with VectorDB cluster. Retrying in 5s...', initiator: 'System' },
    { time: '2023-10-24 10:40:12', type: 'Batch Job', severity: 'Info', description: 'Successfully processed 1,200 documents for ingest.', initiator: 'DataAgent' },
    { time: '2023-10-24 10:38:55', type: 'Performance', severity: 'Warning', description: 'Vector DB query latency > 500ms detected in eu-west-1 region.', initiator: 'Monitor' },
    { time: '2023-10-24 10:15:20', type: 'Deployment', severity: 'Success', description: 'Agent-009 "CreativeWriter" deployed to production successfully.', initiator: 'Alex Morgan' },
    { time: '2023-10-24 09:55:00', type: 'Security', severity: 'Info', description: 'Scheduled rotation of internal service keys completed.', initiator: 'KeyManager' },
    { time: '2023-10-24 09:30:11', type: 'Auth', severity: 'Success', description: 'User login from IP 192.168.1.1', initiator: 'Alex Morgan' },
    { time: '2023-10-24 08:00:00', type: 'System', severity: 'Info', description: 'Daily backup verification completed.', initiator: 'BackupSvc' },
])
</script>

<style scoped>
</style>
