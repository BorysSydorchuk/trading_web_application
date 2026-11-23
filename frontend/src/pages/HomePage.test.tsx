import { act, screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Sidebar } from '@/components/layout/Sidebar'
import { biasKeys, invalidateAfterWrite } from '@/features/bias/api'
import type { BiasStatus } from '@/features/bias/types'
import { dashboardAccount, emptyDashboard } from '@/features/dashboard/dashboard.fixture'
import { fixtureTrade } from '@/features/describe/trade.fixture'
import type { HomeCharts } from '@/features/dashboard/homeCharts/api'
import { homeKeys } from '@/features/home/api'
import { HOME_NOW, homeCharts, homeData, homeLimits, homeMaxLoss, homePosition } from '@/features/home/home.fixture'
import type { HomeData } from '@/features/home/types'
import { uk } from '@/i18n/uk'
import { createQueryClient } from '@/lib/query-client'
import { renderWithProviders } from '@/test/render'
import { mockApi } from '@/test/server'
import { HomePage } from './HomePage'

const t = uk.bias.status
const h = uk.home
const MINUS = '−'
const TOTAL = '[data-testid="hero-total"]'
/** U+202F, the overview thousands separator (queries normalize it, textContent keeps it). */
const NNBSP = ' '

function status(overrides: Partial<BiasStatus> = {}): BiasStatus {
  return {
    date: '2026-11-06', weekday: true, now: '2026-11-06T11:30:00Z',
    sessions: {
      pre_london: { note_id: 7, missing: false, remind: false, from: '07:45', until: '11:00' },
      pre_ny: { note_id: null, missing: true, remind: true, from: '12:30', until: '16:00' },
    },
    weekly: { note_id: 8 }, monthly: { note_id: null }, ...overrides,
  }
}

function serveHome(data: HomeData = homeData(), asked: URLSearchParams[] = []) {
  mockApi(http.get('/api/home', ({ request }) => {
    asked.push(new URL(request.url).searchParams)
    return HttpResponse.json(data)
  }))
}

function serveCharts(data: HomeCharts = homeCharts()) {
  mockApi(http.get('/api/dashboard/charts', () => HttpResponse.json(data)))
}

// Every Home block loads its own endpoint; by default they answer empty / like the mockup.
beforeEach(() => {
  // Range presets use today's Brussels date: pin it to the fixture's «now» (only Date is faked).
  vi.useFakeTimers({ toFake: ['Date'], now: new Date(HOME_NOW) })
  mockApi(
    http.get('/api/dashboard', () => HttpResponse.json(emptyDashboard())),
    http.get('/api/digests/suggestion', () => HttpResponse.json({ weekly: null, monthly: null })),
    http.get('/api/trades', () => HttpResponse.json({ items: [], total: 0 })),
    http.get('/api/bias/status', () => HttpResponse.json(status())),
  )
  serveHome()
})
afterEach(() => {
  vi.useRealTimers()
  window.localStorage.clear()
})

function serveSidebar() {
  mockApi(http.get('/api/inbox/counts', () => HttpResponse.json({ needs_sl: 0, needs_description: 0, draft: 0 })))
}

