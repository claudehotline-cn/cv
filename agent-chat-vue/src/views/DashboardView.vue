<template>
  <el-container class="dashboard-container">
    <!-- Sidebar -->
    <el-aside width="auto">
      <AppSidebar />
    </el-aside>

    <!-- Main Content -->
    <el-container direction="vertical" class="main-content-container">
      <!-- Top Navbar -->
      <el-header class="dashboard-header">
        <div class="header-left">
          <h2 class="page-title">Operations</h2>
          <div class="header-divider"></div>
          <div class="project-selector">
            <span class="project-label">Project:</span>
            <el-dropdown trigger="click">
              <span class="el-dropdown-link project-dropdown-link">
                Core Platform V2
                <el-icon class="el-icon--right"><ArrowDown /></el-icon>
              </span>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item>Core Platform V2</el-dropdown-item>
                  <el-dropdown-item>Agent v1</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </div>
        <div class="header-right">
          <el-input 
            v-model="searchQuery"
            placeholder="Search agents, logs, or metrics..." 
            class="w-64 search-input"
            :prefix-icon="Search"
          />
          <el-button class="icon-only-btn notification-btn" circle>
            <el-icon :size="20"><Bell /></el-icon>
            <span class="notification-badge"></span>
          </el-button>
          <el-button type="primary" class="new-agent-btn">
            <el-icon class="mr-2" :size="18"><Plus /></el-icon>
            New Agent
          </el-button>
        </div>
      </el-header>

      <!-- Scrollable Dashboard Content -->
      <el-main class="dashboard-main">
        <div class="dashboard-content-wrapper">
          <!-- Metrics Grid -->
          <div class="metrics-grid">
            <!-- Metric 1 -->
            <el-card class="metric-card" shadow="hover" :body-style="{ padding: '1.25rem' }">
              <div class="metric-header">
                <p class="metric-label">Total Agent Executions</p>
                <span class="metric-badge success">
                  <span class="material-symbols-outlined icon-14">trending_up</span>
                  12%
                </span>
              </div>
              <p class="metric-value">24,592</p>
              <p class="metric-subtext">vs. 21,940 last week</p>
            </el-card>
            <!-- Metric 2 -->
            <el-card class="metric-card" shadow="hover" :body-style="{ padding: '1.25rem' }">
              <div class="metric-header">
                <p class="metric-label">Active Users</p>
                <span class="metric-badge success">
                  <span class="material-symbols-outlined icon-14">trending_up</span>
                  5%
                </span>
              </div>
              <p class="metric-value">3,400</p>
              <p class="metric-subtext">vs. 3,230 last week</p>
            </el-card>
            <!-- Metric 3 -->
            <el-card class="metric-card" shadow="hover" :body-style="{ padding: '1.25rem' }">
              <div class="metric-header">
                <p class="metric-label">Avg. Response Time</p>
                <span class="metric-badge success">
                  <span class="material-symbols-outlined icon-14">trending_down</span>
                  0.3s
                </span>
              </div>
              <p class="metric-value">1.2s</p>
              <p class="metric-subtext">Optimized for Llama 3</p>
            </el-card>
            <!-- Metric 4 -->
            <el-card class="metric-card" shadow="hover" :body-style="{ padding: '1.25rem' }">
              <div class="metric-header">
                <p class="metric-label">Cost this Month</p>
                <span class="metric-badge danger">
                  <span class="material-symbols-outlined icon-14">trending_up</span>
                  8%
                </span>
              </div>
              <p class="metric-value">$4,250</p>
              <p class="metric-subtext">Projected $5,100</p>
            </el-card>
          </div>

          <!-- Bento Grid Content -->
          <div class="bento-grid">
            <!-- Chart Section (Spans 8 cols) -->
            <div class="chart-section">
              <!-- Main Line Chart -->
              <el-card class="chart-card main-chart" shadow="hover" :body-style="{ padding: '1.5rem', flex: '1', display: 'flex', flexDirection: 'column' }">
                <div class="chart-card-header">
                  <div class="chart-title-group">
                    <h3 class="chart-title">System Activity</h3>
                    <p class="chart-subtitle">Token usage across models (Last 7 Days)</p>
                  </div>
                  <div class="chart-legend">
                    <div class="legend-item">
                      <span class="legend-dot primary"></span>
                      <span class="legend-label">GPT-4</span>
                    </div>
                    <div class="legend-item">
                      <span class="legend-dot teal"></span>
                      <span class="legend-label">Claude 3</span>
                    </div>
                    <div class="legend-item">
                      <span class="legend-dot indigo"></span>
                      <span class="legend-label">Llama 3</span>
                    </div>
                    <el-button class="chart-options-btn" text>
                      <span class="material-symbols-outlined icon-20">more_horiz</span>
                    </el-button>
                  </div>
                </div>
                  <div class="chart-svg-container">
                    <svg class="chart-svg" preserveAspectRatio="none" viewBox="0 0 800 300">
                      <defs>
                        <linearGradient id="grid-fade" x1="0" x2="0" y1="0" y2="1">
                        <stop offset="0%" stop-color="#e2e8f0" stop-opacity="1"></stop>
                        <stop offset="100%" stop-color="#e2e8f0" stop-opacity="0.1"></stop>
                      </linearGradient>
                    </defs>
                    <!-- Grid Lines -->
                    <g class="chart-grid">
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
                <div class="chart-x-axis">
                  <span>Mon</span>
                  <span>Tue</span>
                  <span>Wed</span>
                  <span>Thu</span>
                  <span>Fri</span>
                  <span>Sat</span>
                  <span>Sun</span>
                </div>
              </el-card>

              <!-- Pie Chart & Stats Row -->
              <div class="stats-row">
                <!-- Category Distribution -->
                <el-card class="chart-card pie-chart-card" shadow="hover" :body-style="{ padding: '1.5rem' }">
                  <h3 class="chart-title mb-6">Agent Categories</h3>
                  <div class="pie-chart-content">
                    <div class="pie-chart-wrapper">
                      <svg class="pie-svg" viewBox="0 0 36 36">
                        <!-- Background -->
                        <circle class="pie-bg" cx="18" cy="18" fill="none" r="15.915" stroke="#f1f5f9" stroke-width="5"></circle>
                        <!-- Automation (45%) -->
                        <circle class="pie-segment" cx="18" cy="18" fill="none" r="15.915" stroke="#3267a4" stroke-dasharray="45, 100" stroke-width="5"></circle>
                        <!-- Creative (30%) - Starts at 45% -->
                        <circle cx="18" cy="18" fill="none" r="15.915" stroke="#2dd4bf" stroke-dasharray="30, 100" stroke-dashoffset="-45" stroke-width="5"></circle>
                        <!-- Data (25%) -->
                        <circle cx="18" cy="18" fill="none" r="15.915" stroke="#818cf8" stroke-dasharray="25, 100" stroke-dashoffset="-75" stroke-width="5"></circle>
                      </svg>
                      <div class="pie-chart-overlay">
                        <span class="pie-value">124</span>
                        <span class="pie-label">Agents</span>
                      </div>
                    </div>
                    <div class="pie-legend">
                      <div class="legend-row">
                        <div class="legend-item">
                          <span class="legend-dot primary"></span>
                          <span class="legend-label">Automation</span>
                        </div>
                        <span class="legend-value">45%</span>
                      </div>
                      <div class="legend-row">
                        <div class="legend-item">
                          <span class="legend-dot teal"></span>
                          <span class="legend-label">Creative</span>
                        </div>
                        <span class="legend-value">30%</span>
                      </div>
                      <div class="legend-row">
                        <div class="legend-item">
                          <span class="legend-dot indigo"></span>
                          <span class="legend-label">Data</span>
                        </div>
                        <span class="legend-value">25%</span>
                      </div>
                    </div>
                  </div>
                </el-card>

                <!-- Quick Actions / Mini Stats -->
                <el-card class="chart-card mini-stats-card" shadow="hover" :body-style="{ padding: '1.5rem', flex: '1', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', background: 'transparent' }">
                  <div>
                    <div class="stats-header">
                      <span class="material-symbols-outlined icon-20">bolt</span>
                      <span class="stats-title">System Health</span>
                    </div>
                    <h3 class="stats-value-large">99.9% Uptime</h3>
                    <p class="stats-desc">All systems operational. No major incidents reported in the last 24h.</p>
                  </div>
                  <div class="stats-grid">
                    <div>
                      <p class="stats-sublabel">Error Rate</p>
                      <p class="stats-subvalue">0.02%</p>
                    </div>
                    <div>
                      <p class="stats-sublabel">Queue Depth</p>
                      <p class="stats-subvalue">12ms</p>
                    </div>
                  </div>
                </el-card>
              </div>
            </div>

            <!-- Right Column: Logs (Spans 4 cols) -->
            <div class="logs-section">
              <el-card class="chart-card logs-card" shadow="hover" :body-style="{ padding: '0px', flex: '1', display: 'flex', flexDirection: 'column', overflow: 'hidden' }">
                <template #header>
                  <div class="logs-header">
                    <h3 class="chart-title">Recent Logs</h3>
                    <el-button link type="primary" class="view-all-btn">View All</el-button>
                  </div>
                </template>
                <div class="logs-list">
                  <!-- Timeline vertical line -->
                  <div class="timeline-line"></div>
                  <!-- Log Item 1: Error -->
                  <div class="log-item">
                    <div class="log-icon-wrapper">
                      <div class="log-status-dot error"></div>
                    </div>
                    <div class="log-content">
                      <div class="log-meta">
                        <p class="log-title">Connection Timeout</p>
                        <span class="log-time">10:42 AM</span>
                      </div>
                      <p class="log-message">Agent-007 failed to handshake with VectorDB cluster. Retrying in 5s...</p>
                      <span class="log-badge error">Error</span>
                    </div>
                  </div>
                  <!-- Log Item 2: Info -->
                  <div class="log-item">
                    <div class="log-icon-wrapper">
                      <div class="log-status-dot info"></div>
                    </div>
                    <div class="log-content">
                      <div class="log-meta">
                        <p class="log-title">Batch Processing</p>
                        <span class="log-time">10:40 AM</span>
                      </div>
                      <p class="log-message">Successfully processed 1,200 documents for ingest.</p>
                      <span class="log-badge info">Info</span>
                    </div>
                  </div>
                  <!-- Log Item 3: Warning -->
                  <div class="log-item">
                    <div class="log-icon-wrapper">
                      <div class="log-status-dot warning"></div>
                    </div>
                    <div class="log-content">
                      <div class="log-meta">
                        <p class="log-title">High Latency</p>
                        <span class="log-time">10:38 AM</span>
                      </div>
                      <p class="log-message">Vector DB query latency &gt; 500ms detected in eu-west-1 region.</p>
                      <span class="log-badge warning">Warning</span>
                    </div>
                  </div>
                  <!-- Log Item 4: Success -->
                  <div class="log-item">
                    <div class="log-icon-wrapper">
                      <div class="log-status-dot success"></div>
                    </div>
                    <div class="log-content">
                      <div class="log-meta">
                        <p class="log-title">Agent Deployment</p>
                        <span class="log-time">10:15 AM</span>
                      </div>
                      <p class="log-message">Agent-009 'CreativeWriter' deployed to production successfully.</p>
                      <span class="log-badge success">Success</span>
                    </div>
                  </div>
                  <!-- Log Item 5: Info -->
                  <div class="log-item">
                    <div class="log-icon-wrapper">
                      <div class="log-status-dot info"></div>
                    </div>
                    <div class="log-content">
                      <div class="log-meta">
                        <p class="log-title">API Key Rotation</p>
                        <span class="log-time">09:55 AM</span>
                      </div>
                      <p class="log-message">Scheduled rotation of internal service keys completed.</p>
                      <span class="log-badge info">Info</span>
                    </div>
                  </div>
                </div>
              </el-card>
            </div>
          </div>
        </div>
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { Search, Bell, Plus, ArrowDown } from '@element-plus/icons-vue'
import AppSidebar from '@/components/layout/AppSidebar.vue'

