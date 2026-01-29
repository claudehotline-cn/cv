<script setup lang="ts">
import { ref } from 'vue'
import {
  ArrowRight,
  Refresh,
  Edit,
  Delete,
	  Search,
	  View,
	  Coin,
	  Setting,
	  Document,
	  Share,
	  Connection
	} from '@element-plus/icons-vue'

// Custom icons or Material Symbols aliases if needed
// For now using Element Plus Icons

const chunks = ref([
  {
    id: '#001',
    tag: 'Executive Summary',
    tokens: 45,
    content: 'The company reported a 15% increase in Q3 revenue, driven largely by the successful launch of the new enterprise suite in the North American market. This marks the fourth consecutive quarter of double-digit growth.',
    isActive: true
  },
  {
    id: '#002',
    tag: 'Financials',
    tokens: 32,
    content: 'Operating expenses remained flat due to strategic cost-cutting measures implemented earlier in the fiscal year, specifically within the supply chain logistics division.',
    isActive: false
  },
  {
    id: '#003',
    tag: 'Risk Factors',
    tokens: 50,
    content: 'Risk factors include market volatility in the APAC region, pending regulatory changes in the EU regarding data privacy (GDPR 2.0), and potential currency fluctuations affecting international margins.',
    isActive: false
  },
  {
    id: '#004',
    tag: 'Conclusion',
    tokens: 28,
    content: 'The outlook for Q4 remains positive with projected bookings expected to exceed $50M. Management recommends maintaining the current investment strategy.',
    isActive: false
  }
])

const cleaningRules = ref({
  removeWhitespace: true,
  stripHtml: true,
  fixEncoding: false,
  consolidateShortParagraphs: true
})

const chunkingStrategy = ref({
  maxTokenLimit: 512,
  chunkOverlap: 20
})

const outline = [
  { label: '1. Executive Summary', icon: Document, active: true },
  { label: '1.1 Key Metrics', icon: Connection, indent: true },
  { label: '1.2 Strategic Goals', icon: Connection, indent: true },
  { label: '2. Revenue Streams', icon: Document },
  { label: '3. Risk Factors', icon: Document },
  { label: '3.1 Market Volatility', icon: Connection, indent: true },
  { label: '3.2 Compliance', icon: Connection, indent: true },
  { label: '4. Conclusion', icon: Document }
]
</script>

