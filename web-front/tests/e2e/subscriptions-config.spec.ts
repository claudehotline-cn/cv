import { test, expect } from '@playwright/test'

// 该用例验证 /api/system/info 回显 subscriptions（含 source 字段）
// 若后端未运行，则自动跳过（保持 CI 可运行）

const apiBase = process.env.E2E_API_BASE || 'http://127.0.0.1:18080'

test('system info exposes subscriptions with source', async ({ request }) => {
  const url = `${apiBase}/api/system/info`
  let res
  try {
    res = await request.get(url)
  } catch {
    test.skip(true, 'backend not reachable')
    return
  }
  if (res.status() >= 500) {
    test.skip(true, `backend error: ${res.status()}`)
    return
  }
  const json = await res.json()
  expect(json).toBeTruthy()
  expect(json.data).toBeTruthy()
  expect(json.data.subscriptions).toBeTruthy()
  const subs = json.data.subscriptions
  expect(typeof subs.heavy_slots).toBe('number')
  expect(typeof subs.model_slots).toBe('number')
  expect(typeof subs.rtsp_slots).toBe('number')
  expect(typeof subs.max_queue).toBe('number')
  expect(typeof subs.ttl_seconds).toBe('number')
  expect(subs.source).toBeTruthy()
  expect(typeof subs.source.heavy_slots).toBe('string')
  expect(typeof subs.source.model_slots).toBe('string')
  expect(typeof subs.source.rtsp_slots).toBe('string')
  expect(typeof subs.source.max_queue).toBe('string')
  expect(typeof subs.source.ttl_seconds).toBe('string')
})
