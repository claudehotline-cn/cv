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
        // Always proxy API to Controlplane in dev
        target: 'http://127.0.0.1:18080',
        changeOrigin: true
      },
      '/metrics': {
        // Controlplane metrics endpoint
        target: 'http://127.0.0.1:18080',
        changeOrigin: true
      },
      // WHEP negotiation must go via Controlplane proxy
      '/whep': {
        target: 'http://127.0.0.1:18080',
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
