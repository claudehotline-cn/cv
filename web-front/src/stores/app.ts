import { defineStore } from 'pinia'
import { cp } from '@/api/cp'

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
        const [runtime, summary] = await Promise.allSettled([
          cp.getVaRuntime(),
          cp.getMetricsSummary()
        ])
        const sys: any = {}
        if (runtime.status === 'fulfilled') sys.engine_runtime = runtime.value?.data || runtime.value
        if (summary.status === 'fulfilled') sys.metrics_summary = summary.value?.data || summary.value
        this.system = sys
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

