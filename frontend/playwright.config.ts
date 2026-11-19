import { defineConfig } from '@playwright/test'

// Browser layout regressions (M8-11). Runs the Vite dev server on its own port; every /api call is
// answered inside the test (no backend, no real data). Uses the installed Chrome: no browser download.
const port = 5197

export default defineConfig({
  testDir: './e2e',
  // Design screenshots run on demand only (playwright.screens.config.ts, npm run e2e:screens).
  testIgnore: ['**/screens.spec.ts'],
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: 'list',
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    channel: 'chrome',
    headless: true,
    viewport: { width: 1280, height: 800 },
  },
  webServer: {
    command: 'npm run dev',
    url: `http://127.0.0.1:${port}`,
    reuseExistingServer: false,
    timeout: 60_000,
    // TJ_API_PORT 9 (discard): nothing leaves the machine even if a request escaped the mock.
    env: { TJ_WEB_PORT: String(port), TJ_API_PORT: '9' },
  },
})
