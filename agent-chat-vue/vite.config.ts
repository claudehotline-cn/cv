import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 3000,
    proxy: {
      '/api': {
        // In Docker: agent-chat-api, in local dev: localhost
        target: process.env.API_PROXY_TARGET || 'http://agent-chat-api:8000',
        changeOrigin: true,
      },
    },
  },
})
