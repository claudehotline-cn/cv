import metricsQuery from '@/mocks/metrics_query.json'
import metricsMulti from '@/mocks/metrics_multi.json'
import metricsTop from '@/mocks/metrics_top.json'
import logsRecent from '@/mocks/logs_recent.json'
import eventsRecent from '@/mocks/events_recent.json'
import pipelinesList from '@/mocks/pipelines_list.json'
import sourcesList from '@/mocks/sources_list.json'
import modelsList from '@/mocks/models_list.json'
import graphsList from '@/mocks/graphs_list.json'

export const isMock = !!(import.meta as any).env?.VITE_USE_MOCK

function delay<T>(data: T, ms = 300): Promise<T> { return new Promise(res => setTimeout(() => res(data), ms)) }

function apiBase() {
  const isDev = !!((import.meta as any).env?.DEV)
  if (isDev) return '' // use Vite dev proxy
  const raw = (((import.meta as any).env?.VITE_API_BASE) || '/').toString()
  return raw.trim().replace(/\/+$/, '')
}

export const dataProvider = {
  // Metrics
  async metricsQuery(params: { metric: string; from: number; to: number; stepSec: number; pipeline?: string }) {
    if (isMock) return delay(metricsQuery as any)
    const r = await fetch(apiBase() + '/metrics', { cache:'no-cache' })
    if (!r.ok) throw new Error('metricsQuery failed')
    const txt = await r.text()
    const map: Record<string, number> = {}
    for (const line of txt.split(/\r?\n/)){
      const s = line.trim(); if (!s || s.startsWith('#')) continue
      const m = s.match(/^([a-zA-Z_:][a-zA-Z0-9_:]*)\s+([0-9eE+\-.]+)/)
      if (m){ map[m[1]] = Number(m[2]) }
    }
    const key = Object.keys(map).find(k => k === params.metric || k.includes(params.metric))
    const v = key ? map[key] : 0
    return { series: [{ metric: params.metric, points: [{ t: params.to, v }] }] }
  },
  async metricsTop(params: { metric: string; limit: number }) {
    if (isMock) return delay(metricsTop as any)
    const r = await fetch(apiBase() + '/metrics', { cache:'no-cache' })
    if (!r.ok) throw new Error('metricsTop failed')
    const txt = await r.text()
    const out: Array<{ label: string, value: number }> = []
    for (const line of txt.split(/\r?\n/)){
      const s = line.trim(); if (!s || s.startsWith('#')) continue
      const m = s.match(/^([a-zA-Z_:][a-zA-Z0-9_:]*)\s+([0-9eE+\-.]+)/)
      if (m && (m[1] === params.metric || m[1].includes(params.metric))) out.push({ label: m[1], value: Number(m[2]) })
    }
    out.sort((a,b)=>b.value-a.value)
    return { items: out.slice(0, Math.max(1, params.limit||5)) }
  },
  async metricsMultiQuery(params: { metrics: string[]; from: number; to: number; stepSec: number; pipeline?: string }) {
    if (isMock) return delay(metricsMulti as any)
    const r = await fetch(apiBase() + '/metrics', { cache:'no-cache' })
    if (!r.ok) throw new Error('metricsMultiQuery failed')
    const txt = await r.text()
    const map: Record<string, number> = {}
    for (const line of txt.split(/\r?\n/)){
      const s = line.trim(); if (!s || s.startsWith('#')) continue
      const m = s.match(/^([a-zA-Z_:][a-zA-Z0-9_:]*)\s+([0-9eE+\-.]+)/)
      if (m){ map[m[1]] = Number(m[2]) }
    }
    const series = (params.metrics || []).map(name => {
      const key = Object.keys(map).find(k => k === name || k.includes(name))
      const v = key ? map[key] : 0
      return { metric: name, points: [{ t: params.to, v }] }
    })
    return { series }
  },

  // Logs (DB list)
  async logsRecent(params?: { pipeline?: string; level?: string; from_ts?: number; to_ts?: number; limit?: number; page?: number; page_size?: number }) {
    if (isMock) return delay(logsRecent as any)
    const q = new URLSearchParams()
    if (params?.pipeline) q.set('pipeline', params.pipeline)
    if (params?.level)    q.set('level', params.level)
    if (params?.from_ts)  q.set('from_ts', String(params.from_ts))
    if (params?.to_ts)    q.set('to_ts', String(params.to_ts))
    if (params?.limit)    q.set('limit', String(params.limit))
    if (params?.page)     q.set('page', String(params.page))
    if (params?.page_size) q.set('page_size', String(params.page_size))
    const r = await fetch(apiBase() + '/api/logs' + (q.toString()?('?'+q.toString()):''))
    if (!r.ok) {
      let msg = 'logsRecent failed'
      try { msg = await r.text() } catch {}
      throw new Error(msg)
    }
    return r.json()
  },
  logsSubscribe(cb: (ev: any) => void, opts?: { pipeline?: string; level?: string }) {
    if (isMock) {
      const levels = ['Info','Warning','Error']
      const pipes = (pipelinesList as any).items.map((i: any) => i.name)
      const id = setInterval(() => { const ev = { ts: Date.now(), level: levels[Math.floor(Math.random()*levels.length)], pipeline: pipes[Math.floor(Math.random()*pipes.length)], node: 'model', msg: 'mock log event' }; cb(ev) }, 1500)
      return () => clearInterval(id)
    }
    const base = apiBase()
    const canSSE = typeof window !== 'undefined' && typeof (window as any).EventSource === 'function'
    if (canSSE) {
      const url = new URL(base + '/api/logs/watch_sse')
      if (opts?.pipeline) url.searchParams.set('pipeline', opts.pipeline)
      if (opts?.level)    url.searchParams.set('level', opts.level)
      const es = new (window as any).EventSource(url.toString())
      const onMsg = (e: MessageEvent) => { try { const j = JSON.parse((e as any).data || '{}'); const arr = Array.isArray(j?.items)? j.items : []; arr.forEach(cb) } catch {} }
      es.addEventListener('logs', onMsg as any)
      es.addEventListener('message', onMsg as any)
      return () => { try { es.close() } catch {} }
    }
    let stopped = false; let since = 0
    async function loop(){
      while(!stopped){
        const url = new URL(base + '/api/logs/watch')
        if (since) url.searchParams.set('since', String(since))
        if (opts?.pipeline) url.searchParams.set('pipeline', opts.pipeline)
        if (opts?.level)    url.searchParams.set('level', opts.level)
        url.searchParams.set('timeout_ms','12000'); url.searchParams.set('interval_ms','300')
        try { const r = await fetch(url.toString(), { cache:'no-cache' }); if(r.ok){ const j=await r.json(); const d=j?.data||j; const rev=Number(d?.rev||0); const items = Array.isArray(d?.items)? d.items: []; if (rev && rev !== since) { since = rev; for (const it of items) cb(it) } } } catch {}
      }
    }
    loop(); return () => { stopped = true }
  },

  // Events (DB list)
  async eventsRecent(params?: { pipeline?: string; level?: string; from_ts?: number; to_ts?: number; limit?: number; page?: number; page_size?: number }) {
    if (isMock) return delay(eventsRecent as any)
    const q = new URLSearchParams()
    if (params?.pipeline) q.set('pipeline', params.pipeline)
    if (params?.level)    q.set('level', params.level)
    if (params?.from_ts)  q.set('from_ts', String(params.from_ts))
    if (params?.to_ts)    q.set('to_ts', String(params.to_ts))
    if (params?.limit) q.set('limit', String(params.limit))
    if (params?.page)  q.set('page', String(params.page))
    if (params?.page_size) q.set('page_size', String(params.page_size))
    const r = await fetch(apiBase() + '/api/events/recent' + (q.toString()?('?'+q.toString()):''))
    if (!r.ok) {
      let msg = 'eventsRecent failed'
      try { msg = await r.text() } catch {}
      throw new Error(msg)
    }
    return r.json()
  },
  eventsSubscribe(cb: (ev: any) => void, opts?: { pipeline?: string; level?: string }) {
    if (isMock) {
      const types = ['ok','warn','error','success']
      const pipes = (pipelinesList as any).items.map((i: any) => i.name)
      const id = setInterval(() => { const ty = types[Math.floor(Math.random()*types.length)]; const ev = { ts: Date.now(), level: ty, pipeline: pipes[Math.floor(Math.random()*pipes.length)], type: ty, msg: `mock ${ty}` }; cb(ev) }, 2000)
      return () => clearInterval(id)
    }
    const base = apiBase()
    const canSSE = typeof window !== 'undefined' && typeof (window as any).EventSource === 'function'
    if (canSSE) {
      const url = new URL(base + '/api/events/watch_sse')
      if (opts?.pipeline) url.searchParams.set('pipeline', opts.pipeline)
      if (opts?.level)    url.searchParams.set('level', opts.level)
      const es = new (window as any).EventSource(url.toString())
      const onMsg = (e: MessageEvent) => { try { const j=JSON.parse((e as any).data||'{}'); const arr = Array.isArray(j?.items)? j.items: []; arr.forEach(cb) } catch {} }
      es.addEventListener('events', onMsg as any)
      es.addEventListener('message', onMsg as any)
      return () => { try { es.close() } catch {} }
    }
    let stopped = false; let since = 0
    async function loop(){
      while(!stopped){
        const url = new URL(base + '/api/events/watch')
        if (since) url.searchParams.set('since', String(since))
        if (opts?.pipeline) url.searchParams.set('pipeline', opts.pipeline)
        if (opts?.level)    url.searchParams.set('level', opts.level)
        url.searchParams.set('timeout_ms','12000'); url.searchParams.set('interval_ms','300')
        try { const r = await fetch(url.toString(), { cache:'no-cache' }); if(r.ok){ const j=await r.json(); const d=j?.data||j; const rev=Number(d?.rev||0); const items = Array.isArray(d?.items)? d.items: []; if (rev && rev !== since) { since = rev; for (const it of items) cb(it) } } } catch {}
      }
    }
    loop(); return () => { stopped = true }
  },

  // Lists
  async listPipelines() {
    if (isMock) return delay(pipelinesList as any)
    const r = await fetch(apiBase() + '/api/pipelines')
    if (!r.ok) throw new Error('listPipelines failed')
    return r.json()
  },
  async listSources() {
    if (isMock) return delay(sourcesList as any)
    // 首选 VA 聚合接口，失败或为空时回退到 VSM REST
    try {
      const r = await fetch(apiBase() + '/api/sources')
      if (r.ok) {
        const j = await r.json()
        const items = (((j as any)?.data?.items) ?? (j as any)?.items ?? (Array.isArray(j) ? j : [])) as any[]
        if (Array.isArray(items) && items.length > 0) return { data: { items } }
      }
    } catch {}
    try {
      const mod = await import('@/api/vsm')
      const v = await mod.listSources()
      // 与聚合接口保持结构一致 { data: { items } }
      return { data: { items: v.items } }
    } catch (e) {
      throw new Error('listSources failed')
    }
  },
  // 长轮询 watch：回调拿到 { rev, items }，返回取消函数
  watchSources(cb: (payload: { rev: number, items: any[] }) => void, opts?: { intervalMs?: number; timeoutMs?: number }) {
    // 优先 VA SSE，其次回退 VSM SSE，最后长轮询
    const canSSE = (typeof window !== 'undefined') && typeof (window as any).EventSource === 'function'
    let stopped = false
    let since = 0
    let es: EventSource | null = null
    const interval = Math.max(100, opts?.intervalMs ?? 0)
    const base = apiBase()
    const dispatch = (rev: number, items: any[]) => { if (rev && !stopped) cb({ rev, items }) }
    const attachVA = () => {
      try {
        es = new (window as any).EventSource(base + '/api/sources/watch_sse')
        const onMsg = (e: MessageEvent) => { try { const j=JSON.parse((e as any).data||'{}'); const rev=Number(j?.rev||0); const items = Array.isArray(j?.items)? j.items: []; if (rev) { since = rev; dispatch(rev, items) } } catch {} }
        es.addEventListener('sources', onMsg as any)
        es.addEventListener('message', onMsg as any)
        es.addEventListener('error', () => { try { es?.close() } catch {}; es = null; if (!stopped) attachVSM() })
      } catch { attachVSM() }
    }
    const attachVSM = async () => {
      try {
        const mod = await import('@/api/vsm')
        es = new (window as any).EventSource(mod.sourcesSseUrl({ since }))
        es.addEventListener('message', (e: MessageEvent) => { try { const j=JSON.parse((e as any).data||'{}'); const rev=Number(j?.rev||0); const items = Array.isArray(j?.items)? j.items: []; if (rev) { since = rev; dispatch(rev, items) } } catch {} })
        es.addEventListener('error', () => { try { es?.close() } catch {}; es = null; if (!stopped) startLongPoll() })
      } catch { startLongPoll() }
    }
    const startLongPoll = async () => {
      while(!stopped){
        const url = new URL(base + '/api/sources/watch')
        if (since) url.searchParams.set('since', String(since))
        if (opts?.timeoutMs) url.searchParams.set('timeout_ms', String(opts.timeoutMs))
        try{ const r = await fetch(url.toString(), { cache:'no-cache' }); if (!r.ok) throw new Error('watchSources failed'); const j = await r.json(); const d = j?.data || j; const rev = Number(d?.rev||0); const items = Array.isArray(d?.items)? d.items: []; if (rev && rev !== since){ since = rev; dispatch(rev, items) } }catch{}
        if (interval) await new Promise(res => setTimeout(res, interval))
      }
    }
    if (canSSE) attachVA(); else startLongPoll()
    return () => { stopped = true; try { es?.close() } catch {}; es = null }
  },
  async listModels() {
    if (isMock) return delay(modelsList as any)
    const r = await fetch(apiBase() + '/api/models')
    if (!r.ok) throw new Error('listModels failed')
    return r.json()
  },
  async listGraphs() {
    if (isMock) return delay(graphsList as any)
    const r = await fetch(apiBase() + '/api/graphs')
    if (!r.ok) throw new Error('listGraphs failed')
    return r.json()
  },
  // Sessions
  async listSessions(params?: { stream_id?: string; pipeline?: string; limit?: number; from_ts?: number; to_ts?: number; page?: number; page_size?: number }) {
    const q = new URLSearchParams()
    if (params?.stream_id) q.set('stream_id', params.stream_id)
    if (params?.pipeline)  q.set('pipeline', params.pipeline)
    if (params?.limit)     q.set('limit', String(params.limit))
    if (params?.from_ts)   q.set('from_ts', String(params.from_ts))
    if (params?.to_ts)     q.set('to_ts', String(params.to_ts))
    if (params?.page)      q.set('page', String(params.page))
    if (params?.page_size) q.set('page_size', String(params.page_size))
    const r = await fetch(apiBase() + '/api/sessions' + (q.toString()?('?'+q.toString()):''))
    if (!r.ok) {
      let msg = 'listSessions failed'
      try { msg = await r.text() } catch {}
      try { window.dispatchEvent(new CustomEvent('sessions-error', { detail: msg })) } catch {}
      throw new Error(msg)
    }
    return r.json()
  },
  watchSessions(cb: (payload: { rev: number, items: any[] }) => void, opts?: { stream_id?: string; pipeline?: string; intervalMs?: number; timeoutMs?: number; from_ts?: number; to_ts?: number }) {
    let stopped = false
    let since = 0
    const base = apiBase()
    const interval = Math.max(100, opts?.intervalMs ?? 0)
    async function loop(){
      while(!stopped){
        const url = new URL(base + '/api/sessions/watch')
        if (since) url.searchParams.set('since', String(since))
        if (opts?.stream_id) url.searchParams.set('stream_id', opts.stream_id)
        if (opts?.pipeline)  url.searchParams.set('pipeline', opts.pipeline)
        // 后端 watch 暂不支持时间窗
        if (opts?.timeoutMs) url.searchParams.set('timeout_ms', String(opts.timeoutMs))
        url.searchParams.set('interval_ms', String(Math.max(80, opts?.intervalMs ?? 300)))
        try{
          const r = await fetch(url.toString(), { cache:'no-cache' })
          if(!r.ok) throw new Error('watchSessions failed')
          const j = await r.json(); const d = j?.data || j; const rev = Number(d?.rev||0); const items = Array.isArray(d?.items)? d.items: []
          if (rev && rev !== since){ since = rev; cb({ rev, items }) }
        }catch{}
        if (interval) await new Promise(res => setTimeout(res, interval))
      }
    }
    loop(); return () => { stopped = true }
  },
  async preflightCheck(payload: { source: any; graph: any }) {
    if (isMock) {
      const reasons: string[] = []
      const caps = payload.source?.caps || {}
      const req = payload.graph?.requires || {}
      const pix = caps.pix_fmt || ''
      if (Array.isArray(req.color_format) && !req.color_format.includes(pix)) reasons.push(`像素格式不匹配: ${pix}`)
      const [w,h] = caps.resolution || [0,0]
      const max = req.max_resolution || [99999,99999]
      const min = req.min_resolution || [0,0]
      if (w>max[0] || h>max[1]) reasons.push(`分辨率超过上限: ${w}x${h} > ${max[0]}x${max[1]}`)
      if (w<min[0] || h<min[1]) reasons.push(`分辨率低于下限: ${w}x${h} < ${min[0]}x${min[1]}`)
      const fps = caps.fps || 0
      const fr = req.fps_range || [0,999]
      if (fps<fr[0] || fps>fr[1]) reasons.push(`帧率不在范围 ${fr[0]}-${fr[1]}: ${fps}`)
      return delay({ ok: reasons.length===0, reasons } as any)
    }
    // CP 不提供 /api/preflight（VA 旧接口），此处直接放行，由编排/订阅链路在后台保证可用性
    return { ok: true, reasons: [] } as any
  },

  // Mutations (mock only updates nothing)
  async detachSource(id: string) { if (isMock) return delay({ ok: true } as any, 200); throw new Error('No backend configured') },
  async attachSource(payload: any) { if (isMock) return delay({ ok: true } as any, 200); throw new Error('No backend configured') },
  async startSource(id: string) { if (isMock) return delay({ ok: true, id, status:'Starting' } as any, 200); throw new Error('No backend configured') },
  async stopSource(id: string) { if (isMock) return delay({ ok: true, id, status:'Stopping' } as any, 200); throw new Error('No backend configured') }
}