describe('HomePage layout (M8-10b)', () => {
  it('renders the sections in the mockup order', async () => {
    serveCharts()
    renderWithProviders(<HomePage />)
    await screen.findByText('+741', { selector: TOTAL })
    expect(screen.getByRole('heading', { level: 1, name: h.title })).toBeInTheDocument()
    const titles = screen.getAllByRole('heading', { level: 2 }).map((el) => el.textContent)
    expect(titles).toEqual([
      h.hero.pnlTitle('листопад'),
      h.limits.title,
      h.positions.title,
      h.needs.title,
      h.daily.title,
      h.form.title(20),
      t.title,
    ])
    // KPI toggles sit between the open positions and «Потрібен опис».
    const kpis = screen.getByRole('group', { name: h.kpis.label })
    const positions = screen.getByRole('heading', { name: h.positions.title })
    const needs = screen.getByRole('heading', { name: h.needs.title })
    expect(positions.compareDocumentPosition(kpis) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(kpis.compareDocumentPosition(needs) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('shows the header chips: session, London bias with arrows, «+ Біас NY», calculator link', async () => {
    renderWithProviders(<HomePage />)
    const chips = await screen.findByRole('navigation', { name: h.header.chips })
    expect(await within(chips).findByText(h.header.session('NY', h.header.entriesAllowed))).toBeInTheDocument()
    expect(within(chips).getByText(h.header.london('EURUSD ↑ GER40 ↑'))).toBeInTheDocument()
    expect(within(chips).getByRole('link', { name: h.header.biasNyLabel })).toHaveAttribute('href', '/bias/new?kind=pre_ny&date=2026-11-19')
    expect(within(chips).getByRole('link', { name: h.header.calculator })).toHaveAttribute('href', '/calculator')
    // The old compact calculator is gone: the full page has the same function.
    expect(screen.queryByRole('region', { name: uk.calculator.home.title })).not.toBeInTheDocument()
  })

  it('a missing London bias is a warning chip linking to a new note; no NY chip when it is recorded', async () => {
    serveHome(homeData({ session: { key: 'outside', entries_allowed: false }, bias_today: { pre_london: null, pre_ny_missing: false } }))
    renderWithProviders(<HomePage />)
    const chips = await screen.findByRole('navigation', { name: h.header.chips })
    const london = await within(chips).findByRole('link', { name: h.header.londonMissing })
    expect(london).toHaveAttribute('href', '/bias/new?kind=pre_london&date=2026-11-19')
    expect(within(london).getByText(h.header.londonMissing)).toHaveClass('text-warning')
    expect(within(chips).queryByRole('link', { name: h.header.biasNyLabel })).not.toBeInTheDocument()
    expect(within(chips).getByText(h.header.session(h.header.sessions.outside, h.header.entriesForbidden))).toBeInTheDocument()
  })
})

describe('HomePage hero and KPI toggles', () => {
  it('a KPI card switches the hero chart; clicking it again or «← Крива P&L» returns to the P&L curve', async () => {
    serveCharts()
    const { user } = renderWithProviders(<HomePage />)
    await screen.findByText('+741', { selector: TOTAL })
    expect(screen.getByRole('radiogroup', { name: h.hero.range })).toBeInTheDocument()
    const today = await screen.findByRole('button', { name: new RegExp(`^${h.kpis.today}`) })
    expect(today).toHaveAttribute('aria-pressed', 'false')

    await user.click(today)
    expect(today).toHaveAttribute('aria-pressed', 'true')
    expect(today).toHaveTextContent(h.kpis.hintOn)
    expect(today).toHaveClass('border-2', 'border-profit')
    expect(screen.getByRole('heading', { level: 2, name: h.hero.todayTitle })).toBeInTheDocument()
    expect(screen.getByTestId('hero-total')).toHaveTextContent('+212')
    expect(screen.queryByRole('radiogroup', { name: h.hero.range })).not.toBeInTheDocument()

    await user.click(today)
    expect(today).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByTestId('hero-total')).toHaveTextContent('+741')

    const maxLoss = screen.getByRole('button', { name: new RegExp(`^${h.kpis.maxLoss}`) })
    await user.click(maxLoss)
    expect(screen.getByRole('heading', { level: 2, name: h.hero.maxLossTitle('Funded') })).toBeInTheDocument()
    expect(screen.getByTestId('hero-total')).toHaveTextContent('10.6%')
    expect(screen.getByTestId('hero-total')).toHaveClass('text-ink')
    expect(screen.getByText(h.kpis.maxLossLimit(`${MINUS}10%`))).toBeInTheDocument()
    // The 0 line is always drawn and labelled as the limit.
    expect(screen.getByText(h.hero.maxLossLimitLine)).toBeInTheDocument()
    expect(screen.getByRole('img', { name: h.hero.chartLabel(h.hero.maxLossTitle('Funded'), '10%', '10.6%', '9.8%') })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: h.hero.back }))
    expect(maxLoss).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByRole('radiogroup', { name: h.hero.range })).toBeInTheDocument()
  })

  it('KPI values use the overview formatter (whole values without «.0»)', async () => {
    renderWithProviders(<HomePage />)
    const group = await screen.findByRole('group', { name: h.kpis.label })
    expect(within(group).getByRole('button', { name: new RegExp(`^${h.kpis.winRate}`) })).toHaveTextContent('57%')
    expect(within(group).getByRole('button', { name: new RegExp(`^${h.kpis.avgR}`) })).toHaveTextContent('+1.3R')
    expect(within(group).getAllByTestId('kpi-sparkline')).toHaveLength(4)
  })

  it('labels every point of a short curve and every 3rd + min + last of a long one; the min is below in loss colour', async () => {
    serveCharts()
    const first = renderWithProviders(<HomePage />)
    await screen.findByText('+741', { selector: TOTAL })
    expect(screen.getAllByTestId('hero-value-label').map((el) => el.textContent)).toEqual(['0', '+120', '+30', '+340', '+741'])
    first.unmount()

    const month = ['0', '-20', '-45', '60', '140', '120', '260', '310', '290', '410', '499', '470', '640', '705', '780', '899', '1010', '1241']
    serveCharts(homeCharts(month))
    renderWithProviders(<HomePage />)
    await screen.findByText('+1 241', { selector: TOTAL })
    const labels = screen.getAllByTestId('hero-value-label')
    expect(labels.map((el) => el.textContent)).toEqual([`${MINUS}45`, '+60', '+260', '+410', '+640', '+899', `+1${NNBSP}241`])
    const min = labels[0]
    expect(min).toHaveAttribute('data-kind', 'min')
    expect(min).toHaveClass('text-loss')
    expect(min?.style.transform).toContain('10px)')
    expect(labels.at(-1)).toHaveAttribute('data-kind', 'last')
    expect(screen.getByRole('img', { name: h.hero.chartLabel(h.hero.pnlTitle('листопад'), '0', `+1${NNBSP}241`, `${MINUS}45`) })).toBeInTheDocument()
  })

  it('shows «Немає угод за цей період» for an empty range and remembers the range per browser', async () => {
    const { user } = renderWithProviders(<HomePage />)
    expect(await screen.findByText(uk.dashboard.charts.empty)).toBeInTheDocument()
    await user.click(screen.getByRole('radio', { name: h.hero.ranges.week }))
    expect(screen.getByRole('radio', { name: h.hero.ranges.week })).toHaveAttribute('aria-checked', 'true')
    expect(JSON.parse(window.localStorage.getItem('tj.home.charts') ?? '{}')).toMatchObject({ preset: 'week' })
    expect(screen.getByRole('heading', { level: 2, name: h.hero.pnlTitle(h.hero.periods.week) })).toBeInTheDocument()
  })

  it('a failed charts refresh keeps the curve and says so; mixed currencies ask for one account', async () => {
    let fail = false
    mockApi(http.get('/api/dashboard/charts', () =>
      fail ? HttpResponse.json({ error: { code: 'internal_error', message: 'boom' } }, { status: 500 }) : HttpResponse.json(homeCharts())))
    const { queryClient, unmount } = renderWithProviders(<HomePage />)
    await screen.findAllByTestId('hero-value-label')
    fail = true
    await act(async () => { await queryClient.invalidateQueries({ queryKey: ['dashboard', 'charts'] }) })
    expect(await screen.findByText((text) => text.startsWith(uk.dashboard.charts.refreshError))).toBeInTheDocument()
    expect(screen.getAllByTestId('hero-value-label').length).toBeGreaterThan(0)
    unmount()

    mockApi(http.get('/api/dashboard/charts', () => HttpResponse.json({ error: { code: 'mixed_currency', message: 'x', details: {} } }, { status: 409 })))
    renderWithProviders(<HomePage />)
    expect(await screen.findByText(uk.dashboard.charts.mixedCurrency)).toBeInTheDocument()
  })
})

