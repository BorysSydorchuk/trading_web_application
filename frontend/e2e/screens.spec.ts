import { mkdirSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, test, type Page, type Route } from '@playwright/test'
import {
  ACCOUNTS, AI_MODELS, BIAS_CONFIG, BIAS_NOTE, BIAS_NOTES, CALC_INPUT, CALC_RESULT, DESCRIBE_TRADE, DIGEST_LIST_MONTHLY, EMOTION_OPTIONS, JOURNAL_FIELDS,
  JOURNAL_TRADES, MARGIN_REQUEST, MONTHLY_BIAS_NOTE, MONTHLY_DIGEST, SYMBOL_SPECS, TRADE_SYMBOLS,
} from './screens.fixtures'

/**
 * «Студія» screenshots (M8-10a, M8-10b, M8-10c): full-page screenshots of every sidebar page at 1440 and
 * 1280 px, saved to docs/reports/<SCREENS_DIR>/<page>-<width>.png for the PM review.
 * Run: `npm run e2e:screens` (own config, not part of `npm run e2e`, so normal runs do not rewrite
 * the PNGs). The API is answered here with small fictitious data (no backend, no real account data;
 * the M8-10c page data is in screens.fixtures.ts); endpoints without a fixture fail with 503 and the
 * page shows its error state.
 */

const PAGES = [
  ['home', '/'],
  ['inbox', '/inbox'],
  ['journal', '/journal'],
  ['describe', '/trades/24/describe'],
  ['bias', '/bias'],
  ['bias-note', '/bias/41'],
  ['digests', '/digests'],
  ['digest', '/digests/monthly/2026-10-01'],
  ['calculator', '/calculator'],
  ['settings', '/settings'],
] as const
const WIDTHS = [1440, 1280] as const
const HEIGHT = 900

const here = path.dirname(fileURLToPath(import.meta.url))
/** Output folder under docs/reports (default M8-10b-screens) and an optional page filter, e.g.
 * `SCREENS_DIR=M8-10a-screens` or `SCREENS_PAGES=home` (comma-separated names from PAGES). */
const OUT_DIR = path.resolve(here, '../../docs/reports', process.env.SCREENS_DIR ?? 'M8-10b-screens')
const ONLY = process.env.SCREENS_PAGES?.split(',').map((name) => name.trim()).filter(Boolean) ?? []

const NOW = '2026-11-19T13:42:00Z'

