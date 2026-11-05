import { act, screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'
import { FIXTURE_BIAS_CONFIG, fixtureBiasNote, fixtureEntry } from '@/features/bias/bias.fixture'
import type { BiasExtractResult, BiasNote, BiasNoteInput } from '@/features/bias/types'
import { fixtureNote } from '@/features/voice/note.fixture'
import { uk } from '@/i18n/uk'
import { controlClock, FAKE_AUDIO, installMic, restoreMic } from '@/test/media'
import { renderWithProviders } from '@/test/render'
import { mockApi } from '@/test/server'
import { BiasNotePage } from './BiasNotePage'

const e = uk.bias.editor
const d = uk.bias.directions
const NEW_URL = '/bias/new?kind=pre_ny&date=2026-11-06'
const TRANSCRIPT = 'Золото бичаче від 2650'
const POLL_WAIT = { timeout: 4_000 }

/** Config, by-period (none) and the write endpoints; returns the recorded bodies. */
function serveEditor(options: { byPeriod?: BiasNote | null; note?: BiasNote } = {}) {
  const posted: BiasNoteInput[] = []
  const put: BiasNoteInput[] = []
  mockApi(
    http.get('/api/bias/config', () => HttpResponse.json(FIXTURE_BIAS_CONFIG)),
    http.get('/api/bias/notes/by-period', () =>
      options.byPeriod
        ? HttpResponse.json(options.byPeriod)
        : HttpResponse.json({ error: { code: 'not_found', message: 'none' } }, { status: 404 }),
    ),
    http.post('/api/bias/notes', async ({ request }) => {
      const body = (await request.json()) as BiasNoteInput
      posted.push(body)
      return HttpResponse.json(fixtureBiasNote({ id: 12, kind: body.kind, period_date: body.period_date }), { status: 201 })
    }),
    http.put('/api/bias/notes/:id', async ({ request, params }) => {
      const body = (await request.json()) as BiasNoteInput
      put.push(body)
      return HttpResponse.json(fixtureBiasNote({ id: Number(params.id), kind: body.kind, period_date: body.period_date }))
    }),
  )
  if (options.note) {
    const note = options.note
    mockApi(http.get(`/api/bias/notes/${note.id}`, () => HttpResponse.json(note)))
  }
  return { posted, put }
}

function renderPage(url = NEW_URL) {
  return renderWithProviders(<BiasNotePage />, {
    path: '/bias/:id',
    url,
    routes: [{ path: '/bias', element: <div data-testid="list-page" /> }],
  })
}

async function card(symbol: string): Promise<HTMLElement> {
  return screen.findByRole('region', { name: e.cardLabel(symbol) })
}

function fieldGroup(cardElement: HTMLElement, label: string): HTMLElement {
  return within(cardElement).getByRole('group', { name: new RegExp(`^${label}`) })
}

afterEach(restoreMic)

describe('Bias editor: create', () => {
  it('saves a filled card as POST and leaves empty cards out', async () => {
    const { posted } = serveEditor()
    const { user } = renderPage()

    const xau = await card('XAUUSD')
    expect(screen.getByRole('combobox', { name: new RegExp(`^${e.kind}`) })).toHaveValue('pre_ny')
    expect(screen.getByLabelText(new RegExp(`^${e.date}`))).toHaveValue('2026-11-06')
    await user.click(within(fieldGroup(xau, e.fields.direction)).getByRole('button', { name: d.bullish }))
    await user.type(within(xau).getByLabelText(e.fields.key_levels), '2650 POI')
    await user.click(within(fieldGroup(xau, e.fields.confidence)).getByRole('button', { name: '2' }))
    await user.type(within(xau).getByLabelText(e.fields.narrative), 'Тиск покупців')
    await user.click(screen.getByRole('button', { name: e.save }))

    expect(await screen.findByTestId('list-page')).toBeInTheDocument()
    expect(await screen.findByText(e.saved)).toBeInTheDocument()
    expect(posted).toEqual([
      {
        kind: 'pre_ny',
        period_date: '2026-11-06',
        raw_text: null,
        entries: [
          {
            symbol: 'XAUUSD',
            direction: 'bullish',
            key_levels: '2650 POI',
            narrative: 'Тиск покупців',
            confidence: 2,
            chart_links: [],
            ai_filled_fields: [],
          },
        ],
      },
    ])
  })

  it('shows the normalized Monday for a weekly note and sends it', async () => {
    const { posted } = serveEditor()
    const { user } = renderPage('/bias/new?kind=weekly&date=2026-11-06')

    const eur = await card('EURUSD')
    expect(screen.getByText(e.weekNote('02.11.2026'))).toBeInTheDocument()
    await user.click(within(fieldGroup(eur, e.fields.direction)).getByRole('button', { name: d.neutral }))
    await user.click(screen.getByRole('button', { name: e.save }))

    await screen.findByTestId('list-page')
    expect(posted[0]).toMatchObject({ kind: 'weekly', period_date: '2026-11-02' })
  })

  it('does not send a filled card without direction and marks it', async () => {
    const { posted } = serveEditor()
    const { user } = renderPage()

    const ger = await card('GER40')
    await user.type(within(ger).getByLabelText(e.fields.key_levels), '19500')
    await user.click(screen.getByRole('button', { name: e.save }))

    expect(within(ger).getByRole('alert')).toHaveTextContent(e.directionNeeded)
    expect(await screen.findByText(e.fixErrors)).toBeInTheDocument()
    expect(posted).toEqual([])
  })
})

function extractResult(entries: BiasExtractResult['entries']): BiasExtractResult {
  return {
    entries,
    dropped: [],
    usage: { model: 'm', fallback_used: false, input_tokens: 1, output_tokens: 1, cost_usd: '0.0100', duration_ms: 900 },
  }
}

describe('Bias editor: extraction', () => {
  it('fills cards with AI markers, keeps what the user typed, and saves the markers', async () => {
    const { posted } = serveEditor()
    const extractBodies: unknown[] = []
    mockApi(
      http.post('/api/bias/notes/extract', async ({ request }) => {
        extractBodies.push(await request.json())
        return HttpResponse.json(
          extractResult([
            { symbol: 'EURUSD', fields: { direction: 'bearish', confidence: 3 } },
            { symbol: 'GBPUSD', fields: { direction: 'bullish', key_levels: '1.2900' } },
          ]),
        )
      }),
    )
    const { user } = renderPage()

    const gbp = await card('GBPUSD')
    await user.type(within(gbp).getByLabelText(e.fields.key_levels), 'мої рівні')
    await user.type(screen.getByLabelText(e.rawTextLabel), 'Євро ведмеже, впевненість три. Фунт бичачий від 1.2900')
    await user.click(screen.getByRole('button', { name: uk.describe.input.extract }))

    expect(await screen.findByText(uk.describe.input.extractDone(3))).toBeInTheDocument()
    expect(extractBodies).toEqual([{ kind: 'pre_ny', text: 'Євро ведмеже, впевненість три. Фунт бичачий від 1.2900' }])
    const eur = await card('EURUSD')
    expect(within(fieldGroup(eur, e.fields.direction)).getByRole('button', { name: d.bearish })).toHaveAttribute('aria-pressed', 'true')
    expect(within(fieldGroup(eur, e.fields.direction)).getByText(uk.describe.form.aiBadge)).toBeInTheDocument()
    expect(within(gbp).getByLabelText(e.fields.key_levels)).toHaveValue('мої рівні')

    // Touching a field removes its marker.
    await user.click(within(fieldGroup(eur, e.fields.confidence)).getByRole('button', { name: '2' }))
    expect(within(fieldGroup(eur, e.fields.confidence)).queryByText(uk.describe.form.aiBadge)).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: e.save }))
    await screen.findByTestId('list-page')
    expect(posted[0]?.entries).toEqual([
      expect.objectContaining({ symbol: 'EURUSD', direction: 'bearish', confidence: 2, ai_filled_fields: ['direction'] }),
      expect.objectContaining({ symbol: 'GBPUSD', direction: 'bullish', key_levels: 'мої рівні', ai_filled_fields: ['direction'] }),
    ])
  })

  it('shows ai_not_configured as a calm note next to the button', async () => {
    serveEditor()
    mockApi(
      http.post('/api/bias/notes/extract', () =>
        HttpResponse.json({ error: { code: 'ai_not_configured', message: 'no key' } }, { status: 503 }),
      ),
    )
    const { user } = renderPage()

    await user.type(await screen.findByLabelText(e.rawTextLabel), 'Золото вгору')
    await user.click(screen.getByRole('button', { name: uk.describe.input.extract }))
    expect(await screen.findByText(uk.describe.input.aiNotConfigured)).toBeInTheDocument()
  })
})

