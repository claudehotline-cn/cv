import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import { resolve } from "path";

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      "@": resolve(__dirname, "./src"),
    },
  },
  server: {
    host: "localhost",
    port: 30000,
    proxy: {
      "/api": {
        target: "http://localhost:8082",
        changeOrigin: true,
      },
      // 视频源管理API代理
      "/api/source-manager": {
        target: "http://localhost:8081/api",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/source-manager/, ""),
      },
      // 视频分析API代理
      "/api/analyzer": {
        target: "http://localhost:8082/api",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/analyzer/, ""),
      },
      // WebRTC信令服务代理
      "/signaling": {
        target: "ws://localhost:8889",
        ws: true,
        changeOrigin: true,
      },
      // WebRTC WebSocket代理
      "/api/webrtc": {
        target: "ws://localhost:8889",
        ws: true,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/webrtc/, ""),
      },
    },
  },
  build: {
    outDir: "dist",
    assetsDir: "assets",
  },
});
