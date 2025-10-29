import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import Components from 'unplugin-vue-components/vite'
import AutoImport from 'unplugin-auto-import/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

export default defineConfig({
  plugins: [
    vue(),
    Components({ resolvers: [ElementPlusResolver()] }),
    AutoImport({ resolvers: [ElementPlusResolver()] })
  ],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        // Default to CP in dev
        target: process.env.VITE_API_BASE || 'http://127.0.0.1:18080',
        changeOrigin: true
      },
      '/metrics': {
        target: process.env.VITE_API_BASE || 'http://127.0.0.1:8082',
        changeOrigin: true
      },
      // VA WHEP negotiation (media path stays on VA; CP does not proxy it)
      '/whep': {
        // Route WHEP via CP proxy by default
        target: process.env.VITE_VA_BASE || 'http://127.0.0.1:18080',
        changeOrigin: true
      }
    }
  },
  resolve: {
    alias: {
      '@': '/src'
    }
  }
})
