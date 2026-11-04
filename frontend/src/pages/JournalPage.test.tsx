import { screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { FIXTURE_FIELDS } from '@/features/describe/journalFields.fixture'
import { fixtureTrade } from '@/features/describe/trade.fixture'
import { uk } from '@/i18n/uk'
import { renderWithProviders } from '@/test/render'
import { mockApi } from '@/test/server'
import { JournalPage } from './JournalPage'

const j = uk.journal

/** GET /api/trades records every query string; trades are returned unless the new-fields filter is on. */
function serveJournal() {
  const queries: URLSearchParams[] = []
  mockApi(
    http.get('/api/accounts', () => HttpResponse.json({ items: [] })),
    http.get('/api/journal-fields', () => HttpResponse.json({ fields: FIXTURE_FIELDS })),
    http.get('/api/trades/symbols', () => HttpResponse.json({ items: ['EURUSD'] })),
    http.get('/api/trades', ({ request }) => {
      const params = new URL(request.url).searchParams
      queries.push(params)
      if (params.get('missing_new_fields') === 'true') return HttpResponse.json({ items: [], total: 0 })
      return HttpResponse.json({ items: [fixtureTrade({ status: 'complete' })], total: 1 })
    }),
  )
  return queries
}

describe('JournalPage: "Неповні за новими полями"', () => {
  it('sends missing_new_fields=true, puts it in the URL, resets the page and shows the empty state', async () => {
    const queries = serveJournal()
    const { user, router } = renderWithProviders(<JournalPage />, { path: '/journal', url: '/journal?page=2' })

    const toggle = await screen.findByRole('checkbox', { name: j.filters.missingNewFields })
    expect(toggle).not.toBeChecked()
    expect(queries.at(-1)?.has('missing_new_fields')).toBe(false)

    await user.click(toggle)

    expect(await screen.findByText(j.emptyMissingNewFields)).toBeInTheDocument()
    const last = queries.at(-1)
    expect(last?.get('missing_new_fields')).toBe('true')
    expect(last?.get('offset')).toBe('0')
    const url = new URLSearchParams(router.state.location.search)
    expect(url.get('missing_new_fields')).toBe('true')
    expect(url.has('page')).toBe(false)
    expect(screen.getByRole('checkbox', { name: j.filters.missingNewFields })).toBeChecked()
  })

  it('restores the filter from the URL (reload) and combines it with the other filters', async () => {
    const queries = serveJournal()
    renderWithProviders(<JournalPage />, {
      path: '/journal',
      url: '/journal?missing_new_fields=true&status=complete',
    })

    expect(await screen.findByText(j.emptyMissingNewFields)).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: j.filters.missingNewFields })).toBeChecked()
    const first = queries[0]
    expect(first?.get('missing_new_fields')).toBe('true')
    expect(first?.getAll('status')).toEqual(['complete'])
  })
})
