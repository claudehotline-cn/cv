import { http } from './http'

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

// Control-plane apply (embedded)
export function applyPipeline(spec: any) {
  return http.post('/api/control/apply_pipeline', spec)
}
export function applyPipelines(items: any[]) {
  return http.post('/api/control/apply_pipelines', { items })
}