/** P&L curve of November like the mockup (cumulative USD per closed trade). */
const NOV_CURVE = ['0', '-20', '-45', '60', '140', '120', '260', '310', '290', '410', '499', '470', '640', '705', '780', '899', '1010', '1241.20']
const dayIso = (day: number, hour = 10) => `2026-11-${String(day).padStart(2, '0')}T${String(hour).padStart(2, '0')}:00:00Z`
const ROLLING_WR = ['45', '48', '46', '50', '52', '50', '55', '57']
const ROLLING_R = ['0.6', '0.7', '0.65', '0.9', '1.0', '0.95', '1.2', '1.3']
const CHARTS = {
  from: '2026-11-01', to: '2026-11-19', currency: 'USD', account_size: '30000.00', trades: NOV_CURVE.length - 1,
  equity: NOV_CURVE.map((v, i) => ({ time: i === 0 ? '2026-10-31T23:00:00Z' : dayIso(1 + i), cum_pnl: v, cum_pct: (Number(v) / 300).toFixed(4) })),
  daily: [
    { day: '2026-11-16', net_pnl: '120.00', pct: '0.4000', trades: 1 },
    { day: '2026-11-17', net_pnl: '-90.00', pct: '-0.3000', trades: 2 },
    { day: '2026-11-18', net_pnl: '310.00', pct: '1.0300', trades: 1 },
    { day: '2026-11-19', net_pnl: '401.00', pct: '1.3400', trades: 2 },
  ],
  rolling: ROLLING_WR.map((wr, i) => ({ time: dayIso(10 + i), n: 20, win_rate: wr, avg_r: ROLLING_R[i] ?? '0' })),
  rolling_window: 20,
}
const position = (o: Record<string, unknown>) => ({
  account_id: 1, account_name: 'Demo A', initial_sl: '26430.00000000', tp: '26556.25000000', price_time: '2026-11-19T13:41:00Z',
  tp_r: '1.5000', risk_pct: '1.0000', described: true, ...o,
})
const HOME = {
  now: NOW, timezone: 'Europe/Brussels',
  session: { key: 'ny', entries_allowed: true },
  bias_today: { pre_london: [{ symbol: 'EURUSD', direction: 'bullish' }, { symbol: 'GER40', direction: 'bullish' }], pre_ny_missing: true },
  limits: {
    account_id: 1, account_name: 'Demo A', currency: 'USD',
    day: { pct: '2.1000', loss_pct: '-3.0000', profit_pct: '5.0000' },
    week: { pct: '2.5000', loss_pct: '-6.0000', profit_pct: '10.0000' },
    month: { pct: '3.1000', loss_pct: '-10.0000', profit_pct: '10.0000' },
    trades_week: 7, max_trades_week: 10, to_daily_stop_pct: '5.1000', floating_pnl: '36.20', floating_included: true,
  },
  kpis: {
    today: {
      pnl: '212.40', pct: '2.1240', trades: 3,
      series: ['0', '45', '30', '110', '96', '160', '212.40'].map((v, i) => ({ time: `2026-11-19T${String(7 + i).padStart(2, '0')}:00:00Z`, cum_pnl: v })),
    },
    win_rate: { value: '57.0000', n: 20, window: 20, series: ROLLING_WR.map((v, i) => ({ time: dayIso(10 + i), value: v })) },
    avg_r: { value: '1.3000', n: 20, window: 20, series: ROLLING_R.map((v, i) => ({ time: dayIso(10 + i), value: v })) },
    max_loss: {
      account_id: 1, account_name: 'Demo A', pct: '13.1240', limit_pct: '-10.0000', equity: '31305.40', equity_source: 'mt5',
      series: ['10', '10.8', '10.2', '11.6', '12.1', '11.7', '12.6', '13.124'].map((v, i) => ({ time: dayIso(1 + 2 * i), pct: v })),
    },
  },
  open_positions: [
    position({
      trade_id: 10, symbol: 'GER40', direction: 'buy', volume: '0.13', open_time: '2026-11-19T12:44:00Z', entry_price: '26480.50000000',
      current_price: '26523.4', pnl: '64.20', r_now: '0.7000', mae_r: '0.2000', mfe_r: '0.8000',
    }),
    position({
      trade_id: 11, symbol: 'EURUSD', direction: 'sell', account_id: 2, account_name: 'Demo B', volume: '0.50', open_time: '2026-11-19T13:05:00Z',
      entry_price: '1.10950000', initial_sl: '1.11150000', tp: '1.10650000', current_price: '1.10910', pnl: '-28.00', r_now: '-0.3000',
      mae_r: '0.4000', mfe_r: '0.1000', described: false,
    }),
    position({
      trade_id: 12, symbol: 'XAUUSD', direction: 'buy', volume: '0.20', open_time: '2026-11-19T13:30:00Z', entry_price: '4100.00000000',
      initial_sl: '4080.00000000', tp: '4130.00000000', current_price: null, pnl: null, r_now: null, price_time: '2026-11-19T13:31:00Z',
      mae_r: '0.3000', mfe_r: '0.4000',
    }),
  ],
  open_totals: { pnl: null, risk_pct: '3.0000', price_time: '2026-11-19T13:31:00Z' },
}
const needTrade = (id: number, symbol: string, day: number, r: string) => ({
  id, account_id: 1, account_name: 'Demo A', position_id: 900 + id, symbol, direction: 'buy', status: 'needs_description',
  open_time: dayIso(day, 9), close_time: dayIso(day, 11), duration_seconds: 7200, entry_price: '1.00000000', exit_price: '1.00100000',
  volume: '0.10', initial_sl: '0.99900000', last_sl: '0.99900000', tp: null, commission: '0.00', swap: '0.00',
  gross_pnl: r.startsWith('-') ? '-100.00' : '150.00', net_pnl: r.startsWith('-') ? '-100.00' : '150.00', pnl_pct: null, balance_at_open: null,
  risk_amount: '100.00', risk_pct: '1.0000', r_multiple: r, planned_rr: null, session: 'ny', weekday: 3, hour: 14, is_reentry: false,
  bias_alignment: null, bias_alignment_weekly: null, bias_alignment_monthly: null, violations: [], excluded_from_stats: false,
  excluded_reason: null, excluded_at: null,
})
const NEEDS = {
  items: [
    needTrade(31, 'XAUUSD', 19, '2.1000'), needTrade(32, 'EURUSD', 18, '-1.0000'), needTrade(33, 'GER40', 18, '1.6000'),
    needTrade(34, 'GBPUSD', 17, '-1.0000'), needTrade(35, 'GER40', 17, '0.4000'),
  ],
  total: 12,
}

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
  '/api/dashboard/charts': CHARTS,
  '/api/home': HOME,
  '/api/trades': JOURNAL_TRADES,
  '/api/trades/symbols': TRADE_SYMBOLS,
  '/api/trades/24': DESCRIBE_TRADE,
  '/api/journal-fields': JOURNAL_FIELDS,
  '/api/journal-options/emotion_before': { field: 'emotion_before', options: EMOTION_OPTIONS },
  '/api/journal-options/emotion_after': { field: 'emotion_after', options: EMOTION_OPTIONS },
  '/api/digests': {
    items: [
      { id: 5, kind: 'weekly', period_start: '2026-11-09', period_end: '2026-11-15', generated_at: '2026-11-15T12:00:00Z', trades: 9, net_pnl: '1241.20', net_pnl_pct: '4.1240', total_r: '6.3000', win_rate: '55.5600', reviewed: true, reviewed_at: '2026-11-16T09:00:00Z' },
      { id: 4, kind: 'weekly', period_start: '2026-11-02', period_end: '2026-11-08', generated_at: '2026-11-08T12:00:00Z', trades: 6, net_pnl: '-120.50', net_pnl_pct: '-1.2050', total_r: '-1.5000', win_rate: '33.3300', reviewed: false, reviewed_at: null },
    ],
  },
  '/api/digests/by-period': MONTHLY_DIGEST,
  '/api/bias/notes': BIAS_NOTES,
  '/api/bias/notes/41': BIAS_NOTE,
  '/api/bias/notes/38': MONTHLY_BIAS_NOTE,
  // The open note's own period: the editor treats it as itself, not a clash.
  '/api/bias/notes/by-period': BIAS_NOTE,
  '/api/bias/config': BIAS_CONFIG,
  '/api/accounts': ACCOUNTS,
  '/api/accounts/1/symbol-specs': SYMBOL_SPECS,
  '/api/accounts/2/symbol-specs': SYMBOL_SPECS,
  '/api/ai/models': AI_MODELS,
  '/api/calculator/margin-requests/91': MARGIN_REQUEST,
  '/api/ai/usage': { month: '2026-11', cost_usd: '1.20', calls: 14, failed_calls: 0, unpriced_calls: 0, input_tokens: 42000, output_tokens: 9000, configured: true, extraction_model: 'claude-sonnet-5-5', key_state: 'ok' },
  '/api/system/desktop': { supported: true, autostart: true, terminals_visible: false },
}