const searchQuery = ref('')
</script>

<style scoped>
/* Dashboard Specific Deep Overrides for Element Plus */
.dashboard-container {
    --shadow-card: 0 1px 3px 0 rgba(0, 0, 0, 0.1), 0 1px 2px 0 rgba(0, 0, 0, 0.06);
    --shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
}


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
    color: var(--text-primary);
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
    border-color: var(--accent-primary);
    color: var(--accent-primary);
    background-color: #ffffff;
}
:deep(.dark .notification-btn:hover) {
    background-color: #1f2937;
}

/* New Agent Button */
:deep(.new-agent-btn) {
    background-color: var(--accent-primary);
    border-color: var(--accent-primary);
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

/* Card Overrides */
:deep(.el-card) {
    border-radius: 0.75rem; /* rounded-xl */
}
:deep(.el-card__header) {
    padding: 1.25rem; /* p-5 */
    border-bottom: 1px solid var(--border-color);
}
:deep(.dark .el-card__header) {
    border-bottom: 1px solid #1f2937; /* gray-800 */
}

.dashboard-header {
    background-color: var(--bg-primary);
    border-bottom: 1px solid var(--border-color);
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 32px;
    flex-shrink: 0;
    z-index: 10;
    height: 64px;
    --el-header-padding: 0 32px;
}

.dashboard-main {
    flex: 1;
    overflow-y: auto;
    padding: 32px !important;
}

.header-left {
    display: flex;
    align-items: center;
    gap: 24px;
}

.header-right {
    display: flex;
    align-items: center;
    gap: 16px;
}

.page-title {
    font-size: 18px;
    font-weight: 700;
    color: var(--text-primary);
}

.header-divider {
    height: 24px;
    width: 1px;
    background-color: var(--border-color);
}

.project-selector {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 14px;
}

.project-label {
    color: var(--text-secondary);
}

.project-dropdown-link {
    display: flex;
    align-items: center;
    gap: 4px;
    font-weight: 500;
    color: var(--text-primary);
    transition: color 0.15s;
    cursor: pointer;
}
.project-dropdown-link:hover {
    color: var(--accent-primary);
}

.dashboard-content-wrapper {
    max-width: 1400px;
    margin: 0 auto;
    display: flex;
    flex-direction: column;
    gap: 24px;
}

.metrics-grid {
    display: grid;
    grid-template-columns: repeat(1, minmax(0, 1fr));
    gap: 16px;
}
@media (min-width: 768px) {
    .metrics-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
}
@media (min-width: 1024px) {
    .metrics-grid {
        grid-template-columns: repeat(4, minmax(0, 1fr));
    }
}

:deep(.metric-card) {
    border-radius: 12px;
    border: none;
    background-color: var(--bg-primary);
    box-shadow: var(--shadow-card);
    transition: box-shadow 0.3s;
}
:deep(.dark .metric-card) {
    border: 1px solid var(--border-color);
}

:deep(.metric-card:hover) {
    box-shadow: var(--shadow-md);
}

.metric-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 16px;
}

