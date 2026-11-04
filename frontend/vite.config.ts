import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
export default defineConfig({
  plugins: [vue()], base: '/admin/',
  build: { outDir: '../memory_center/service/static', emptyOutDir: true },
})