describe('HomePage «Ліміти»', () => {
  it('draws day/week/month bars with the loss zone, fill from zero and the zero tick; trades and room to the stop', async () => {
    renderWithProviders(<HomePage />)
    const card = (await screen.findByRole('heading', { name: h.limits.title })).closest('section')
    if (!card) throw new Error('limits card expected')
    const bars = await within(card).findAllByTestId('limit-bar')
    expect(bars).toHaveLength(3)
    const day = within(card).getByRole('img', { name: h.limits.barLabel(h.limits.day, '+2.1%', `${MINUS}3%`, '+5%') })
    expect(within(day).getByTestId('limit-zero').style.left).toBe('37.5%')
    expect(within(day).getByTestId('limit-loss-zone').style.width).toBe('37.5%')
    expect(within(day).getByTestId('limit-fill').style.left).toBe('37.5%')
    expect(within(day).getByTestId('limit-fill').style.width).toBe('26.25%')
    expect(within(card).getByText('Funded')).toBeInTheDocument()
    expect(within(card).getByText(h.limits.trades).nextElementSibling).toHaveTextContent('7 / 10')
    expect(within(card).getByText(h.limits.toStop).nextElementSibling).toHaveTextContent('5.1%')
  })

  it('a month without account_limits has no loss zone; the header account chip scopes the page, the card has no switch', async () => {
    const asked: URLSearchParams[] = []
    serveHome(homeData({ limits: homeLimits({ month: { pct: '3.1000', loss_pct: null, profit_pct: null } }) }), asked)
    mockApi(http.get('/api/dashboard', () => HttpResponse.json(emptyDashboard({
      accounts: [dashboardAccount({ id: 1, name: 'Funded' }), dashboardAccount({ id: 2, name: 'Funded 2' })],
    }))))
    const { user } = renderWithProviders(<HomePage />)
    const month = await screen.findByRole('img', { name: h.limits.barLabel(h.limits.month, '+3.1%', h.limits.noLimit, h.limits.noLimit) })
    expect(within(month).queryByTestId('limit-loss-zone')).not.toBeInTheDocument()
    expect(within(month).getByTestId('limit-zero').style.left).toBe('50%')
    expect(await screen.findByText(`Funded · ${h.limits.closest}`)).toBeInTheDocument()
    expect(asked[0]?.has('account_id')).toBe(false)

    const card = screen.getByRole('heading', { name: h.limits.title }).closest('section')
    if (!card) throw new Error('limits card expected')
    expect(within(card).queryByRole('combobox')).not.toBeInTheDocument()
    const chips = screen.getByRole('navigation', { name: h.header.chips })
    const select = within(chips).getByRole('combobox', { name: h.header.account })
    expect(within(select).getAllByRole('option').map((o) => o.textContent)).toEqual([h.header.allAccounts, 'Funded', 'Funded 2'])
    await user.selectOptions(select, '2')
    await waitFor(() => expect(asked.at(-1)?.get('account_id')).toBe('2'))
    expect(JSON.parse(window.localStorage.getItem('tj.home.charts') ?? '{}')).toMatchObject({ accountId: 2 })
    // A native select: reachable by keyboard; back to «Усі рахунки».
    select.focus()
    expect(select).toHaveFocus()
    await user.selectOptions(select, '')
    expect(select).toHaveValue('')
    expect(JSON.parse(window.localStorage.getItem('tj.home.charts') ?? '{}')).toMatchObject({ accountId: null })
  })
})

