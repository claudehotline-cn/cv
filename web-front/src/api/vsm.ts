const VSM_BASE = (import.meta as any).env?.VITE_VSM_BASE || 'http://127.0.0.1:7071'

function baseUrl(path: string) {
  return (VSM_BASE as string).replace(/\/+$/, '') + path
}

export async function listSources(): Promise<{ items: any[] }> {
  const r = await fetch(baseUrl('/api/source/list'))
  if (!r.ok) throw new Error('VSM /api/source/list failed')
  const j = await r.json()
  const items = Array.isArray(j?.data) ? j.data : []
  // normalize fields: id, uri, status/phase, fps, caps (if any)
  const mapped = items.map((s: any) => ({
    id: s.id || s.attach_id || s.source_id || '',
    name: s.name || s.attach_id || '',
    uri: s.uri || s.source_uri || '',
    status: s.status || s.phase || '',
    fps: s.fps ?? 0,
    loss: s.loss_pct ?? 0,
    jitter: s.jitter_ms ?? 0,
    caps: s.caps || s.cap || undefined
  }))
  return { items: mapped }
}

export function sourcesSseUrl(params?: { since?: number; keepalive_ms?: number; max_sec?: number }) {
  const q = new URLSearchParams()
  if (params?.since) q.set('since', String(params.since))
  if (params?.keepalive_ms) q.set('keepalive_ms', String(params.keepalive_ms))
  if (params?.max_sec) q.set('max_sec', String(params.max_sec))
  return baseUrl('/api/source/watch_sse') + (q.toString() ? ('?' + q.toString()) : '')
}

