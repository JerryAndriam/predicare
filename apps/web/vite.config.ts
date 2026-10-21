import { defineConfig } from 'vite'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'

// En production, le navigateur ne voit qu'une seule origine : la passerelle
// Traefik route /api/core, /api/inference et /api/rag vers le bon service.
// En developpement, on reproduit EXACTEMENT ce routage avec trois proxys,
// sinon l'ecran « alertes » appellerait api-core pour /api/rag et echouerait.
const cible = (port: number) => `http://localhost:${port}`

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api/core': { target: cible(8001), changeOrigin: true },
      '/api/inference': { target: cible(8002), changeOrigin: true },
      '/api/rag': { target: cible(8003), changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
})