describe('HomePage «Відкриті позиції»', () => {
  it('shows a card per position with P&L, R, ladder, MAE/MFE, description state and «Описати»', async () => {
    serveHome(homeData({
      open_positions: [
        homePosition(),
        homePosition({ trade_id: 42, symbol: 'EURUSD', direction: 'sell', account_name: 'Funded 2', entry_price: '1.10950000', current_price: '1.10910000', pnl: '-28.00', r_now: '-0.3000', described: false }),
      ],
      open_totals: { pnl: '36.20', risk_pct: '1.6560', price_time: '2026-11-19T13:41:30Z' },
    }))
    renderWithProviders(<HomePage />)
    const ger = await screen.findByRole('article', { name: 'GER40' })
    expect(within(ger).getByText('+64')).toHaveClass('text-profit')
    expect(within(ger).getByText('+0.7R')).toBeInTheDocument()
    expect(within(ger).getByText(h.positions.meta('0.13', 'Funded', '58 хв'))).toBeInTheDocument()
    expect(within(ger).getByTestId('position-now-tag')).toHaveTextContent('26 523')
    expect(within(ger).getByTestId('position-now-dot').style.left).toBe('68%')
    expect(within(ger).getByTestId('position-band').style.left).toBe('32%')
    expect(within(ger).getByText('+1.5R')).toBeInTheDocument()
    expect(within(ger).getByText(h.positions.mae('0.2R'))).toBeInTheDocument()
    expect(within(ger).getByText(h.positions.mfe('0.8R'))).toBeInTheDocument()
    expect(within(ger).getByText(h.positions.described)).toBeInTheDocument()
    expect(within(ger).getByRole('link', { name: h.positions.describeLabel('GER40') })).toHaveAttribute('href', '/trades/41/describe')
    const eur = screen.getByRole('article', { name: 'EURUSD' })
    expect(within(eur).getByText(`${MINUS}28`)).toHaveClass('text-loss')
    expect(within(eur).getByText(h.positions.notDescribed)).toBeInTheDocument()
    expect(screen.getByRole('img', { name: h.positions.live })).toBeInTheDocument()
    expect(screen.getByLabelText(`${h.positions.total}: +36`)).toHaveTextContent('+36 USD')
    expect(screen.getByText(h.positions.risk('1.7%'))).toBeInTheDocument()
  })

  it('without live values says «ціна недоступна» or «дані застаріли HH:MM» in the warning tone', async () => {
    serveHome(homeData({
      open_positions: [
        homePosition({ current_price: null, pnl: null, r_now: null, price_time: '2026-11-19T13:30:00Z' }),
        homePosition({ trade_id: 43, symbol: 'XAUUSD', current_price: null, pnl: null, r_now: null, price_time: null }),
      ],
      open_totals: { pnl: null, risk_pct: '1.3120', price_time: null },
    }))
    renderWithProviders(<HomePage />)
    const ger = await screen.findByRole('article', { name: 'GER40' })
    expect(within(ger).getByTestId('position-live-note')).toHaveTextContent(h.positions.stale('14:30'))
    expect(within(ger).getByTestId('position-live-note')).toHaveClass('text-warning')
    expect(within(ger).queryByTestId('position-now-dot')).not.toBeInTheDocument()
    expect(within(screen.getByRole('article', { name: 'XAUUSD' })).getByTestId('position-live-note')).toHaveTextContent(h.positions.priceUnavailable)
    expect(screen.queryByRole('img', { name: h.positions.live })).not.toBeInTheDocument()
  })

  it('a position MT5 no longer reports says «Не вдалося підтвердити закриття», never a live card', async () => {
    serveHome(homeData({
      open_positions: [
        homePosition({ symbol: 'GBPUSD', close_unconfirmed: true, current_price: null, pnl: null, r_now: null, price_time: null }),
      ],
      open_totals: { pnl: null, risk_pct: '0.5000', price_time: null },
    }))
    renderWithProviders(<HomePage />)
    const card = await screen.findByRole('article', { name: 'GBPUSD' })
    expect(within(card).getByTestId('position-live-note')).toHaveTextContent(h.positions.closeUnconfirmed)
    expect(within(card).getByTestId('position-live-note')).toHaveClass('text-warning')
    expect(within(card).getByTestId('position-close-unconfirmed')).toHaveTextContent(h.positions.closeUnconfirmedHint)
    expect(within(card).queryByTestId('position-ladder')).not.toBeInTheDocument()
    expect(within(card).queryByLabelText(/^MAE /)).not.toBeInTheDocument()
    expect(within(card).getByRole('link', { name: h.positions.describeLabel('GBPUSD') })).toBeInTheDocument()
  })

  it('shows the empty state without positions', async () => {
    renderWithProviders(<HomePage />)
    expect(await screen.findByText(h.positions.empty)).toBeInTheDocument()
  })
})

describe('HomePage «Потрібен опис»', () => {
  const trade = (id: number, symbol: string, r: string) =>
    fixtureTrade({ id, symbol, close_time: '2026-11-18T10:00:00Z', net_pnl: r.startsWith('-') ? '-50.00' : '80.00', r_multiple: r })

  it('shows up to 5 tiles with symbol, R, date and «Описати», plus «+N у журналі»', async () => {
    const asked: URLSearchParams[] = []
    mockApi(http.get('/api/trades', ({ request }) => {
      asked.push(new URL(request.url).searchParams)
      return HttpResponse.json({
        items: [trade(21, 'XAUUSD', '2.1000'), trade(22, 'EURUSD', '-1.0000'), trade(23, 'GER40', '1.6000'), trade(24, 'GBPUSD', '-1.0000'), trade(25, 'GER40', '0.4000')],
        total: 12,
      })
    }))
    renderWithProviders(<HomePage />)
    const tile = await screen.findByRole('link', { name: h.needs.tileLabel('XAUUSD', '18.11') })
    expect(tile).toHaveAttribute('href', '/trades/21/describe')
    expect(within(tile).getByText('+2.1R')).toHaveClass('text-profit')
    expect(within(screen.getByRole('link', { name: h.needs.tileLabel('EURUSD', '18.11') })).getByText(`${MINUS}1R`)).toHaveClass('text-loss')
    expect(screen.getByRole('link', { name: h.needs.moreLabel(7) })).toHaveAttribute('href', '/journal?status=needs_description&excluded=hide')
    expect(screen.getByLabelText(h.needs.count(12))).toHaveTextContent('12')
    expect(asked[0]?.getAll('status')).toEqual(['needs_description'])
    expect(asked[0]?.get('excluded')).toBe('false')
    expect(asked[0]?.get('archived')).toBe('false')
    expect(asked[0]?.get('limit')).toBe('5')
  })

  it('shows the empty state and no «+N» tile when everything is described', async () => {
    renderWithProviders(<HomePage />)
    expect(await screen.findByText(h.needs.empty)).toBeInTheDocument()
    expect(screen.queryByText(h.needs.moreText)).not.toBeInTheDocument()
  })

  it('shows a visible error when the list cannot load', async () => {
    mockApi(http.get('/api/trades', () => HttpResponse.json({ error: { code: 'internal_error', message: 'boom' } }, { status: 500 })))
    renderWithProviders(<HomePage />)
    expect(await screen.findByText((text) => text.startsWith(h.needs.error))).toBeInTheDocument()
  })
})

