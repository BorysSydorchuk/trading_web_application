import { act, screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'
import type { TradeDetail } from '@/features/trades/types'
import { fixtureNote } from '@/features/voice/note.fixture'
import type { AudioNote } from '@/features/voice/types'
import { uk } from '@/i18n/uk'
import { DescribePage } from '@/pages/DescribePage'
import { controlClock, denied, FAKE_AUDIO, installMic, restoreMic } from '@/test/media'
import { renderWithProviders } from '@/test/render'
import { mockApi } from '@/test/server'
import { FIXTURE_FIELDS } from './journalFields.fixture'
import { fixtureTrade } from './trade.fixture'

const t = uk.describe
const v = uk.voice
const TRANSCRIPT = 'Вихід по TP, все за планом'
const POLL_WAIT = { timeout: 4_000 }

function serveTrade(trade: TradeDetail) {
  mockApi(
    http.get(`/api/trades/${trade.id}`, () => HttpResponse.json(trade)),
    http.get('/api/journal-fields', () => HttpResponse.json({ fields: FIXTURE_FIELDS })),
  )
}

/** GET /api/audio/{id} answers with `states` in turn, the last one repeated. */
function serveNoteStates(id: number, states: readonly AudioNote[]) {
  let calls = 0
  mockApi(
    http.get(`/api/audio/${id}`, () => {
      const note = states[Math.min(calls, states.length - 1)]
      calls += 1
      return HttpResponse.json(note)
    }),
  )
  return () => calls
}

function renderPage(trade: TradeDetail) {
  return renderWithProviders(<DescribePage />, {
    path: '/trades/:id/describe',
    url: `/trades/${trade.id}/describe`,
    routes: [{ path: '/inbox', element: <div data-testid="inbox-page" /> }],
  })
}

async function textBox(): Promise<HTMLTextAreaElement> {
  return (await screen.findByLabelText(t.input.rawTextLabel)) as HTMLTextAreaElement
}

afterEach(restoreMic)

describe('Describe screen voice notes', () => {
  it('uploads a recording, shows progress and appends the transcript once', async () => {
    installMic()
    const clock = controlClock()
    const trade = fixtureTrade()
    serveTrade(trade)
    const uploads: { type: string | null; body: string }[] = []
    mockApi(
      http.post(`/api/trades/${trade.id}/audio`, async ({ request }) => {
        uploads.push({ type: request.headers.get('content-type'), body: await request.text() })
        return HttpResponse.json(fixtureNote({ id: 5 }), { status: 201 })
      }),
    )
    const polls = serveNoteStates(5, [
      fixtureNote({ id: 5, status: 'processing', progress: 0.45 }),
      fixtureNote({ id: 5, status: 'done', progress: 1, transcript: TRANSCRIPT }),
    ])
    const { user } = renderPage(trade)

    const box = await textBox()
    await user.type(box, 'Вхід від FVG H4')
    const record = screen.getByRole('button', { name: v.recorder.hold })
    await user.pointer({ keys: '[MouseLeft>]', target: record })
    await screen.findByText(v.recorder.recording)
    clock.advance(3_000)
    await user.pointer({ keys: '[/MouseLeft]', target: record })

    const row = await screen.findByRole('listitem', { name: v.notes.label(1) })
    expect(uploads).toEqual([{ type: 'audio/webm', body: FAKE_AUDIO }])
    expect(await within(row).findByText(v.notes.processing(45), {}, POLL_WAIT)).toBeInTheDocument()
    expect(within(row).getByRole('progressbar')).toHaveAttribute('aria-valuenow', '45')
    expect(await within(row).findByText(v.notes.done, {}, POLL_WAIT)).toBeInTheDocument()
    expect(within(row).getByText(v.notes.inserted)).toBeInTheDocument()
    await waitFor(() => expect(box).toHaveValue(`Вхід від FVG H4\n\n${TRANSCRIPT}`))

    // Later renders (typing) and the stopped polling never add it a second time.
    await user.type(box, '!')
    expect(box).toHaveValue(`Вхід від FVG H4\n\n${TRANSCRIPT}!`)
    const pollsWhenDone = polls()
    await new Promise((resolve) => window.setTimeout(resolve, 1_300))
    expect(polls()).toBe(pollsWhenDone)
    expect(box).toHaveValue(`Вхід від FVG H4\n\n${TRANSCRIPT}!`)
    // The form is dirty: the extraction button works on the new text.
    expect(screen.getByRole('button', { name: t.input.extract })).toBeEnabled()
  })

  it('shows a failed note with its error and replay, and retry puts it back in the queue', async () => {
    const failed = fixtureNote({ id: 9, status: 'failed', error_code: 'no_speech' })
    const trade = fixtureTrade({ audio_notes: [failed] })
    serveTrade(trade)
    let retried = 0
    mockApi(
      http.post('/api/audio/9/retry', () => {
        retried += 1
        return HttpResponse.json(fixtureNote({ id: 9, status: 'pending' }))
      }),
    )
    serveNoteStates(9, [fixtureNote({ id: 9, status: 'done', progress: 1, transcript: TRANSCRIPT })])
    const { user } = renderPage(trade)

    const row = await screen.findByRole('listitem', { name: v.notes.label(1) })
    expect(within(row).getByRole('alert')).toHaveTextContent(uk.errors.transcription.no_speech)
    expect(within(row).getByLabelText(v.notes.player(1))).toHaveAttribute('src', '/api/audio/9/file')

    await user.click(within(row).getByRole('button', { name: v.notes.retry }))

    expect(retried).toBe(1)
    expect(await within(row).findByText(v.notes.done, {}, POLL_WAIT)).toBeInTheDocument()
    expect(await textBox()).toHaveValue(TRANSCRIPT)
  })

  it('keeps polling a pending note from the trade after a reload', async () => {
    const trade = fixtureTrade({ raw_text: 'Мій текст', audio_notes: [fixtureNote({ id: 11, status: 'pending' })] })
    serveTrade(trade)
    serveNoteStates(11, [fixtureNote({ id: 11, status: 'done', progress: 1, transcript: TRANSCRIPT })])
    renderPage(trade)

    const row = await screen.findByRole('listitem', { name: v.notes.label(1) })
    expect(within(row).getByText(v.notes.pending)).toBeInTheDocument()
    expect(await within(row).findByText(v.notes.done, {}, POLL_WAIT)).toBeInTheDocument()
    expect(await textBox()).toHaveValue(`Мій текст\n\n${TRANSCRIPT}`)
  })

  it('offers "Вставити в текст" for a note that was already done', async () => {
    const done = fixtureNote({ id: 12, status: 'done', progress: 1, transcript: TRANSCRIPT })
    const trade = fixtureTrade({ raw_text: 'Мій текст', audio_notes: [done] })
    serveTrade(trade)
    const { user } = renderPage(trade)

    const box = await textBox()
    expect(box).toHaveValue('Мій текст')
    const row = await screen.findByRole('listitem', { name: v.notes.label(1) })
    await user.click(within(row).getByRole('button', { name: v.notes.insert }))

    expect(box).toHaveValue(`Мій текст\n\n${TRANSCRIPT}`)
    expect(within(row).getByText(v.notes.inserted)).toBeInTheDocument()
    expect(within(row).queryByRole('button', { name: v.notes.insert })).not.toBeInTheDocument()
  })

  it('shows a denied microphone and the text box still works', async () => {
    installMic({ reject: denied() })
    const trade = fixtureTrade()
    serveTrade(trade)
    const { user } = renderPage(trade)

    const box = await textBox()
    await user.pointer({ keys: '[MouseLeft>]', target: screen.getByRole('button', { name: v.recorder.hold }) })

    const group = screen.getByRole('group', { name: t.voice.title })
    expect(await within(group).findByRole('alert')).toHaveTextContent(v.recorder.errors.denied)
    await user.type(box, 'Опис текстом')
    expect(box).toHaveValue('Опис текстом')
    expect(screen.getByRole('button', { name: t.input.extract })).toBeEnabled()
  })

  it('keeps a failed note when its retry fails twice', async () => {
    const trade = fixtureTrade({ audio_notes: [fixtureNote({ id: 9, status: 'failed', error_code: 'timeout' })] })
    serveTrade(trade)
    let retried = 0
    mockApi(
      http.post('/api/audio/9/retry', () => {
        retried += 1
        return HttpResponse.json({ error: { code: 'db_unavailable', message: 'down' } }, { status: 503 })
      }),
    )
    const { user } = renderPage(trade)

    const row = await screen.findByRole('listitem', { name: v.notes.label(1) })
    const retry = within(row).getByRole('button', { name: v.notes.retry })
    await user.click(retry)
    await waitFor(() => expect(retry).toBeEnabled())
    await user.click(retry)
    await waitFor(() => expect(retried).toBe(2))

    await waitFor(() => expect(retry).toBeEnabled())
    expect(within(row).getByRole('alert')).toHaveTextContent(uk.errors.transcription.timeout)
    expect(within(row).getByLabelText(v.notes.player(1))).toHaveAttribute('src', '/api/audio/9/file')
  })

  it('shows a failed poll on the row and recovers on the next one', async () => {
    const trade = fixtureTrade({ audio_notes: [fixtureNote({ id: 13, status: 'pending' })] })
    serveTrade(trade)
    let calls = 0
    mockApi(
      http.get('/api/audio/13', () => {
        calls += 1
        if (calls === 1) return HttpResponse.json({ error: { code: 'db_unavailable', message: 'down' } }, { status: 503 })
        return HttpResponse.json(fixtureNote({ id: 13, status: 'done', progress: 1, transcript: TRANSCRIPT }))
      }),
    )
    renderPage(trade)

    const row = await screen.findByRole('listitem', { name: v.notes.label(1) })
    expect(await within(row).findByText(v.notes.pollError, {}, POLL_WAIT)).toBeInTheDocument()
    expect(await within(row).findByText(v.notes.done, {}, POLL_WAIT)).toBeInTheDocument()
    expect(within(row).queryByText(v.notes.pollError)).not.toBeInTheDocument()
    expect(await textBox()).toHaveValue(TRANSCRIPT)
  })

  it('blocks a new recording while a failed upload is kept, until it is discarded', async () => {
    const mic = installMic()
    const clock = controlClock()
    const trade = fixtureTrade()
    serveTrade(trade)
    mockApi(
      http.post(`/api/trades/${trade.id}/audio`, () =>
        HttpResponse.json({ error: { code: 'unsupported_media_type', message: 'no' } }, { status: 415 }),
      ),
    )
    const { user, router } = renderPage(trade)

    const record = await screen.findByRole('button', { name: v.recorder.hold })
    await user.pointer({ keys: '[MouseLeft>]', target: record })
    await screen.findByText(v.recorder.recording)
    clock.advance(2_000)
    await user.pointer({ keys: '[/MouseLeft]', target: record })

    const group = screen.getByRole('group', { name: t.voice.title })
    expect(await within(group).findByRole('alert')).toHaveTextContent(uk.errors.unsupported_media_type)
    expect(record).toBeDisabled()
    expect(within(group).getByText(t.voice.resolveFirst)).toBeInTheDocument()
    await user.pointer({ keys: '[MouseLeft>]', target: record })
    expect(mic.getUserMedia).toHaveBeenCalledTimes(1)

    // Leaving with only an unsent recording (text untouched) asks first.
    await act(() => router.navigate('/inbox'))
    expect(await screen.findByText(t.unsaved.title)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: t.unsaved.stay }))

    await user.click(within(group).getByRole('button', { name: t.voice.discard }))
    expect(within(group).queryByRole('alert')).not.toBeInTheDocument()
    expect(record).toBeEnabled()
  })

  it('keeps a recording whose upload failed and sends it again', async () => {
    installMic()
    const clock = controlClock()
    const trade = fixtureTrade()
    serveTrade(trade)
    let attempts = 0
    mockApi(
      http.post(`/api/trades/${trade.id}/audio`, () => {
        attempts += 1
        if (attempts === 1) {
          return HttpResponse.json({ error: { code: 'audio_too_large', message: 'too big' } }, { status: 413 })
        }
        return HttpResponse.json(fixtureNote({ id: 5, status: 'done', progress: 1, transcript: TRANSCRIPT }), {
          status: 201,
        })
      }),
    )
    const { user } = renderPage(trade)

    const record = await screen.findByRole('button', { name: v.recorder.hold })
    await user.pointer({ keys: '[MouseLeft>]', target: record })
    await screen.findByText(v.recorder.recording)
    clock.advance(2_000)
    await user.pointer({ keys: '[/MouseLeft]', target: record })

    const group = screen.getByRole('group', { name: t.voice.title })
    expect(await within(group).findByRole('alert')).toHaveTextContent(uk.errors.audio_too_large)
    await user.click(within(group).getByRole('button', { name: t.voice.retryUpload }))

    expect(await screen.findByRole('listitem', { name: v.notes.label(1) })).toBeInTheDocument()
    expect(attempts).toBe(2)
    expect(within(group).queryByRole('alert')).not.toBeInTheDocument()
  })
})
