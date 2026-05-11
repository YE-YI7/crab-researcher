import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    port: 3000,
    proxy: {
      '/api': 'http://localhost:8002',
    },
  },
  build: {
    // Split React/runtime libs into their own chunk so app code can change
    // without busting the (much more stable) vendor cache.
    rollupOptions: {
      output: {
        manualChunks: {
          'react-vendor': ['react', 'react-dom'],
          markdown: ['react-markdown'],
        },
      },
    },
    // Quiet the default 500 KB warning — we're well under it; the heads-up
    // is more annoying than helpful at our size.
    chunkSizeWarningLimit: 600,
  },
})