describe('HomePage bottom charts', () => {
  it('«P&L по днях» bars with value labels and «Форма · 20 угод» end labels', async () => {
    serveCharts()
    renderWithProviders(<HomePage />)
    expect(await screen.findAllByTestId('daily-bar')).toHaveLength(4)
    expect(screen.getAllByTestId('daily-value').map((el) => el.textContent)).toEqual(['+120', `${MINUS}90`, '+310', '+401'])
    expect(screen.getByRole('img', { name: h.daily.label(`Пн +120, Вт ${MINUS}90, Ср +310, Чт +401`) })).toBeInTheDocument()
    expect(screen.getAllByTestId('form-end-label').map((el) => el.textContent)).toEqual(['57%', '+1.3R'])
    expect(screen.getByRole('img', { name: h.form.label('45%', '57%', '+0.6R', '+1.3R') })).toBeInTheDocument()
  })

  it('both show an empty note for a range without trades', async () => {
    renderWithProviders(<HomePage />)
    expect(await screen.findByText(h.daily.empty)).toBeInTheDocument()
    expect(screen.getByText(h.form.empty)).toBeInTheDocument()
  })
})

describe('HomePage errors, stop banner, digest suggestion', () => {
  it('keeps the last Home data with a visible error when a refresh fails, without a global toast', async () => {
    const queryClient = createQueryClient()
    queryClient.setDefaultOptions({ queries: { retry: false } })
    renderWithProviders(<HomePage />, { queryClient })
    await screen.findByRole('group', { name: h.kpis.label })
    mockApi(http.get('/api/home', () => HttpResponse.json({ error: { code: 'internal_error', message: 'boom' } }, { status: 500 })))
    await act(async () => { await queryClient.invalidateQueries({ queryKey: homeKeys.all }) })
    const alert = await screen.findByText(h.hero.homeError)
    expect(alert.closest('[role="alert"]')).toHaveTextContent(uk.dashboard.staleNote)
    expect(screen.getByRole('group', { name: h.kpis.label })).toBeInTheDocument()
    expect(screen.getAllByText(uk.errors.internal_error)).toHaveLength(1)
  })

  it('shows a readable config error on the first load and retries', async () => {
    mockApi(http.get('/api/home', () => HttpResponse.json(
      { error: { code: 'config_error', message: 'bad', details: { file: 'rules.yaml', reason: 'mojibake', problems: [] } } },
      { status: 500 },
    )))
    const { user } = renderWithProviders(<HomePage />)
    const title = await screen.findByText(h.hero.homeError)
    const alert = title.closest('[role="alert"]')
    if (!(alert instanceof HTMLElement)) throw new Error('alert expected')
    expect(within(alert).getByText(uk.errors.config_error_reasons.mojibake('rules.yaml'))).toBeInTheDocument()
    serveHome()
    await user.click(within(alert).getByRole('button', { name: uk.common.retry }))
    expect(await screen.findByRole('group', { name: h.kpis.label })).toBeInTheDocument()
    expect(screen.queryByText(h.hero.homeError)).not.toBeInTheDocument()
  })

  it('shows the stop banner when a stop is hit', async () => {
    mockApi(http.get('/api/dashboard', () => HttpResponse.json(emptyDashboard({ stop: { today: true, week: false } }))))
    renderWithProviders(<HomePage />)
    expect(await screen.findByText(uk.dashboard.stopToday)).toBeInTheDocument()
    expect(screen.queryByText(uk.dashboard.stopWeek)).not.toBeInTheDocument()
  })

  it('shows the digest suggestion with a link to the period', async () => {
    mockApi(http.get('/api/digests/suggestion', () => HttpResponse.json({ weekly: { period_start: '2026-11-09' }, monthly: null })))
    renderWithProviders(<HomePage />)
    const weekly = await screen.findByRole('article', { name: uk.dashboard.suggestion.weekly('9–15 лист.') })
    expect(within(weekly).getByRole('link', { name: uk.dashboard.suggestion.open })).toHaveAttribute('href', '/digests?kind=weekly&date=2026-11-09')
  })
})

