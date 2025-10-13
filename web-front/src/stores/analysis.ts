import { defineStore } from 'pinia'
import { dataProvider } from '@/api/dataProvider'

type SourceItem = { id: string; name?: string; uri?: string; phase?: string }
type ModelItem = { id: string; task?: string; family?: string; variant?: string; path?: string }
type PipelineItem = { name: string; status?: string; fps?: number; input_fps?: number; alerts?: number }

function randomFps() { return (22 + Math.random() * 6).toFixed(1) }
function randomLatency() { return Math.round(32 + Math.random() * 12) }

export const useAnalysisStore = defineStore('analysis', {
  state: () => ({
    loading: false,
    sources: [] as SourceItem[],
    models: [] as ModelItem[],
    pipelines: [] as PipelineItem[],
    currentSourceId: '' as string,
    currentModelUri: '' as string,
    currentPipeline: '' as string,
    analyzing: false,
    whepUrl: '' as string,
    stats: { fps: '0.0', p95: '0', alerts: 0 } as { fps: string; p95: string; alerts: number }
  }),
  getters: {
    currentSource(state) {
      return state.sources.find(s => s.id === state.currentSourceId) || null
    },
    currentModel(state) {
      return state.models.find(m => m.id === state.currentModelUri) || null
    }
  },
  actions: {
    async bootstrap() {
      if (this.sources.length || this.loading) return
      this.loading = true
      try {
        const [sourcesResp, modelsResp, pipelinesResp] = await Promise.all([
          dataProvider.listSources(),
          dataProvider.listModels?.() ?? Promise.resolve({ items: [] }),
          dataProvider.listPipelines?.() ?? Promise.resolve({ items: [] })
        ])
        this.sources = (sourcesResp as any).items ?? (sourcesResp as any) ?? []
        this.models = ((modelsResp as any).items ?? []) as ModelItem[]
        this.pipelines = ((pipelinesResp as any).items ?? []) as PipelineItem[]
        if (this.sources.length) {
          this.setSource(this.sources[0].id)
        }
        if (this.pipelines.length) {
          this.currentPipeline = this.pipelines[0].name
        }
        if (this.models.length) {
          this.currentModelUri = this.models[0].id
        }
        this.refreshStats()
      } finally {
        this.loading = false
      }
    },
    setSource(id: string) {
      this.currentSourceId = id
      this.whepUrl = id ? `mock://whep/${id}` : ''
      this.refreshStats()
    },
    setModel(id: string) {
      this.currentModelUri = id
      this.refreshStats()
    },
    setPipeline(name: string) {
      this.currentPipeline = name
      this.refreshStats()
    },
    setAnalyzing(v: boolean) {
      this.analyzing = v
      this.refreshStats()
    },
    async startAnalysis() {
      this.setAnalyzing(true)
    },
    async stopAnalysis() {
      this.setAnalyzing(false)
    },
    async hotswapModel(id: string) {
      this.setModel(id)
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
