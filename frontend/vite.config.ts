/// <reference types="vitest/config" />
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const rootDir = path.dirname(fileURLToPath(import.meta.url))
// Defaults 5173/8000 (scripts/dev.py). A QA launcher may run a second app on other ports
// (TJ_WEB_PORT / TJ_API_PORT, scripts/qa_live_check_m6.py) next to the normal one; an empty or
// invalid value falls back to the default. `preview` below stays on 8000 (not used by the QA).
function portFromEnv(value: string | undefined, fallback: number): number {
  const port = Number(value || fallback)
  return Number.isInteger(port) && port > 0 && port < 65536 ? port : fallback
}
const webPort = portFromEnv(process.env.TJ_WEB_PORT, 5173)
const apiTarget = `http://127.0.0.1:${portFromEnv(process.env.TJ_API_PORT, 8000)}`
const localHeaders = {
  'X-Frame-Options': 'DENY',
  'Content-Security-Policy': "frame-ancestors 'none'",
  'X-Content-Type-Options': 'nosniff',
}

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
    headers: localHeaders,
    host: '127.0.0.1',
    port: webPort,
    strictPort: true,
    proxy: {
      '/api': { target: apiTarget, changeOrigin: false },
    },
  },
  test: {
    // M8-17: half the logical CPUs (8 on the 16-thread dev laptop). Vitest's default (all but
    // one) starved every jsdom worker: typing flows took ~4.7 s against the 5 s timeout and
    // the whole run was slower (23 s at 15 workers, 18 s at 8). `--maxWorkers` still wins
    // (trading hours: make check VITEST_WORKERS=2).
    maxWorkers: Math.max(1, Math.floor(os.availableParallelism() / 2)),
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
    headers: localHeaders,
    host: '127.0.0.1',
    port: 4173,
    strictPort: true,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false },
    },
  },
})
