import { test, expect } from '@playwright/test'
import fs from 'fs'
import path from 'path'

const base = process.env.E2E_BASE_URL || 'http://127.0.0.1:4173'
const outDir = path.resolve(process.cwd(), 'tests', 'artifacts')

test.beforeAll(async () => {
  if (!fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true })
})

test('screenshot observability and analysis', async ({ page }) => {
  // Observability
  await page.goto(base.replace(/\/+$/,'') + '/#/observability')
  await page.waitForLoadState('load')
  const obsPath = path.join(outDir, 'observability.png')
  await page.screenshot({ path: obsPath, fullPage: true })
  console.log('screenshot:', obsPath)

  // Analysis (初始态)
  await page.goto(base.replace(/\/+$/,'') + '/#/analysis')
  await page.waitForLoadState('load')
  const anaPath = path.join(outDir, 'analysis.png')
  await page.screenshot({ path: anaPath, fullPage: true })
  console.log('screenshot:', anaPath)
})

