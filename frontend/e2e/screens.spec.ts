import { mkdirSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, test, type Page, type Route } from '@playwright/test'

/**
 * M8-10a «Студія» foundations: full-page screenshots of every sidebar page at 1440 and 1280 px,
 * saved to docs/reports/M8-10a-screens/<page>-<width>.png for the PM review.
 * Run: `npm run e2e:screens` (own config, not part of `npm run e2e`, so normal runs do not rewrite
 * the PNGs). The API is answered here with small fictitious data (no backend, no real account data);
 * endpoints without a fixture fail with 503 and the page shows its error state.
 */

const PAGES = [
  ['home', '/'],
  ['inbox', '/inbox'],
  ['journal', '/journal'],
  ['bias', '/bias'],
  ['digests', '/digests'],
  ['calculator', '/calculator'],
  ['settings', '/settings'],
] as const
const WIDTHS = [1440, 1280] as const
const HEIGHT = 900

const here = path.dirname(fileURLToPath(import.meta.url))
const OUT_DIR = path.resolve(here, '../../docs/reports/M8-10a-screens')

const NOW = '2026-11-19T13:42:00Z'

const period = (pnl: string, pct: string) => ({ pnl, pct, low_pnl: '-40.00', low_pct: '-0.0400', high_pnl: pnl, high_pct: pct })

const FIXTURES: Record<string, unknown> = {
  '/api/health': {
    status: 'ok',
    version: '0.8.0',
    time_utc: NOW,
    db: { ok: true, latency_ms: 2, error: null },
    ai: { state: 'ok', checked_at: NOW },
    backups: {
      state: 'ok', last_success_at: '2026-11-18T22:00:00Z', last_failure_at: null, error_code: null, last_error_code: null,
      overdue: false, attempts: 1, failed_attempts: 0, next_due_at: '2026-11-19T22:00:00Z', retry_at: null,
    },
  },
  '/api/sync/status': {
    items: ['Demo A', 'Demo B'].map((name, i) => ({
      account_id: i + 1, account_name: name, state: 'ok', last_attempt_utc: NOW, last_success_utc: NOW,
      error_code: null, error_message: null, server_offset_hours: 2, open_positions: 1,
    })),
  },
  '/api/inbox/counts': { needs_sl: 1, needs_description: 11, draft: 1 },
  '/api/bias/status': {
    date: '2026-11-19', weekday: true, now: NOW,
    sessions: {
      pre_london: { note_id: 7, missing: false, remind: false, from: '07:45', until: '11:00' },
      pre_ny: { note_id: null, missing: true, remind: true, from: '12:30', until: '16:00' },
    },
    weekly: { note_id: 8 }, monthly: { note_id: null },
  },
  '/api/dashboard': {
    now: NOW,
    accounts: [{
      id: 1, name: 'Demo A', currency: 'USD', account_size: '10000.00',
      today: period('212.40', '2.1240'), week: period('741.00', '7.4100'),
      limits: { daily_loss_pct: '-3.0000', daily_profit_pct: '5.0000', weekly_loss_pct: '-6.0000', weekly_profit_pct: '10.0000' },
      today_state: 'ok', week_state: 'ok',
    }],
    stop: { today: false, week: false },
    open_positions: [
      { trade_id: 10, account_name: 'Demo A', symbol: 'GER40', direction: 'buy', volume: '0.13', entry_price: '26480.50000000', open_time: '2026-11-19T12:44:00Z', initial_sl: '26430.00000000', risk_amount: '65.60', risk_pct: '0.6560' },
      { trade_id: 11, account_name: 'Demo B', symbol: 'EURUSD', direction: 'sell', volume: '0.50', entry_price: '1.10950000', open_time: '2026-11-19T13:05:00Z', initial_sl: '1.11150000', risk_amount: '100.00', risk_pct: '1.0000' },
    ],
    inbox: { needs_sl: 1, needs_description: 11, draft: 1 },
  },
  '/api/digests/suggestion': { weekly: null, monthly: null },
  '/api/dashboard/charts': {
    from: '2026-11-01', to: '2026-11-19', currency: 'USD', account_size: '10000.00', trades: 0,
    equity: [], daily: [], rolling: [], rolling_window: 20,
  },
  '/api/trades': { items: [], total: 0 },
  '/api/trades/symbols': { items: [] },
  '/api/digests': {
    items: [
      { id: 5, kind: 'weekly', period_start: '2026-11-09', period_end: '2026-11-15', generated_at: '2026-11-15T12:00:00Z', trades: 9, net_pnl: '1241.20', net_pnl_pct: '4.1240', total_r: '6.3000', win_rate: '55.5600', reviewed: true, reviewed_at: '2026-11-16T09:00:00Z' },
      { id: 4, kind: 'weekly', period_start: '2026-11-02', period_end: '2026-11-08', generated_at: '2026-11-08T12:00:00Z', trades: 6, net_pnl: '-120.50', net_pnl_pct: '-1.2050', total_r: '-1.5000', win_rate: '33.3300', reviewed: false, reviewed_at: null },
    ],
  },
  '/api/bias/notes': { items: [] },
  '/api/accounts': { items: [] },
  '/api/ai/models': { models: [], defaults: { trade_extraction: 'claude-sonnet-5-5', bias_extraction: 'claude-sonnet-5-5', digest_summary: 'claude-opus-5-5' } },
  '/api/ai/usage': { month: '2026-11', cost_usd: '1.20', calls: 14, failed_calls: 0, unpriced_calls: 0, input_tokens: 42000, output_tokens: 9000, configured: true, extraction_model: 'claude-sonnet-5-5', key_state: 'ok' },
  '/api/system/desktop': { supported: true, autostart: true, terminals_visible: false },
}

function answer(route: Route) {
  const { pathname } = new URL(route.request().url())
  const body = route.request().method() === 'GET' ? FIXTURES[pathname] : undefined
  return body === undefined ? route.fulfill({ status: 503, json: { detail: 'e2e' } }) : route.fulfill({ json: body })
}

/** <main> is the only scroll container: grow the viewport until its whole content is visible. */
async function fitContent(page: Page) {
  const extra = await page.locator('main').evaluate((el) => el.scrollHeight - el.clientHeight)
  if (extra > 0) {
    const viewport = page.viewportSize()
    if (viewport) await page.setViewportSize({ width: viewport.width, height: viewport.height + extra })
  }
}

test.beforeAll(() => {
  mkdirSync(OUT_DIR, { recursive: true })
})

test.beforeEach(async ({ page }) => {
  await page.route((url) => url.pathname.startsWith('/api/'), answer)
})

for (const width of WIDTHS) {
  for (const [name, url] of PAGES) {
    test(`screenshot ${name} @${width}`, async ({ page }) => {
      await page.setViewportSize({ width, height: HEIGHT })
      await page.goto(url)
      await expect(page.locator('main')).toBeVisible()
      await page.waitForLoadState('networkidle')
      await page.evaluate(() => document.fonts.ready)
      await fitContent(page)
      await page.screenshot({ path: path.join(OUT_DIR, `${name}-${width}.png`), fullPage: true, animations: 'disabled' })
    })
  }
}