<template>
  <el-container class="editor-layout">
    <!-- Top Header -->
    <el-header class="editor-header">
      <div class="header-left">
        <div class="brand">
          <el-icon class="brand-icon"><Connection /></el-icon>
          <span class="brand-name">Knowledge Base Agent</span>
        </div>
        <div class="divider"></div>
        <el-breadcrumb :separator-icon="ArrowRight">
          <el-breadcrumb-item>Documents</el-breadcrumb-item>
          <el-breadcrumb-item class="active-crumb">Q3 Financial Report.pdf</el-breadcrumb-item>
        </el-breadcrumb>
      </div>
      <div class="header-right">
        <el-button plain class="btn-secondary">Exit Editor</el-button>
        <el-button type="primary" class="btn-primary">Deploy Agent</el-button>
        <el-avatar :size="36" class="user-avatar">AM</el-avatar>
      </div>
    </el-header>

    <el-container class="main-body">
      <!-- Left Sidebar: Outline -->
      <el-aside width="320px" class="outline-sidebar">
        <div class="doc-meta">
          <div class="doc-info-card">
            <div class="doc-icon">
              <el-icon><Document /></el-icon>
            </div>
            <div class="doc-details">
              <div class="doc-title">Q3 Financial Report.pdf</div>
              <div class="doc-sub">1.4 MB • English</div>
            </div>
          </div>
          <div class="doc-stats">
            <div class="stat-box">
              <span class="stat-label">Total Tokens</span>
              <span class="stat-value">14,500</span>
            </div>
            <div class="stat-box">
              <span class="stat-label">Chunks</span>
              <span class="stat-value">42</span>
            </div>
          </div>
        </div>

        <div class="outline-nav">
          <div class="nav-title">DOCUMENT OUTLINE</div>
          <el-scrollbar>
            <div class="nav-list">
              <div 
                v-for="item in outline" 
                :key="item.label" 
                class="nav-item"
                :class="{ active: item.active, indent: item.indent }"
              >
                <el-icon class="nav-icon"><component :is="item.icon" /></el-icon>
                <span>{{ item.label }}</span>
              </div>
            </div>
          </el-scrollbar>
        </div>
        
        <div class="sidebar-footer">
          Last synced: Today, 10:23 AM
        </div>
      </el-aside>

      <!-- Center: Editor -->
      <el-main class="editor-main">
        <div class="toolbar-sticky">
          <div class="toolbar-left">
            <span class="chunk-count">42 Chunks Generated</span>
            <div class="v-divider"></div>
            <el-button link type="primary" :icon="Refresh" class="regenerate-btn">Regenerate All</el-button>
          </div>
          <div class="toolbar-right">
            <el-button-group>
              <el-button plain :icon="Share" />
              <el-button plain :icon="Connection" />
            </el-button-group>
            <div class="v-divider"></div>
            <el-input
              placeholder="Find in chunks..."
              :prefix-icon="Search"
              class="chunk-search"
            />
          </div>
        </div>

        <div class="chunk-list">
          <div 
            v-for="chunk in chunks" 
            :key="chunk.id" 
            class="chunk-card"
            :class="{ active: chunk.isActive }"
          >
            <div class="chunk-header">
              <div class="header-info">
                <span class="chunk-id">{{ chunk.id }}</span>
                <el-tag size="small" effect="light" class="chunk-tag">{{ chunk.tag }}</el-tag>
              </div>
              <div class="header-actions">
                <div class="token-badge">
                  <el-icon><Coin /></el-icon>
                  {{ chunk.tokens }} Tokens
                </div>
                <el-button link :icon="Edit" />
                <el-button link :icon="Delete" class="delete-btn" />
              </div>
            </div>
            <div class="chunk-content">
              <el-input
                v-if="chunk.isActive"
                v-model="chunk.content"
                type="textarea"
                :rows="3"
                resize="none"
                class="content-editor"
              />
              <p v-else class="content-text">{{ chunk.content }}</p>
            </div>
          </div>

          <div class="load-more">
            <el-button round class="load-more-btn">
              Load More Chunks
              <el-icon class="el-icon--right"><ArrowRight /></el-icon>
            </el-button>
          </div>
        </div>
      </el-main>

      <!-- Right Sidebar: Rules -->
      <el-aside width="320px" class="rules-sidebar">
        <div class="sidebar-header-title">
          <el-icon color="#0d776e"><Setting /></el-icon>
          <span>Cleaning Rules</span>
        </div>

        <el-scrollbar class="rules-content">
          <div class="rule-section">
            <div class="section-title">TEXT FORMATTING</div>
            <div class="rule-item">
              <div class="rule-label">
                <div class="title">Remove Whitespace</div>
                <div class="desc">Trims excessive spaces and line breaks.</div>
              </div>
              <el-switch v-model="cleaningRules.removeWhitespace" />
            </div>
            <div class="rule-item">
              <div class="rule-label">
                <div class="title">Strip HTML Tags</div>
                <div class="desc">Removes all HTML markup tags.</div>
              </div>
              <el-switch v-model="cleaningRules.stripHtml" />
            </div>
            <div class="rule-item">
              <div class="rule-label">
                <div class="title">Fix Encoding</div>
                <div class="desc">Corrects garbled characters.</div>
              </div>
              <el-switch v-model="cleaningRules.fixEncoding" />
            </div>
          </div>

          <div class="h-divider"></div>

          <div class="rule-section">
            <div class="section-title">CHUNKING STRATEGY</div>
            <div class="slider-item">
              <div class="slider-label">
                <span>Max Token Limit</span>
                <el-tag size="small" type="primary" class="slider-value">{{ chunkingStrategy.maxTokenLimit }}</el-tag>
              </div>
              <el-slider v-model="chunkingStrategy.maxTokenLimit" :min="128" :max="2048" />
              <div class="slider-range">
                <span>128</span>
                <span>2048</span>
              </div>
            </div>
            <div class="slider-item">
              <div class="slider-label">
                <span>Chunk Overlap</span>
                <el-tag size="small" type="primary" class="slider-value">{{ chunkingStrategy.chunkOverlap }}%</el-tag>
              </div>
              <el-slider v-model="chunkingStrategy.chunkOverlap" :min="0" :max="50" />
              <div class="slider-range">
                <span>0%</span>
                <span>50%</span>
              </div>
            </div>
          </div>

          <div class="h-divider"></div>

          <div class="rule-section">
            <div class="section-title">ADVANCED</div>
            <div class="rule-item">
              <div class="rule-label">
                <div class="title">Consolidate Short Paragraphs</div>
              </div>
              <el-switch v-model="cleaningRules.consolidateShortParagraphs" />
            </div>
          </div>
        </el-scrollbar>

        <div class="rules-footer">
          <el-button type="primary" class="btn-save">Save Changes</el-button>
          <el-button plain class="btn-preview">
            <el-icon><View /></el-icon> Preview Result
          </el-button>
          <p class="reindex-note">Changes will require re-indexing.</p>
        </div>
      </el-aside>
    </el-container>
  </el-container>
