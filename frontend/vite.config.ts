import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 前端只负责规格编辑与出图预览，绘图/排版仍在 Python 后端（api.py）。
// 开发时把 /api 代理到 127.0.0.1:8000，业务代码一律使用相对路径。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    // 样例规格位于仓库根的 examples/ 下，需要允许读取工程目录之外的文件
    fs: { allow: ['..'] },
    proxy: {
      // 只匹配 /api 与 /api/*，避免误伤 /api-platform 等前端路由
      '^/api(?:/|$)': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: false,
      },
    },
  },
  // npm run preview 也走同一个后端，方便检查构建产物
  preview: {
    port: 4173,
    proxy: {
      '^/api(?:/|$)': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: false,
      },
    },
  },
})
