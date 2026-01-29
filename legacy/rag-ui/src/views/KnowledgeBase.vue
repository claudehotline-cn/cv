<script setup lang="ts">
import { ref } from 'vue'
import {
  Menu as IconMenu,
  Setting,
  Folder,
  Search,
  Bell,
  Upload,
  Files,
  Monitor,
  CheckCircle,
  DataAnalysis,
  Link as IconLink,
  Document,
  MoreFilled,
  Refresh,
  View,
  Grid
} from '@element-plus/icons-vue'

// Mock Data
const stats = ref([
  { label: 'Total Documents', value: '142' },
  { label: 'Total Tokens', value: '8.4M' },
  { label: 'Last Synced', value: '2h ago' }
])

const activeFilter = ref('All Types')
const filters = ['All Types', 'PDF', 'Spreadsheets']

const tableData = ref([
  {
    icon: Document,
    iconClass: 'icon-pdf',
    name: 'Q3_Financial_Report_Final.pdf',
    meta: '2.4 MB • PDF Document',
    date: 'Oct 24, 2023',
    status: 'Ready',
    statusType: 'success'
  },
  {
    icon: Document,
    iconClass: 'icon-word',
    name: 'Competitor_Analysis_2024.docx',
    meta: '1.1 MB • Word Document',
    date: 'Just now',
    status: 'Processing',
    statusType: 'warning'
  },
  {
    icon: IconLink,
    iconClass: 'icon-link',
    name: 'https://stripe.com/docs/api',
    meta: 'URL Scrape • External',
    date: 'Yesterday',
    status: 'Failed',
    statusType: 'danger'
  },
  {
    icon: DataAnalysis,
    iconClass: 'icon-csv',
    name: 'Q1-Q2_Raw_Data.csv',
    meta: '4.8 MB • CSV Spreadsheet',
    date: 'Oct 20, 2023',
    status: 'Ready',
    statusType: 'success'
  },
  {
    icon: Document,
    iconClass: 'icon-pdf',
    name: 'Employee_Handbook_v4.pdf',
    meta: '8.2 MB • PDF Document',
    date: 'Oct 18, 2023',
    status: 'Ready',
    statusType: 'success'
  }
])
</script>