</template>

<style scoped>
.editor-layout {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background-color: #f7f7f8;
  color: #2e3136;
  font-family: 'Inter', sans-serif;
}

/* Header */
.editor-header {
  height: 64px;
  background-color: #f8fcfb;
  border-bottom: 3px solid #dce2e5;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  flex-shrink: 0;
  z-index: 100;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #0e1b1a;
}

.brand-icon {
  font-size: 24px;
  color: #0d776e;
}

.brand-name {
  font-size: 18px;
  font-weight: 700;
  letter-spacing: -0.015em;
}

.divider {
  width: 1px;
  height: 24px;
  background-color: #dce2e5;
  margin: 0 8px;
}

.active-crumb {
  font-weight: 500;
  color: #2e3136;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.btn-primary {
  background-color: #0d776e;
  border-color: #0d776e;
  font-weight: 700;
}

.btn-primary:hover {
  background-color: #0a5f58;
  border-color: #0a5f58;
}

.btn-secondary {
  border-color: #dce2e5;
  color: #2e3136;
  font-weight: 500;
}

.user-avatar {
  background-color: #0d776e;
  color: white;
  font-weight: 600;
}

/* Main Body */
.main-body {
  flex: 1;
  overflow: hidden;
}

/* Left Sidebar */
.outline-sidebar {
  background-color: #edf0f1;
  border-right: 1px solid #dce2e5;
  display: flex;
  flex-direction: column;
}

.doc-meta {
  padding: 20px;
  border-bottom: 2px solid #dce2e5;
  background: rgba(237, 240, 241, 0.5);
}

.doc-info-card {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}

.doc-icon {
  width: 40px;
  height: 40px;
  background: white;
  border: 1px solid #dce2e5;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #ef4444;
  box-shadow: 0 1px 2px rgba(0,0,0,0.05);
}

.doc-title {
  font-size: 14px;
  font-weight: 700;
  color: #2e3136;
  margin-bottom: 4px;
}

.doc-sub {
  font-size: 12px;
  color: #6b7280;
}

