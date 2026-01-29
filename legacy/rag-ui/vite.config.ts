import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      // RAG API requests to rag-service
      '/api/agents/article': {
        target: 'http://article-agent:8130',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/agents\/article/, '')
      },
      '/api/agents/data': {
        target: 'http://agent-langchain:8100',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/agents\/data/, '')
      },
      '/api': {
        target: 'http://rag-service:8200',
        changeOrigin: true
      }
    }
  }
})
