import { defineConfig } from '@playwright/test'
import base from './playwright.config'

// M8-10a design screenshots (e2e/screens.spec.ts): same dev server and mocked API as the layout
// tests, run on demand with `npm run e2e:screens`. Writes docs/reports/M8-10a-screens/*.png.
export default defineConfig({
  ...base,
  testIgnore: [],
  testMatch: 'screens.spec.ts',
})