<template>
  <el-container class="layout-container">
    <!-- Sidebar -->
    <el-aside width="280px" class="aside">
      <div class="brand">
        <div class="logo-box">
          <el-icon :size="20"><Monitor /></el-icon>
        </div>
        <span class="brand-text">Agent OS</span>
      </div>

      <div class="scroll-area">
        <el-menu class="custom-menu" default-active="3">
          <el-menu-item index="1">
            <el-icon><IconMenu /></el-icon>
            <span>Dashboard</span>
          </el-menu-item>
          <el-menu-item index="2">
            <el-icon><Monitor /></el-icon>
            <span>Agents</span>
          </el-menu-item>
          <el-menu-item index="3" class="is-active">
            <el-icon><Files /></el-icon>
            <span>Knowledge Base</span>
          </el-menu-item>
          <el-menu-item index="4">
            <el-icon><Setting /></el-icon>
            <span>Settings</span>
          </el-menu-item>
        </el-menu>

        <div class="collections">
          <div class="section-header">
            <span>COLLECTIONS</span>
            <el-button link type="primary" size="small">+</el-button>
          </div>
          <el-menu class="custom-menu collections-menu" default-active="finance">
             <el-menu-item index="all">
               <el-icon><Folder /></el-icon>
               <span>All Files</span>
             </el-menu-item>
             <!-- Active Collection -->
             <el-menu-item index="finance" class="collection-active">
               <el-icon color="#475569"><Folder /></el-icon>
               <span class="flex-1">Finance Docs</span>
               <span class="badge">24</span>
             </el-menu-item>
             <el-menu-item index="tech">
               <el-icon><Folder /></el-icon>
               <span>Tech Wiki</span>
             </el-menu-item>
             <el-menu-item index="hr">
               <el-icon><Folder /></el-icon>
               <span>HR Policies</span>
             </el-menu-item>
             <el-menu-item index="product">
               <el-icon><Folder /></el-icon>
               <span>Product Specs</span>
             </el-menu-item>
          </el-menu>
        </div>
      </div>

      <div class="storage-widget">
        <el-card shadow="never" class="storage-card">
          <div class="storage-info">
             <div class="storage-icon">
               <el-icon><Upload /></el-icon>
             </div>
             <div>
               <div class="storage-title">Vector Storage</div>
               <div class="storage-sub">4.5GB of 10GB used</div>
             </div>
          </div>
          <el-progress :percentage="45" :show-text="false" class="storage-progress" />
        </el-card>
      </div>
    </el-aside>

    <el-container>
      <!-- Header -->
      <el-header class="header">
        <div class="breadcrumbs">
          <el-breadcrumb separator="/">
            <el-breadcrumb-item>Knowledge Base</el-breadcrumb-item>
            <el-breadcrumb-item>Collections</el-breadcrumb-item>
            <el-breadcrumb-item>
              <span class="active-crumb">
                <el-icon><Folder /></el-icon> Finance Docs
              </span>
            </el-breadcrumb-item>
          </el-breadcrumb>
        </div>
        
        <div class="header-actions">
           <el-input 
             class="search-input" 
             placeholder="Search files..." 
             :prefix-icon="Search"
           />
           <div class="notification-btn">
             <el-badge is-dot class="item">
               <el-icon :size="20"><Bell /></el-icon>
             </el-badge>
           </div>
           <el-avatar :size="36" src="https://cube.elemecdn.com/0/88/03b0d39583f48206768a7534e55bcpng.png" />
        </div>
      </el-header>

      <!-- Main -->
      <el-main class="main-content">
        <div class="main-inner">
          <!-- Page Title -->
          <div class="page-title-row">
            <div>
              <h1>Finance Docs</h1>
              <p class="subtitle">Manage financial reports, quarterly reviews, and raw data for agent context.</p>
            </div>
            <div class="actions">
               <el-button-group>
                 <el-button :icon="View" />
                 <el-button :icon="Grid" />
               </el-button-group>
               <el-button type="primary" :icon="Upload">Upload Data</el-button>
            </div>
          </div>

          <!-- Stats -->
          <el-row :gutter="16" class="stats-row">
            <el-col :span="6" v-for="stat in stats" :key="stat.label">
              <el-card shadow="never" class="stat-card">
                <div class="stat-label">{{ stat.label }}</div>
                <div class="stat-value">{{ stat.value }}</div>
              </el-card>
            </el-col>
            <el-col :span="6">
              <el-card shadow="never" class="stat-card health-card">
                 <div class="health-bg"></div>
                 <div class="health-content">
                   <div class="health-label">
                     AGENT HEALTH <el-icon><CheckCircle /></el-icon>
                   </div>
                   <div class="health-desc">Data is vectorized & ready for queries.</div>
                 </div>
              </el-card>
            </el-col>
          </el-row>

          <!-- Main Table Card -->
          <el-card shadow="never" class="table-card" :body-style="{ padding: '0' }">
             <!-- Filter Bar -->
             <div class="filter-bar">
               <div class="filters">
                 <span>Filter by:</span>
                 <el-check-tag 
                   v-for="f in filters" 
                   :key="f" 
                   :checked="activeFilter === f" 
                   @change="activeFilter = f" 
                   class="custom-tag"
                 >
                   {{ f }}
                 </el-check-tag>
               </div>
               <span class="count">Showing 5 of 142 items</span>
             </div>

             <!-- Table -->
             <el-table :data="tableData" style="width: 100%" class="custom-table" header-row-class-name="table-header">
                <el-table-column label="DOCUMENT NAME" min-width="300">
                  <template #default="{ row }">
                     <div class="doc-cell">
                       <div class="icon-box" :class="row.iconClass">
                         <el-icon><component :is="row.icon" /></el-icon>
                       </div>
                       <div>
                         <div class="doc-name">{{ row.name }}</div>
                         <div class="doc-meta">{{ row.meta }}</div>
                       </div>
                     </div>
                  </template>
                </el-table-column>
                <el-table-column prop="date" label="DATE UPLOADED" width="150" />
                <el-table-column label="VECTOR STATUS" width="180">
                  <template #default="{ row }">
                    <el-tag :type="row.statusType" effect="light" round class="status-tag">
                      <el-icon v-if="row.status === 'Processing'" class="is-loading"><Refresh /></el-icon>
                      <el-icon v-else-if="row.status === 'Failed'"><DataAnalysis /></el-icon>
                      <el-icon v-else><CheckCircle /></el-icon>
                      {{ row.status }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="ACTIONS" width="200" align="right">
                  <template #default="{ row }">
                    <div class="action-buttons">
                      <el-button v-if="row.status === 'Failed'" size="small" type="danger" plain :icon="Refresh">Retry</el-button>
                      <el-button v-else size="small" plain>Segments</el-button>
                      <el-button size="small" text :icon="MoreFilled" />
                    </div>
                  </template>
                </el-table-column>
             </el-table>
          </el-card>

          <!-- Footer Banner -->
          <div class="footer-banner">
             <div class="banner-content">
               <div class="banner-icon"><el-icon><DataAnalysis /></el-icon></div>
               <div>
                 <h3>Need help structuring your data?</h3>
                 <p>Read our guide on optimal chunking strategies.</p>
               </div>
             </div>
             <el-button class="banner-btn">Read Guide</el-button>
          </div>

        </div>
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@200..800&display=swap');

/* Global Variables Override */
.layout-container {
  height: 100vh;
  font-family: 'Manrope', sans-serif;
  color: #0f172a;
  background-color: #fafafa;
}

/* Sidebar */
.aside {
  background: #ffffff;
  border-right: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
}
.brand {
  height: 64px;
  display: flex;
  align-items: center;
  padding: 0 24px;
  gap: 12px;
  border-bottom: 1px solid #f1f5f9;
}
.logo-box {
  width: 32px;
  height: 32px;
  background: #146cf0;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
}
.brand-text {
  font-weight: 700;
  font-size: 18px;
  letter-spacing: -0.02em;
}

.scroll-area {
  flex: 1;
  overflow-y: auto;
  padding: 24px 16px;
  display: flex;
  flex-direction: column;
  gap: 32px;
}

/* Menu Customization */
:deep(.el-menu) {
  border-right: none;
  background: transparent;
}
:deep(.el-menu-item) {
  height: 44px;
  line-height: 44px;
  border-radius: 8px;
  margin-bottom: 4px;
  color: #64748b;
  font-weight: 500;
}
:deep(.el-menu-item:hover) {
  background-color: #f8fafc;
  color: #0f172a;
}
:deep(.el-menu-item.is-active) {
  background-color: rgba(20, 108, 240, 0.05);
  color: #146cf0;
  font-weight: 700;
}
:deep(.el-sub-menu__title:hover) {
  background-color: #f8fafc;
}

.collections .section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 12px;
  font-size: 12px;
  font-weight: 700;
  color: #94a3b8;
  margin-bottom: 8px;
}