describe('HomePage bias status', () => {
  it('shows all periods, server reminders and links with the server Brussels date', async () => {
    renderWithProviders(<HomePage />)
    expect(await screen.findByText(t.date('2026-11-06'))).toBeInTheDocument()
    const london = screen.getByRole('article', { name: uk.bias.kinds.pre_london })
    expect(within(london).getByRole('link', { name: t.open })).toHaveAttribute('href', '/bias/7')
    const ny = screen.getByRole('article', { name: uk.bias.kinds.pre_ny })
    expect(within(ny).getByText(t.reminder(uk.bias.kinds.pre_ny))).toBeInTheDocument()
    expect(within(ny).getByRole('link', { name: t.record })).toHaveAttribute('href', '/bias/new?kind=pre_ny&date=2026-11-06')
    expect(within(screen.getByRole('article', { name: uk.bias.kinds.weekly })).getByRole('link', { name: t.open })).toHaveAttribute('href', '/bias/8')
    expect(within(screen.getByRole('article', { name: uk.bias.kinds.monthly })).getByRole('link', { name: t.record })).toHaveAttribute('href', '/bias/new?kind=monthly&date=2026-11-06')
    expect(within(london).queryByRole('status')).not.toBeInTheDocument()
  })

  it('shows loading, reports failure, and retries successfully', async () => {
    let release!: () => void
    const pending = new Promise<void>((resolve) => { release = resolve })
    mockApi(http.get('/api/bias/status', async () => {
      await pending
      return HttpResponse.json({ error: { code: 'config_error', message: 'Broken config' } }, { status: 500 })
    }))
    const { user } = renderWithProviders(<HomePage />)
    expect(screen.getByText(t.loading)).toBeInTheDocument()
    release()
    expect(await screen.findByText(t.loadError)).toBeInTheDocument()
    expect(screen.queryByRole('article', { name: uk.bias.kinds.pre_ny })).not.toBeInTheDocument()
    mockApi(http.get('/api/bias/status', () => HttpResponse.json(status())))
    await user.click(screen.getByRole('button', { name: uk.common.retry }))
    expect(await screen.findByRole('article', { name: uk.bias.kinds.pre_ny })).toBeInTheDocument()
    expect(screen.queryByText(t.loadError)).not.toBeInTheDocument()
  })

  it('trusts remind=false for missing weekend sessions without browser time calculations', async () => {
    const data = status({ date: '2026-11-07', weekday: false })
    data.sessions.pre_london = { ...data.sessions.pre_london, note_id: null, missing: true }
    data.sessions.pre_ny.remind = false
    mockApi(http.get('/api/bias/status', () => HttpResponse.json(data)))
    renderWithProviders(<HomePage />)
    await screen.findByText(t.date(data.date))
    expect(screen.getAllByText(t.missing)).toHaveLength(3)
    expect(screen.queryByText(t.reminder(uk.bias.kinds.pre_london))).not.toBeInTheDocument()
    expect(screen.queryByText(t.reminder(uk.bias.kinds.pre_ny))).not.toBeInTheDocument()
  })

  it('refreshes Home and sidebar together after a note write, clearing the reminder badge', async () => {
    serveSidebar()
    let data = status()
    let requests = 0
    mockApi(http.get('/api/bias/status', () => { requests += 1; return HttpResponse.json(data) }))
    const { queryClient } = renderWithProviders(<><Sidebar /><HomePage /></>)
    expect(await screen.findByLabelText(t.badge(1))).toHaveTextContent('1')
    expect(requests).toBe(1)
    data = status()
    data.sessions.pre_ny = { ...data.sessions.pre_ny, note_id: 9, missing: false, remind: false }
    await act(async () => { await invalidateAfterWrite(queryClient) })
    await waitFor(() => expect(screen.queryByLabelText(t.badge(1))).not.toBeInTheDocument())
    expect(within(screen.getByRole('article', { name: uk.bias.kinds.pre_ny })).getByRole('link', { name: t.open })).toHaveAttribute('href', '/bias/9')
    expect(requests).toBe(2)
  })

  it('polls the server after 60 seconds and reveals a newly due reminder', async () => {
    let data = status()
    data.sessions.pre_ny.remind = false
    let requests = 0
    mockApi(http.get('/api/bias/status', () => { requests += 1; return HttpResponse.json(data) }))
    const { unmount } = renderWithProviders(<HomePage />)
    await screen.findByText(t.date(data.date))
    expect(screen.queryByText(t.reminder(uk.bias.kinds.pre_ny))).not.toBeInTheDocument()
    // Keep network and React scheduling real; advance only the polling interval's clock.
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    try {
      // Remount so the query observer schedules its polling timer on the controlled clock.
      unmount()
      const mounted = renderWithProviders(<HomePage />)
      await screen.findByText(t.date(data.date))
      const before = requests
      data = status()
      await act(async () => { vi.advanceTimersByTime(60_000) })
      expect(await screen.findByText(t.reminder(uk.bias.kinds.pre_ny))).toBeInTheDocument()
      expect(requests).toBe(before + 1)
      mounted.unmount()
    } finally {
      vi.useRealTimers()
    }
  })

  it('replaces a stale reminder badge with an unavailable indicator after refresh fails', async () => {
    serveSidebar()
    const { queryClient } = renderWithProviders(<><Sidebar /><HomePage /></>)
    await screen.findByLabelText(t.badge(1))
    mockApi(http.get('/api/bias/status', () => HttpResponse.json({}, { status: 500 })))
    await act(async () => { await queryClient.invalidateQueries({ queryKey: biasKeys.status }) })
    expect(await screen.findByLabelText(t.loadError)).toHaveTextContent(t.unavailable)
    expect(screen.queryByLabelText(t.badge(1))).not.toBeInTheDocument()
    expect(screen.queryByRole('article', { name: uk.bias.kinds.pre_ny })).not.toBeInTheDocument()
    expect(screen.getByText(t.loadError)).toBeInTheDocument()
  })
})

/** The P&L curve of `homeCharts` at the given instants (`from`: the range start the API echoes). */
function chartsAt(times: readonly string[], from = '2026-11-01'): HomeCharts {
  const base = homeCharts(times.map((_, i) => `${i * 10}.00`))
  return { ...base, from, equity: base.equity.map((p, i) => ({ ...p, time: times[i] ?? p.time })) }
}

const xLabelTexts = () => screen.getAllByTestId('hero-x-label').map((el) => el.textContent)

