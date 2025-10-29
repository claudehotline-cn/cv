import { test, expect } from '@playwright/test'

const base = process.env.E2E_BASE_URL || 'http://127.0.0.1:4173'
const apiBase = process.env.E2E_API_BASE || 'http://127.0.0.1:18080'

test('observability page shows subscriptions source', async ({ page, request }) => {
  // 预览服务不可达则跳过
  let previewOk = false
  try {
    const r = await request.get(base.replace(/\/+$/,'') + '/')
    previewOk = r.ok()
  } catch { previewOk = false }
  test.skip(!previewOk, 'preview server not reachable')
  await page.goto(base.replace(/\/+$/,'') + '/#/observability')
  const label = page.getByText('Subscriptions source:')
  await expect(label).toBeVisible()
  // 如果后端可达，则进一步校验来源值是否为 env/config/defaults
  let okApi = false
  try {
    const r = await request.get(apiBase.replace(/\/+$/,'') + '/api/system/info')
    okApi = r.ok()
  } catch { okApi = false }
  if (okApi) {
    const text = await page.locator('.sys-grid').textContent()
    expect(text || '').toMatch(/Subscriptions source:/)
    expect(text || '').toMatch(/heavy=|model=|rtsp=|queue=|ttl=/)
  }
})
