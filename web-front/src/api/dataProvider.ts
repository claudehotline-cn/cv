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

export const dataProvider = {
  // Metrics
  async metricsQuery(params: { metric: string; from: number; to: number; stepSec: number; pipeline?: string }) {
    if (isMock) return delay(metricsQuery as any)
    throw new Error('No backend configured')
  },
  async metricsTop(params: { metric: string; limit: number }) {
    if (isMock) return delay(metricsTop as any)
    throw new Error('No backend configured')
  },
  async metricsMultiQuery(params: { metrics: string[]; from: number; to: number; stepSec: number; pipeline?: string }) {
    if (isMock) return delay(metricsMulti as any)
    throw new Error('No backend configured')
  },

  // Logs
  async logsRecent(params?: { pipeline?: string; level?: string; since?: number; limit?: number }) {
    if (isMock) return delay(logsRecent as any)
    throw new Error('No backend configured')
  },
  logsSubscribe(cb: (ev: any) => void) {
    if (!isMock) return () => {}
    const levels = ['Info','Warning','Error']
    const pipes = (pipelinesList as any).items.map((i: any) => i.name)
    const id = setInterval(() => {
      const ev = { ts: Date.now(), level: levels[Math.floor(Math.random()*levels.length)], pipeline: pipes[Math.floor(Math.random()*pipes.length)], node: 'model', msg: 'mock log event' }
      cb(ev)
    }, 1500)
    return () => clearInterval(id)
  },

  // Events
  async eventsRecent(params?: { limit?: number }) {
    if (isMock) return delay(eventsRecent as any)
    throw new Error('No backend configured')
  },
  eventsSubscribe(cb: (ev: any) => void) {
    if (!isMock) return () => {}
    const types = ['ok','warn','error','success']
    const pipes = (pipelinesList as any).items.map((i: any) => i.name)
    const id = setInterval(() => {
      const ty = types[Math.floor(Math.random()*types.length)]
      const ev = { ts: Date.now(), level: ty, pipeline: pipes[Math.floor(Math.random()*pipes.length)], type: ty, msg: `mock ${ty}` }
      cb(ev)
    }, 2000)
    return () => clearInterval(id)
  },

  // Lists
  async listPipelines() { if (isMock) return delay(pipelinesList as any); throw new Error('No backend configured') },
  async listSources() { if (isMock) return delay(sourcesList as any); throw new Error('No backend configured') },
  async listModels() { if (isMock) return delay(modelsList as any); throw new Error('No backend configured') },
  async listGraphs() { if (isMock) return delay(graphsList as any); throw new Error('No backend configured') },
  async preflightCheck(payload: { source: any; graph: any }) {
    if (!isMock) throw new Error('No backend configured')
    const reasons: string[] = []
    const caps = payload.source?.caps || {}
    const req = payload.graph?.requires || {}
    const pix = caps.pix_fmt || ''
    if (Array.isArray(req.color_format) && !req.color_format.includes(pix)) reasons.push(`像素格式不兼容: ${pix}`)
    const [w,h] = caps.resolution || [0,0]
    const max = req.max_resolution || [99999,99999]
    const min = req.min_resolution || [0,0]
    if (w>max[0] || h>max[1]) reasons.push(`分辨率超出最大: ${w}x${h} > ${max[0]}x${max[1]}`)
    if (w<min[0] || h<min[1]) reasons.push(`分辨率低于最小: ${w}x${h} < ${min[0]}x${min[1]}`)
    const fps = caps.fps || 0
    const fr = req.fps_range || [0,999]
    if (fps<fr[0] || fps>fr[1]) reasons.push(`帧率不在范围 ${fr[0]}-${fr[1]}: ${fps}`)
    return delay({ ok: reasons.length===0, reasons } as any)
  },

  // Mutations (mock only updates nothing)
  async detachSource(id: string) { if (isMock) return delay({ ok: true } as any, 200); throw new Error('No backend configured') },
  async attachSource(payload: any) { if (isMock) return delay({ ok: true } as any, 200); throw new Error('No backend configured') },
  async startSource(id: string) { if (isMock) return delay({ ok: true, id, status:'Starting' } as any, 200); throw new Error('No backend configured') },
  async stopSource(id: string) { if (isMock) return delay({ ok: true, id, status:'Stopping' } as any, 200); throw new Error('No backend configured') }
}
