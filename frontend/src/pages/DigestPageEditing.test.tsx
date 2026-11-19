/** Digest page: review and next-period bias editing (unsaved guard, audio notes, delete + create, errors). */
import { screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { FIXTURE_BIAS_CONFIG, fixtureBiasNote } from '@/features/bias/bias.fixture'
import type { BiasNote, BiasNoteInput } from '@/features/bias/types'
import { fixtureDigest } from '@/features/digests/digest.fixture'
import type { Digest } from '@/features/digests/types'
import { fixtureNote } from '@/features/voice/note.fixture'
import { uk } from '@/i18n/uk'
import { renderWithProviders } from '@/test/render'
import { mockApi } from '@/test/server'
import { DigestPage } from './DigestPage'

const r = uk.digests.review
const e = uk.bias.editor
const LIST_PAGE = 'list page'
const SECTION = uk.digests.nextBias.weekly('16.11.2026')
const AUDIO = fixtureNote({ id: 31, trade_id: null, bias_note_id: 9, status: 'done', transcript: 'Старий запис' })

/** The digest (mutable through `state.digest`) plus the endpoints every test needs. */
function serve(initial: Digest = fixtureDigest()) {
  const state = { digest: initial }
  mockApi(
    http.get('/api/journal-fields', () => HttpResponse.json({ fields: [] })),
    http.get('/api/bias/config', () => HttpResponse.json(FIXTURE_BIAS_CONFIG)),
    http.get('/api/digests/by-period', () => HttpResponse.json(state.digest)),
    http.get('/api/digests', () => HttpResponse.json({ items: [] })),
    http.get('/api/digests/suggestion', () => HttpResponse.json({ weekly: null, monthly: null })),
  )
  return state
}

function render() {
  return renderWithProviders(<DigestPage />, {
    path: '/digests/:kind/:date',
    url: '/digests/weekly/2026-11-09',
    routes: [{ path: '/digests', element: <p>{LIST_PAGE}</p> }],
  })
}

function existingNote(overrides: Partial<BiasNote> = {}): BiasNote {
  return fixtureBiasNote({ id: 9, kind: 'weekly', period_date: '2026-11-16', raw_text: 'Старий біас', audio_notes: [AUDIO], ...overrides })
}

describe('DigestPage editing', () => {
  beforeEach(() => mockApi(http.get('/api/audio/31', () => HttpResponse.json(AUDIO))))

  it('keeps the audio notes of an existing next-period note after saving it', async () => {
    serve(fixtureDigest({ next_bias_note_id: 9 }))
    const put: BiasNoteInput[] = []
    mockApi(
      http.get('/api/bias/notes/9', () => HttpResponse.json(existingNote())),
      http.put('/api/bias/notes/9', async ({ request }) => {
        const body = (await request.json()) as BiasNoteInput
        put.push(body)
        return HttpResponse.json(existingNote({ raw_text: body.raw_text }))
      }),
    )
    const { user } = render()
    const section = await screen.findByRole('region', { name: SECTION })
    const text = await within(section).findByDisplayValue('Старий біас')
    expect(await within(section).findAllByRole('listitem')).toHaveLength(1)
    await user.type(text, ' і далі')
    await user.click(within(section).getByRole('button', { name: e.save }))
    await waitFor(() => expect(put).toHaveLength(1))
    expect(await screen.findByText(e.saved)).toBeInTheDocument()
    await waitFor(() => expect(within(section).getAllByRole('listitem')).toHaveLength(1))
    expect(await within(section).findByDisplayValue('Старий біас і далі')).toBeInTheDocument()
  })

  it('deletes the embedded note and creates a new one in the same session', async () => {
    const state = serve(fixtureDigest({ next_bias_note_id: 9 }))
    const posts: BiasNoteInput[] = []
    mockApi(
      http.get('/api/bias/notes/9', () => HttpResponse.json(existingNote({ audio_notes: [] }))),
      http.delete('/api/bias/notes/9', () => {
        state.digest = fixtureDigest({ next_bias_note_id: null })
        return new HttpResponse(null, { status: 204 })
      }),
      http.post('/api/bias/notes', async ({ request }) => {
        const body = (await request.json()) as BiasNoteInput
        posts.push(body)
        return HttpResponse.json(fixtureBiasNote({ id: 12, kind: 'weekly', period_date: body.period_date, raw_text: body.raw_text }), { status: 201 })
      }),
    )
    const { user } = render()
    const section = await screen.findByRole('region', { name: SECTION })
    await within(section).findByDisplayValue('Старий біас')
    await user.click(within(section).getByRole('button', { name: e.delete }))
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: e.delete }))
    expect(await screen.findByText(e.deleted)).toBeInTheDocument()
    const fresh = await screen.findByRole('region', { name: SECTION })
    const text = within(fresh).getByLabelText(e.rawTextLabel)
    await waitFor(() => expect(text).toHaveValue(''))
    await user.type(text, 'Новий біас')
    await user.click(within(fresh).getByRole('button', { name: e.save }))
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0]).toMatchObject({ kind: 'weekly', period_date: '2026-11-16', raw_text: 'Новий біас' })
    expect(screen.queryByText(LIST_PAGE)).not.toBeInTheDocument()
  })

  it('guards unsaved review text when leaving the screen', async () => {
    serve()
    const { user } = render()
    await user.type(await screen.findByLabelText(r.what_to_fix), 'Ранні входи')
    await screen.findByRole('region', { name: SECTION })
    await user.click(screen.getByRole('link', { name: uk.digests.page.back }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(uk.digests.unsaved)).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: uk.describe.unsaved.stay }))
    expect(screen.getByLabelText(r.what_to_fix)).toHaveValue('Ранні входи')
  })

  it('guards unsaved review text while the bias editor is not shown', async () => {
    serve()
    mockApi(http.get('/api/bias/config', () => HttpResponse.json({ error: { code: 'config_error', message: 'x' } }, { status: 500 })))
    const { user } = render()
    await user.type(await screen.findByLabelText(r.what_worked), 'Терпіння')
    await screen.findByText(uk.digests.nextBias.loadError)
    await user.click(screen.getByRole('link', { name: uk.digests.page.back }))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
  })

  it('keeps the text and the save button after a failed PATCH', async () => {
    serve()
    mockApi(http.patch('/api/digests/5', () => HttpResponse.json({ error: { code: 'validation_error', message: 'x' } }, { status: 422 })))
    const { user } = render()
    const field = await screen.findByLabelText(r.focus_next)
    await user.type(field, 'Тільки QM')
    await user.click(screen.getByRole('button', { name: r.save }))
    expect(await screen.findByText(uk.errors.validation_error)).toBeInTheDocument()
    expect(field).toHaveValue('Тільки QM')
    expect(screen.getByRole('button', { name: r.save })).toBeEnabled()
  })

  it('keeps unsaved review text when the digest is regenerated', async () => {
    serve()
    mockApi(http.post('/api/digests', () => HttpResponse.json(fixtureDigest({ generated_at: '2026-11-14T13:00:00Z' }))))
    const { user } = render()
    const field = await screen.findByLabelText(r.what_worked)
    await user.type(field, 'Чекав підтвердження')
    await user.click(screen.getByRole('button', { name: uk.digests.page.regenerate }))
    expect(await screen.findByText(uk.digests.page.regenerated)).toBeInTheDocument()
    expect(screen.getByLabelText(r.what_worked)).toHaveValue('Чекав підтвердження')
  })

  it('shows the Brussels review date in the header', async () => {
    serve(fixtureDigest({ reviewed: true, reviewed_at: '2026-11-15T23:30:00Z', what_worked: 'x' }))
    render()
    expect(await screen.findByText(uk.digests.page.reviewedOn('16.11.2026'))).toBeInTheDocument()
  })

  it('shows the snapshot currency in money headers', async () => {
    serve()
    render()
    const combined = await screen.findByRole('article', { name: uk.digests.blocks.combined })
    expect(within(combined).getByText(uk.digests.withCurrency(uk.digests.blocks.metrics.net_pnl, 'USD'))).toBeInTheDocument()
    const rules = screen.getByRole('table', { name: uk.digests.rules.title })
    expect(within(rules).getByText(uk.digests.withCurrency(uk.digests.rules.pnl, 'USD'))).toBeInTheDocument()
  })
})
