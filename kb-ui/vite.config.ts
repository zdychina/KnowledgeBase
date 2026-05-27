import { defineConfig } from 'vite'
import { resolve } from 'path'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

export default defineConfig({
  plugins: [
    vue(),
    AutoImport({
      resolvers: [ElementPlusResolver()],
    }),
    Components({
      resolvers: [ElementPlusResolver()],
    }),
  ],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api/mining': {
        target: 'http://localhost:8901',
        rewrite: (path) => path.replace(/^\/api\/mining/, ''),
      },
      '/api/serving': {
        target: 'http://localhost:8081',
        rewrite: (path) => path.replace(/^\/api\/serving/, ''),
      },
      '/api/llm': {
        target: 'http://localhost:8900',
        rewrite: (path) => path.replace(/^\/api\/llm/, ''),
      },
    },
  },
})
