import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The built UI ships inside the Python wheel (no CDN: works offline / air-gapped).
export default defineConfig({
  plugins: [react()],
  base: './',
  build: {
    outDir: '../python/src/glowtrace/_ui',
    emptyOutDir: true,
    chunkSizeWarningLimit: 1500,
  },
  server: {
    proxy: { '/_glowtrace/api': 'http://127.0.0.1:8000' },
  },
})