describe('Bias editor: voice on a new note', () => {
  it('creates the note with entries [] first, uploads, appends the transcript and later saves with PUT', async () => {
    installMic()
    const clock = controlClock()
    const { posted, put } = serveEditor()
    const uploads: { type: string | null; body: string }[] = []
    const order: string[] = []
    mockApi(
      http.post('/api/bias/notes/12/audio', async ({ request }) => {
        order.push(`upload after ${posted.length} create`)
        uploads.push({ type: request.headers.get('content-type'), body: await request.text() })
        return HttpResponse.json(fixtureNote({ id: 31, trade_id: null, bias_note_id: 12 }), { status: 201 })
      }),
      http.get('/api/audio/31', () =>
        HttpResponse.json(fixtureNote({ id: 31, trade_id: null, bias_note_id: 12, status: 'done', progress: 1, transcript: TRANSCRIPT })),
      ),
    )
    const { user, router } = renderPage()

    const box = await screen.findByLabelText(e.rawTextLabel)
    await user.type(box, 'Ранок спокійний')
    const record = screen.getByRole('button', { name: uk.voice.recorder.hold })
    await user.pointer({ keys: '[MouseLeft>]', target: record })
    await screen.findByText(uk.voice.recorder.recording)
    clock.advance(3_000)
    await user.pointer({ keys: '[/MouseLeft]', target: record })

    await screen.findByRole('listitem', { name: uk.voice.notes.label(1) })
    expect(posted).toEqual([{ kind: 'pre_ny', period_date: '2026-11-06', raw_text: 'Ранок спокійний', entries: [] }])
    expect(order).toEqual(['upload after 1 create'])
    expect(uploads).toEqual([{ type: 'audio/webm', body: FAKE_AUDIO }])
    await waitFor(() => expect(router.state.location.pathname).toBe('/bias/12'))
    await waitFor(() => expect(box).toHaveValue(`Ранок спокійний\n\n${TRANSCRIPT}`), POLL_WAIT)
    // Same editor after the URL change: the delete button of the saved note is there.
    expect(screen.getByRole('button', { name: e.delete })).toBeInTheDocument()

    const xau = await card('XAUUSD')
    await user.click(within(fieldGroup(xau, e.fields.direction)).getByRole('button', { name: d.bullish }))
    await user.click(screen.getByRole('button', { name: e.save }))

    await screen.findByTestId('list-page')
    expect(posted).toHaveLength(1)
    expect(put).toEqual([
      {
        kind: 'pre_ny',
        period_date: '2026-11-06',
        raw_text: `Ранок спокійний\n\n${TRANSCRIPT}`,
        entries: [expect.objectContaining({ symbol: 'XAUUSD', direction: 'bullish' })],
      },
    ])
  })
})

