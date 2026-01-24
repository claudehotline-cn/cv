<template>
  <div class="h-screen overflow-hidden flex bg-background-light dark:bg-background-dark font-display text-text-main antialiased">
    <!-- Sidebar -->
    <!-- Sidebar -->
    <AppSidebar />

    <!-- Main Content -->
    <main class="flex-1 flex flex-col h-full relative overflow-hidden">
      <!-- Top Navbar -->
      <header class="bg-surface-light dark:bg-surface-dark border-b border-border-color dark:border-gray-800 h-16 flex items-center justify-between px-8 flex-shrink-0 z-10">
        <div class="flex items-center gap-6">
          <h2 class="text-lg font-bold text-text-main dark:text-white">Operations</h2>
          <div class="h-6 w-px bg-border-color dark:bg-gray-700"></div>
          <div class="flex items-center gap-2 text-sm">
            <span class="text-text-secondary dark:text-gray-400">Project:</span>
            <button class="flex items-center gap-1 font-medium text-text-main dark:text-white hover:text-primary transition-colors">
              Core Platform V2
              <span class="material-symbols-outlined" style="font-size: 18px;">expand_more</span>
            </button>
          </div>
        </div>
        <div class="flex items-center gap-4">
          <el-input 
            v-model="searchQuery"
            placeholder="Search agents, logs, or metrics..." 
            class="w-64 search-input"
            :prefix-icon="Search"
          />
          <el-button class="icon-only-btn notification-btn" circle>
            <el-icon :size="20"><Bell /></el-icon>
            <span class="absolute top-2 right-2 size-2 bg-red-500 rounded-full border-2 border-white dark:border-gray-800"></span>
          </el-button>
          <el-button type="primary" class="new-agent-btn">
            <el-icon class="mr-2" :size="18"><Plus /></el-icon>
            New Agent
          </el-button>
        </div>
      </header>

      <!-- Scrollable Dashboard Content -->
      <div class="flex-1 overflow-y-auto p-8">
        <div class="max-w-[1400px] mx-auto flex flex-col gap-6">
          <!-- Metrics Grid -->
          <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            <!-- Metric 1 -->
            <div class="bg-surface-light dark:bg-surface-dark rounded-xl p-5 border border-border-color dark:border-gray-800 shadow-card hover:shadow-md transition-shadow">
              <div class="flex justify-between items-start mb-4">
                <p class="text-text-secondary dark:text-gray-400 text-sm font-medium">Total Agent Executions</p>
                <span class="bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 text-xs font-bold px-2 py-1 rounded-full flex items-center gap-1">
                  <span class="material-symbols-outlined" style="font-size: 14px;">trending_up</span>
                  12%
                </span>
              </div>
              <p class="text-3xl font-extrabold text-text-main dark:text-white tracking-tight">24,592</p>
              <p class="text-xs text-text-secondary dark:text-gray-500 mt-2">vs. 21,940 last week</p>
            </div>
            <!-- Metric 2 -->
            <div class="bg-surface-light dark:bg-surface-dark rounded-xl p-5 border border-border-color dark:border-gray-800 shadow-card hover:shadow-md transition-shadow">
              <div class="flex justify-between items-start mb-4">
                <p class="text-text-secondary dark:text-gray-400 text-sm font-medium">Active Users</p>
                <span class="bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 text-xs font-bold px-2 py-1 rounded-full flex items-center gap-1">
                  <span class="material-symbols-outlined" style="font-size: 14px;">trending_up</span>
                  5%
                </span>
              </div>
              <p class="text-3xl font-extrabold text-text-main dark:text-white tracking-tight">3,400</p>
              <p class="text-xs text-text-secondary dark:text-gray-500 mt-2">vs. 3,230 last week</p>
            </div>
            <!-- Metric 3 -->
            <div class="bg-surface-light dark:bg-surface-dark rounded-xl p-5 border border-border-color dark:border-gray-800 shadow-card hover:shadow-md transition-shadow">
              <div class="flex justify-between items-start mb-4">
                <p class="text-text-secondary dark:text-gray-400 text-sm font-medium">Avg. Response Time</p>
                <span class="bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 text-xs font-bold px-2 py-1 rounded-full flex items-center gap-1">
                  <span class="material-symbols-outlined" style="font-size: 14px;">trending_down</span>
                  0.3s
                </span>
              </div>
              <p class="text-3xl font-extrabold text-text-main dark:text-white tracking-tight">1.2s</p>
              <p class="text-xs text-text-secondary dark:text-gray-500 mt-2">Optimized for Llama 3</p>
            </div>
            <!-- Metric 4 -->
            <div class="bg-surface-light dark:bg-surface-dark rounded-xl p-5 border border-border-color dark:border-gray-800 shadow-card hover:shadow-md transition-shadow">
              <div class="flex justify-between items-start mb-4">
                <p class="text-text-secondary dark:text-gray-400 text-sm font-medium">Cost this Month</p>
                <span class="bg-red-50 dark:bg-red-900/30 text-red-600 dark:text-red-400 text-xs font-bold px-2 py-1 rounded-full flex items-center gap-1">
                  <span class="material-symbols-outlined" style="font-size: 14px;">trending_up</span>
                  8%
                </span>
              </div>
              <p class="text-3xl font-extrabold text-text-main dark:text-white tracking-tight">$4,250</p>
              <p class="text-xs text-text-secondary dark:text-gray-500 mt-2">Projected $5,100</p>
            </div>
          </div>

          <!-- Bento Grid Content -->
          <div class="grid grid-cols-1 lg:grid-cols-12 gap-6">
            <!-- Chart Section (Spans 8 cols) -->
            <div class="lg:col-span-8 flex flex-col gap-6">
              <!-- Main Line Chart -->
              <div class="bg-surface-light dark:bg-surface-dark rounded-xl border border-border-color dark:border-gray-800 shadow-card p-6 flex flex-col h-full min-h-[400px]">
                <div class="flex justify-between items-center mb-6">
                  <div>
                    <h3 class="text-lg font-bold text-text-main dark:text-white">System Activity</h3>
                    <p class="text-sm text-text-secondary dark:text-gray-400">Token usage across models (Last 7 Days)</p>
                  </div>
                  <div class="flex items-center gap-4">
                    <div class="flex items-center gap-2">
                      <span class="size-2 rounded-full bg-primary"></span>
                      <span class="text-xs font-medium text-text-secondary dark:text-gray-400">GPT-4</span>
                    </div>
                    <div class="flex items-center gap-2">
                      <span class="size-2 rounded-full bg-teal-400"></span>
                      <span class="text-xs font-medium text-text-secondary dark:text-gray-400">Claude 3</span>
                    </div>
                    <div class="flex items-center gap-2">
                      <span class="size-2 rounded-full bg-indigo-400"></span>
                      <span class="text-xs font-medium text-text-secondary dark:text-gray-400">Llama 3</span>
                    </div>
                    <button class="ml-2 p-1 text-text-secondary hover:text-primary rounded">
                      <span class="material-symbols-outlined" style="font-size: 20px;">more_horiz</span>
                    </button>
                  </div>
                </div>
                <div class="flex-1 w-full relative">
                  <svg class="w-full h-full overflow-visible" preserveAspectRatio="none" viewBox="0 0 800 300">
                    <defs>
                      <linearGradient id="grid-fade" x1="0" x2="0" y1="0" y2="1">
                        <stop offset="0%" stop-color="#e2e8f0" stop-opacity="1"></stop>
                        <stop offset="100%" stop-color="#e2e8f0" stop-opacity="0.1"></stop>
                      </linearGradient>
                    </defs>
                    <!-- Grid Lines -->
                    <g class="chart-grid opacity-30">
                      <line stroke-dasharray="4 4" x1="0" x2="800" y1="250" y2="250"></line>
                      <line stroke-dasharray="4 4" x1="0" x2="800" y1="190" y2="190"></line>
                      <line stroke-dasharray="4 4" x1="0" x2="800" y1="130" y2="130"></line>
                      <line stroke-dasharray="4 4" x1="0" x2="800" y1="70" y2="70"></line>
                      <line stroke-dasharray="4 4" x1="0" x2="800" y1="10" y2="10"></line>
                    </g>
                    <!-- Data Lines -->
                    <!-- GPT-4 (Primary Blue) -->
                    <path d="M0,200 C50,180 100,210 150,150 S250,50 350,80 S450,120 550,60 S650,20 800,40" fill="none" stroke="#3267a4" stroke-linecap="round" stroke-width="3"></path>
                    <circle cx="150" cy="150" fill="white" r="4" stroke="#3267a4" stroke-width="2"></circle>
                    <circle cx="350" cy="80" fill="white" r="4" stroke="#3267a4" stroke-width="2"></circle>
                    <circle cx="550" cy="60" fill="white" r="4" stroke="#3267a4" stroke-width="2"></circle>
                    <!-- Claude (Teal) -->
                    <path d="M0,240 C60,230 120,220 200,200 S300,180 400,150 S550,130 650,110 S750,90 800,80" fill="none" stroke="#2dd4bf" stroke-linecap="round" stroke-width="3"></path>
                    <!-- Llama 3 (Indigo) -->
                    <path d="M0,220 C40,240 100,230 180,240 S280,210 380,220 S500,180 600,190 S700,160 800,170" fill="none" stroke="#818cf8" stroke-dasharray="6 4" stroke-linecap="round" stroke-width="3"></path>
                  </svg>
                </div>
                <div class="flex justify-between mt-4 text-xs font-bold text-text-secondary dark:text-gray-500 uppercase tracking-wider">
                  <span>Mon</span>
                  <span>Tue</span>
                  <span>Wed</span>
                  <span>Thu</span>
                  <span>Fri</span>
                  <span>Sat</span>
                  <span>Sun</span>
                </div>
              </div>

              <!-- Pie Chart & Stats Row -->
              <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                <!-- Category Distribution -->
                <div class="bg-surface-light dark:bg-surface-dark rounded-xl border border-border-color dark:border-gray-800 shadow-card p-6">
                  <h3 class="text-lg font-bold text-text-main dark:text-white mb-6">Agent Categories</h3>
                  <div class="flex items-center gap-6">
                    <div class="relative size-32 flex-shrink-0">
                      <svg class="w-full h-full -rotate-90" viewBox="0 0 36 36">
                        <!-- Background -->
                        <circle class="dark:stroke-gray-800" cx="18" cy="18" fill="none" r="15.915" stroke="#f1f5f9" stroke-width="5"></circle>
                        <!-- Automation (45%) -->
                        <circle class="transition-all duration-1000" cx="18" cy="18" fill="none" r="15.915" stroke="#3267a4" stroke-dasharray="45, 100" stroke-width="5"></circle>
                        <!-- Creative (30%) - Starts at 45% -->
                        <circle cx="18" cy="18" fill="none" r="15.915" stroke="#2dd4bf" stroke-dasharray="30, 100" stroke-dashoffset="-45" stroke-width="5"></circle>
                        <!-- Data (25%) -->
                        <circle cx="18" cy="18" fill="none" r="15.915" stroke="#818cf8" stroke-dasharray="25, 100" stroke-dashoffset="-75" stroke-width="5"></circle>
                      </svg>
                      <div class="absolute inset-0 flex items-center justify-center flex-col">
                        <span class="text-2xl font-bold text-text-main dark:text-white">124</span>
                        <span class="text-[10px] text-text-secondary uppercase">Agents</span>
                      </div>
                    </div>
                    <div class="flex flex-col gap-3 flex-1">
                      <div class="flex justify-between items-center">
                        <div class="flex items-center gap-2">
                          <span class="size-2 rounded-full bg-primary"></span>
                          <span class="text-sm text-text-secondary dark:text-gray-300">Automation</span>
                        </div>
                        <span class="text-sm font-bold text-text-main dark:text-white">45%</span>
                      </div>
                      <div class="flex justify-between items-center">
                        <div class="flex items-center gap-2">
                          <span class="size-2 rounded-full bg-teal-400"></span>
                          <span class="text-sm text-text-secondary dark:text-gray-300">Creative</span>
                        </div>
                        <span class="text-sm font-bold text-text-main dark:text-white">30%</span>
                      </div>
                      <div class="flex justify-between items-center">
                        <div class="flex items-center gap-2">
                          <span class="size-2 rounded-full bg-indigo-400"></span>
                          <span class="text-sm text-text-secondary dark:text-gray-300">Data</span>
                        </div>
                        <span class="text-sm font-bold text-text-main dark:text-white">25%</span>
                      </div>
                    </div>
                  </div>
                </div>

                <!-- Quick Actions / Mini Stats -->
                <div class="bg-gradient-to-br from-primary to-[#2A5494] rounded-xl shadow-card p-6 text-white flex flex-col justify-between">
                  <div>
                    <div class="flex items-center gap-2 mb-2 opacity-80">
                      <span class="material-symbols-outlined" style="font-size: 20px;">bolt</span>
                      <span class="text-sm font-medium uppercase tracking-wide">System Health</span>
                    </div>
                    <h3 class="text-2xl font-bold mb-1">99.9% Uptime</h3>
                    <p class="text-sm opacity-80">All systems operational. No major incidents reported in the last 24h.</p>
                  </div>
                  <div class="mt-4 pt-4 border-t border-white/20 grid grid-cols-2 gap-4">
                    <div>
                      <p class="text-xs opacity-70 uppercase">Error Rate</p>
                      <p class="text-lg font-bold">0.02%</p>
                    </div>
                    <div>
                      <p class="text-xs opacity-70 uppercase">Queue Depth</p>
                      <p class="text-lg font-bold">12ms</p>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- Right Column: Logs (Spans 4 cols) -->
            <div class="lg:col-span-4 flex flex-col h-full">
              <div class="bg-surface-light dark:bg-surface-dark rounded-xl border border-border-color dark:border-gray-800 shadow-card flex flex-col h-full">
                <div class="p-5 border-b border-border-color dark:border-gray-800 flex justify-between items-center">
                  <h3 class="text-lg font-bold text-text-main dark:text-white">Recent Logs</h3>
                  <button class="text-xs font-semibold text-primary hover:text-blue-700 transition-colors">View All</button>
                </div>
                <div class="flex-1 overflow-y-auto p-4 flex flex-col gap-1 relative">
                  <!-- Timeline vertical line -->
                  <div class="absolute left-[34px] top-6 bottom-6 w-[2px] bg-gray-100 dark:bg-gray-800 z-0"></div>
                  <!-- Log Item 1: Error -->
                  <div class="relative z-10 flex gap-4 p-3 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors group cursor-pointer">
                    <div class="flex flex-col items-center pt-1">
                      <div class="size-3 rounded-full bg-red-500 border-2 border-white dark:border-gray-700 shadow-sm ring-2 ring-red-100 dark:ring-red-900/30"></div>
                    </div>
                    <div class="flex-1 min-w-0">
                      <div class="flex justify-between items-start mb-0.5">
                        <p class="text-sm font-semibold text-text-main dark:text-white truncate pr-2">Connection Timeout</p>
                        <span class="text-[11px] text-text-secondary whitespace-nowrap">10:42 AM</span>
                      </div>
                      <p class="text-xs text-text-secondary line-clamp-2">Agent-007 failed to handshake with VectorDB cluster. Retrying in 5s...</p>
                      <span class="inline-flex mt-2 items-center px-2 py-0.5 rounded text-[10px] font-medium bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-400">Error</span>
                    </div>
                  </div>
                  <!-- Log Item 2: Info -->
                  <div class="relative z-10 flex gap-4 p-3 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors group cursor-pointer">
                    <div class="flex flex-col items-center pt-1">
                      <div class="size-3 rounded-full bg-blue-500 border-2 border-white dark:border-gray-700 shadow-sm"></div>
                    </div>
                    <div class="flex-1 min-w-0">
                      <div class="flex justify-between items-start mb-0.5">
                        <p class="text-sm font-semibold text-text-main dark:text-white truncate pr-2">Batch Processing</p>
                        <span class="text-[11px] text-text-secondary whitespace-nowrap">10:40 AM</span>
                      </div>
                      <p class="text-xs text-text-secondary line-clamp-2">Successfully processed 1,200 documents for ingest.</p>
                      <span class="inline-flex mt-2 items-center px-2 py-0.5 rounded text-[10px] font-medium bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400">Info</span>
                    </div>
                  </div>
                  <!-- Log Item 3: Warning -->
                  <div class="relative z-10 flex gap-4 p-3 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors group cursor-pointer">
                    <div class="flex flex-col items-center pt-1">
                      <div class="size-3 rounded-full bg-amber-500 border-2 border-white dark:border-gray-700 shadow-sm"></div>
                    </div>
                    <div class="flex-1 min-w-0">
                      <div class="flex justify-between items-start mb-0.5">
                        <p class="text-sm font-semibold text-text-main dark:text-white truncate pr-2">High Latency</p>
                        <span class="text-[11px] text-text-secondary whitespace-nowrap">10:38 AM</span>
                      </div>
                      <p class="text-xs text-text-secondary line-clamp-2">Vector DB query latency &gt; 500ms detected in eu-west-1 region.</p>
                      <span class="inline-flex mt-2 items-center px-2 py-0.5 rounded text-[10px] font-medium bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">Warning</span>
                    </div>
                  </div>
                  <!-- Log Item 4: Success -->
                  <div class="relative z-10 flex gap-4 p-3 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors group cursor-pointer">
                    <div class="flex flex-col items-center pt-1">
                      <div class="size-3 rounded-full bg-green-500 border-2 border-white dark:border-gray-700 shadow-sm"></div>
                    </div>
                    <div class="flex-1 min-w-0">
                      <div class="flex justify-between items-start mb-0.5">
                        <p class="text-sm font-semibold text-text-main dark:text-white truncate pr-2">Agent Deployment</p>
                        <span class="text-[11px] text-text-secondary whitespace-nowrap">10:15 AM</span>
                      </div>
                      <p class="text-xs text-text-secondary line-clamp-2">Agent-009 'CreativeWriter' deployed to production successfully.</p>
                      <span class="inline-flex mt-2 items-center px-2 py-0.5 rounded text-[10px] font-medium bg-green-50 text-green-700 dark:bg-green-900/30 dark:text-green-400">Success</span>
                    </div>
                  </div>
                  <!-- Log Item 5: Info -->
                  <div class="relative z-10 flex gap-4 p-3 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors group cursor-pointer">
                    <div class="flex flex-col items-center pt-1">
                      <div class="size-3 rounded-full bg-blue-500 border-2 border-white dark:border-gray-700 shadow-sm"></div>
                    </div>
                    <div class="flex-1 min-w-0">
                      <div class="flex justify-between items-start mb-0.5">
                        <p class="text-sm font-semibold text-text-main dark:text-white truncate pr-2">API Key Rotation</p>
                        <span class="text-[11px] text-text-secondary whitespace-nowrap">09:55 AM</span>
                      </div>
                      <p class="text-xs text-text-secondary line-clamp-2">Scheduled rotation of internal service keys completed.</p>
                      <span class="inline-flex mt-2 items-center px-2 py-0.5 rounded text-[10px] font-medium bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400">Info</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { Search, Bell, Plus } from '@element-plus/icons-vue'
