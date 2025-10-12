export interface HttpOptions {
  baseURL?: string
  headers?: Record<string, string>
}

const defaultBase = (import.meta as any).env?.VITE_API_BASE || '/'

export class HttpClient {
  constructor(private opts: HttpOptions = {}) {}
  private url(path: string) { return (this.opts.baseURL || defaultBase).replace(/\/$/, '') + path }
  async get<T>(path: string): Promise<T> {
    const r = await fetch(this.url(path), { credentials: 'omit' })
    if (!r.ok) throw new Error(await r.text())
    return r.json() as Promise<T>
  }
  async post<T>(path: string, body?: any): Promise<T> {
    const r = await fetch(this.url(path), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(this.opts.headers||{}) },
      body: body ? JSON.stringify(body) : undefined,
      credentials: 'omit'
    })
    if (!r.ok) throw new Error(await r.text())
    return r.json() as Promise<T>
  }
  async patch<T>(path: string, body?: any): Promise<T> {
    const r = await fetch(this.url(path), {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', ...(this.opts.headers||{}) },
      body: body ? JSON.stringify(body) : undefined
    })
    if (!r.ok) throw new Error(await r.text())
    return r.json() as Promise<T>
  }
  async getText(path: string): Promise<string> {
    const r = await fetch(this.url(path), { credentials: 'omit' })
    if (!r.ok) throw new Error(await r.text())
    return r.text()
  }
}

export const http = new HttpClient()
