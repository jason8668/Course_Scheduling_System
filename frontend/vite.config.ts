import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: true,
    port: 5173,
    // 开发模式:/api 代理到后端。
    // Docker 内用服务名 api;本机直跑时设 VITE_API_PROXY=http://localhost:8000。
    proxy: {
      '/api': {
        target: process.env.VITE_API_PROXY || 'http://api:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    // 只跑 src 内的单元测试;e2e/ 由 Playwright 执行
    include: ['src/**/*.{test,spec}.ts'],
  },
})
