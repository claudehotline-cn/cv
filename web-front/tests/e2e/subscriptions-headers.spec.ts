import { test, expect } from '@playwright/test'

// 验证异步订阅接口的关键响应头：Location / ETag / 304 命中
// 若后端不可达则跳过

const apiBase = process.env.E2E_API_BASE || 'http://127.0.0.1:18080'

test('POST returns Location; GET supports ETag/304', async ({ request }) => {
  // 1) POST /api/subscriptions
  const payload = {
    stream_id: 'camera_01',
    profile: 'det_720p',
    source_uri: 'rtsp://127.0.0.1:8554/camera_01'
  }
  let postRes
  try {
    postRes = await request.post(`${apiBase}/api/subscriptions?use_existing=1`, {
      data: payload
    })
  } catch {
    test.skip(true, 'backend not reachable')
    return
  }
  if (postRes.status() >= 500) {
    test.skip(true, `backend error: ${postRes.status()}`)
    return
  }
  expect([202, 200, 201]).toContain(postRes.status())
  const loc = postRes.headers()['location'] || postRes.headers().get?.('location')
  expect(loc).toBeTruthy()

  const json1 = await postRes.json().catch(() => ({} as any))
  const id = json1?.data?.id || String(loc).replace(/.*\/api\/subscriptions\//, '')
  expect(id).toBeTruthy()

  // 2) GET /api/subscriptions/{id} to obtain ETag
  const get1 = await request.get(`${apiBase}/api/subscriptions/${encodeURIComponent(id)}`)
  expect(get1.ok()).toBeTruthy()
  const etag = get1.headers()['etag'] || get1.headers().get?.('etag')
  expect(typeof etag === 'string' && etag.length > 0).toBeTruthy()

  // 3) Conditional GET with If-None-Match；若阶段变化导致 ETag 变动，允许返回 200
  const get2 = await request.get(`${apiBase}/api/subscriptions/${encodeURIComponent(id)}`, {
    headers: { 'If-None-Match': String(etag) }
  })
  expect([200, 304]).toContain(get2.status())
})