.metric-label {
    color: var(--text-secondary);
    font-size: 14px;
    font-weight: 500;
}
:deep(.dark .metric-label) {
    color: #9ca3af;
}

.metric-badge {
    font-size: 12px;
    font-weight: 700;
    padding: 4px 8px;
    border-radius: 9999px;
    display: flex;
    align-items: center;
    gap: 4px;
}

.metric-badge.success {
    background-color: #dcfce7; /* green-100 */
    color: #15803d; /* green-700 */
}
:deep(.dark .metric-badge.success) {
    background-color: rgba(21, 128, 61, 0.3);
    color: #4ade80; /* green-400 */
}

.metric-badge.danger {
    background-color: #fef2f2; /* red-50 */
    color: #dc2626; /* red-600 */
}
:deep(.dark .metric-badge.danger) {
    background-color: rgba(127, 29, 29, 0.3);
    color: #f87171; /* red-400 */
}

.metric-value {
    font-size: 30px;
    font-weight: 800;
    color: var(--text-primary);
    letter-spacing: -0.025em;
    line-height: 1;
}

.metric-subtext {
    font-size: 12px;
    color: var(--text-secondary);
    margin-top: 8px;
}

/* Bento Grid */
.bento-grid {
    display: grid;
    grid-template-columns: 1fr;
    gap: 24px;
}
@media (min-width: 1024px) {
    .bento-grid {
        grid-template-columns: repeat(12, minmax(0, 1fr));
    }
}

