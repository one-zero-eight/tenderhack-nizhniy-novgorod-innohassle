import { defineConfig } from 'vite'
import { tanstackRouter } from '@tanstack/router-plugin/vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

// https://vite.dev/config/
export default defineConfig({
  server: {
    port: 3000,
    watch: {
      usePolling: true, // Required for file watching in Docker
    },
    host: true,
  },
  plugins: [
    tanstackRouter({
      target: 'react',
      semicolons: true,
      quoteStyle: 'single',
      autoCodeSplitting: true,
      routeFileIgnorePrefix: '-',
      routesDirectory: 'src/app/routes',
      generatedRouteTree: 'src/app/routeTree.gen.ts',
    }),
    react(),
    tailwindcss(),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
})
