import { defineStore } from 'pinia'

const STORAGE_KEY = 'ui.sidebarCollapsed'

function loadCollapsed(): boolean {
  if (typeof window === 'undefined') return false
  try {
    return window.localStorage.getItem(STORAGE_KEY) === '1'
  } catch {
    return false
  }
}

function persistCollapsed(v: boolean) {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(STORAGE_KEY, v ? '1' : '0')
  } catch {
    // ignore
  }
}

export const useUiStore = defineStore('ui', {
  state: () => ({
    sidebarCollapsed: loadCollapsed(),
  }),
  actions: {
    setSidebarCollapsed(v: boolean) {
      this.sidebarCollapsed = v
      persistCollapsed(v)
    },
    toggleSidebarCollapsed() {
      this.setSidebarCollapsed(!this.sidebarCollapsed)
    },
  },
})
