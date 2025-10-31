import { defineStore } from 'pinia'
import { getSystemInfo } from '@/api/cp'

export const useAppStore = defineStore('app', {
  state: () => ({
    online: false as boolean,
    system: null as any,
    notification: { title: '', text: '', type: 'success' as 'success'|'info'|'warning'|'error' },
    fullscreenEditor: false as boolean
  }),
  actions: {
    async refresh() {
      try {
        const resp = await getSystemInfo()
        this.system = resp?.data || null
        this.online = true
      } catch {
        this.online = false
      }
    },
    setFullscreenEditor(v: boolean) {
      this.fullscreenEditor = !!v
    },
    toast(title: string, text: string, type: 'success'|'info'|'warning'|'error'='success') {
      this.notification = { title, text, type }
      setTimeout(() => { this.notification = { title: '', text: '', type: 'success' } }, 10)
    }
  }
})

