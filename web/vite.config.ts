import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Dev server (npm run dev, port 5173) forwards API calls to FastAPI on port 8000, so the
// browser sees one origin and no CORS setup is needed. The production build (npm run build)
// is served by FastAPI itself at /web/, hence the relative base.
const API = process.env.API_URL ?? 'http://127.0.0.1:8000'

export default defineConfig({
  base: './',
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(import.meta.dirname, 'src') } },
  server: {
    port: 5173,
    proxy: { '/api': API, '/health': API },
  },
})
