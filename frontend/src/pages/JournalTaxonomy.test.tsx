/** M8-04..08 Journal page: journal field filters in the URL and the API query; trade detail violations. */
import { screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { TAXONOMY_FIELDS, emptyTaxonomyJournal } from '@/features/describe/journalFields.fixture'
import { fixtureTrade } from '@/features/describe/trade.fixture'
import { uk } from '@/i18n/uk'
import { renderWithProviders } from '@/test/render'
import { mockApi } from '@/test/server'
import { JournalPage } from './JournalPage'

const j = uk.journal

function serveJournal() {
  const queries: URLSearchParams[] = []
  mockApi(
    http.get('/api/accounts', () => HttpResponse.json({ items: [] })),
    http.get('/api/journal-fields', () => HttpResponse.json({ fields: TAXONOMY_FIELDS })),
    http.get('/api/trades/symbols', () => HttpResponse.json({ items: ['EURUSD'] })),
    http.get('/api/trades', ({ request }) => {
      queries.push(new URL(request.url).searchParams)
      return HttpResponse.json({ items: [fixtureTrade({ status: 'complete' })], total: 1 })
    }),
  )
  return queries
}

function urlParams(router: { state: { location: { search: string } } }): URLSearchParams {
  return new URLSearchParams(router.state.location.search)
}

describe('JournalPage: journal field filters (M8-04..08)', () => {
  it('offers the new fields as filters with labels from the API', async () => {
    serveJournal()
    renderWithProviders(<JournalPage />, { path: '/journal' })
    for (const label of ['POI', 'Тип FVG H1', 'Тип FVG H4', 'Контекст H1', 'Контекст H4', 'Модель входу']) {
      expect(await screen.findByRole('button', { name: new RegExp(`^${label}`) })).toBeInTheDocument()
    }
    // Legacy fields are never filters.
    expect(screen.queryByRole('button', { name: /^Контекст \(Flow/ })).not.toBeInTheDocument()
  })

  it('puts journal=<key>:<value> in the URL and the query, «не заповнено» as null, with the other filters', async () => {
    const queries = serveJournal()
    const { user, router } = renderWithProviders(<JournalPage />, { path: '/journal', url: '/journal?status=complete&page=2' })

    await user.click(await screen.findByRole('button', { name: /^POI/ }))
    const list = await screen.findByRole('list', { name: 'POI' })
    await user.click(within(list).getByRole('checkbox', { name: 'FVG H1' }))
    await user.click(within(list).getByRole('checkbox', { name: j.filters.notFilled }))

    await waitFor(() => expect(queries.at(-1)?.getAll('journal')).toEqual(['poi_types:fvg_h1', 'poi_types:null']))
    expect(queries.at(-1)?.getAll('status')).toEqual(['complete'])
    expect(queries.at(-1)?.get('offset')).toBe('0')
    expect(urlParams(router).getAll('journal')).toEqual(['poi_types:fvg_h1', 'poi_types:null'])
    expect(urlParams(router).has('page')).toBe(false)
  })

  it('restores journal filters of several fields from the URL (reload)', async () => {
    const queries = serveJournal()
    renderWithProviders(<JournalPage />, {
      path: '/journal',
      url: '/journal?journal=h1_context:flow&journal=entry_model:qm_m5&journal=h1_context:range',
    })
    await waitFor(() => expect(queries.length).toBeGreaterThan(0))
    expect(queries[0]?.getAll('journal')).toEqual(['h1_context:flow', 'h1_context:range', 'entry_model:qm_m5'])
    expect(await screen.findByRole('button', { name: /^Контекст H1/ })).toHaveTextContent(j.filters.selected(2))
    expect(screen.getByRole('button', { name: /^Модель входу/ })).toHaveTextContent('QM M5')
    expect(screen.getByRole('button', { name: j.resetFilters })).toBeInTheDocument()
  })
})

describe('Trade detail dialog: violations and old fields (M8-04..08)', () => {
  it('shows each violation with its details and a legacy value', async () => {
    serveJournal()
    mockApi(
      http.get('/api/trades/7', () =>
        HttpResponse.json(
          fixtureTrade({
            status: 'complete',
            journal: { ...emptyTaxonomyJournal(), fvg_kind: 'na' },
            rule_violations: [
              { rule_key: 'daily_risk', source: 'auto', details: 'daily_stop_loss_pct: day P&L reached -3.10% before entry <= limit -3.0%' },
              { rule_key: 'entry_weak_poi', source: 'user', details: null },
            ],
          }),
        ),
      ),
    )
    const { user } = renderWithProviders(<JournalPage />, { path: '/journal' })
    await user.click(await screen.findByRole('row', { name: j.openRow('EURUSD') }))
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByText('Порушення денного ризику')).toBeInTheDocument()
    expect(within(dialog).getByText(/day P&L reached -3\.10%/)).toBeInTheDocument()
    expect(within(dialog).getByText('Вхід від слабкої POI')).toBeInTheDocument()
    expect(within(dialog).getByText(uk.describe.form.legacyValue('н/з'))).toBeInTheDocument()
    expect(within(dialog).queryByText('Контекст (Flow H1 синхронний з H4)')).not.toBeInTheDocument()
  })
})
