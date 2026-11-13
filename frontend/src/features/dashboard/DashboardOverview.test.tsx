import { act, screen, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import type { SyncStatusRow } from '@/features/sync/api'
import { uk } from '@/i18n/uk'
import { createQueryClient } from '@/lib/query-client'
import { renderWithProviders } from '@/test/render'
import { mockApi } from '@/test/server'
import { dashboardKeys } from './api'
import { dashboardAccount, emptyDashboard, openPosition, periodBlock } from './dashboard.fixture'
import { DashboardOverview } from './DashboardOverview'
import type { Dashboard, DigestSuggestion } from './types'

const d = uk.dashboard
// Testing Library normalizes the narrow no-break group separator to a plain space.

function syncRow(overrides: Partial<SyncStatusRow> = {}): SyncStatusRow {
  return {
    account_id: 1, account_name: 'FTMO 100k', state: 'ok',
    last_attempt_utc: '2026-11-13T09:59:00Z', last_success_utc: '2026-11-13T09:59:00Z',
    error_code: null, error_message: null, server_offset_hours: 2, open_positions: 1, ...overrides,
  }
}

function serve(dashboard: Dashboard, suggestion: DigestSuggestion = { weekly: null, monthly: null }) {
  mockApi(
    http.get('/api/dashboard', () => HttpResponse.json(dashboard)),
    http.get('/api/digests/suggestion', () => HttpResponse.json(suggestion)),
  )
}

describe('DashboardOverview', () => {
  beforeEach(() => mockApi(http.get('/api/sync/status', () => HttpResponse.json({ items: [syncRow()] }))))

  it('shows the stop banner only when a stop is hit', async () => {
    serve(emptyDashboard({ accounts: [dashboardAccount({ today_state: 'stop_loss' })], stop: { today: true, week: false } }))
    renderWithProviders(<DashboardOverview />)
    const banner = await screen.findByRole('alert')
    expect(within(banner).getByText(d.stopToday)).toBeInTheDocument()
    expect(within(banner).queryByText(d.stopWeek)).not.toBeInTheDocument()
    expect(screen.getByText(d.accounts.states.stop_loss)).toBeInTheDocument()
  })

  it('shows both banner lines for a weekly stop and none when all is ok', async () => {
    serve(emptyDashboard({ stop: { today: true, week: true } }))
    const first = renderWithProviders(<DashboardOverview />)
    expect(await screen.findByText(d.stopWeek)).toBeInTheDocument()
    expect(screen.getByText(d.stopToday)).toBeInTheDocument()
    first.unmount()
    serve(emptyDashboard({ accounts: [dashboardAccount()] }))
    renderWithProviders(<DashboardOverview />)
    await screen.findByRole('article', { name: 'FTMO 100k' })
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.queryByText(d.stopToday)).not.toBeInTheDocument()
  })

  it('shows P&L in money and percent vs limits, a disabled limit as «вимкнено»', async () => {
    const account = dashboardAccount({
      today: periodBlock({ pnl: '-425.00', pct: '-0.4250' }),
      week: periodBlock({ pnl: '1200.5', pct: '1.2005' }),
      limits: { daily_loss_pct: '-3.0000', daily_profit_pct: null, weekly_loss_pct: '-6.0000', weekly_profit_pct: '10.0000' },
    })
    serve(emptyDashboard({ accounts: [account] }))
    renderWithProviders(<DashboardOverview />)
    const card = await screen.findByRole('article', { name: 'FTMO 100k' })
    const today = within(card).getByRole('row', { name: new RegExp(`^${d.accounts.today}`) })
    expect(within(today).getByText('−425.00 USD')).toHaveClass('text-loss')
    expect(within(today).getByText('−0.43%')).toBeInTheDocument()
    expect(within(today).getByText('−3.00%')).toBeInTheDocument()
    expect(within(today).getByText(d.limitOff)).toBeInTheDocument()
    expect(within(today).getByText(d.accounts.states.ok)).toBeInTheDocument()
    const week = within(card).getByRole('row', { name: new RegExp(`^${d.accounts.week}`) })
    expect(within(week).getByText('1 200.50 USD')).toHaveClass('text-profit')
    expect(within(week).getByText('1.20%')).toBeInTheDocument()
    expect(within(week).getByText('−6.00%')).toBeInTheDocument()
    expect(within(week).getByText('10.00%')).toBeInTheDocument()
    expect(within(card).getByText(d.accounts.size('100 000.00 USD'))).toBeInTheDocument()
  })

  it('shows inbox counts with links and the quick links', async () => {
    serve(emptyDashboard({ inbox: { needs_sl: 2, needs_description: 3, draft: 1 } }))
    renderWithProviders(<DashboardOverview />)
    expect(await screen.findByRole('link', { name: `${d.inbox.needs_sl}: 2` })).toHaveAttribute('href', '/inbox')
    expect(screen.getByRole('link', { name: `${d.inbox.needs_description}: 3` })).toHaveAttribute('href', '/journal?status=needs_description')
    expect(screen.getByRole('link', { name: `${d.inbox.draft}: 1` })).toHaveAttribute('href', '/journal?status=draft')
    expect(screen.getByRole('link', { name: d.links.calculator })).toHaveAttribute('href', '/calculator')
    expect(screen.getByRole('link', { name: d.links.describe })).toHaveAttribute('href', '/inbox')
  })

  it('lists open positions in the API order with Brussels open times', async () => {
    serve(emptyDashboard({
      open_positions: [
        openPosition({ trade_id: 11, symbol: 'GER40', direction: 'sell', open_time: '2026-11-12T22:30:00Z', initial_sl: null, risk_amount: null, risk_pct: null }),
        openPosition({ trade_id: 10, open_time: '2026-11-13T08:05:00Z' }),
      ],
    }))
    renderWithProviders(<DashboardOverview />)
    const table = await screen.findByRole('table', { name: d.positions.title })
    const [, first, second] = within(table).getAllByRole('row')
    expect(within(table).getAllByRole('row')).toHaveLength(3)
    if (!first || !second) throw new Error('two position rows expected')
    expect(within(first).getByText('GER40')).toBeInTheDocument()
    expect(within(first).getByText('Sell')).toBeInTheDocument()
    expect(within(first).getByText('12.11, 23:30')).toBeInTheDocument()
    expect(within(first).getAllByText(uk.common.empty)).toHaveLength(2)
    expect(within(second).getByText('XAUUSD')).toBeInTheDocument()
    expect(within(second).getByText('13.11, 09:05')).toBeInTheDocument()
    expect(within(second).getByText('2650.12')).toBeInTheDocument()
    expect(within(second).getByText('2640.00')).toBeInTheDocument()
    expect(within(second).getByText('0.51%')).toBeInTheDocument()
  })

  it('shows empty states without accounts or positions, and the sync rows', async () => {
    serve(emptyDashboard())
    renderWithProviders(<DashboardOverview />)
    expect(await screen.findByText(d.accounts.empty)).toBeInTheDocument()
    expect(screen.getByText(d.positions.empty)).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    const sync = screen.getByRole('region', { name: d.sync.title })
    expect(await within(sync).findByRole('button', { name: /^FTMO 100k: / })).toBeInTheDocument()
  })

  it('shows a readable error naming the broken config file, and retries', async () => {
    mockApi(
      http.get('/api/dashboard', () => HttpResponse.json(
        { error: { code: 'config_error', message: 'bad', details: { file: 'rules.yaml', reason: 'mojibake', problems: [] } } },
        { status: 500 },
      )),
      http.get('/api/digests/suggestion', () => HttpResponse.json({ weekly: null, monthly: null })),
    )
    const { user } = renderWithProviders(<DashboardOverview />)
    const alert = await screen.findByRole('alert')
    expect(within(alert).getByText(d.loadError)).toBeInTheDocument()
    expect(within(alert).getByText(uk.errors.config_error_reasons.mojibake('rules.yaml'))).toBeInTheDocument()
    expect(screen.queryByText(d.accounts.title)).not.toBeInTheDocument()
    serve(emptyDashboard())
    await user.click(within(alert).getByRole('button', { name: uk.common.retry }))
    expect(await screen.findByText(d.accounts.empty)).toBeInTheDocument()
    expect(screen.queryByText(d.loadError)).not.toBeInTheDocument()
  })

  it('shows the digest suggestion with a link to the period, and hides it when there is none', async () => {
    serve(emptyDashboard(), { weekly: { period_start: '2026-11-09' }, monthly: { period_start: '2026-10-01' } })
    const first = renderWithProviders(<DashboardOverview />)
    const weekly = await screen.findByRole('article', { name: d.suggestion.weekly('9–15 лист.') })
    expect(within(weekly).getByRole('link', { name: d.suggestion.open })).toHaveAttribute('href', '/digests?kind=weekly&date=2026-11-09')
    const monthly = screen.getByRole('article', { name: d.suggestion.monthly('жовтень 2026') })
    expect(within(monthly).getByRole('link', { name: d.suggestion.open })).toHaveAttribute('href', '/digests?kind=monthly&date=2026-10-01')
    first.unmount()
    serve(emptyDashboard())
    renderWithProviders(<DashboardOverview />)
    await screen.findByText(d.accounts.empty)
    expect(screen.queryByRole('link', { name: d.suggestion.open })).not.toBeInTheDocument()
  })

  it('keeps the last data with a stale note when a refresh fails, without a global toast', async () => {
    // The app client (global error toasts on), without retries so the failure shows at once.
    const queryClient = createQueryClient()
    queryClient.setDefaultOptions({ queries: { retry: false } })
    serve(emptyDashboard({ accounts: [dashboardAccount()] }))
    renderWithProviders(<DashboardOverview />, { queryClient })
    await screen.findByRole('article', { name: 'FTMO 100k' })
    mockApi(http.get('/api/dashboard', () => HttpResponse.json({ error: { code: 'internal_error', message: 'boom' } }, { status: 500 })))
    await act(async () => { await queryClient.invalidateQueries({ queryKey: dashboardKeys.dashboard }) })
    const alert = await screen.findByRole('alert')
    expect(within(alert).getByText(d.loadError)).toBeInTheDocument()
    expect(within(alert).getByText(d.staleNote)).toBeInTheDocument()
    expect(screen.getByRole('article', { name: 'FTMO 100k' })).toBeInTheDocument()
    // Only the inline block shows the error text: no toast from the poll.
    expect(screen.getAllByText(uk.errors.internal_error)).toHaveLength(1)
  })

  it('shows a short note when the digest suggestion fails to load', async () => {
    mockApi(
      http.get('/api/dashboard', () => HttpResponse.json(emptyDashboard())),
      http.get('/api/digests/suggestion', () => HttpResponse.json({}, { status: 500 })),
    )
    renderWithProviders(<DashboardOverview />)
    expect(await screen.findByText(d.suggestion.loadError)).toBeInTheDocument()
    expect(screen.getByText(d.accounts.empty)).toBeInTheDocument()
  })
})