describe('HomePage hero x labels (M8-10b follow-up, owner fix)', () => {
  const quarter = ['2026-08-18T22:00:00Z', '2026-09-03T10:00:00Z', '2026-09-15T10:00:00Z', '2026-10-02T10:00:00Z', '2026-10-20T10:00:00Z', '2026-11-05T10:00:00Z', '2026-11-18T10:00:00Z']

  it('«3 міс» and «Рік» label month starts of the actual span (from the first trade)', async () => {
    serveCharts(chartsAt(quarter))
    const { user } = renderWithProviders(<HomePage />)
    await screen.findByText('+60', { selector: TOTAL })
    await user.click(screen.getByRole('radio', { name: h.hero.ranges.months3 }))
    await waitFor(() => expect(xLabelTexts()).toEqual(['вер', 'жов', 'лис']))
    await user.click(screen.getByRole('radio', { name: h.hero.ranges.year }))
    await waitFor(() => expect(xLabelTexts()).toEqual(['вер', 'жов', 'лис']))
  })

  it('«Усе» adds the year when the points span years', async () => {
    serveCharts(chartsAt(['2026-11-30T23:00:00Z', '2026-12-10T10:00:00Z', '2027-01-05T10:00:00Z', '2027-01-20T10:00:00Z', '2027-02-20T10:00:00Z'], '2026-12-01'))
    const { user } = renderWithProviders(<HomePage />)
    await user.click(await screen.findByRole('radio', { name: h.hero.ranges.all }))
    await waitFor(() => expect(xLabelTexts()).toEqual(['гру 26', 'січ 27', 'лют 27']))
  })

  it('«Місяць» keeps DD.MM labels from the first trade', async () => {
    serveCharts(chartsAt(quarter))
    renderWithProviders(<HomePage />)
    await screen.findByText('+60', { selector: TOTAL })
    expect(xLabelTexts()).toEqual(['03.09', '15.09', '02.10', '20.10', '18.11'])
    expect(screen.queryByTestId('hero-data-from')).not.toBeInTheDocument()
  })

  it('the «дані з» note needs the data to start at least 7 days after the range start', async () => {
    serveCharts(chartsAt(['2026-10-31T23:00:00Z', '2026-11-07T10:00:00Z', '2026-11-12T10:00:00Z']))
    const first = renderWithProviders(<HomePage />)
    await screen.findByText('+20', { selector: TOTAL })
    expect(screen.queryByTestId('hero-data-from')).not.toBeInTheDocument()
    first.unmount()

    serveCharts(chartsAt(['2026-10-31T23:00:00Z', '2026-11-08T10:00:00Z', '2026-11-12T10:00:00Z']))
    renderWithProviders(<HomePage />)
    expect(await screen.findByTestId('hero-data-from')).toHaveTextContent(h.hero.dataFrom('08.11'))
  })

  it('a short history in «Рік»: DD.MM labels without repeats and the muted «дані з 28.10» note', async () => {
    const trades = Array.from({ length: 16 }, (_, i) => new Date(Date.UTC(2026, 9, 28 + Math.floor(i * 1.5), 10)).toISOString())
    serveCharts(chartsAt(['2025-11-19T23:00:00Z', ...trades], '2025-11-20'))
    const { user } = renderWithProviders(<HomePage />)
    await user.click(await screen.findByRole('radio', { name: h.hero.ranges.year }))
    const note = await screen.findByTestId('hero-data-from')
    expect(note).toHaveTextContent(h.hero.dataFrom('28.10'))
    expect(note).toHaveClass('text-ink-muted')
    const texts = xLabelTexts()
    expect(texts[0]).toBe('28.10')
    expect(texts.every((text) => /^\d{2}\.\d{2}$/.test(text ?? ''))).toBe(true)
    expect(new Set(texts).size).toBe(texts.length)
  })
})

describe('HomePage «До макс. збитку» KPI', () => {
  const card = async () => screen.findByRole('button', { name: new RegExp(`^${h.kpis.maxLoss}`) })

  it('replaces «Просідання»: room in ink with the account and the limit, MT5 equity has no note', async () => {
    renderWithProviders(<HomePage />)
    const kpi = await card()
    expect(kpi).toHaveTextContent('10.6%')
    expect(within(kpi).getByText('10.6%')).toHaveClass('text-ink')
    expect(kpi).toHaveTextContent(h.kpis.maxLossCaption('Funded', `${MINUS}10%`))
    expect(within(kpi).queryByTestId('kpi-no-floating')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Просідання/ })).not.toBeInTheDocument()
  })

  it('near the floor the value is in the loss colour; without MT5 equity a muted note says so', async () => {
    serveHome(homeData({ kpis: { ...homeData().kpis, max_loss: homeMaxLoss({ pct: '1.5000', equity_source: 'balance' }) } }))
    const { user } = renderWithProviders(<HomePage />)
    const kpi = await card()
    expect(within(kpi).getByText('1.5%')).toHaveClass('text-loss')
    expect(within(kpi).getByTestId('kpi-no-floating')).toHaveTextContent(h.kpis.maxLossNoFloating)
    expect(within(kpi).getByTestId('kpi-no-floating')).toHaveClass('text-ink-muted')
    await user.click(kpi)
    expect(screen.getByTestId('hero-total')).toHaveClass('text-loss')
    expect(screen.getByText(`${h.kpis.maxLossLimit(`${MINUS}10%`)} · ${h.kpis.maxLossNoFloating}`)).toBeInTheDocument()
  })

  it('a cTrader account: fresh equity counts as live and no MT5 position data is needed', async () => {
    // The API labels any fresh synced equity `mt5`, cTrader included (backend home_max_loss.py).
    serveHome(homeData({
      limits: homeLimits({ account_name: 'CT Demo', floating_pnl: '56.25', floating_included: true }),
      kpis: { ...homeData().kpis, max_loss: homeMaxLoss({ account_name: 'CT Demo', equity: '10056.25', equity_source: 'mt5' }) },
      open_positions: [],
    }))
    renderWithProviders(<HomePage />)
    const kpi = await card()
    expect(kpi).toHaveTextContent('10.6%')
    expect(kpi).toHaveTextContent(h.kpis.maxLossCaption('CT Demo', `${MINUS}10%`))
    expect(within(kpi).queryByTestId('kpi-no-floating')).not.toBeInTheDocument()
  })

  it('a cTrader account with only a balance: the room shows with the no-floating note', async () => {
    serveHome(homeData({
      kpis: { ...homeData().kpis, max_loss: homeMaxLoss({ account_name: 'CT Demo', equity: '10000.00', equity_source: 'balance', pct: '10.0000' }) },
    }))
    renderWithProviders(<HomePage />)
    const kpi = await card()
    expect(kpi).toHaveTextContent('10%')
    expect(within(kpi).getByTestId('kpi-no-floating')).toHaveTextContent(h.kpis.maxLossNoFloating)
  })

  it('no account limits: «—», the hint, and the hero says the limits are not set', async () => {
    serveHome(homeData({ kpis: { ...homeData().kpis, max_loss: null } }))
    const { user } = renderWithProviders(<HomePage />)
    const kpi = await card()
    expect(kpi).toHaveTextContent(uk.common.empty)
    expect(kpi).toHaveTextContent(h.kpis.maxLossNoLimits)
    await user.click(kpi)
    expect(screen.getByRole('heading', { level: 2, name: h.hero.maxLossTitle('') })).toBeInTheDocument()
    expect(screen.getAllByText(h.kpis.maxLossNoLimits)).toHaveLength(2)
  })
})

