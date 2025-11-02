import { test, expect } from '@playwright/test'
import fs from 'fs'
import path from 'path'

const base = process.env.E2E_BASE_URL || 'http://127.0.0.1:4173'
const apiBase = process.env.E2E_API_BASE || 'http://127.0.0.1:18080'
const outDir = path.resolve(process.cwd(), 'tests', 'artifacts')

test.beforeAll(async () => {
  if (!fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true })
})

test('timeline durations should show non-zero in at least one phase', async ({ page, request }) => {
  // 后端可达，否则跳过
  try {
    const r = await request.get(apiBase.replace(/\/+$/, '') + '/api/system/info?ping=1')
    test.skip(!r.ok(), 'backend not reachable')
  } catch { test.skip(true, 'backend not reachable') }

  await page.goto(base.replace(/\/+$/, '') + '/#/analysis')
  await page.waitForLoadState('load')

  const switches = page.locator('.toolbar .el-switch')
  await switches.first().click()

  const progress = page.locator('.progress')
  await progress.waitFor({ state: 'visible', timeout: 10000 }).catch(() => {})

  // 等待时间线出现并提取文本
  const tl = page.locator('.timeline')
  await tl.waitFor({ state: 'visible', timeout: 20000 }).catch(() => {})
  const txt = (await tl.textContent()) || ''

  // 解析秒值，允许出现 0，但至少一项应 >0
  const num = (label: string) => {
    const m = new RegExp(label + '\\s+([0-9]+\\.[0-9]+|[0-9]+)s').exec(txt)
    return m ? parseFloat(m[1]) : 0
  }
  const vOpen = num('RTSP')
  const vLoad = num('模型')
  const vStart = num('启动')
  const anyPositive = (vOpen > 0) || (vLoad > 0) || (vStart > 0)
  expect(anyPositive).toBeTruthy()

  const png = path.join(outDir, 'timeline-assert.png')
  await page.screenshot({ path: png, fullPage: true })
  console.log('screenshot:', png)
})
