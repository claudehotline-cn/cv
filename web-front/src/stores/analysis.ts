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
    currentSubId: '' as string,
    subPhase: '' as string,
    subProgress: 0 as number,
    _subSSE: null as EventSource | null,
    _subRetries: 0 as number,
    muteAutoStartUntil: 0 as number,
    stats: { fps: '0.0', p95: '0', alerts: 0 } as { fps: string; p95: string; alerts: number },
    errMsg: '' as string
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
          dataProvider.listSources().catch((e:any) => { this.errMsg = `sources 加载失败: ${e?.message||e}`; return { items: [] } }),
          (dataProvider.listModels?.() ?? Promise.resolve({ items: [] })).catch((e:any) => { /* ignore */ return { items: [] } }),
          (dataProvider.listPipelines?.() ?? Promise.resolve({ items: [] })).catch((e:any) => { /* ignore */ return { items: [] } }),
          ((dataProvider as any).listGraphs?.() ?? Promise.resolve({ items: [] })).catch((e:any) => { this.errMsg = this.errMsg || `graphs 加载失败: ${e?.message||e}`; return { items: [] } })
        ])
        const sysData = (sysResp as any).data || {}
        this.whepBase = (sysData.sfu?.whep_base || '').toString()
        {
          const sAny: any = (sourcesResp as any)
          const raw = ((sAny?.data && (sAny.data.items || sAny.data)) || sAny?.items || sAny) || []
          const arr = Array.isArray(raw) ? raw : []
          this.sources = arr
            .map((s: any) => ({
              id: s?.id || s?.stream_id || s?.attach_id || s?.name || '',
              name: s?.name || s?.id || s?.stream_id || s?.attach_id || '',
              uri: s?.uri || s?.source_uri || '',
              status: s?.status || s?.phase || '',
              caps: s?.caps || s?.capabilities
            }))
            .filter((x: any) => !!x.id)
        }
        this.models = ((modelsResp as any).data ?? (modelsResp as any).items ?? []) as ModelItem[]
        this.pipelines = ((pipelinesResp as any).data ?? (pipelinesResp as any).items ?? []) as PipelineItem[]
        {
          const raw = (((graphsResp as any)?.data?.items) ?? (graphsResp as any).data ?? (graphsResp as any).items ?? []) as any[]
          this.graphs = Array.isArray(raw)
            ? raw.map((g: any) => ({
                graph_id: g?.graph_id || g?.id || g?.name || '',
                name: g?.name || g?.id || g?.graph_id || '',
                requires: g?.requires
              })) as GraphItem[]
            : ([] as GraphItem[])
        }
        if (!this.errMsg && !this.sources.length) this.errMsg = 'sources 为空'
        if (!this.errMsg && !this.graphs.length) this.errMsg = 'graphs 为空'
        if (this.sources.length) {
          const run = this.sources.find(s => (s as any).status === 'Running')
          this.setSource((run?.id) || this.sources[0].id)
        }
        if (this.pipelines.length) {
          this.currentPipeline = this.pipelines[0].name
        } else {
          this.currentPipeline = 'det_720p'
        }
        if (this.graphs.length) {
          this.currentGraphId = this.graphs[0].graph_id
        } else {
          this.currentGraphId = 'analyzer_multistage_example'
        }
        if (this.models.length) {
          this.currentModelUri = this.models[0].id
        }
        this.refreshStats()
        if (this.autoPlay && !this.analyzing && Date.now() >= this.muteAutoStartUntil) {
          await this.startAnalysis()
        }
      } finally {
        this.loading = false
      }
    },
    setSource(id: string) {
      this.currentSourceId = id
      this.updateWhepUrl()
      // 延后到订阅成功后再更新 whepUrl
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
      // 归一化为绝对 URL，兼容相对配置
      const absBase = ((): string => { try { return new URL(base, window.location.origin).toString().replace(/\/+$/, '') } catch { return base } })()
      if (absBase && this.currentSourceId && this.currentPipeline) {
        this.whepUrl = `${absBase}/whep?stream=${encodeURIComponent(this.currentSourceId)}:${encodeURIComponent(this.currentPipeline)}`
      } else {
        this.whepUrl = ''
      }
    },
    setAutoPlay(v: boolean){ this.autoPlay = v; localStorage.setItem('va_autoplay', v ? 'on' : 'off') },
    setAnalyzing(v: boolean) {
      this.analyzing = v
      this.refreshStats()
    },
    async startAnalysis() {
      // reset error/progress state at the very beginning
      this.errMsg = ''
      this.subPhase = 'pending'
      this.subProgress = 5
      const pf = await this.preflight()
      if (!pf.ok) {
        this.setAnalyzing(false)
        return pf
      }
      // ensure defaults to avoid 400 Bad Request
      if (!this.currentPipeline) this.currentPipeline = 'det_720p'
      if (!this.currentGraphId) this.currentGraphId = 'analyzer_multistage_example'
      if (!this.currentSourceId) {
        try {
          if (!this.sources.length) {
            const res: any = await (dataProvider as any).listSources?.()
            const raw = (res?.data?.items ?? res?.items ?? (Array.isArray(res) ? res : [])) || []
            const arr = Array.isArray(raw) ? raw : []
            if (arr.length) {
              this.sources = arr.map((s: any) => ({
                id: s?.id || s?.stream_id || s?.attach_id || s?.name || '',
                name: s?.name || s?.id || s?.stream_id || s?.attach_id || '',
                uri: s?.uri || s?.source_uri || '',
                status: s?.status || s?.phase || '',
                caps: s?.caps || s?.capabilities
              })).filter((x: any) => !!x.id)
            }
          }
          if (this.sources.length) this.currentSourceId = this.sources[0].id
        } catch {}
      }
      try {
        const src = this.sources.find(s => s.id === this.currentSourceId)
        const profile = this.currentPipeline
        const uri = src?.uri || ''
        const model = this.currentModelUri || undefined
        // 优先使用异步订阅接口（SSE 实时进度）
        // @ts-ignore
        if (typeof window !== 'undefined') {
          const mod = await import('@/api/cp')
          // 防止同 stream:profile 残留管线导致内部切换失败，先尝试一次性退订（忽略错误）
          // 仅使用异步订阅路径，不调用旧的控制平面/同步接口
          const subId = await mod.createSubscription(this.currentSourceId, profile, uri, model)
          if (!subId) throw new Error('createSubscription failed')
          this.currentSubId = subId
          // 建立 SSE
          try { this._subSSE?.close() } catch {}
          const esUrl = mod.subscriptionEventsUrl(subId)
          const es = new EventSource(esUrl)
          this._subSSE = es
          this._subRetries = 0
          const phaseToProgress = (p: string) => {
            switch ((p||'').toLowerCase()) {
              case 'pending': return 5
              case 'preparing': return 15
              case 'opening_rtsp': return 35
              case 'loading_model': return 65
              case 'starting_pipeline': return 85
              case 'ready': return 100
              case 'failed': return 100
              case 'cancelled': return 100
              default: return 0
            }
          }
          es.addEventListener('phase', (ev: MessageEvent) => {
            try {
              const data = JSON.parse((ev as any).data || '{}')
              const phase = (data.phase || '').toString()
              this.subPhase = phase
              this.subProgress = phaseToProgress(phase)
              if (phase.toLowerCase() === 'ready') {
                const w = (data.whep_url || '') as string
                if (w) this.whepUrl = w; else this.updateWhepUrl()
                this.setAnalyzing(true)
                try { this._subSSE?.close() } catch {}
                this._subSSE = null
              } else if (phase.toLowerCase() === 'failed' || phase.toLowerCase() === 'cancelled') {
                this.errMsg = (data.reason || phase) as string
                try { this._subSSE?.close() } catch {}
                this._subSSE = null
                this.setAnalyzing(false)
              }
            } catch {}
          })
          es.addEventListener('error', async () => {
            // SSE 断线：轻量回退一次性查询，并尝试指数退避重连（仅在未就绪且未取消时）
            try {
              const st: any = await mod.getSubscription(subId).catch(()=>null)
              const phase = (st?.data?.phase || '').toString()
              if (phase) { this.subPhase = phase; this.subProgress = phaseToProgress(phase) }
              if ((phase||'').toLowerCase() === 'ready') {
                const w = st?.data?.whep_url || ''
                if (w) this.whepUrl = w; else this.updateWhepUrl()
                this.setAnalyzing(true)
                try { this._subSSE?.close() } catch {}
                this._subSSE = null
                return
              }
            } catch {}
            try { this._subSSE?.close() } catch {}
            this._subSSE = null
            if (!this.analyzing && this.currentSubId === subId) {
              this._subRetries = (this._subRetries || 0) + 1
              const delay = Math.min(8000, Math.pow(2, this._subRetries) * 500)
              setTimeout(() => {
                if (this.analyzing || this.currentSubId !== subId) return
                const nes = new EventSource(esUrl)
                this._subSSE = nes
                // 复用相同监听器
                nes.addEventListener('phase', (ev: MessageEvent) => {
                  try {
                    const data = JSON.parse((ev as any).data || '{}')
                    const phase = (data.phase || '').toString()
                    this.subPhase = phase
                    this.subProgress = phaseToProgress(phase)
                    if (phase.toLowerCase() === 'ready') {
                      const w = (data.whep_url || '') as string
                      if (w) this.whepUrl = w; else this.updateWhepUrl()
                      this.setAnalyzing(true)
                      try { this._subSSE?.close() } catch {}
                      this._subSSE = null
                    } else if (phase.toLowerCase() === 'failed' || phase.toLowerCase() === 'cancelled') {
                      this.errMsg = (data.reason || phase) as string
                      try { this._subSSE?.close() } catch {}
                      this._subSSE = null
                      this.setAnalyzing(false)
                    }
                  } catch {}
                })
                nes.addEventListener('error', () => { /* 将由外层 onerror 再次处理 */ })
              }, delay)
            }
          })
          // 后备超时：若 SSE 未触发，进行一次性轮询兜底
          setTimeout(async () => {
            if (!this.analyzing && this.currentSubId === subId) {
              const st: any = await mod.getSubscription(subId).catch(()=>null)
              const phase = (st?.data?.phase || '').toString().toLowerCase()
              if (phase === 'ready') { const w = st?.data?.whep_url || ''; if (w) this.whepUrl = w; else this.updateWhepUrl(); this.setAnalyzing(true) }
            }
          }, 2500)
        }
        return { ok: true } as const
      } catch (e:any) {
        // fallback 一次：修正常见的 profile/source_uri 缺失
        const firstMsg = (e?.message || '').toString()
        try {
          if (!this.currentPipeline) this.currentPipeline = 'det_720p'
          if (!this.currentGraphId) this.currentGraphId = 'analyzer_multistage_example'
          if (!this.currentSourceId && this.sources.length) this.currentSourceId = this.sources[0].id
          const src2 = this.sources.find(s => s.id === this.currentSourceId)
          const uri2 = src2?.uri || ''
          // @ts-ignore
          if (typeof window !== 'undefined' && this.currentSourceId && this.currentPipeline && uri2) {
            const mod = await import('@/api/cp')
            const subId = await mod.createSubscription(this.currentSourceId, this.currentPipeline, uri2, this.currentModelUri || undefined)
            this.currentSubId = subId
            try { this._subSSE?.close() } catch {}
            const es = new EventSource(mod.subscriptionEventsUrl(subId))
            this._subSSE = es
            es.addEventListener('phase', (ev: MessageEvent) => {
              try {
                const data = JSON.parse((ev as any).data || '{}')
                const phase = (data.phase || '').toString()
                this.subPhase = phase
                this.subProgress = ['pending','preparing','opening_rtsp','loading_model','starting_pipeline','ready'].indexOf(phase.toLowerCase()) >= 0
                  ? [5,15,35,65,85,100][['pending','preparing','opening_rtsp','loading_model','starting_pipeline','ready'].indexOf(phase.toLowerCase())]
                  : 0
                if (phase.toLowerCase() === 'ready') {
                  const w = (data.whep_url || '') as string
                  if (w) this.whepUrl = w; else this.updateWhepUrl()
                  this.setAnalyzing(true)
                  try { this._subSSE?.close() } catch {}
                  this._subSSE = null
                } else if (phase.toLowerCase() === 'failed' || phase.toLowerCase() === 'cancelled') {
                  this.errMsg = (data.reason || phase) as string
                  try { this._subSSE?.close() } catch {}
                  this._subSSE = null
                  this.setAnalyzing(false)
                }
              } catch {}
            })
            return { ok: true } as const
          }
        } catch (e2:any) {
          this.setAnalyzing(false)
          return { ok:false, reasons:[ firstMsg || e2?.message || 'subscribe failed' ] } as any
        }
        this.setAnalyzing(false)
        return { ok:false, reasons:[ firstMsg || 'subscribe failed' ] } as any
      }
    },
    async stopAnalysis() {
      try {
        // 仅取消异步订阅；不再调用旧的 /api/unsubscribe
        // @ts-ignore
        if (typeof window !== 'undefined' && this.currentSubId) { const mod = await import('@/api/cp'); await mod.cancelSubscription(this.currentSubId).catch(()=>{}) }
      } catch (e) {}
      try { this._subSSE?.close() } catch {}
      this._subSSE = null
      this.subPhase = ''
      this.subProgress = 0
      this.currentSubId = ''
      this.setAnalyzing(false)
      // 取消后短期抑制 AutoPlay 触发的自动重启
      this.muteAutoStartUntil = Date.now() + 3000
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
