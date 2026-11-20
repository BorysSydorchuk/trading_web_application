import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, test, type Page, type Route } from '@playwright/test'

/**
 * «Головна» hero chart x labels (M8-10b owner fix): a short history (trades from 28.10.2026) in
 * every range at 1280 and 1440 px. Date labels must not overlap or repeat, value labels and the last
 * pill must not overlap, and the «дані з 28.10» note shows only when the data starts a week or more
 * after the range start. The API is answered here with fictitious data; everything else fails with 503.
 * `HERO_SCREENS=1` also saves the «Рік» hero card to docs/reports/M8-10b-screens/hero-year-<width>.png.
 */

const WIDTHS = [1280, 1440] as const
const NOW = '2026-11-20T12:00:00Z'
const FIRST_TRADE_DAY = '2026-10-28'
const SAVE_SCREENS = process.env.HERO_SCREENS === '1'
const OUT_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../docs/reports/M8-10b-screens')

/** Range button text, the first x label expected (the first trade inside the range), note shown. */
const RANGES = [
  { name: 'Тиждень', first: '16.11', note: false },
  { name: 'Місяць', first: '02.11', note: false },
  { name: '3 міс', first: '28.10', note: true },
  { name: 'Рік', first: '28.10', note: true },
  { name: 'Усе', first: '28.10', note: true },
] as const

const DAY_MS = 86_400_000

/** Two trades every weekday from 28.10 to 20.11 (10:00 and 14:00 UTC). */
const TRADE_TIMES: string[] = (() => {
  const times: string[] = []
  for (let ms = Date.parse(`${FIRST_TRADE_DAY}T00:00:00Z`); ms <= Date.parse(NOW); ms += DAY_MS) {
    const day = new Date(ms)
    if (day.getUTCDay() === 0 || day.getUTCDay() === 6) continue
    const iso = day.toISOString().slice(0, 10)
    times.push(`${iso}T10:00:00Z`, `${iso}T14:00:00Z`)
  }
  return times.filter((t) => t <= NOW)
})()

/** GET /api/dashboard/charts for the requested range: 0 at the range start, then the trades in range. */
function charts(from: string, to: string) {
  const trades = TRADE_TIMES.filter((t) => t.slice(0, 10) >= from && t.slice(0, 10) <= to)
  const start = new Date(`${from}T00:00:00+01:00`).toISOString()
  const equity = [{ time: start, cum_pnl: '0.00', cum_pct: '0.0000' }]
  trades.forEach((time, i) => {
    const cum = ((i + 1) * 37 - (i % 3) * 55).toFixed(2)
    equity.push({ time, cum_pnl: cum, cum_pct: (Number(cum) / 100).toFixed(4) })
  })
  return {
    from, to, currency: 'USD', account_size: '10000.00', trades: trades.length, equity,
    daily: [], rolling: [], rolling_window: 20,
  }
}

function answer(route: Route) {
  const url = new URL(route.request().url())
  if (route.request().method() === 'GET' && url.pathname === '/api/dashboard/charts') {
    return route.fulfill({ json: charts(url.searchParams.get('from') ?? '', url.searchParams.get('to') ?? '') })
  }
  return route.fulfill({ status: 503, json: { detail: 'e2e' } })
}

interface LabelBox {
  text: string
  left: number
  right: number
  top: number
  bottom: number
}

function boxes(page: Page, testId: string): Promise<LabelBox[]> {
  return page.locator(`[data-testid="${testId}"]`).evaluateAll((els) =>
    els.map((el) => {
      const r = el.getBoundingClientRect()
      return { text: el.textContent ?? '', left: r.left, right: r.right, top: r.top, bottom: r.bottom }
    }),
  )
}

const xLabels = (page: Page) => boxes(page, 'hero-x-label')

const overlaps = (a: LabelBox, b: LabelBox) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom

function expectNoOverlap(labels: readonly LabelBox[], where: string) {
  labels.forEach((a, i) => {
    for (const b of labels.slice(i + 1)) expect(overlaps(a, b), `${where}: «${a.text}» overlaps «${b.text}»`).toBe(false)
  })
}

function heroCard(page: Page) {
  return page.getByRole('radiogroup', { name: 'Період графіка' }).locator('xpath=ancestor::section[1]')
}

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(new Date(NOW))
  await page.route((url) => url.pathname.startsWith('/api/'), answer)
})

for (const width of WIDTHS) {
  test(`hero x labels do not overlap or repeat in every range @${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/')
    const group = page.getByRole('radiogroup', { name: 'Період графіка' })
    await expect(group).toBeVisible()
    for (const range of RANGES) {
      await group.getByRole('radio', { name: range.name, exact: true }).click()
      await expect.poll(async () => (await xLabels(page))[0]?.text, { message: `${range.name}: first label` }).toBe(range.first)
      const labels = await xLabels(page)
      const where = `${range.name} @${width}`
      expect(labels.length, `${where}: label count`).toBeGreaterThanOrEqual(2)
      const texts = labels.map((l) => l.text)
      expect(new Set(texts).size, `${where}: duplicate texts ${texts.join(', ')}`).toBe(texts.length)
      expectNoOverlap(labels, `${where} date`)
      const values = await boxes(page, 'hero-value-label')
      expect(values.length, `${where}: value labels`).toBeGreaterThanOrEqual(1)
      expectNoOverlap(values, `${where} value`)
      const note = page.getByTestId('hero-data-from')
      if (range.note) await expect(note, where).toBeVisible()
      else await expect(note, where).toHaveCount(0)
      if (range.first === '28.10' && range.note) await expect(note).toHaveText('дані з 28.10')
      if (SAVE_SCREENS && range.name === 'Рік') {
        await page.evaluate(() => document.fonts.ready)
        await heroCard(page).screenshot({ path: path.join(OUT_DIR, `hero-year-${width}.png`), animations: 'disabled' })
      }
    }
  })
}
