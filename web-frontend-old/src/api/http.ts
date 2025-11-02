export const API_BASE: string = (import.meta as any)?.env?.VITE_API_BASE || '/api';

export interface JsonResponse<T = any> { success?: boolean; data?: T; error?: string; message?: string }

export async function http<T = any>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { ...(init.headers as any) };
  if (init.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
  const resp = await fetch(`${API_BASE}${path}`, { ...init, headers });
  let payload: JsonResponse<T> | null = null;
  try { payload = await resp.json(); } catch { payload = null as any; }
  if (!resp.ok) {
    const msg = (payload as any)?.error || (payload as any)?.message || resp.statusText;
    throw new Error(msg || 'Request failed');
  }
  if (payload && Object.prototype.hasOwnProperty.call(payload, 'data')) return payload.data as T;
  return (payload as any) as T;
}