.collection-active {
  background-color: #f1f5f9 !important;
  color: #0f172a !important; 
  border-left: 3px solid #146cf0;
  border-radius: 0 8px 8px 0;
  margin-left: -16px; /* Breakout left */
  padding-left: 29px !important;
}

.badge {
  background: white;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 11px;
  border: 1px solid #e2e8f0;
  color: #64748b;
}

/* Storage Widget */
.storage-widget {
  padding: 16px;
  background: #f8fafc;
  border-top: 1px solid #e2e8f0;
}
.storage-card {
  border-radius: 12px;
  border: 1px solid #e2e8f0;
}
.storage-info {
  display: flex;
  gap: 12px;
  margin-bottom: 12px;
}
.storage-icon {
  background: #e0e7ff;
  color: #4f46e5;
  padding: 8px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.storage-title {font-size: 14px; font-weight: 700;}
.storage-sub {font-size: 12px; color: #64748b;}
:deep(.el-progress-bar__inner) { background-color: #146cf0; }

/* Header */
.header {
  background: #ffffff;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 32px;
}
.active-crumb {
  display: flex;
  align-items: center;
  gap: 6px;
  background: #f1f5f9;
  padding: 4px 8px;
  border-radius: 4px;
  font-weight: 600;
  color: #0f172a;
}
.header-actions {
  display: flex;
  align-items: center;
  gap: 16px;
}
.search-input { width: 250px; }
:deep(.el-input__wrapper) {
  background: #f8fafc;
  box-shadow: none;
  border: 1px solid transparent;
}
:deep(.el-input__wrapper:hover) { border-color: #e2e8f0; }
:deep(.el-input__wrapper.is-focus) { 
  background: white; 
  box-shadow: 0 0 0 1px #146cf0; 
}

/* Main Content */
.main-content {
  padding: 32px;
  background: #fafafa;
}
.main-inner {
  max-width: 1200px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.page-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
h1 { font-size: 30px; font-weight: 800; margin: 0 0 4px 0; letter-spacing: -0.02em; }
.subtitle { color: #64748b; font-size: 16px; margin: 0; }

/* Stats */
.stat-card {
  border-radius: 12px;
  border: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  justify-content: center;
  height: 100%;
}
.stat-label { font-size: 12px; font-weight: 600; text-transform: uppercase; color: #64748b; margin-bottom: 4px; }
.stat-value { font-size: 24px; font-weight: 700; color: #0f172a; }

.health-card {
  background: #eef2ff;
  border: 1px solid #e0e7ff;
  position: relative;
  overflow: hidden;
}
.health-bg {
  position: absolute;
  top: -20px; right: -20px;
  width: 80px; height: 80px;
  background: #e0e7ff;
  opacity: 0.5;
  border-radius: 50%;
}
.health-label {
  color: #4f46e5;
  font-weight: 700;
  font-size: 12px;
  display: flex; align-items: center; gap: 4px;
}
.health-desc { font-size: 14px; font-weight: 500; color: #0f172a; }

/* Table Card */
.table-card {
  border-radius: 12px;
  border: 1px solid #e2e8f0;
  overflow: hidden;
}
.filter-bar {
  padding: 16px 24px;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.filters {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 14px;
  font-weight: 600;
  color: #64748b;
}
.custom-tag {
  background: white;
  border: 1px solid #e2e8f0;
  font-weight: 500;
  color: #0f172a;
  padding: 4px 12px;
}
.custom-tag.is-checked {
  background-color: white;
  border-color: #146cf0;
  color: #146cf0;
}
.count { font-size: 12px; color: #94a3b8; }

:deep(th.table-header) {
  background-color: #f8fafc !important;
  color: #64748b;
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 12px 0;
}
.doc-cell { display: flex; align-items: center; gap: 16px; }
.icon-box {
  width: 40px; height: 40px;
  border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  font-size: 20px;
}
.icon-pdf { background: #fef2f2; color: #ef4444; border: 1px solid #fee2e2; }
.icon-word { background: #eff6ff; color: #3b82f6; border: 1px solid #dbeafe; }
.icon-link { background: #f1f5f9; color: #64748b; border: 1px solid #e2e8f0; }
.icon-csv { background: #f0fdf4; color: #16a34a; border: 1px solid #dcfce7; }

.doc-name { font-weight: 700; color: #0f172a; font-size: 14px; }
.doc-meta { font-size: 12px; color: #64748b; }

.status-tag { 
  font-weight: 700; 
  display: inline-flex; 
  align-items: center; 
  gap: 6px; 
  border: none;
}
:deep(.el-tag--success) { background: #ecfdf5; color: #047857; }
:deep(.el-tag--warning) { background: #fffbeb; color: #b45309; }
:deep(.el-tag--danger) { background: #fff1f2; color: #be123c; }

/* Banner */
.footer-banner {
  background: linear-gradient(to right, #146cf0, #6366f1);
  border-radius: 12px;
  padding: 24px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  color: white;
  box-shadow: 0 10px 15px -3px rgba(99, 102, 241, 0.2);
}
.banner-content { display: flex; align-items: center; gap: 16px; }
.banner-icon {
  background: rgba(255,255,255,0.2);
  padding: 12px;
  border-radius: 8px;
}
.banner-content h3 { font-size: 18px; font-weight: 700; margin: 0; }
.banner-content p { color: #e0e7ff; margin: 0; font-size: 14px; }
.banner-btn {
  background: white;
  color: #146cf0;
  font-weight: 700;
  border: none;
}
</style>
