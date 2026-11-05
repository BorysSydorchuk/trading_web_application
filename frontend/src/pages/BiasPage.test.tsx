import { screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { fixtureBiasNote, fixtureEntry } from '@/features/bias/bias.fixture'
import type { BiasNote } from '@/features/bias/types'
import { uk } from '@/i18n/uk'
import { renderWithProviders } from '@/test/render'
import { mockApi } from '@/test/server'
import { BiasPage } from './BiasPage'

const l = uk.bias.list
const r = uk.bias.result

/** GET /api/bias/notes records the `kind` filter of every request and answers with the matching notes. */
function serveNotes(notes: readonly BiasNote[]) {
  const requests: string[][] = []
  mockApi(
    http.get('/api/bias/notes', ({ request }) => {
      const kinds = new URL(request.url).searchParams.getAll('kind')
      requests.push(kinds)
      const items = kinds.length === 0 ? notes : notes.filter((note) => kinds.includes(note.kind))
      return HttpResponse.json({ items })
    }),
  )
  return requests
}

const NOTES = [
  fixtureBiasNote({
    id: 4,
    kind: 'pre_ny',
    period_date: '2026-11-03',
    entries: [
      fixtureEntry({ id: 41, symbol: 'EURUSD', direction: 'bearish', key_levels: '1.0850 POI', confidence: 3 }),
      fixtureEntry({ id: 42, symbol: 'XAUUSD', direction: 'no_trade', key_levels: null, confidence: null }),
    ],
  }),
  fixtureBiasNote({ id: 5, kind: 'pre_london', period_date: '2026-11-03', entries: [] }),
  fixtureBiasNote({
    id: 6,
    kind: 'weekly',
    period_date: '2026-11-02',
    entries: [fixtureEntry({ id: 61, symbol: 'GER40', direction: 'neutral', was_correct: true, was_correct_source: 'manual' })],
  }),
]

function renderPage(url = '/bias') {
  return renderWithProviders(<BiasPage />, {
    path: '/bias',
    url,
    routes: [
      { path: '/bias/new', element: <div data-testid="new-page" /> },
      { path: '/bias/:id', element: <div data-testid="note-page" /> },
    ],
  })
}

describe('BiasPage list', () => {
  it('groups notes by date with kind labels and a compact row per symbol', async () => {
    serveNotes(NOTES)
    renderPage()

    const day = await screen.findByRole('region', { name: '03.11.2026, вт' })
    const ny = within(day).getByRole('article', { name: l.noteLabel(uk.bias.kinds.pre_ny, '03.11.2026') })
    const eur = within(ny).getByRole('listitem', { name: 'EURUSD' })
    expect(eur).toHaveTextContent(uk.bias.directions.bearish)
    expect(eur).toHaveTextContent(l.confidence(3))
    expect(eur).toHaveTextContent('1.0850 POI')
    const xau = within(ny).getByRole('listitem', { name: 'XAUUSD' })
    expect(xau).toHaveTextContent(uk.bias.directions.no_trade)
    expect(xau).toHaveTextContent(l.noLevels)
    const london = within(day).getByRole('article', { name: l.noteLabel(uk.bias.kinds.pre_london, '03.11.2026') })
    expect(london).toHaveTextContent(l.noEntries)
    expect(within(ny).getByRole('link', { name: l.open })).toHaveAttribute('href', '/bias/4')

    const week = screen.getByRole('region', { name: '02.11.2026, пн' })
    expect(within(week).getByRole('article', { name: l.noteLabel(uk.bias.kinds.weekly, '02.11.2026') })).toHaveTextContent(
      l.weekOf('02.11', '08.11'),
    )
  })

  it('filters by kind through the API and offers a new note of that kind', async () => {
    const requests = serveNotes(NOTES)
    const { user, router } = renderPage()
    await screen.findByRole('region', { name: '03.11.2026, вт' })

    const filter = screen.getByRole('group', { name: l.filterLabel })
    await user.click(within(filter).getByRole('button', { name: uk.bias.kinds.weekly }))

    await waitFor(() => expect(requests.at(-1)).toEqual(['weekly']))
    await waitFor(() => expect(screen.queryByRole('region', { name: '03.11.2026, вт' })).not.toBeInTheDocument())
    expect(screen.getByRole('region', { name: '02.11.2026, пн' })).toBeInTheDocument()
    expect(router.state.location.search).toBe('?kind=weekly')
    expect(within(filter).getByRole('button', { name: uk.bias.kinds.weekly })).toHaveAttribute('aria-pressed', 'true')
    expect(within(filter).getByRole('button', { name: l.allKinds })).toHaveAttribute('aria-pressed', 'false')

    await user.click(screen.getByRole('link', { name: l.newBias }))
    expect(await screen.findByTestId('new-page')).toBeInTheDocument()
    expect(router.state.location.search).toBe('?kind=weekly')
  })

  it('shows the empty state and a load error with retry', async () => {
    let calls = 0
    mockApi(
      http.get('/api/bias/notes', () => {
        calls += 1
        if (calls === 1) return HttpResponse.json({ error: { code: 'config_error', message: 'x', details: { reason: 'mojibake', file: 'bias.yaml' } } }, { status: 500 })
        return HttpResponse.json({ items: [] })
      }),
    )
    const { user } = renderPage()

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(l.loadError)
    expect(alert).toHaveTextContent(uk.errors.config_error_reasons.mojibake('bias.yaml'))
    await user.click(within(alert).getByRole('button', { name: uk.common.retry }))
    expect(await screen.findByText(l.empty)).toBeInTheDocument()
  })
})

describe('BiasPage result marking', () => {
  it('marks a symbol as correct, then resets it (PATCH result)', async () => {
    serveNotes(NOTES)
    const bodies: unknown[] = []
    mockApi(
      http.patch('/api/bias/entries/41/result', async ({ request }) => {
        const body = (await request.json()) as { was_correct: boolean | null }
        bodies.push(body)
        return HttpResponse.json(
          fixtureEntry({ id: 41, symbol: 'EURUSD', direction: 'bearish', key_levels: '1.0850 POI', confidence: 3, was_correct: body.was_correct, was_correct_source: body.was_correct === null ? null : 'manual' }),
        )
      }),
    )
    const { user } = renderPage()

    const eur = await screen.findByRole('listitem', { name: 'EURUSD' })
    const group = within(eur).getByRole('group', { name: r.groupLabel('EURUSD') })
    await user.click(within(group).getByRole('button', { name: r.yes }))

    await waitFor(() => expect(within(group).getByRole('button', { name: r.yes })).toHaveAttribute('aria-pressed', 'true'))
    await user.click(within(group).getByRole('button', { name: r.reset }))
    await waitFor(() => expect(within(group).getByRole('button', { name: r.yes })).toHaveAttribute('aria-pressed', 'false'))
    expect(bodies).toEqual([{ was_correct: true }, { was_correct: null }])
  })

  it('shows a saved mark and no marking on a future note', async () => {
    serveNotes([
      ...NOTES,
      fixtureBiasNote({ id: 9, period_date: '2099-01-02', entries: [fixtureEntry({ id: 91, symbol: 'GBPUSD' })] }),
    ])
    renderPage()

    const ger = await screen.findByRole('listitem', { name: 'GER40' })
    expect(within(ger).getByRole('button', { name: r.yes })).toHaveAttribute('aria-pressed', 'true')
    const gbp = screen.getByRole('listitem', { name: 'GBPUSD' })
    expect(within(gbp).queryByRole('group')).not.toBeInTheDocument()
  })
})
