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
export async function createSubscription(stream_id: string, profile: string, source_uri: string, model_id?: string): Promise<string> {
  const body: any = { stream_id, profile, source_uri }
  if (model_id) body.model_id = model_id
  const r: any = await http.post('/api/subscriptions', body)
  return r?.data?.id || ''
}
export function getSubscription(id: string) {
  return http.get<any>(`/api/subscriptions/${encodeURIComponent(id)}`)
}
export function cancelSubscription(id: string) {
  return fetch((http as any).url?.(`/api/subscriptions/${encodeURIComponent(id)}`) || ((import.meta as any).env?.VITE_API_BASE || '') + `/api/subscriptions/${encodeURIComponent(id)}`, {
    method: 'DELETE', headers: { 'Content-Type': 'application/json' }
  }).then(r => { if (!r.ok) throw new Error('cancelSubscription failed'); return r.json() })
}
export function subscriptionEventsUrl(id: string) {
  const base = (((import.meta as any).env?.VITE_API_BASE || '') as string).toString().replace(/\/+$/, '')
  return `${base}/api/subscriptions/${encodeURIComponent(id)}/events`
}

// Control-plane apply（保留旧接口别名）
export function applyPipeline(spec: any) { return http.post('/api/control/apply_pipeline', spec) }
export function applyPipelines(items: any[]) { return http.post('/api/control/apply_pipelines', { items }) }

// 设计文档中的 CP 封装（基于 VITE_CP_BASE_URL）
const CP_BASE = (import.meta as any).env?.VITE_CP_BASE_URL || (import.meta as any).env?.VITE_API_BASE || ''
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
