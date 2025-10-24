import { http } from './http'

export interface SystemInfo {
  code: string
  data: any
  success: boolean
}

export interface WalSummary {
  code: string
  success: boolean
  data: { enabled: boolean; failed_restart: number }
}

export interface WalTail {
  code: string
  success: boolean
  data: { count: number; items: string[] }
}

export async function getSystemInfo() {
  return http.get<SystemInfo>('/api/system/info')
}

export async function getWalSummary() {
  return http.get<WalSummary>('/api/admin/wal/summary')
}

export async function getWalTail(n: number) {
  const q = Number.isFinite(n) && n>0 ? n : 200
  return http.get<WalTail>(`/api/admin/wal/tail?n=${q}`)
}

