import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    // Proxy API requests to the Flask backend during development.
    // When you fetch("/api/status"), Vite forwards it to Flask at :8080.
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
    },
  },
  build: {
    // Output the production build to ../dashboard/static/react so Flask
    // can serve it directly — no separate frontend server needed.
    outDir: '../dashboard/static/react',
    emptyOutDir: true,
  },
})
