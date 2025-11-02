import { http } from './http'

// 现有 API（保留兼容）
export interface SystemInfoResp { data: any, success?: boolean }
export function getSystemInfo() { return http.get<SystemInfoResp>('/api/system/info') }

export interface PipelinesResp { data: any[] }
export function listPipelines() { return http.get<PipelinesResp>('/api/pipelines') }

export function subscribePipeline(stream_id: string, profile: string, source_uri: string, model_id?: string) {
  const body: any = { stream_id, profile, source_uri }
  if (model_id) body.model_id = model_id
  return http.post('/api/subscribe', body)
}
export function unsubscribePipeline(stream_id: string, profile: string) {
  return http.post('/api/unsubscribe', { stream_id, profile })
}
export function switchModel(stream_id: string, profile: string, model_id: string) {
  return http.post('/api/model/switch', { stream_id, profile, model_id })
}

export function listModels() { return http.get<{ data: any[] }>('/api/models') }
export function listProfiles() { return http.get<{ data: any[] }>('/api/profiles') }

export function setEngine(options: Record<string, any>) {
  return http.post('/api/engine/set', options)
}

// --- Async subscriptions API ---
export async function createSubscription(stream_id: string, profile: string, source_uri: string, model_id?: string, opts?: { useExisting?: boolean, source_id?: string }): Promise<string> {
  const body: any = { stream_id, profile }
  if (source_uri) body.source_uri = source_uri
  if (!source_uri && opts?.source_id) body.source_id = opts.source_id
  if (model_id) body.model_id = model_id
  const q = new URLSearchParams()
  if (opts?.useExisting) q.set('use_existing', '1')
  // 兼容后端查询串回退解析
  if (stream_id) q.set('stream_id', stream_id)
  if (profile) q.set('profile', profile)
  if (body.source_uri) q.set('source_uri', body.source_uri)
  if (!body.source_uri && opts?.source_id) q.set('source_id', opts.source_id)
  const qp = q.toString() ? ('?' + q.toString()) : ''
  const r: any = await http.post('/api/subscriptions' + qp, body)
  // 兼容后端不同分支的返回格式：优先 data.id，其次顶层 id
  return (r?.data?.id || r?.id || '')
}
export function getSubscription(id: string) {
  return http.get<any>(`/api/subscriptions/${encodeURIComponent(id)}`)
}
export function getSubscriptionWithTimeline(id: string) {
  return http.get<any>(`/api/subscriptions/${encodeURIComponent(id)}?include=timeline`)
}
export function cancelSubscription(id: string) {
  const path = `/api/subscriptions/${encodeURIComponent(id)}`
  const base = ((import.meta as any).env?.DEV ? '' : (((import.meta as any).env?.VITE_API_BASE || '') as string)).toString().replace(/\/+$/, '')
  const url = (http as any).url?.(path) || (base + path)
  return fetch(url, { method: 'DELETE', headers: { 'Content-Type': 'application/json' } })
    .then(r => { if (!r.ok) throw new Error('cancelSubscription failed'); return r.json() })
}
export function subscriptionEventsUrl(id: string) {
  const path = `/api/subscriptions/${encodeURIComponent(id)}/events`
  const base = ((import.meta as any).env?.DEV ? '' : (((import.meta as any).env?.VITE_API_BASE || '') as string)).toString().replace(/\/+$/, '')
  return `${base}${path}`
}

// Control-plane apply（保留旧接口别名）
export function applyPipeline(spec: any) { return http.post('/api/control/apply_pipeline', spec) }
export function applyPipelines(items: any[]) { return http.post('/api/control/apply_pipelines', { items }) }
export function controlDrain(pipeline_name: string, timeout_sec = 5) {
  return http.post('/api/control/drain', { pipeline_name, timeout_sec })
}

// 切换 Pipeline 分析模式（同一 key，暂停=raw 直通，实时=分析叠加）
export function setPipelineMode(stream_id: string, profile: string, analysis_enabled: boolean) {
  return http.post('/api/control/pipeline_mode', { stream_id, profile, analysis_enabled })
}

// 设计文档中的 CP 封装（基于 VITE_CP_BASE_URL）
const CP_BASE = ((import.meta as any).env?.DEV ? '' : ((import.meta as any).env?.VITE_CP_BASE_URL || (import.meta as any).env?.VITE_API_BASE || ''))
export const cp = {
  async metricsQuery(params: { metric:string; from:number; to:number; stepSec:number; pipeline?:string }) {
    const q = new URLSearchParams({
      m: params.metric,
      from: String(params.from),
      to: String(params.to),
      step: String(params.stepSec),
      ...(params.pipeline ? { pipeline: params.pipeline } : {})
    })
    const r = await fetch(`${CP_BASE.replace(/\/+$/,'')}/metrics/query?`+q.toString())
    if (!r.ok) throw new Error('metricsQuery failed'); return r.json()
  },
  async metricsTop(params: { metric:string; limit:number }) {
    const q = new URLSearchParams({ m: params.metric, limit: String(params.limit) })
    const r = await fetch(`${CP_BASE.replace(/\/+$/,'')}/metrics/top?`+q.toString())
    if (!r.ok) throw new Error('metricsTop failed'); return r.json()
  },
  metricsMultiQuery(params: { metrics: string[]; from: number; to: number; stepSec: number; pipeline?: string }) {
    const body = { metrics: params.metrics, from: params.from, to: params.to, step: params.stepSec, pipeline: params.pipeline }
    return fetch(`${CP_BASE.replace(/\/+$/,'')}/metrics/multi-query`, {
      method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)
    }).then(r => { if(!r.ok) throw new Error('metricsMultiQuery failed'); return r.json() })
  },
  logsRecent(params: { pipeline?: string; level?: string; since?: number; limit?: number }) {
    const q = new URLSearchParams()
    if (params.pipeline) q.set('pipeline', params.pipeline)
    if (params.level)    q.set('level', params.level)
    if (params.since)    q.set('since', String(params.since))
    if (params.limit)    q.set('limit', String(params.limit))
    return fetch(`${CP_BASE.replace(/\/+$/,'')}/logs?${q.toString()}`)
      .then(r => { if(!r.ok) throw new Error('logsRecent failed'); return r.json() })
  },
  logsStreamUrl(params?: { pipeline?: string; level?: string }) {
    const base = CP_BASE.replace(/\/+$/,'')
    const q = new URLSearchParams()
    if (params?.pipeline) q.set('pipeline', params.pipeline)
    if (params?.level)    q.set('level', params.level)
    return `${base}/logs/stream?${q.toString()}`
  },
  eventsRecent(params?: { limit?: number }) {
    const q = new URLSearchParams()
    if (params?.limit) q.set('limit', String(params.limit))
    return fetch(`${CP_BASE.replace(/\/+$/,'')}/events/recent?${q.toString()}`)
      .then(r => { if(!r.ok) throw new Error('eventsRecent failed'); return r.json() })
  },
  eventsStreamUrl() {
    const base = CP_BASE.replace(/\/+$/,'')
    return `${base}/events/stream`
  },
  attachSource(payload: { attach_id:string; source_uri:string; pipeline_id:string; options?:Record<string,string> }) {
    return fetch(`${CP_BASE.replace(/\/+$/,'')}/sources:attach`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
    }).then(r => { if(!r.ok) throw new Error('attachSource failed'); return r.json() })
  }
}