.doc-stats {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.stat-box {
  background: white;
  padding: 10px;
  border-radius: 4px;
  border: 1px solid #dce2e5;
}

.stat-label {
  display: block;
  font-size: 11px;
  color: #9ca3af;
  margin-bottom: 4px;
}

.stat-value {
  font-size: 14px;
  font-weight: 600;
  color: #2e3136;
}

.outline-nav {
  flex: 1;
  padding: 16px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.nav-title {
  font-size: 11px;
  font-weight: 700;
  color: #9ca3af;
  letter-spacing: 0.05em;
  margin-bottom: 12px;
  padding: 0 8px;
}

.nav-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px;
  font-size: 14px;
  color: #4b5563;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}

.nav-item:hover {
  background-color: white;
  color: #2e3136;
  box-shadow: 0 1px 2px rgba(0,0,0,0.05);
}

.nav-item.active {
  background-color: white;
  color: #0d776e;
  font-weight: 500;
  border: 1px solid #dce2e5;
  box-shadow: 0 1px 2px rgba(0,0,0,0.05);
}

.nav-item.indent {
  padding-left: 20px;
}

.nav-icon {
  font-size: 18px;
}

.nav-item.indent .nav-icon {
  font-size: 16px;
  opacity: 0.5;
}

.sidebar-footer {
  padding: 16px;
  border-top: 1px solid #dce2e5;
  background: white;
  font-size: 11px;
  color: #9ca3af;
  text-align: center;
}

/* Editor Main */
.editor-main {
  flex: 1;
  padding: 0;
  background-color: #f7f7f8;
  display: flex;
  flex-direction: column;
}

.toolbar-sticky {
  position: sticky;
  top: 0;
  z-index: 10;
  background: rgba(247, 247, 248, 0.95);
  backdrop-filter: blur(4px);
  padding: 12px 24px;
  border-bottom: 1px solid #dce2e5;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.chunk-count {
  font-size: 14px;
  font-weight: 600;
  color: #374151;
}

.v-divider {
  width: 1px;
  height: 16px;
  background-color: #dce2e5;
}

.regenerate-btn {
  font-size: 12px;
  font-weight: 500;
  color: #0d776e;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.chunk-search {
  width: 180px;
}

:deep(.chunk-search .el-input__wrapper) {
  border-radius: 6px;
  box-shadow: 0 0 0 1px #dce2e5 inset;
}

/* Chunk List */
.chunk-list {
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: 900px;
  margin: 0 auto;
  width: 100%;
}

.chunk-card {
  background: white;
  border: 1px solid #dce2e5;
  border-radius: 6px;
  transition: all 0.2s;
  overflow: hidden;
}

.chunk-card:hover {
  border-color: rgba(13, 119, 110, 0.5);
  box-shadow: 0 2px 4px rgba(0,0,0,0.05);
}

.chunk-card.active {
  border-color: #0d776e;
  box-shadow: 0 4px 12px rgba(13, 119, 110, 0.08), 0 0 0 1px rgba(13, 119, 110, 0.2);
}

.chunk-header {
  padding: 8px 16px;
  background: rgba(249, 250, 251, 0.5);
  border-bottom: 1px solid #f3f4f6;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.chunk-card.active .chunk-header {
  background: rgba(13, 119, 110, 0.05);
  border-bottom-color: rgba(13, 119, 110, 0.1);
}

.chunk-id {
  font-family: monospace;
  font-size: 12px;
  font-weight: 700;
  color: #9ca3af;
  margin-right: 12px;
}

.chunk-card.active .chunk-id {
  color: #0d776e;
}

.chunk-tag {
  background-color: #f3f4f6;
  border: 1px solid #e5e7eb;
  color: #6b7280;
  font-weight: 700;
  font-size: 10px;
  padding: 0 8px;
}

.chunk-card.active .chunk-tag {
  background-color: rgba(13, 119, 110, 0.1);
  border-color: rgba(13, 119, 110, 0.2);
  color: #0d776e;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.token-badge {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  font-weight: 500;
  color: #6b7280;
  background: white;
  padding: 2px 8px;
  border-radius: 4px;
  border: 1px solid #dce2e5;
}

.chunk-content {
  padding: 16px;
}

.content-text {
  font-size: 14px;
  line-height: 1.6;
  color: #2e3136;
  margin: 0;
}

:deep(.content-editor .el-textarea__inner) {
  border: none;
  padding: 0;
  font-size: 14px;
  line-height: 1.6;
  color: #2e3136;
  background: transparent;
}

:deep(.content-editor .el-textarea__inner:focus) {
  box-shadow: none;
}

.delete-btn:hover {
  color: #ef4444 !important;
}

.load-more {
  display: flex;
  justify-content: center;
  margin-top: 16px;
  padding-bottom: 40px;
}

.load-more-btn {
  font-size: 12px;
  font-weight: 500;
  padding: 8px 20px;
  color: #6b7280;
  box-shadow: 0 1px 2px rgba(0,0,0,0.05);
}

/* Right Sidebar */
.rules-sidebar {
  background-color: #edf0f1;
  border-left: 1px solid #dce2e5;
  display: flex;
  flex-direction: column;
}

.sidebar-header-title {
  padding: 20px;
  background: #edf0f1;
  border-bottom: 1px solid #dce2e5;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 700;
}

.rules-content {
  flex: 1;
  padding: 20px;
}

.rule-section {
  margin-bottom: 24px;
}

.section-title {
  font-size: 11px;
  font-weight: 700;
  color: #9ca3af;
  letter-spacing: 0.05em;
  margin-bottom: 16px;
}

.rule-item {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
}

.rule-label .title {
  font-size: 14px;
  font-weight: 500;
  color: #2e3136;
  margin-bottom: 4px;
}

.rule-label .desc {
  font-size: 12px;
  color: #6b7280;
}

.h-divider {
  height: 1px;
  background-color: #dce2e5;
  margin: 24px 0;
}

.slider-item {
  margin-bottom: 24px;
}

.slider-label {
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
  font-size: 14px;
  font-weight: 500;
}

.slider-value {
  background-color: rgba(13, 119, 110, 0.1);
  color: #0d776e;
  border: none;
  font-weight: 700;
}

:deep(.el-slider__bar) {
  background-color: #0d776e;
}

:deep(.el-slider__button) {
  border-color: #0d776e;
}

.slider-range {
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  color: #9ca3af;
  margin-top: 4px;
}

.rules-footer {
  padding: 20px;
  background: white;
  border-top: 1px solid #dce2e5;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.btn-save {
  width: 100%;
  height: 40px;
  background-color: #0d776e;
  border-color: #0d776e;
  font-weight: 700;
  box-shadow: 0 4px 6px -1px rgba(13, 119, 110, 0.2);
}

.btn-preview {
  width: 100%;
  height: 40px;
  font-weight: 700;
  color: #2e3136;
}

.reindex-note {
  font-size: 10px;
  color: #9ca3af;
  text-align: center;
  margin: 0;
}

/* Switches color */
:deep(.el-switch.is-checked .el-switch__core) {
  background-color: #0d776e;
}
</style>