.chart-section {
    display: flex;
    flex-direction: column;
    gap: 24px;
}
@media (min-width: 1024px) {
    .chart-section {
        grid-column: span 8 / span 8;
    }
}

:deep(.chart-card) {
    border-radius: 12px;
    border: none !important;
    background-color: var(--bg-primary) !important;
    box-shadow: var(--shadow-card);
    transition: box-shadow 0.3s;
}
:deep(.dark .chart-card) {
    border: 1px solid var(--border-color) !important;
}
:deep(.chart-card.main-chart) {
    height: 100%;
    min-height: 400px;
}

.chart-card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 24px;
}

.chart-title {
    font-size: 18px;
    font-weight: 700;
    color: var(--text-primary);
}

.chart-subtitle {
    font-size: 14px;
    color: var(--text-secondary);
}

.chart-legend {
    display: flex;
    align-items: center;
    gap: 16px;
}

.legend-item {
    display: flex;
    align-items: center;
    gap: 8px;
}

.legend-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
}
.legend-dot.primary { background-color: var(--accent-primary); }
.legend-dot.teal { background-color: #2dd4bf; }
.legend-dot.indigo { background-color: #818cf8; }

.legend-label {
    font-size: 12px;
    font-weight: 500;
    color: var(--text-secondary);
}
:deep(.dark .legend-label) {
    color: #9ca3af;
}

.chart-options-btn {
    margin-left: 8px;
    padding: 4px !important;
    height: auto !important;
    color: var(--text-secondary) !important;
    border-radius: 4px;
}
.chart-options-btn:hover {
    color: var(--accent-primary) !important;
}

.chart-svg-container {
    flex: 1;
    width: 100%;
    position: relative;
}

.chart-x-axis {
    display: flex;
    justify-content: space-between;
    margin-top: 16px;
    font-size: 12px;
    font-weight: 700;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.05em;
}
:deep(.dark .chart-x-axis) {
    color: #6b7280;
}

.chart-svg {
    width: 100%;
    height: 100%;
    overflow: visible;
}

.chart-grid {
    opacity: 0.3;
}

.icon-14 {
    font-size: 14px !important;
}

.icon-20 {
    font-size: 20px !important;
}

/* Pie Chart & Stats */
.stats-row {
    display: grid;
    grid-template-columns: 1fr;
    gap: 24px;
}
@media (min-width: 768px) {
    .stats-row {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
}

.pie-chart-content {
    display: flex;
    align-items: center;
    gap: 24px;
}

.pie-chart-wrapper {
    position: relative;
    width: 128px; /* size-32 */
    height: 128px;
    flex-shrink: 0;
}

.pie-svg {
    width: 100%;
    height: 100%;
    transform: rotate(-90deg);
}

.pie-bg {
    stroke: #f1f5f9;
}
:deep(.dark .pie-bg) {
    stroke: #1f2937; /* gray-800 */
}

.pie-segment {
    transition-property: all;
    transition-timing-function: cubic-bezier(0.4, 0, 0.2, 1);
    transition-duration: 1000ms;
}

.pie-chart-overlay {
    position: absolute;
    inset: 0;
    display: flex;
    justify-content: center;
    align-items: center;
    flex-direction: column;
}

.pie-value {
    font-size: 24px;
    font-weight: 700;
    color: var(--text-primary);
}

.pie-label {
    font-size: 10px;
    color: var(--text-secondary);
    text-transform: uppercase;
}

.pie-legend {
    display: flex;
    flex-direction: column;
    gap: 12px;
    flex: 1;
}

.legend-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.legend-value {
    font-size: 14px;
    font-weight: 700;
    color: var(--text-main);
}
:deep(.dark .legend-value) {
    color: white;
}

.dashboard-container {
    height: 100vh;
    overflow: hidden;
    background-color: var(--el-bg-color-page);
    font-family: 'Inter', sans-serif; /* assuming font-display maps to Inter or similar */
    color: var(--text-primary);
    -webkit-font-smoothing: antialiased;
}

.main-content-container {
    flex: 1;
    height: 100%;
    position: relative;
    overflow: hidden;
}

.notification-badge {
    position: absolute;
    top: 8px; /* top-2 */
    right: 8px; /* right-2 */
    width: 8px; /* size-2 */
    height: 8px;
    background-color: #ef4444; /* red-500 */
    border-radius: 9999px; /* rounded-full */
    border: 2px solid white;
}
:deep(.dark .notification-badge) {
    border-color: #1f2937; /* gray-800 */
}

/* Mini Stats Card */
:deep(.mini-stats-card) {
    background: linear-gradient(to bottom right, var(--accent-primary), #2A5494) !important;
    color: white !important;
    border: none !important;
}

.stats-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 8px;
    opacity: 0.8;
}

.stats-title {
    font-size: 14px;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.025em;
}

.stats-value-large {
    font-size: 24px;
    font-weight: 700;
    margin-bottom: 4px;
}

.stats-desc {
    font-size: 14px;
    opacity: 0.8;
}

.stats-grid {
    margin-top: 16px;
    padding-top: 16px;
    border-top: 1px solid rgba(255, 255, 255, 0.2);
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 16px;
}

.stats-sublabel {
    font-size: 12px;
    opacity: 0.7;
    text-transform: uppercase;
}

.stats-subvalue {
    font-size: 18px;
    font-weight: 700;
}

/* Logs Section */
.logs-section {
    display: flex;
    flex-direction: column;
    height: 100%;
}
@media (min-width: 1024px) {
    .logs-section {
        grid-column: span 4 / span 4;
    }
}

.logs-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.view-all-btn {
    font-size: 12px !important;
    font-weight: 600 !important;
    padding: 0 !important;
    min-height: auto !important;
}

.logs-list {
    flex: 1;
    overflow-y: auto;
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 4px;
    position: relative;
}

.timeline-line {
    position: absolute;
    left: 34px;
    top: 24px;
    bottom: 24px;
    width: 2px;
    background-color: #f3f4f6;
    z-index: 0;
}
:deep(.dark .timeline-line) {
    background-color: #1f2937;
}

.log-item {
    position: relative;
    z-index: 10;
    display: flex;
    gap: 16px;
    padding: 12px;
    border-radius: 8px;
    transition: background-color 0.15s;
    cursor: pointer;
}
.log-item:hover {
    background-color: #f9fafb;
}
:deep(.dark .log-item:hover) {
    background-color: rgba(31, 41, 55, 0.5);
}

.log-icon-wrapper {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding-top: 4px;
}

.log-status-dot {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    border: 2px solid white;
    box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
}
:deep(.dark .log-status-dot) {
    border: 2px solid #374151;
}

.log-status-dot.error {
    background-color: #ef4444; /* red-500 */
    box-shadow: 0 0 0 2px #fee2e2;
}
:deep(.dark .log-status-dot.error) {
    box-shadow: 0 0 0 2px rgba(127, 29, 29, 0.3);
}

.log-status-dot.info {
    background-color: #3b82f6; /* blue-500 */
}

.log-status-dot.warning {
    background-color: #f59e0b; /* amber-500 */
}

.log-status-dot.success {
    background-color: #22c55e; /* green-500 */
}

.log-content {
    flex: 1;
    min-width: 0;
}

.log-meta {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 2px;
}

.log-title {
    font-size: 14px;
    font-weight: 600;
    color: var(--text-primary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    padding-right: 8px;
}

.log-time {
    font-size: 11px;
    color: var(--text-secondary);
    white-space: nowrap;
}

.log-message {
    font-size: 12px;
    color: var(--text-secondary);
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
}

.log-badge {
    display: inline-flex;
    margin-top: 8px;
    align-items: center;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 10px;
    font-weight: 500;
}

.log-badge.error {
    background-color: #fef2f2;
    color: #b91c1c;
}
:deep(.dark .log-badge.error) {
    background-color: rgba(127, 29, 29, 0.3);
    color: #f87171;
}

.log-badge.info {
    background-color: #eff6ff;
    color: #1d4ed8;
}
:deep(.dark .log-badge.info) {
    background-color: rgba(30, 58, 138, 0.3);
    color: #60a5fa;
}

.log-badge.warning {
    background-color: #fffbeb;
    color: #b45309;
}
:deep(.dark .log-badge.warning) {
    background-color: rgba(120, 53, 15, 0.3);
    color: #fbbf24;
}

.log-badge.success {
    background-color: #f0fdf4;
    color: #15803d;
}
:deep(.dark .log-badge.success) {
    background-color: rgba(20, 83, 45, 0.3);
    color: #4ade80;
}</style>
