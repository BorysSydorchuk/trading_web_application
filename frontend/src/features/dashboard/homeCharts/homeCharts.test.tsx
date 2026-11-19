import { screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'
import { uk } from '@/i18n/uk'
import { renderWithProviders } from '@/test/render'
import { mockApi } from '@/test/server'
import type { DashboardAccount } from '../types'
import type { HomeCharts as Charts } from './api'
import { HomeCharts } from './HomeCharts'
import { DEFAULT_SELECTION, loadSelection, rangeOf, saveSelection } from './range'

const t = uk.dashboard.charts
const TODAY = '2026-11-19' // Thursday
const ACCOUNTS = [
  { id: 1, name: 'Alpha' },
  { id: 2, name: 'Beta' },
] as unknown as DashboardAccount[]

const DATA: Charts = {
  from: '2026-11-01',
  to: TODAY,
  currency: 'USD',
  account_size: '10000.00',
  trades: 2,
  equity: [
    { time: '2026-10-31T23:00:00Z', cum_pnl: '0.00', cum_pct: '0.0000' },
    { time: '2026-11-12T09:00:00Z', cum_pnl: '100.00', cum_pct: '1.0000' },
    { time: '2026-11-13T09:00:00Z', cum_pnl: '50.00', cum_pct: '0.5000' },
  ],
  daily: [
    { day: '2026-11-12', net_pnl: '100.00', pct: '1.0000', trades: 1 },
    { day: '2026-11-13', net_pnl: '-50.00', pct: '-0.5000', trades: 1 },
  ],
  rolling: [
    { time: '2026-11-12T09:00:00Z', n: 1, win_rate: '100.0000', avg_r: '1.0000' },
    { time: '2026-11-13T09:00:00Z', n: 2, win_rate: '50.0000', avg_r: '0.2500' },
  ],
  rolling_window: 20,
}

afterEach(() => window.localStorage.clear())

describe('M8-14 range presets', () => {
  it('computes Brussels date ranges, «Свої дати» only when valid', () => {
    expect(rangeOf({ ...DEFAULT_SELECTION, preset: 'week' }, TODAY)).toEqual({ from: '2026-11-16', to: TODAY })
    expect(rangeOf({ ...DEFAULT_SELECTION, preset: 'month' }, TODAY)).toEqual({ from: '2026-11-01', to: TODAY })
    expect(rangeOf({ ...DEFAULT_SELECTION, preset: 'months3' }, TODAY)).toEqual({ from: '2026-08-20', to: TODAY })
    expect(rangeOf({ ...DEFAULT_SELECTION, preset: 'year' }, TODAY)).toEqual({ from: '2025-11-20', to: TODAY })
    // month ends and leap days clamp to the target month (no roll-over into the next one)
    expect(rangeOf({ ...DEFAULT_SELECTION, preset: 'months3' }, '2026-05-31')).toEqual({ from: '2026-03-01', to: '2026-05-31' })
    expect(rangeOf({ ...DEFAULT_SELECTION, preset: 'year' }, '2028-02-29')).toEqual({ from: '2027-03-01', to: '2028-02-29' })
    expect(rangeOf({ ...DEFAULT_SELECTION, preset: 'custom', from: '2026-11-10', to: '2026-11-01' }, TODAY)).toBeNull()
    expect(rangeOf({ ...DEFAULT_SELECTION, preset: 'custom', from: '2026-11-01', to: '2026-11-10' }, TODAY)).toEqual({
      from: '2026-11-01',
      to: '2026-11-10',
    })
  })

  it('remembers the selection per browser; defaults «Місяць», all accounts', () => {
    expect(loadSelection()).toEqual(DEFAULT_SELECTION)
    saveSelection({ preset: 'year', from: '', to: '', accountId: 2 })
    expect(loadSelection()).toEqual({ preset: 'year', from: '', to: '', accountId: 2 })
    window.localStorage.setItem('tj.home.charts', '{broken')
    expect(loadSelection()).toEqual(DEFAULT_SELECTION)
  })
})

describe('M8-14 HomeCharts', () => {
  it('shows «Немає угод за цей період» for an empty range', async () => {
    renderWithProviders(<HomeCharts accounts={ACCOUNTS} />)
    expect(await screen.findByText(t.empty)).toBeInTheDocument()
  })

  it('draws the three charts and asks for the chosen account', async () => {
    const asked: URLSearchParams[] = []
    mockApi(
      http.get('/api/dashboard/charts', ({ request }) => {
        asked.push(new URL(request.url).searchParams)
        return HttpResponse.json(DATA)
      }),
    )
    const { user } = renderWithProviders(<HomeCharts accounts={ACCOUNTS} />)

    expect(await screen.findByRole('img', { name: uk.digests.charts.equitySummary(t.equity, '+50.00 USD', 2) })).toBeInTheDocument()
    expect(screen.getAllByTestId('daily-bar')).toHaveLength(2)
    expect(screen.getByTestId('rolling-win-rate')).toBeInTheDocument()
    expect(screen.getByText((text) => text.includes(t.ofSize('+0.50%')))).toBeInTheDocument()
    expect(asked[0]?.has('account_id')).toBe(false)

    await user.selectOptions(screen.getByLabelText(t.account), '2')
    await screen.findAllByTestId('daily-bar')
    expect(asked.at(-1)?.get('account_id')).toBe('2')
    expect(loadSelection().accountId).toBe(2)

    await user.click(screen.getByRole('button', { name: t.presets.week }))
    expect(screen.getByRole('button', { name: t.presets.week })).toHaveAttribute('aria-pressed', 'true')
  })

  it('«Свої дати» asks only once both dates are valid', async () => {
    const asked: URLSearchParams[] = []
    mockApi(
      http.get('/api/dashboard/charts', ({ request }) => {
        asked.push(new URL(request.url).searchParams)
        return HttpResponse.json(DATA)
      }),
    )
    const { user } = renderWithProviders(<HomeCharts accounts={ACCOUNTS} />)
    await screen.findAllByTestId('daily-bar')

    await user.click(screen.getByRole('button', { name: t.presets.custom }))
    expect(screen.getByText(t.customHint)).toBeInTheDocument()
    const calls = asked.length
    await user.type(screen.getByLabelText(t.from), '2026-11-01')
    await user.type(screen.getByLabelText(t.to), '2026-11-10')

    expect(screen.queryByText(t.customHint)).not.toBeInTheDocument()
    await screen.findAllByTestId('daily-bar')
    expect(asked.length).toBeGreaterThan(calls)
    expect(asked.at(-1)?.get('from')).toBe('2026-11-01')
    expect(asked.at(-1)?.get('to')).toBe('2026-11-10')
  })

  it('a failed refresh keeps the charts and says so', async () => {
    let fail = false
    mockApi(
      http.get('/api/dashboard/charts', () =>
        fail ? HttpResponse.json({ error: { code: 'internal_error', message: 'boom' } }, { status: 500 }) : HttpResponse.json(DATA),
      ),
    )
    const { queryClient } = renderWithProviders(<HomeCharts accounts={ACCOUNTS} />)
    await screen.findAllByTestId('daily-bar')

    fail = true
    await queryClient.invalidateQueries()

    expect(await screen.findByRole('alert')).toHaveTextContent(t.refreshError)
    expect(screen.getAllByTestId('daily-bar')).toHaveLength(2)
  })

  it('shows a readable message for mixed currencies on the first load', async () => {
    mockApi(
      http.get('/api/dashboard/charts', () =>
        HttpResponse.json({ error: { code: 'mixed_currency', message: 'x', details: {} } }, { status: 409 }),
      ),
    )
    renderWithProviders(<HomeCharts accounts={ACCOUNTS} />)
    expect(await screen.findByRole('alert')).toHaveTextContent(t.mixedCurrency)
  })
})
