import { http } from './http'

// System & Models
export const getSystemInfo = () => http('/api/system/info')
export const getSystemStats = () => http('/api/system/stats')
export const getModels = () => http('/api/models')
export const getProfiles = () => http('/api/profiles')
export const setEngine = (body: any) => http('/api/engine/set', { method: 'POST', body: JSON.stringify(body) })

// Pipelines (lifecycle)
export const getPipelines = () => http('/api/pipelines')
export const subscribe = (p: { stream_id?: string; stream?: string; profile: string; source_uri?: string; url?: string; model_id?: string }) =>
  http('/api/subscribe', { method: 'POST', body: JSON.stringify(p) })
export const unsubscribe = (p: { stream_id?: string; stream?: string; profile: string }) =>
  http('/api/unsubscribe', { method: 'POST', body: JSON.stringify(p) })
export const switchSource = (p: { stream_id?: string; stream?: string; profile: string; source_uri?: string; url?: string }) =>
  http('/api/source/switch', { method: 'POST', body: JSON.stringify(p) })
export const switchModel = (p: { stream_id?: string; stream?: string; profile: string; model_id: string }) =>
  http('/api/model/switch', { method: 'POST', body: JSON.stringify(p) })
export const setModelParams = (p: { stream_id?: string; stream?: string; profile: string; conf?: number; iou?: number }) =>
  http('/api/model/params', { method: 'PATCH', body: JSON.stringify(p) })

// Logging & Metrics runtime
export const getLogging = () => http('/api/logging')
export const setLogging = (p: any) => http('/api/logging/set', { method: 'POST', body: JSON.stringify(p) })
export const getMetricsCfg = () => http('/api/metrics')
export const setMetricsCfg = (p: any) => http('/api/metrics/set', { method: 'POST', body: JSON.stringify(p) })

