import metricsQuery from '@/mocks/metrics_query.json'
import metricsMulti from '@/mocks/metrics_multi.json'
import metricsTop from '@/mocks/metrics_top.json'
import logsRecent from '@/mocks/logs_recent.json'
import eventsRecent from '@/mocks/events_recent.json'
import pipelinesList from '@/mocks/pipelines_list.json'
import sourcesList from '@/mocks/sources_list.json'
import modelsList from '@/mocks/models_list.json'

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

  // Mutations (mock only updates nothing)
  async detachSource(id: string) { if (isMock) return delay({ ok: true } as any, 200); throw new Error('No backend configured') },
  async attachSource(payload: any) { if (isMock) return delay({ ok: true } as any, 200); throw new Error('No backend configured') }
}
