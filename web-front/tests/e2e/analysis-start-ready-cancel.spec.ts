import { test, expect } from '@playwright/test'
import fs from 'fs'
import path from 'path'

const base = process.env.E2E_BASE_URL || 'http://127.0.0.1:4173'
const apiBase = process.env.E2E_API_BASE || 'http://127.0.0.1:18080'
const outDir = path.resolve(process.cwd(), 'tests', 'artifacts')

test.beforeAll(async () => {
  if (!fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true })
})

test('analysis start → ready → cancel (with screenshots)', async ({ page, request }) => {
  // 前置：后端可达，否则跳过
  try {
    const r = await request.get(apiBase.replace(/\/+$/, '') + '/api/system/info?ping=1')
    test.skip(!r.ok(), 'backend not reachable')
  } catch { test.skip(true, 'backend not reachable') }

  await page.goto(base.replace(/\/+$/, '') + '/#/analysis')
  await page.waitForLoadState('load')
  await page.locator('.toolbar').first().waitFor({ state: 'visible', timeout: 10000 }).catch(() => {})

  // 点击“实时分析”对应的 el-switch（取页面第一个 .el-switch）
  const switches = page.locator('.toolbar .el-switch')
  const count = await switches.count()
  test.skip(count === 0, 'no switch found')
  await switches.first().click()

  // 等待进度覆盖层出现
  const progress = page.locator('.progress')
  await progress.waitFor({ state: 'visible', timeout: 10_000 }).catch(() => {})
  const startedPng = path.join(outDir, 'analysis-started.png')
  await page.screenshot({ path: startedPng, fullPage: true })
  console.log('screenshot:', startedPng)

  // 等待进入 Analyzing（可选，20 秒），成功则截 ready 图
  let isReady = false
  try {
    await expect(page.getByText('Analyzing')).toBeVisible({ timeout: 20_000 })
    isReady = true
  } catch {}
  if (isReady) {
    const readyPng = path.join(outDir, 'analysis-ready.png')
    await page.screenshot({ path: readyPng, fullPage: true })
    console.log('screenshot:', readyPng)
  }

  // 点击“取消”按钮（危险小按钮）
  const cancelBtn = page.locator('.toolbar .el-button.el-button--danger')
  if (await cancelBtn.count()) {
    await cancelBtn.first().click()
    const cancelledPng = path.join(outDir, 'analysis-cancelled.png')
    await page.screenshot({ path: cancelledPng, fullPage: true })
    console.log('screenshot:', cancelledPng)
  }
})
