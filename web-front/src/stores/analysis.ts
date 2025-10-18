import { defineStore } from 'pinia'
import { dataProvider } from '@/api/dataProvider'
import { getSystemInfo } from '@/api/cp'

type SourceItem = { id: string; name?: string; uri?: string; status?: string; caps?: any }
type ModelItem = { id: string; task?: string; family?: string; variant?: string; path?: string }
type GraphItem = { graph_id: string; name?: string; requires?: any }
type PipelineItem = { name: string; status?: string; fps?: number; input_fps?: number; alerts?: number }

function randomFps() { return (22 + Math.random() * 6).toFixed(1) }
function randomLatency() { return Math.round(32 + Math.random() * 12) }

export const useAnalysisStore = defineStore('analysis', {
  state: () => ({
    loading: false,
    sources: [] as SourceItem[],
    models: [] as ModelItem[],
    pipelines: [] as PipelineItem[],
    graphs: [] as GraphItem[],
    currentSourceId: '' as string,
    currentModelUri: '' as string,
    currentPipeline: '' as string,
    currentGraphId: '' as string,
    autoPlay: (localStorage.getItem('va_autoplay') ?? 'on') !== 'off',
    analyzing: false,
    whepUrl: '' as string,
    whepBase: '' as string,
    stats: { fps: '0.0', p95: '0', alerts: 0 } as { fps: string; p95: string; alerts: number }
  }),
  getters: {
    currentSource(state) {
      return state.sources.find(s => s.id === state.currentSourceId) || null
    },
    currentModel(state) {
      return state.models.find(m => m.id === state.currentModelUri) || null
    },
    currentGraph(state) {
      return state.graphs.find(g => g.graph_id === state.currentGraphId) || null
    }
  },
  actions: {
    async bootstrap() {
      if (this.sources.length || this.loading) return
      this.loading = true
      try {
        const [sysResp, sourcesResp, modelsResp, pipelinesResp, graphsResp] = await Promise.all([
          getSystemInfo().catch(() => ({ data: {} } as any)),
          dataProvider.listSources(),
          dataProvider.listModels?.() ?? Promise.resolve({ items: [] }),
          dataProvider.listPipelines?.() ?? Promise.resolve({ items: [] }),
          (dataProvider as any).listGraphs?.() ?? Promise.resolve({ items: [] })
        ])
        const sysData = (sysResp as any).data || {}
        this.whepBase = (sysData.sfu?.whep_base || '').toString()
        this.sources = (sourcesResp as any).data ?? (sourcesResp as any).items ?? (sourcesResp as any) ?? []
        this.models = ((modelsResp as any).data ?? (modelsResp as any).items ?? []) as ModelItem[]
        this.pipelines = ((pipelinesResp as any).data ?? (pipelinesResp as any).items ?? []) as PipelineItem[]
        this.graphs = ((graphsResp as any).data ?? (graphsResp as any).items ?? []) as GraphItem[]
        if (this.sources.length) {
          const run = this.sources.find(s => (s as any).status === 'Running')
          this.setSource((run?.id) || this.sources[0].id)
        }
        if (this.pipelines.length) {
          this.currentPipeline = this.pipelines[0].name
        }
        if (this.graphs.length) {
          this.currentGraphId = this.graphs[0].graph_id
        }
        if (this.models.length) {
          this.currentModelUri = this.models[0].id
        }
        this.refreshStats()
        if (this.autoPlay && !this.analyzing) {
          await this.startAnalysis()
        }
      } finally {
        this.loading = false
      }
    },
    setSource(id: string) {
      this.currentSourceId = id
      this.updateWhepUrl()
      this.refreshStats()
    },
    setModel(id: string) {
      this.currentModelUri = id
      this.refreshStats()
    },
    setPipeline(name: string) {
      this.currentPipeline = name
      this.updateWhepUrl()
      this.refreshStats()
    },
    setGraph(id: string) {
      this.currentGraphId = id
      this.refreshStats()
    },
    updateWhepUrl() {
      // 优先使用后端回传的 whep_base；为空时退回到 API 基址
      const apiBase = ((import.meta as any).env?.VITE_API_BASE || '').toString()
      const base = (this.whepBase || apiBase || '').replace(/\/+$/, '')
      if (base && this.currentSourceId && this.currentPipeline) {
        this.whepUrl = `${base}/whep?stream=${encodeURIComponent(this.currentSourceId)}:${encodeURIComponent(this.currentPipeline)}`
      } else {
        this.whepUrl = this.currentSourceId ? `mock://whep/${this.currentSourceId}` : ''
      }
    },
    setAutoPlay(v: boolean){ this.autoPlay = v; localStorage.setItem('va_autoplay', v ? 'on' : 'off') },
    setAnalyzing(v: boolean) {
      this.analyzing = v
      this.refreshStats()
    },
    async startAnalysis() {
      const pf = await this.preflight()
      if (!pf.ok) {
        this.setAnalyzing(false)
        return pf
      }
      try {
        const src = this.sources.find(s => s.id === this.currentSourceId)
        const profile = this.currentPipeline
        const uri = src?.uri || ''
        const model = this.currentModelUri || undefined
        // 调用 CP 创建会话
        // @ts-ignore
        if (typeof window !== 'undefined') { const mod = await import('@/api/cp'); await mod.subscribePipeline(this.currentSourceId, profile, uri, model) }
        this.setAnalyzing(true)
        return { ok: true } as const
      } catch (e:any) {
        this.setAnalyzing(false)
        return { ok:false, reasons:[ e?.message || 'subscribe failed' ] } as any
      }
    },
    async stopAnalysis() {
      try {
        const profile = this.currentPipeline
        // @ts-ignore
        if (typeof window !== 'undefined') { const mod = await import('@/api/cp'); await mod.unsubscribePipeline(this.currentSourceId, profile) }
      } catch (e) {}
      this.setAnalyzing(false)
    },
    async hotswapModel(id: string) {
      this.setModel(id)
    },
    async preflight() {
      try {
        const src = this.sources.find(s => s.id === this.currentSourceId)
        const graph = this.graphs.find(g => g.graph_id === this.currentGraphId)
        const pf = await (dataProvider as any).preflightCheck?.({ source: src, graph })
        if (pf) return pf
      } catch (e) {}
      return { ok: true, reasons: [] }
    },
    refreshStats() {
      const pipeline = this.pipelines.find(p => p.name === this.currentPipeline)
      const fps = this.analyzing ? (pipeline?.fps ?? Number(randomFps())) : 0
      const p95 = this.analyzing ? randomLatency() : 0
      const alerts = this.analyzing ? (pipeline?.alerts ?? Math.floor(Math.random() * 3)) : 0
      this.stats = { fps: fps.toString(), p95: p95.toString(), alerts }
    }
  }
})