describe('Bias editor: server errors', () => {
  it('shows 409 bias_note_exists with a link to the existing note', async () => {
    serveEditor()
    mockApi(
      http.post('/api/bias/notes', () =>
        HttpResponse.json({ error: { code: 'bias_note_exists', message: 'exists', details: { id: 5 } } }, { status: 409 }),
      ),
    )
    const { user } = renderPage()

    const eur = await card('EURUSD')
    await user.click(within(fieldGroup(eur, e.fields.direction)).getByRole('button', { name: d.bullish }))
    await user.click(screen.getByRole('button', { name: e.save }))

    const notice = (await screen.findByText(e.exists(uk.bias.kinds.pre_ny, '06.11.2026'))).closest('[role="alert"]')
    if (!(notice instanceof HTMLElement)) throw new Error('no notice')
    expect(within(notice).getByRole('link', { name: e.openExisting })).toHaveAttribute('href', '/bias/5')
    expect(await screen.findByText(uk.errors.bias_note_exists)).toBeInTheDocument()
  })

  it('warns ahead when a note for the kind and date exists', async () => {
    serveEditor({ byPeriod: fixtureBiasNote({ id: 8, period_date: '2026-11-06' }) })
    renderPage()

    const link = await screen.findByRole('link', { name: e.openExisting })
    expect(link).toHaveAttribute('href', '/bias/8')
  })

  it('puts 422 entries.<i>.<field> errors next to the field of the sent card', async () => {
    serveEditor()
    mockApi(
      http.post('/api/bias/notes', () =>
        HttpResponse.json(
          {
            error: {
              code: 'validation_error',
              message: 'bad',
              details: { fields: { 'entries.1.narrative': 'too long', period_date: 'bad' } },
            },
          },
          { status: 422 },
        ),
      ),
    )
    const { user } = renderPage()

    const eur = await card('EURUSD')
    const ger = await card('GER40')
    await user.click(within(fieldGroup(eur, e.fields.direction)).getByRole('button', { name: d.bullish }))
    await user.click(within(fieldGroup(ger, e.fields.direction)).getByRole('button', { name: d.bearish }))
    await user.type(within(ger).getByLabelText(e.fields.narrative), 'текст')
    await user.click(screen.getByRole('button', { name: e.save }))

    expect(await within(ger).findByRole('alert')).toHaveTextContent(uk.describe.form.serverRejected)
    expect(within(eur).queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByLabelText(new RegExp(`^${e.date}`))).toHaveAttribute('aria-invalid', 'true')

    // Editing the field clears its error.
    await user.type(within(ger).getByLabelText(e.fields.narrative), '!')
    expect(within(ger).queryByRole('alert')).not.toBeInTheDocument()
  })

  it('shows a broken bias.yaml with the config_error text', async () => {
    mockApi(
      http.get('/api/bias/config', () =>
        HttpResponse.json(
          { error: { code: 'config_error', message: 'x', details: { reason: 'mojibake', file: 'bias.yaml' } } },
          { status: 500 },
        ),
      ),
    )
    renderPage()

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(e.configError)
    expect(alert).toHaveTextContent(uk.errors.config_error_reasons.mojibake('bias.yaml'))
  })
})

