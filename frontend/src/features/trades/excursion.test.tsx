import { render, screen, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { FIXTURE_FIELDS } from '@/features/describe/journalFields.fixture'
import { fixtureTrade } from '@/features/describe/trade.fixture'
import { ExcursionsCard } from '@/features/digests/ExcursionsCard'
import { uk } from '@/i18n/uk'
import { renderWithProviders } from '@/test/render'
import { mockApi } from '@/test/server'
import { formatR } from './format'
import { ExcursionR } from './TradeCell'
import { TradeDetailDialog } from './TradeDetailDialog'
import type { TradeDetail } from './types'

const x = uk.trades.excursion

function serve(trade: TradeDetail) {
  mockApi(
    http.get(`/api/trades/${trade.id}`, () => HttpResponse.json(trade)),
    http.get('/api/journal-fields', () => HttpResponse.json({ fields: FIXTURE_FIELDS })),
  )
}

describe('M8-16 MAE / MFE', () => {
  it('cell: R, «поточні» for an open trade, a note without MT5 history', () => {
    const { rerender } = render(<ExcursionR value="1.0000" status="final" />)
    expect(screen.getByText(formatR('1.0000'))).toBeInTheDocument()
    expect(screen.queryByText(x.running)).not.toBeInTheDocument()

    rerender(<ExcursionR value="0.5000" status="running" />)
    expect(screen.getByText(x.running)).toBeInTheDocument()

    rerender(<ExcursionR value={null} status="unavailable" />)
    expect(screen.getByText(x.unavailable)).toBeInTheDocument()
  })

  it('trade details show both sides with points, price and Brussels time', async () => {
    const trade = fixtureTrade({
      excursion_status: 'final',
      mfe_r: '1.0000',
      mfe_points: '300.0',
      mfe_price: '1.16800',
      mfe_time: '2026-10-20T06:10:00Z',
      mae_r: null,
      mae_points: '120.0',
      mae_price: '1.16380',
      mae_time: '2026-10-20T06:05:00Z',
    })
    serve(trade)
    renderWithProviders(<TradeDetailDialog tradeId={trade.id} onClose={() => {}} />)

    const mfe = await screen.findByText((text) => text.startsWith(`${formatR('1.0000')} · 300.0 п.`))
    expect(mfe).toHaveTextContent('20.10.2026')
    // without R on this side: points only, marked
    expect(screen.getByText((text) => text.startsWith('120.0 п.') && text.includes(x.noSl))).toBeInTheDocument()
  })

  it('trade details say when it is not computed yet', async () => {
    const trade = fixtureTrade({ excursion_status: null })
    serve(trade)
    renderWithProviders(<TradeDetailDialog tradeId={trade.id} onClose={() => {}} />)
    expect(await screen.findByText(x.notYet)).toBeInTheDocument()
  })

  it('digest card: averages and losers that reached 1R first', () => {
    render(
      <ExcursionsCard
        block={{
          n_winners: 2,
          n_losers: 2,
          winners_avg_mfe_r: '2.0000',
          losers_avg_mfe_r: '0.7000',
          losers_reached_1r: 1,
          losers_reached_1r_share: '50.0000',
        }}
      />,
    )
    const t = uk.digests.excursions
    const card = screen.getByRole('region', { name: t.title })
    expect(within(card).getByText(t.winners(2)).nextElementSibling).toHaveTextContent(formatR('2.0000'))
    expect(within(card).getByText(t.reached).nextElementSibling).toHaveTextContent('1 (50')
  })
})
