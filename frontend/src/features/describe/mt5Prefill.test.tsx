import { screen, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import type { JournalField, TradeDetail } from '@/features/trades/types'
import { uk } from '@/i18n/uk'
import { DescribePage } from '@/pages/DescribePage'
import { renderWithProviders } from '@/test/render'
import { mockApi } from '@/test/server'
import { fieldDomId } from './formModel'
import { initialMt5Filled } from './mt5Prefill'
import { fixtureTrade } from './trade.fixture'
import type { JournalInput } from './types'

const f = uk.describe.form
const opt = (value: string) => ({ value, label: value, deprecated: false })
const FIELDS: readonly JournalField[] = [
  {
    key: 'exit_reason',
    label: 'Причина виходу',
    type: 'enum',
    options: [opt('fractal_update'), opt('point_b'), opt('sl'), opt('tp')],
    required: true,
    storage: 'column',
  },
]

function prefilled(source: TradeDetail['exit_reason_source'], value: string | null = 'sl'): TradeDetail {
  return fixtureTrade({ exit_reason_source: source, journal: { exit_reason: value } })
}

function serve(trade: TradeDetail) {
  const saved: JournalInput[] = []
  mockApi(
    http.get(`/api/trades/${trade.id}`, () => HttpResponse.json(trade)),
    http.get('/api/journal-fields', () => HttpResponse.json({ fields: FIELDS })),
    http.put(`/api/trades/${trade.id}/journal`, async ({ request }) => {
      saved.push((await request.json()) as JournalInput)
      return HttpResponse.json({ ...trade, status: 'draft' })
    }),
  )
  return saved
}

function renderPage(trade: TradeDetail) {
  return renderWithProviders(<DescribePage />, {
    path: '/trades/:id/describe',
    url: `/trades/${trade.id}/describe`,
    routes: [{ path: '/inbox', element: <div data-testid="inbox-page" /> }],
  })
}

/** The exit_reason field block (label row + buttons). */
async function exitReasonBlock(): Promise<HTMLElement> {
  const label = await screen.findByText('Причина виходу')
  const block = label.closest<HTMLElement>('[role="group"]')
  if (!block) throw new Error('no exit_reason group')
  return block
}

describe('MT5-prefilled exit reason (M8-09)', () => {
  it('marks only an untouched MT5 or price-match value', () => {
    expect([...initialMt5Filled(prefilled('mt5_reason'))]).toEqual([['exit_reason', 'mt5_reason']])
    expect([...initialMt5Filled(prefilled('price_match'))]).toEqual([['exit_reason', 'price_match']])
    expect(initialMt5Filled(prefilled('owner')).size).toBe(0)
    expect(initialMt5Filled(prefilled(null)).size).toBe(0)
    expect(initialMt5Filled(prefilled('mt5_reason', null)).size).toBe(0)
  })

  it('shows the MT5 badge with the source hint and drops it once the owner changes the value', async () => {
    const trade = prefilled('price_match')
    const saved = serve(trade)
    const { user } = renderPage(trade)

    const block = await exitReasonBlock()
    const badge = within(block).getByText(f.mt5Badge)
    expect(badge).toHaveAttribute('title', f.mt5FilledHint.price_match)
    expect(within(block).getByRole('button', { name: 'sl' })).toHaveAttribute('aria-pressed', 'true')

    const field = document.getElementById(fieldDomId('exit_reason'))
    if (!field) throw new Error('no exit_reason field')
    await user.click(within(field).getByRole('button', { name: 'fractal_update' }))
    expect(within(block).queryByText(f.mt5Badge)).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: uk.describe.save.draft }))
    expect(await screen.findByTestId('inbox-page')).toBeInTheDocument()
    expect(saved[0]?.fields).toMatchObject({ exit_reason: 'fractal_update' })
  })

  it('shows no badge for an owner value', async () => {
    const trade = prefilled('owner', 'point_b')
    serve(trade)
    renderPage(trade)
    const block = await exitReasonBlock()
    expect(within(block).queryByText(f.mt5Badge)).not.toBeInTheDocument()
    expect(within(block).queryByText(f.aiBadge)).not.toBeInTheDocument()
  })
})
