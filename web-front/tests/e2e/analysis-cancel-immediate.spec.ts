import { test, expect } from '@playwright/test'
import fs from 'fs'
import path from 'path'

const base = process.env.E2E_BASE_URL || 'http://127.0.0.1:4173'
const apiBase = process.env.E2E_API_BASE || 'http://127.0.0.1:18080'
const outDir = path.resolve(process.cwd(), 'tests', 'artifacts')

test.beforeAll(async () => {
  if (!fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true })
})

test('analysis start and cancel immediately', async ({ page, request }) => {
  try {
    const r = await request.get(apiBase.replace(/\/+$/, '') + '/api/system/info?ping=1')
    test.skip(!r.ok(), 'backend not reachable')
  } catch { test.skip(true, 'backend not reachable') }

  await page.goto(base.replace(/\/+$/, '') + '/#/analysis')
  await page.waitForLoadState('load')

  const switches = page.locator('.toolbar .el-switch')
  await switches.first().click()

  const cancelBtn = page.locator('.toolbar .el-button.el-button--danger')
  await cancelBtn.first().click()

  const png = path.join(outDir, 'analysis-cancel-immediate.png')
  await page.screenshot({ path: png, fullPage: true })
  console.log('screenshot:', png)

  // 至少不处于 Analyzing
  await expect(page.getByText('Analyzing')).toHaveCount(0)
})