import AppSidebar from '@/components/layout/AppSidebar.vue'

const searchQuery = ref('')
</script>

<style scoped>
/* Dashboard Specific Deep Overrides for Element Plus */

/* Search Input */
:deep(.search-input .el-input__wrapper) {
    background-color: #f3f4f6; /* gray-100 */
    box-shadow: none;
    border-radius: 0.5rem; /* rounded-lg */
    padding-left: 10px;
}
:deep(.dark .search-input .el-input__wrapper) {
    background-color: #1f2937; /* gray-800 */
}
:deep(.search-input .el-input__wrapper.is-focus) {
    box-shadow: 0 0 0 2px rgba(50, 103, 164, 0.2); /* primary/20 ring */
    background-color: #ffffff;
}
:deep(.dark .search-input .el-input__wrapper.is-focus) {
    background-color: #374151; /* gray-700 */
}
:deep(.search-input .el-input__inner) {
    color: var(--text-main);
}

/* Notification Button */
:deep(.notification-btn) {
    width: 36px; /* size-9 */
    height: 36px;
    border-color: var(--border-color);
    background-color: #ffffff;
    color: var(--text-secondary);
    transition: all 0.15s ease;
}
:deep(.dark .notification-btn) {
    background-color: #1f2937; /* gray-800 */
    border-color: #374151; /* gray-700 */
}
:deep(.notification-btn:hover) {
    border-color: var(--primary-color);
    color: var(--primary-color);
    background-color: #ffffff;
}
:deep(.dark .notification-btn:hover) {
    background-color: #1f2937;
}

/* New Agent Button */
:deep(.new-agent-btn) {
    background-color: var(--primary-color);
    border-color: var(--primary-color);
    border-radius: 0.5rem; /* rounded-lg */
    font-weight: 500;
    box-shadow: 0 1px 2px 0 rgba(59, 130, 246, 0.3); /* shadow-blue-500/30 */
    padding: 8px 16px;
    height: auto;
}
:deep(.new-agent-btn:hover) {
    background-color: #1d4ed8; /* blue-700 */
    border-color: #1d4ed8;
}

/* Scrollbar customization if needed globally or per component */
::-webkit-scrollbar {
    width: 6px;
    height: 6px;
}
::-webkit-scrollbar-track {
    background: transparent;
}
::-webkit-scrollbar-thumb {
    background: #cbd5e1;
    border-radius: 3px;
}
::-webkit-scrollbar-thumb:hover {
    background: #94a3b8;
}
</style>
