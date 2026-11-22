/** M8-04..08 digest breakdowns: field (multi note), combination, H1 × H4 matrix, old snapshots. */
import { screen, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { TAXONOMY_FIELDS } from '@/features/describe/journalFields.fixture'
import { uk } from '@/i18n/uk'
import { renderWithProviders } from '@/test/render'
import { mockApi } from '@/test/server'
import { BreakdownTables } from './BreakdownTables'
import type { Breakdown } from './types'

const t = uk.digests.breakdowns

function group(key: Breakdown['groups'][number]['key'], trades: number, netPnl: string, totalR: string, winRate: string | null) {
  return { key, trades, net_pnl: netPnl, total_r: totalR, win_rate: winRate }
}

function render(breakdowns: Record<string, Breakdown>) {
  mockApi(http.get('/api/journal-fields', () => HttpResponse.json({ fields: TAXONOMY_FIELDS })))
  return renderWithProviders(<BreakdownTables breakdowns={breakdowns} currency="USD" />)
}

describe('BreakdownTables (M8-04..08)', () => {
  it('shows weekday and hour as pastel cells, not tables, scaled by P&L', async () => {
    render({
      weekday: { kind: 'field', groups: [group(0, 2, '300.00', '3.0000', '100.0000'), group(1, 1, '-30.00', '-0.3000', '0.0000')], coverage: { filled: 3, total: 3 } },
      hour: { kind: 'field', groups: [group(9, 3, '0.00', '0.0000', null)], coverage: { filled: 3, total: 3 } },
    })
    const days = await screen.findByRole('article', { name: uk.trades.columns.weekday })
    expect(within(days).queryByRole('table')).not.toBeInTheDocument()
    expect(within(days).getByText(uk.trades.weekdays[0] ?? '').closest('li')).toHaveClass('bg-profit-light')
    expect(within(days).getByText(uk.trades.weekdays[1] ?? '').closest('li')).toHaveClass('bg-loss-wash')
    const hours = screen.getByRole('article', { name: uk.trades.columns.hour })
    expect(within(hours).getByText(t.hour('09')).closest('li')).toHaveClass('bg-track')
    expect(within(hours).getByText(t.cellTrades(3))).toBeInTheDocument()
  })

  it('renders a multi field with the «each value» note and coverage', async () => {
    render({
      poi_types: {
        kind: 'field',
        groups: [group('fvg_h4', 2, '150.00', '2.0000', '50.0000'), group(null, 1, '-50.00', '-1.0000', '0.0000')],
        coverage: { filled: 2, total: 3 },
      },
    })
    const table = await screen.findByRole('article', { name: 'POI' })
    expect(await within(table).findByText('FVG H4')).toBeInTheDocument()
    expect(within(table).getByText(t.multiNote)).toBeInTheDocument()
    expect(within(table).getByText(t.coverage(2, 3))).toBeInTheDocument()
    expect(within(table).getByText(t.notFilled)).toBeInTheDocument()
  })

  it('renders the combination table «POI: комбінації» with option labels', async () => {
    render({
      poi_types__combo: {
        kind: 'combination',
        groups: [group('fvg_h4 + fvg_h1', 1, '100.00', '1.5000', '100.0000'), group('other', 1, '-20.00', '-0.5000', '0.0000')],
        coverage: { filled: 2, total: 2 },
      },
    })
    const table = await screen.findByRole('article', { name: t.combinationTitle('POI') })
    expect(await within(table).findByText('FVG H4 + FVG H1')).toBeInTheDocument()
    expect(within(table).getByText('Інше')).toBeInTheDocument()
    expect(within(table).queryByText(t.multiNote)).not.toBeInTheDocument()
  })

  it('renders the H1 × H4 matrix: H1 rows, H4 columns, «N угод · P&L · R · WR», empty cells «—»', async () => {
    render({
      h1_context__x__h4_context: {
        kind: 'matrix',
        groups: [
          group(['flow', 'flow'], 3, '300.00', '4.5000', '66.6667'),
          group(['range', 'reversal'], 1, '-100.00', '-1.0000', '0.0000'),
          group(['flow', null], 1, '10.00', '0.2000', '100.0000'),
        ],
        coverage: { filled: 4, total: 5 },
      },
    })
    const table = await screen.findByRole('article', { name: t.matrixTitle('Контекст H1', 'Контекст H4') })
    expect(await within(table).findByRole('columnheader', { name: 'Reversal' })).toBeInTheDocument()
    expect(within(table).getByText(t.coverage(4, 5))).toBeInTheDocument()
    const headers = within(table).getAllByRole('columnheader').map((h) => h.textContent)
    expect(headers).toEqual([t.matrixCorner('Контекст H1', 'Контекст H4'), 'Flow', 'Reversal', t.notFilled])
    const flow = within(table).getByRole('rowheader', { name: 'Flow' }).closest('tr')
    const range = within(table).getByRole('rowheader', { name: 'Range' }).closest('tr')
    if (!flow || !range) throw new Error('missing matrix rows')
    const flowCells = within(flow).getAllByRole('cell')
    expect(flowCells[0]).toHaveTextContent(new RegExp(`^${t.matrixTrades(3)} · .*300.* · .*4\\.5.* · 66`))
    expect(flowCells[1]).toHaveTextContent(t.matrixEmpty)
    expect(flowCells[2]).toHaveTextContent(t.matrixTrades(1))
    expect(within(range).getAllByRole('cell')[0]).toHaveTextContent(t.matrixEmpty)
    expect(within(range).getAllByRole('cell')[1]).toHaveTextContent(t.matrixTrades(1))
  })

  it('shows an old `poi_type` breakdown with the POI field label and option labels', async () => {
    render({
      poi_type: {
        groups: [group('fvg_h1', 2, '40.00', '1.0000', '50.0000'), group(null, 1, '-10.00', '-0.2000', '0.0000')],
        coverage: { filled: 2, total: 3 },
      },
    })
    const table = await screen.findByRole('article', { name: 'POI' })
    expect(await within(table).findByText('FVG H1')).toBeInTheDocument()
    expect(within(table).getByText(t.coverage(2, 3))).toBeInTheDocument()
    // A single-choice old breakdown: no «each value» note.
    expect(within(table).queryByText(t.multiNote)).not.toBeInTheDocument()
  })

  it('treats a snapshot entry without kind as a field breakdown (old digests)', async () => {
    render({
      entry_model: {
        groups: [group('qm_m5', 2, '80.00', '1.0000', '50.0000')],
        coverage: { filled: 2, total: 2 },
      },
    })
    const table = await screen.findByRole('article', { name: 'Модель входу' })
    expect(await within(table).findByText('QM M5')).toBeInTheDocument()
    expect(within(table).getByText(t.coverage(2, 2))).toBeInTheDocument()
    expect(within(table).queryByText(t.multiNote)).not.toBeInTheDocument()
  })
})
