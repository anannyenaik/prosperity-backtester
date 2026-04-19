import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: './',
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    sourcemap: false,
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      output: {
        manualChunks(id) {
          const moduleId = id.replace(/\\/g, '/')
          if (moduleId.includes('/node_modules/recharts/')) {
            return 'charts'
          }
          if (
            moduleId.includes('/node_modules/react/') ||
            moduleId.includes('/node_modules/react-dom/') ||
            moduleId.includes('/node_modules/scheduler/')
          ) {
            return 'vendor'
          }
        },
      },
    },
  },
  server: {
    port: 5174,
    proxy: {
      '/api': 'http://127.0.0.1:5555',
    },
  },
})