describe('HomePage neutral pills', () => {
  it('Buy/Sell and the description state are neutral; P&L keeps sign colours', async () => {
    serveHome(homeData({
      open_positions: [homePosition(), homePosition({ trade_id: 42, symbol: 'EURUSD', direction: 'sell', pnl: '-28.00', r_now: '-0.3000', described: false })],
      open_totals: { pnl: '36.20', risk_pct: '1.6560', price_time: '2026-11-19T13:41:30Z' },
    }))
    renderWithProviders(<HomePage />)
    const ger = await screen.findByRole('article', { name: 'GER40' })
    const eur = screen.getByRole('article', { name: 'EURUSD' })
    expect(within(ger).getByText(h.positions.sides.buy ?? '')).toHaveAttribute('data-tone', 'neutral')
    expect(within(eur).getByText(h.positions.sides.sell ?? '')).toHaveAttribute('data-tone', 'neutral')
    expect(within(ger).getByText(h.positions.described)).toHaveAttribute('data-tone', 'neutral')
    expect(within(eur).getByText(h.positions.notDescribed)).toHaveAttribute('data-tone', 'neutral')
    expect(within(eur).getByText(`${MINUS}28`)).toHaveClass('text-loss')
    expect(screen.getByLabelText(`${h.positions.total}: +36`)).toHaveAttribute('data-tone', 'profit')
  })

  it('the «Без опису» count pill is neutral', async () => {
    mockApi(http.get('/api/trades', () => HttpResponse.json({ items: [fixtureTrade({ id: 21 })], total: 3 })))
    renderWithProviders(<HomePage />)
    expect(await screen.findByLabelText(h.needs.count(3))).toHaveAttribute('data-tone', 'neutral')
  })
})

describe('HomePage pinned backend cases (2026-11-20)', () => {
  it('409 mixed_currency on /api/home asks to pick one account', async () => {
    mockApi(http.get('/api/home', () => HttpResponse.json({ error: { code: 'mixed_currency', message: 'x', details: {} } }, { status: 409 })))
    renderWithProviders(<HomePage />)
    expect(await screen.findAllByText(uk.dashboard.charts.mixedCurrency)).toHaveLength(2)
    expect(screen.getByText(h.hero.homeError)).toBeInTheDocument()
  })

  it('no account: limits empty state; no account size: «—» value and no fill; disabled limits «без ліміту»', async () => {
    serveHome(homeData({ limits: null }))
    const first = renderWithProviders(<HomePage />)
    expect(await screen.findByText(h.limits.empty)).toBeInTheDocument()
    first.unmount()

    serveHome(homeData({
      limits: homeLimits({ day: { pct: null, loss_pct: null, profit_pct: '5.0000' }, to_daily_stop_pct: null, max_trades_week: null }),
      kpis: { ...homeData().kpis, max_loss: null },
    }))
    renderWithProviders(<HomePage />)
    const day = await screen.findByRole('img', { name: h.limits.barLabel(h.limits.day, uk.common.empty, h.limits.noLimit, '+5%') })
    expect(within(day).getByTestId('limit-fill')).toHaveClass('hidden')
    expect(screen.getByText(h.limits.toStop).nextElementSibling).toHaveTextContent(uk.common.empty)
    expect(screen.getByText(h.limits.trades).nextElementSibling).toHaveTextContent(/^7$/)
    const maxLoss = screen.getByRole('button', { name: new RegExp(`^${h.kpis.maxLoss}`) })
    expect(maxLoss).toHaveTextContent(uk.common.empty)
    expect(maxLoss).toHaveTextContent(h.kpis.maxLossNoLimits)
  })

  it('normalises stored and MT5 price precision; null totals hide the pills; no usable SL hides the R scale', async () => {
    serveHome(homeData({
      open_positions: [
        homePosition({ symbol: 'XAUUSD', entry_price: '2650.00000000', current_price: '2655' }),
        homePosition({ trade_id: 44, symbol: 'EURUSD', current_price: '1.1091', r_now: null, tp_r: null }),
      ],
      open_totals: { pnl: null, risk_pct: null, price_time: null },
    }))
    renderWithProviders(<HomePage />)
    const xau = await screen.findByRole('article', { name: 'XAUUSD' })
    expect(within(xau).getByTestId('position-now-tag')).toHaveTextContent('2 655')
    const eur = screen.getByRole('article', { name: 'EURUSD' })
    expect(within(eur).queryByTestId('position-ladder')).not.toBeInTheDocument()
    expect(within(eur).getByText(h.positions.noSl)).toBeInTheDocument()
    expect(screen.queryByLabelText(new RegExp(`^${h.positions.total}`))).not.toBeInTheDocument()
    expect(screen.queryByText(/^ризик /)).not.toBeInTheDocument()
  })
})
