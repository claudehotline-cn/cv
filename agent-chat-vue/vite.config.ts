import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
      // Docker: /agent-sdk, Local: ../agent-sdk
      '@agent-sdk': process.env.DOCKER_ENV
        ? '/agent-sdk'
        : resolve(__dirname, '../agent-sdk'),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 3000,
    allowedHosts: true,
    proxy: {
      '/api': {
        // In Docker: agent-api, in local dev: localhost
        target: process.env.API_PROXY_TARGET || 'http://agent-api:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