/** POST answers: the calculator result (screenshot of a computed lot) and its live margin request. */
const POSTS: Record<string, unknown> = {
  '/api/calculator/calculate': CALC_RESULT,
  '/api/calculator/margin-requests': MARGIN_REQUEST,
}

function getBody(url: URL): unknown {
  const { pathname, searchParams } = url
  // «Головна» asks /api/trades for the trades waiting for a description (M8-15 tiles).
  if (pathname === '/api/trades' && searchParams.getAll('status').includes('needs_description')) return NEEDS
  if (pathname === '/api/digests' && searchParams.get('kind') === 'monthly') return DIGEST_LIST_MONTHLY
  return FIXTURES[pathname]
}

function answer(route: Route) {
  const url = new URL(route.request().url())
  const body = route.request().method() === 'GET' ? getBody(url) : POSTS[url.pathname]
  return body === undefined ? route.fulfill({ status: 503, json: { detail: 'e2e' } }) : route.fulfill({ json: body })
}

/** «Калькулятор»: fill the form and calculate, so the screenshot shows a result. */
async function calculate(page: Page) {
  const form = page.getByRole('form', { name: 'Калькулятор розміру позиції' })
  await form.getByLabel('Символ').selectOption(CALC_INPUT.symbol)
  await form.getByLabel('Вхід').fill(CALC_INPUT.entry)
  await form.getByLabel('SL, ціна').fill(CALC_INPUT.sl)
  await form.getByLabel('Ризик, %').fill(CALC_INPUT.risk)
  await form.getByRole('button', { name: 'Розрахувати' }).click()
  await page.waitForLoadState('networkidle')
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
  for (const [name, url] of PAGES.filter(([page]) => ONLY.length === 0 || ONLY.includes(page))) {
    test(`screenshot ${name} @${width}`, async ({ page }) => {
      await page.setViewportSize({ width, height: HEIGHT })
      await page.goto(url)
      await expect(page.locator('main')).toBeVisible()
      await page.waitForLoadState('networkidle')
      if (name === 'calculator') await calculate(page)
      await page.evaluate(() => document.fonts.ready)
      await fitContent(page)
      await page.screenshot({ path: path.join(OUT_DIR, `${name}-${width}.png`), fullPage: true, animations: 'disabled' })
    })
  }
}
