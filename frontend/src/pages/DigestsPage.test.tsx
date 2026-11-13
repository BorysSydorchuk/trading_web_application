import { screen, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { fixtureListItem } from '@/features/digests/digest.fixture'
import { uk } from '@/i18n/uk'
import { renderWithProviders } from '@/test/render'
import { mockApi } from '@/test/server'
import { DigestsPage } from './DigestsPage'

const l = uk.digests.list

beforeEach(() => mockApi(http.get('/api/digests/suggestion', () => HttpResponse.json({ weekly: null, monthly: null }))))

const DIGEST_PAGE = 'digest page'

function render(url = '/digests') {
  return renderWithProviders(<DigestsPage />, {
    path: '/digests',
    url,
    routes: [{ path: '/digests/:kind/:date', element: <p>{DIGEST_PAGE}</p> }],
  })
}

describe('DigestsPage list', () => {
  it('shows reviewed and virtual rows newest first with their badges', async () => {
    mockApi(
      http.get('/api/digests', () =>
        HttpResponse.json({
          items: [
            fixtureListItem({ id: null, period_start: '2026-11-09', period_end: '2026-11-15', generated_at: null, net_pnl_pct: null, total_r: null, win_rate: null, trades: 3, net_pnl: '-40.00' }),
            fixtureListItem({ id: 4, period_start: '2026-11-02', period_end: '2026-11-08', reviewed: true, reviewed_at: '2026-11-07T23:30:00Z', net_pnl: '310.00', net_pnl_pct: '3.1000', total_r: '4.2500', win_rate: '66.6667' }),
          ],
        }),
      ),
    )
    render()
    const table = await screen.findByRole('table', { name: uk.digests.kinds.weekly })
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows).toHaveLength(2)
    const [virtual, reviewed] = rows as [HTMLElement, HTMLElement]
    expect(within(virtual).getByRole('link', { name: 'Тиждень 9–15 лист. 2026' })).toHaveAttribute('href', '/digests/weekly/2026-11-09')
    expect(within(virtual).getByText(l.notReviewed)).toBeInTheDocument()
    expect(within(virtual).getByText('−40.00')).toHaveClass('text-loss')
    expect(within(virtual).getAllByText(uk.common.empty)).toHaveLength(3)
    // 23:30 UTC on 7 Nov is 8 Nov in Brussels.
    expect(within(reviewed).getByText(l.reviewed('08.11.2026'))).toBeInTheDocument()
    expect(within(reviewed).getByText('3.10%')).toBeInTheDocument()
    expect(within(reviewed).getByText('+4.25R')).toBeInTheDocument()
    expect(within(reviewed).getByText('66.67%')).toBeInTheDocument()
  })

  it('switches to monthly digests', async () => {
    const kinds: (string | null)[] = []
    mockApi(
      http.get('/api/digests', ({ request }) => {
        const kind = new URL(request.url).searchParams.get('kind')
        kinds.push(kind)
        return HttpResponse.json({ items: kind === 'monthly' ? [fixtureListItem({ kind: 'monthly', period_start: '2026-11-01', period_end: '2026-11-30' })] : [] })
      }),
    )
    const { user } = render()
    expect(await screen.findByText(l.empty)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: uk.digests.kinds.monthly }))
    expect(await screen.findByRole('link', { name: 'Місяць: листопад 2026' })).toHaveAttribute('href', '/digests/monthly/2026-11-01')
    expect(kinds).toEqual(['weekly', 'monthly'])
  })

  it('shows a load error with retry', async () => {
    mockApi(http.get('/api/digests', () => HttpResponse.json({ error: { code: 'db_unavailable', message: 'down' } }, { status: 503 })))
    const { user } = render()
    expect(await screen.findByText(uk.errors.db_unavailable)).toBeInTheDocument()
    mockApi(http.get('/api/digests', () => HttpResponse.json({ items: [fixtureListItem()] })))
    await user.click(screen.getByRole('button', { name: uk.common.retry }))
    expect(await screen.findByRole('link', { name: 'Тиждень 9–15 лист. 2026' })).toBeInTheDocument()
  })

  it('opens the period of the Home suggestion link', async () => {
    const { router } = render('/digests?kind=monthly&date=2026-10-01')
    expect(await screen.findByText(DIGEST_PAGE)).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/digests/monthly/2026-10-01')
  })
})
