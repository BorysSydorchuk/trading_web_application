import { screen, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { Sidebar } from '@/components/layout/Sidebar'
import { fixtureTrade } from '@/features/describe/trade.fixture'
import { homeData, homePosition } from '@/features/home/home.fixture'
import type { HomeData } from '@/features/home/types'
import { uk } from '@/i18n/uk'
import { formatShortDateTimeBrussels } from '@/lib/time'
import { renderWithProviders } from '@/test/render'
import { mockApi } from '@/test/server'
import { InboxPage } from './InboxPage'

const p = uk.inboxPage
const OPEN_TIME = '2026-11-19T12:44:00Z'

function serveHome(data: HomeData) {
  mockApi(http.get('/api/home', () => HttpResponse.json(data)))
}

beforeEach(() => {
  mockApi(
    http.get('/api/trades', () =>
      HttpResponse.json({ items: [fixtureTrade({ id: 7, symbol: 'XAUUSD', status: 'needs_description' })], total: 1 }),
    ),
    http.get('/api/inbox/counts', () => HttpResponse.json({ needs_sl: 0, needs_description: 1, draft: 0 })),
    http.get('/api/bias/status', () => HttpResponse.json({}, { status: 404 })),
    http.get('/api/journal-fields', () => HttpResponse.json({ fields: [] })),
  )
})

describe('InboxPage open positions group (M8-10b)', () => {
  it('lists undescribed open positions of all accounts with an «Описати» link; counts stay closed-only', async () => {
    serveHome(
      homeData({
        open_positions: [
          homePosition({ trade_id: 41, symbol: 'GER40', direction: 'buy', account_name: 'Funded', open_time: OPEN_TIME, described: false }),
          homePosition({ trade_id: 42, symbol: 'EURUSD', account_id: 2, account_name: 'Demo', described: true }),
          homePosition({ trade_id: 43, symbol: 'US100', direction: 'sell', account_id: 2, account_name: 'Demo', described: false }),
        ],
      }),
    )
    renderWithProviders(
      <>
        <Sidebar />
        <InboxPage />
      </>,
    )

    const table = await screen.findByRole('table', { name: p.open.title })
    expect(screen.getByRole('heading', { name: p.open.title })).toBeInTheDocument()
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows).toHaveLength(2)
    const [ger, us] = rows
    if (!ger || !us) throw new Error('two rows expected')
    expect(ger).toHaveTextContent('GER40')
    expect(ger).toHaveTextContent('Funded')
    expect(ger).toHaveTextContent(uk.trades.direction.buy)
    expect(ger).toHaveTextContent(formatShortDateTimeBrussels(OPEN_TIME))
    expect(within(ger).getByRole('link', { name: p.describe })).toHaveAttribute('href', '/trades/41/describe')
    expect(us).toHaveTextContent('US100')
    expect(us).toHaveTextContent('Demo')
    expect(within(table).queryByText('EURUSD')).not.toBeInTheDocument()

    // The closed-trade group and the sidebar badge count only the closed trade.
    const closedGroup = (await screen.findByRole('heading', { level: 2, name: p.groups.needs_description })).closest('section')
    if (!closedGroup) throw new Error('closed group expected')
    expect(closedGroup.querySelector('.num')).toHaveTextContent('1')
    expect(await screen.findByLabelText(uk.inbox.badgeLabel(1))).toHaveTextContent('1')
  })

  it('hides the group when every open position is described', async () => {
    serveHome(homeData({ open_positions: [homePosition({ described: true })] }))
    renderWithProviders(<InboxPage />)
    expect(await screen.findByRole('heading', { level: 2, name: p.groups.needs_description })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: p.open.title })).not.toBeInTheDocument()
  })

  it('hides the group without open positions', async () => {
    serveHome(homeData({ open_positions: [] }))
    renderWithProviders(<InboxPage />)
    expect(await screen.findByRole('heading', { level: 2, name: p.groups.needs_description })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: p.open.title })).not.toBeInTheDocument()
  })

  it('a /api/home error shows an inline error in the group, no toast, and the rest of the page works', async () => {
    mockApi(http.get('/api/home', () => HttpResponse.json({ detail: 'boom' }, { status: 500 })))
    renderWithProviders(<InboxPage />)
    const alert = await screen.findByText(new RegExp(p.open.loadError))
    expect(alert.closest('[role="alert"]')).not.toBeNull()
    expect(screen.getByRole('button', { name: uk.common.retry })).toBeInTheDocument()
    expect(await screen.findByRole('heading', { level: 2, name: p.groups.needs_description })).toBeInTheDocument()
    expect(screen.getByText('XAUUSD')).toBeInTheDocument()
    expect(document.querySelector('[data-sonner-toast]')).toBeNull()
  })
})
