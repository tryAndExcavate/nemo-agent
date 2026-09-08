import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 后端 FastAPI 路由前缀（来自 app/api/* 的 APIRouter prefix）
const BACKEND_PREFIXES = [
  '/agent', '/api', '/file', '/chat', '/session',
  '/branches', '/models', '/base', '/conversations',
]
// FastAPI 直接托管的独立静态页面（Vite 本身不提供，需转发到后端）
const BACKEND_PAGES = ['/blueprint.html']

const proxy = {}
for (const p of [...BACKEND_PREFIXES, ...BACKEND_PAGES]) {
  proxy[p] = { target: 'http://localhost:8888', changeOrigin: true }
}

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy,
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