describe('Bias editor: edit and delete', () => {
  const note = fixtureBiasNote({
    id: 3,
    kind: 'pre_london',
    period_date: '2026-11-02',
    raw_text: 'Ранковий біас',
    entries: [fixtureEntry({ id: 7, symbol: 'XAUUSD', direction: 'bullish', ai_filled_fields: ['direction'] })],
  })

  it('loads the saved note with its AI markers and saves with PUT', async () => {
    const { put } = serveEditor({ note, byPeriod: note })
    const { user } = renderPage('/bias/3')

    const xau = await card('XAUUSD')
    expect(screen.getByRole('combobox', { name: new RegExp(`^${e.kind}`) })).toHaveValue('pre_london')
    expect(screen.getByLabelText(e.rawTextLabel)).toHaveValue('Ранковий біас')
    expect(within(xau).getByLabelText(e.fields.key_levels)).toHaveValue('2650 POI FVG H1')
    expect(within(fieldGroup(xau, e.fields.direction)).getByText(uk.describe.form.aiBadge)).toBeInTheDocument()
    // Its own note found by-period is not a clash.
    expect(screen.queryByRole('link', { name: e.openExisting })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: e.save }))
    await screen.findByTestId('list-page')
    expect(put).toEqual([
      {
        kind: 'pre_london',
        period_date: '2026-11-02',
        raw_text: 'Ранковий біас',
        entries: [expect.objectContaining({ symbol: 'XAUUSD', direction: 'bullish', ai_filled_fields: ['direction'] })],
      },
    ])
  })

  it('deletes after an in-app confirmation', async () => {
    serveEditor({ note, byPeriod: note })
    let deleted = 0
    mockApi(
      http.delete('/api/bias/notes/3', () => {
        deleted += 1
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const { user } = renderPage('/bias/3')

    await user.click(await screen.findByRole('button', { name: e.delete }))
    const dialog = await screen.findByRole('dialog', { name: e.deleteTitle })
    expect(deleted).toBe(0)
    await user.click(within(dialog).getByRole('button', { name: e.delete }))

    expect(await screen.findByTestId('list-page')).toBeInTheDocument()
    expect(deleted).toBe(1)
    expect(await screen.findByText(e.deleted)).toBeInTheDocument()
  })

  it('asks before leaving with unsaved edits', async () => {
    serveEditor({ note, byPeriod: note })
    const { user, router } = renderPage('/bias/3')

    await user.type(await screen.findByLabelText(e.rawTextLabel), '!')
    await act(() => router.navigate('/bias'))
    expect(await screen.findByText(e.unsaved)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: uk.describe.unsaved.stay }))
    expect(router.state.location.pathname).toBe('/bias/3')
  })
})
