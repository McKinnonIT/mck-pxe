import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(__dirname, './src') } },
  server: {
    // Dev: run the API with DEV_USER set, e.g. `uvicorn mckpxe.main:app --port 8000`
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
})
