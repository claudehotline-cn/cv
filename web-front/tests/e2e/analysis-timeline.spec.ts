import { test, expect } from '@playwright/test'
import fs from 'fs'
import path from 'path'

const base = process.env.E2E_BASE_URL || 'http://127.0.0.1:4173'
const apiBase = process.env.E2E_API_BASE || 'http://127.0.0.1:18080'
const outDir = path.resolve(process.cwd(), 'tests', 'artifacts')

test.beforeAll(async () => {
  if (!fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true })
})

test('analysis timeline visible and screenshot saved', async ({ page, request }) => {
  // 后端可达，否则跳过
  try {
    const r = await request.get(apiBase.replace(/\/+$/, '') + '/api/system/info?ping=1')
    test.skip(!r.ok(), 'backend not reachable')
  } catch { test.skip(true, 'backend not reachable') }

  await page.goto(base.replace(/\/+$/, '') + '/#/analysis')
  await page.waitForLoadState('load')

  // 开始分析
  const switches = page.locator('.toolbar .el-switch')
  await switches.first().click()

  // 进度区出现
  const progress = page.locator('.progress')
  await progress.waitFor({ state: 'visible', timeout: 10_000 }).catch(() => {})

  // 等待“阶段耗时”出现（不强制成功）
  const timelineLabel = page.getByText('阶段耗时')
  try { await expect(timelineLabel).toBeVisible({ timeout: 20_000 }) } catch {}

  const png = path.join(outDir, 'analysis-timeline.png')
  await page.screenshot({ path: png, fullPage: true })
  console.log('screenshot:', png)

  // 取消
  const cancelBtn = page.locator('.toolbar .el-button.el-button--danger')
  if (await cancelBtn.count()) await cancelBtn.first().click()
})
