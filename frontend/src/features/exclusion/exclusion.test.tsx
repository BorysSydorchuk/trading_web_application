import { screen, within } from '@testing-library/react'
import { setupUser } from '@/test/user'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { fixtureTrade } from '@/features/describe/trade.fixture'
import { formatPct } from '@/features/dashboard/format'
import { ExcludedTrades } from '@/features/digests/ExcludedTrades'
import { TradesTable } from '@/features/journal/TradesTable'
import { formatSignedMoney } from '@/features/trades/format'
import type { TradeDetail } from '@/features/trades/types'
import { uk } from '@/i18n/uk'
import { renderWithProviders } from '@/test/render'
import { mockApi } from '@/test/server'
import { ExclusionPanel } from './ExclusionPanel'

const t = uk.exclusion
const REASON = 'перевірка торгівлі на новому рахунку'

function excludedTrade(): TradeDetail {
  return fixtureTrade({
    symbol: 'XAUUSD',
    excluded_from_stats: true,
    excluded_reason: REASON,
    excluded_at: '2026-11-18T10:00:00Z',
    exclusion_history: [{ action: 'exclude', reason: REASON, at: '2026-11-18T10:00:00Z' }],
  })
}

function serveExclusion(trade: TradeDetail) {
  const calls: { path: string; body: unknown }[] = []
  const handler = async ({ request }: { request: Request }) => {
    calls.push({ path: new URL(request.url).pathname, body: await request.json() })
    return HttpResponse.json(trade)
  }
  mockApi(http.post(`/api/trades/${trade.id}/exclude`, handler), http.post(`/api/trades/${trade.id}/include`, handler))
  return calls
}

describe('ExclusionPanel (Describe screen)', () => {
  it('requires a reason before excluding, then sends the trimmed reason', async () => {
    const user = setupUser()
    const trade = fixtureTrade()
    const calls = serveExclusion(trade)
    renderWithProviders(<ExclusionPanel trade={trade} />)

    await user.click(screen.getByRole('button', { name: t.exclude }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: t.exclude }))
    expect(within(dialog).getByText(t.reasonRequired)).toBeInTheDocument()
    expect(calls).toHaveLength(0)

    await user.type(within(dialog).getByLabelText(t.reason), `  ${REASON}  `)
    await user.click(within(dialog).getByRole('button', { name: t.exclude }))

    await screen.findByText(t.excludedToast)
    expect(calls).toEqual([{ path: `/api/trades/${trade.id}/exclude`, body: { reason: REASON } }])
  })

  it('shows the excluded state, reason and history, and returns the trade without a reason', async () => {
    const user = setupUser()
    const trade = excludedTrade()
    const calls = serveExclusion(trade)
    renderWithProviders(<ExclusionPanel trade={trade} />)

    expect(screen.getByText(t.panelExcluded)).toBeInTheDocument()
    expect(screen.getByText(REASON)).toBeInTheDocument()
    expect(screen.getByText(t.badge)).toHaveAttribute('title', t.badgeTitle(REASON))

    await user.click(screen.getByRole('button', { name: t.include }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: t.include }))

    await screen.findByText(t.includedToast)
    expect(calls).toEqual([{ path: `/api/trades/${trade.id}/include`, body: { reason: null } }])
  })

  it('shows a server error inside the dialog', async () => {
    const user = setupUser()
    const trade = fixtureTrade()
    mockApi(
      http.post(`/api/trades/${trade.id}/exclude`, () =>
        HttpResponse.json({ error: { code: 'already_excluded', message: 'x' } }, { status: 409 }),
      ),
    )
    renderWithProviders(<ExclusionPanel trade={trade} />)

    await user.click(screen.getByRole('button', { name: t.exclude }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText(t.reason), REASON)
    await user.click(within(dialog).getByRole('button', { name: t.exclude }))

    expect(await within(dialog).findByRole('alert')).toHaveTextContent(uk.errors.already_excluded)
  })
})

describe('Journal row', () => {
  it('shows the badge and opens the dialog from the row menu without opening the row', async () => {
    const user = setupUser()
    const opened: number[] = []
    renderWithProviders(
      <TradesTable
        trades={[excludedTrade()]}
        columns={['symbol']}
        sort="close_time"
        order="desc"
        onSort={() => undefined}
        onOpen={(trade) => opened.push(trade.id)}
        violationLabel={(key) => key}
      />,
    )

    expect(screen.getByText(t.badge)).toHaveAttribute('title', t.badgeTitle(REASON))
    await user.click(screen.getByRole('button', { name: t.menu('XAUUSD') }))
    await user.click(await screen.findByRole('button', { name: t.include }))

    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    expect(opened).toEqual([])
  })
})

describe('Digest excluded block', () => {
  it('lists excluded trades and the account total', () => {
    renderWithProviders(
      <ExcludedTrades
        currency="USD"
        block={{
          trades: 1,
          net_pnl: '-50.00',
          account_net_pnl: '50.00',
          items: [
            {
              trade_id: 3,
              account_id: 1,
              account_name: 'Alpha',
              symbol: 'XAUUSD',
              close_time: '2026-11-11T09:00:00Z',
              net_pnl: '-50.00',
              reason: REASON,
            },
          ],
        }}
      />,
    )

    expect(screen.getByRole('heading', { name: uk.digests.excluded.summary(1, `${formatSignedMoney('-50.00')} USD`) })).toBeInTheDocument()
    expect(screen.getByText(REASON)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'XAUUSD' })).toBeInTheDocument()
  })

  it('shows the account P&L percent next to the account total when the snapshot has it', () => {
    renderWithProviders(
      <ExcludedTrades
        currency="USD"
        block={{ trades: 1, net_pnl: '-50.00', account_net_pnl: '-50.00', account_net_pnl_pct: '-0.5000', items: [] }}
      />,
    )
    const pct = screen.getByTestId('excluded-account-pct')
    expect(pct).toHaveTextContent(uk.digests.excluded.accountPct(formatPct('-0.5000')))
    expect(pct).toHaveClass('text-loss')
  })

  it('shows no percent for older snapshots without account_net_pnl_pct (or null)', () => {
    const { unmount } = renderWithProviders(
      <ExcludedTrades currency="USD" block={{ trades: 1, net_pnl: '-50.00', account_net_pnl: '50.00', items: [] }} />,
    )
    expect(screen.queryByTestId('excluded-account-pct')).not.toBeInTheDocument()
    unmount()
    renderWithProviders(
      <ExcludedTrades currency="USD" block={{ trades: 1, net_pnl: '-50.00', account_net_pnl: '50.00', account_net_pnl_pct: null, items: [] }} />,
    )
    expect(screen.queryByTestId('excluded-account-pct')).not.toBeInTheDocument()
  })

  it('renders nothing without excluded trades', () => {
    renderWithProviders(
      <ExcludedTrades currency="USD" block={{ trades: 0, net_pnl: '0.00', account_net_pnl: '10.00', items: [] }} />,
    )
    expect(screen.queryByRole('heading')).not.toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })
})
