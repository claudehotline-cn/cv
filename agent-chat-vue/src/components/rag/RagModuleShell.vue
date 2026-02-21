<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, type RouteLocationRaw } from 'vue-router'

type NavItem = {
  label: string
  icon: string
  to: RouteLocationRaw
}

type Props = {
  breadcrumb: string
  title: string
  searchPlaceholder: string
  primaryActionLabel: string
}

defineProps<Props>()

const search = defineModel<string>('search', { default: '' })
const emit = defineEmits<{ (e: 'primary'): void }>()

const route = useRoute()
const activePath = computed(() => route.path)
const activeKbId = computed(() => {
  const raw = route.query.kbId
  if (raw === undefined || raw === null) return null
  const s = String(raw).trim()
  return s ? s : null
})

function withKb(path: string): RouteLocationRaw {
  if (!activeKbId.value) return path
  return { path, query: { kbId: activeKbId.value } }
}

const navItems: NavItem[] = [
  { label: 'Dashboard', icon: 'dashboard', to: '/' },
  { label: 'Knowledge Base', icon: 'monitor', to: withKb('/finance-docs') },
  { label: 'Retrieval Lab', icon: 'science', to: withKb('/rag-eval') },
  { label: 'Datasets', icon: 'database', to: withKb('/rag/datasets') },
  { label: 'Benchmarks', icon: 'fact_check', to: withKb('/rag/benchmarks') },
  { label: 'Audit', icon: 'article', to: { path: '/audit', query: { agent: 'rag' } } },
]

function isActive(to: RouteLocationRaw) {
  const path = typeof to === 'string' ? to : (to as any)?.path
  if (!path) return false
  if (path === '/') return activePath.value === '/'
  return activePath.value.startsWith(String(path))
}
</script>

<template>
  <div class="rag-module">
    <aside class="sidebar">
      <div class="brand">
        <div class="mark" />
        <div class="brand-title">RAG Module</div>
      </div>

      <nav class="nav">
        <router-link
          v-for="item in navItems"
          :key="item.label"
          class="nav-item"
          :class="{ active: isActive(item.to) }"
          :to="item.to"
        >
          <span class="material-symbols-outlined nav-ico" :class="{ filled: isActive(item.to) }">{{ item.icon }}</span>
          <span class="nav-label">{{ item.label }}</span>
        </router-link>
      </nav>

      <div class="spacer" />

      <div class="hint">
        <div class="hint-title">Tip</div>
        <div class="hint-text">
          Datasets store eval cases per KB. Use Benchmarks to run them in batch.
        </div>
      </div>
    </aside>

    <main class="main">
      <header class="header">
        <div class="header-left">
          <div class="breadcrumb">{{ breadcrumb }}</div>
          <div class="page-title">{{ title }}</div>
        </div>

        <div class="header-right">
          <label class="search" aria-label="Search">
            <span class="material-symbols-outlined search-ico">search</span>
            <input v-model="search" class="search-input" :placeholder="searchPlaceholder" />
          </label>
          <button class="primary" type="button" @click="emit('primary')">
            <span class="material-symbols-outlined btn-ico">add</span>
            {{ primaryActionLabel }}
          </button>
        </div>
      </header>

      <div class="content">
        <slot />
      </div>
    </main>
  </div>
</template>

<style scoped>
.rag-module {
  --bg: #fafafa;
  --surface: #ffffff;
  --surface-2: #f8fafc;
  --border: #e2e8f0;
  --text: #0f172a;
  --muted: #94a3b8;
  --muted-2: #64748b;
  --primary: #146cf0;

  font-family: Manrope, var(--font-sans);
  background: var(--bg);
  color: var(--text);
  height: 100vh;
  display: grid;
  grid-template-columns: 280px 1fr;
  overflow: hidden;
}

.sidebar {
  background: var(--surface);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  min-height: 0;
}


.brand {
  height: 64px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 24px;
  border-bottom: 1px solid #f1f5f9;
}

.mark {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: var(--primary);
}

.brand-title {
  font-size: 18px;
  font-weight: 700;
}

.nav {
  padding: 24px 16px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  overflow: auto;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  height: 44px;
  padding: 0 12px;
  border-radius: 8px;
  color: var(--muted-2);
  text-decoration: none;
  font-weight: 600;
}

.nav-item:hover {
  background: #f8fafc;
  color: var(--text);
}

.nav-item.active {
  background: #f1f5f9;
  color: var(--primary);
  border-radius: 0 8px 8px 0;
}

.nav-ico {
  font-size: 20px;
  color: currentColor;
}

.nav-ico.filled {
  font-variation-settings: 'FILL' 1;
}

.nav-label {
  font-size: 13px;
}



.spacer {
  flex: 1;
}

.hint {
  margin: 0 16px 24px;
  padding: 16px;
  border-radius: 12px;
  background: var(--surface-2);
  border: 1px solid var(--border);
}

.hint-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--muted);
}

.hint-text {
  margin-top: 8px;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.45;
}

.main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
}

.header {
  height: 64px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 18px;
  gap: 12px;
}

.header-left {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.breadcrumb {
  font-size: 12px;
  font-weight: 700;
  color: var(--muted);
}

.page-title {
  font-size: 20px;
  font-weight: 800;
  color: var(--text);
}

.header-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.search {
  width: 260px;
  height: 40px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 14px;
  border-radius: 999px;
  background: var(--surface-2);
  border: 1px solid var(--border);
}

.search-ico {
  font-size: 18px;
  color: var(--muted);
}

.search-input {
  border: 0;
  outline: none;
  background: transparent;
  width: 100%;
  font-family: inherit;
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
}

.search-input::placeholder {
  color: var(--muted);
  font-weight: 600;
}

.primary {
  height: 40px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 0 16px;
  border: 0;
  border-radius: 999px;
  background: var(--primary);
  color: #ffffff;
  font-family: inherit;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}

.primary:hover {
  filter: brightness(0.97);
}

.btn-ico {
  font-size: 18px;
}

.content {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 32px;
}

@media (max-width: 980px) {
  .rag-module {
    grid-template-columns: 1fr;
  }
  .sidebar {
    display: none;
  }
  .content {
    padding: 18px;
  }
  .search {
    width: 220px;
  }
}

@media (max-width: 640px) {
  .search {
    display: none;
  }
  .page-title {
    font-size: 18px;
  }
}
</style>
