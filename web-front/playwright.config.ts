import { defineConfig } from '@playwright/test'

// 基础配置：
// - baseURL 用于页面导航；默认从 E2E_BASE_URL 读取，否则使用 http://127.0.0.1:4173
// - 也支持直接使用 request fixture 调用后端 API：E2E_API_BASE
export default defineConfig({
  testDir: 'tests/e2e',
  timeout: 60_000,
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://127.0.0.1:4173',
    headless: true,
    trace: 'off',
  },
  reporter: [['list']],
})

