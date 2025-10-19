export interface HttpOptions {
  baseURL?: string
  headers?: Record<string, string>
}

// Sanitize base URL: trim whitespace and remove trailing slashes
const defaultBase = (() => {
  const raw = ((import.meta as any).env?.VITE_API_BASE || '/').toString()
  return raw.trim().replace(/\/+$/, '') || '/'
})()

export class HttpClient {
  constructor(private opts: HttpOptions = {}) {}
  private url(path: string) {
    const base = (this.opts.baseURL || defaultBase).toString().trim().replace(/\/+$/, '')
    return base + path
  }
  private withTimeout(init: RequestInit & { timeoutMs?: number } = {}): RequestInit {
    const timeoutMs = (init.timeoutMs ?? (Number((import.meta as any).env?.VITE_HTTP_TIMEOUT_MS) || 10000))
    if (!timeoutMs) return init
    const ctrl = new AbortController()
    const id = setTimeout(() => ctrl.abort(), timeoutMs)
    const merged: RequestInit = { ...init, signal: ctrl.signal }
    ;(merged as any)._cancel = () => clearTimeout(id)
    return merged
  }
  async get<T>(path: string): Promise<T> {
    const req = this.withTimeout({ credentials: 'omit' })
    const r = await fetch(this.url(path), req)
    if (!r.ok) throw new Error(await r.text())
    return r.json() as Promise<T>
  }
  async post<T>(path: string, body?: any): Promise<T> {
    const req = this.withTimeout({
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(this.opts.headers||{}) },
      body: body ? JSON.stringify(body) : undefined,
      credentials: 'omit'
    })
    const r = await fetch(this.url(path), req)
    if (!r.ok) throw new Error(await r.text())
    return r.json() as Promise<T>
  }
  async patch<T>(path: string, body?: any): Promise<T> {
    const req = this.withTimeout({
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', ...(this.opts.headers||{}) },
      body: body ? JSON.stringify(body) : undefined
    })
    const r = await fetch(this.url(path), req)
    if (!r.ok) throw new Error(await r.text())
    return r.json() as Promise<T>
  }
  async getText(path: string): Promise<string> {
    const req = this.withTimeout({ credentials: 'omit' })
    const r = await fetch(this.url(path), req)
    if (!r.ok) throw new Error(await r.text())
    return r.text()
  }
}

export const http = new HttpClient()

