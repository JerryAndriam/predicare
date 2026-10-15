import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// `VITE_API_BASE_URL` est injecte a la construction (ARG de build Docker).
// En developpement local, Vite proxifie /api vers api-core pour reproduire
// l'architecture de production : le navigateur ne voit qu'une seule origine.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.VITE_API_BASE_URL ?? 'http://localhost:8001',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
})