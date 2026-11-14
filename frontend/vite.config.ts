/// <reference types="vitest/config" />
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const rootDir = path.dirname(fileURLToPath(import.meta.url))
// Defaults 5173/8000 (scripts/dev.py). A QA launcher may run a second app on other ports
// (TJ_WEB_PORT / TJ_API_PORT, scripts/qa_live_check_m6.py) next to the normal one.
const webPort = Number(process.env.TJ_WEB_PORT ?? 5173)
const apiTarget = `http://127.0.0.1:${Number(process.env.TJ_API_PORT ?? 8000)}`

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': path.resolve(rootDir, 'src') },
  },
  build: {
    rolldownOptions: {
      output: {
        // Vendor chunks: cached across app releases and keep every chunk under the 500 kB warning.
        codeSplitting: {
          groups: [
            { name: 'vendor-react', test: /node_modules[\\/](react|react-dom|scheduler)[\\/]/ },
            { name: 'vendor-router', test: /node_modules[\\/]react-router[\\/]/ },
            { name: 'vendor', test: /node_modules[\\/]/ },
          ],
        },
      },
    },
  },
  server: {
    host: '127.0.0.1',
    port: webPort,
    strictPort: true,
    proxy: {
      '/api': { target: apiTarget, changeOrigin: false },
    },
  },
  test: {
    // Explicit imports from 'vitest' (no globals). Two projects, one `vitest run`:
    // pure-logic tests (*.test.ts) in Node, component tests (*.test.tsx) in jsdom with MSW.
    projects: [
      {
        extends: true,
        test: { name: 'logic', include: ['src/**/*.test.ts'], environment: 'node' },
      },
      {
        extends: true,
        test: {
          name: 'components',
          include: ['src/**/*.test.tsx'],
          environment: 'jsdom',
          setupFiles: ['./src/test/setup.ts'],
        },
      },
    ],
  },
  preview: {
    host: '127.0.0.1',
    port: 4173,
    strictPort: true,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false },
    },
  },
})
