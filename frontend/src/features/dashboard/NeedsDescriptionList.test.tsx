import { screen, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { fixtureTrade } from '@/features/describe/trade.fixture'
import { uk } from '@/i18n/uk'
import { renderWithProviders } from '@/test/render'
import { mockApi } from '@/test/server'
import { NeedsDescriptionList } from './NeedsDescriptionList'

const n = uk.dashboard.needsDescription

describe('NeedsDescriptionList (M8-15)', () => {
  it('lists closed trades without a description, each with «Описати», and links to the rest', async () => {
    const asked: URLSearchParams[] = []
    mockApi(
      http.get('/api/trades', ({ request }) => {
        asked.push(new URL(request.url).searchParams)
        return HttpResponse.json({
          items: [fixtureTrade({ id: 21, symbol: 'XAUUSD', close_time: '2026-11-11T09:00:00Z', net_pnl: '-50.00' })],
          total: 12,
        })
      }),
    )
    renderWithProviders(<NeedsDescriptionList />)

    const table = await screen.findByRole('table', { name: n.title })
    const [, row] = within(table).getAllByRole('row')
    if (!row) throw new Error('one trade row expected')
    expect(within(row).getByText('XAUUSD')).toBeInTheDocument()
    expect(within(row).getByText('11.11, 10:00')).toBeInTheDocument()
    expect(within(row).getByRole('link', { name: n.describeLabel('XAUUSD', '11.11, 10:00') })).toHaveAttribute('href', '/trades/21/describe')
    expect(screen.getByRole('link', { name: n.all(12) })).toHaveAttribute('href', '/journal?status=needs_description&excluded=hide')
    // Same rule as the inbox count: needs_description, counted in statistics.
    expect(asked[0]?.getAll('status')).toEqual(['needs_description'])
    expect(asked[0]?.get('excluded')).toBe('false')
    expect(asked[0]?.get('archived')).toBe('false')
  })

  it('shows an empty note when everything is described', async () => {
    mockApi(http.get('/api/trades', () => HttpResponse.json({ items: [], total: 0 })))
    renderWithProviders(<NeedsDescriptionList />)
    expect(await screen.findByText(n.empty)).toBeInTheDocument()
  })

  it('shows a visible error when the list cannot load', async () => {
    mockApi(http.get('/api/trades', () => HttpResponse.json({ error: { code: 'internal_error', message: 'boom' } }, { status: 500 })))
    renderWithProviders(<NeedsDescriptionList />)
    expect(await screen.findByRole('alert')).toHaveTextContent(n.error)
  })
})
