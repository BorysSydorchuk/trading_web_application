import { screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { FIXTURE_BIAS_CONFIG, fixtureBiasNote } from '@/features/bias/bias.fixture'
import type { BiasNoteInput } from '@/features/bias/types'
import { fixtureBlock, fixtureDigest } from '@/features/digests/digest.fixture'
import type { Digest, ReviewInput } from '@/features/digests/types'
import { uk } from '@/i18n/uk'
import { renderWithProviders } from '@/test/render'
import { mockApi } from '@/test/server'
import { DigestPage } from './DigestPage'

const b = uk.digests.blocks
const URL = '/digests/weekly/2026-11-09'
const notFound = () => HttpResponse.json({ error: { code: 'not_found', message: 'none' } }, { status: 404 })

/** Journal fields and bias config used by the sections and the embedded bias editor. */
function serveCommon() {
  mockApi(
    http.get('/api/journal-fields', () =>
      HttpResponse.json({
        fields: [{ key: 'entry_model', label: 'Модель входу', type: 'enum', analytics: true, options: [{ value: 'qm', label: 'QM', deprecated: false }] }],
      }),
    ),
    http.get('/api/bias/config', () => HttpResponse.json(FIXTURE_BIAS_CONFIG)),
  )
}

function serveDigest(digest: Digest = fixtureDigest()) {
  serveCommon()
  mockApi(http.get('/api/digests/by-period', () => HttpResponse.json(digest)))
}

/** The table row of a metric label. */
function metricRow(block: HTMLElement, label: string): HTMLElement {
  const row = within(block).getByText(label).closest('tr')
  if (!(row instanceof HTMLElement)) throw new Error(`no row for ${label}`)
  return row
}

function aiSection(): HTMLElement {
  return screen.getByRole('region', { name: uk.digests.page.aiSummary })
}

function render(url = URL) {
  return renderWithProviders(<DigestPage />, { path: '/digests/:kind/:date', url })
}

describe('DigestPage', () => {
  it('creates a missing digest on demand (POST) and renders it', async () => {
    serveCommon()
    const posted: unknown[] = []
    mockApi(
      http.get('/api/digests/by-period', notFound),
      http.post('/api/digests', async ({ request }) => {
        posted.push(await request.json())
        return HttpResponse.json(fixtureDigest(), { status: 201 })
      }),
    )
    render()
    expect(await screen.findByRole('heading', { name: 'Тиждень 9–15 лист. 2026' })).toBeInTheDocument()
    expect(posted).toEqual([{ kind: 'weekly', date: '2026-11-09' }])
  })

  it('moves a date inside the period to the period start', async () => {
    serveDigest()
    const { router } = render('/digests/weekly/2026-11-12')
    await screen.findByRole('heading', { name: 'Тиждень 9–15 лист. 2026' })
    expect(router.state.location.pathname).toBe(URL)
  })

  it('highlights worse red and better green with the norm text', async () => {
    serveDigest()
    render()
    const combined = await screen.findByRole('article', { name: b.combined })
    const winRate = metricRow(combined, b.metrics.win_rate)
    expect(winRate).toHaveAttribute('data-deviation', 'worse')
    expect(within(winRate).getByText('25.00%')).toHaveClass('text-loss')
    expect(within(winRate).getByText('норма 62.50 ± 12.50')).toBeInTheDocument()
    const totalR = metricRow(combined, b.metrics.total_r)
    expect(within(totalR).getByText('+3.50R')).toHaveClass('text-profit')
    // 3 of 4 trades have R: «за 3/4 угод» links to the trades without R (PM 2026-11-14)
    expect(within(totalR).getByRole('link', { name: b.rMissingLink(1) })).toHaveTextContent(b.rOf(3, 4))
    const pct = metricRow(combined, b.metrics.net_pnl_pct)
    expect(within(pct).getByText('−1.21%')).toBeInTheDocument()
    expect(within(combined).queryByText(b.normUnavailable)).not.toBeInTheDocument()
    expect(within(combined).getByRole('link', { name: 'GER40' })).toHaveAttribute('href', '/trades/41/describe')
  })

  it('shows «замало історії для норми» on a block without a norm', async () => {
    serveDigest()
    render()
    const alpha = await screen.findByRole('article', { name: 'Alpha' })
    expect(within(alpha).getByText(b.normUnavailable)).toBeInTheDocument()
  })

  it('shows breakdown coverage, rules and the three bias scopes', async () => {
    serveDigest()
    render()
    const model = await screen.findByRole('article', { name: 'Модель входу' })
    expect(within(model).getByText('заповнено 3/4')).toBeInTheDocument()
    expect(within(model).getByText('QM')).toBeInTheDocument()
    expect(within(model).getByText(uk.digests.breakdowns.notFilled)).toBeInTheDocument()
    const symbol = screen.getByRole('article', { name: uk.trades.columns.symbol })
    expect(within(symbol).queryByText(/заповнено/)).not.toBeInTheDocument()
    const rules = screen.getByRole('table', { name: uk.digests.rules.title })
    expect(within(rules).getByText(uk.trades.rules.max_risk_pct)).toBeInTheDocument()
    const bias = uk.digests.bias
    const daily = screen.getByRole('article', { name: bias.scopes.daily })
    expect(within(daily).getByText('66.67%')).toBeInTheDocument()
    expect(within(daily).getByText(bias.marked(3, 4))).toBeInTheDocument()
    expect(within(screen.getByRole('article', { name: bias.scopes.weekly })).getByText('100.00%')).toBeInTheDocument()
    const monthly = screen.getByRole('article', { name: bias.scopes.monthly })
    expect(within(monthly).getByText(bias.marked(0, 1))).toBeInTheDocument()
  })

  it('saves the review (PATCH) and the next-week bias from the same screen', async () => {
    serveDigest()
    const patched: ReviewInput[] = []
    const biasPosts: BiasNoteInput[] = []
    mockApi(
      http.patch('/api/digests/5', async ({ request }) => {
        const body = (await request.json()) as ReviewInput
        patched.push(body)
        return HttpResponse.json(fixtureDigest({ ...body, reviewed: true }))
      }),
      http.get('/api/digests', () => HttpResponse.json({ items: [] })),
      http.get('/api/digests/suggestion', () => HttpResponse.json({ weekly: null, monthly: null })),
      http.post('/api/bias/notes', async ({ request }) => {
        const body = (await request.json()) as BiasNoteInput
        biasPosts.push(body)
        return HttpResponse.json(fixtureBiasNote({ id: 77, kind: body.kind, period_date: body.period_date }), { status: 201 })
      }),
    )
    const { user } = render()
    await user.type(await screen.findByLabelText(uk.digests.review.what_worked), 'Чекав POI')
    await user.click(screen.getByRole('button', { name: uk.digests.review.save }))
    await waitFor(() => expect(patched).toEqual([{ what_worked: 'Чекав POI', what_to_fix: '', focus_next: '' }]))
    expect(await screen.findByText(uk.digests.review.saved)).toBeInTheDocument()

    const section = screen.getByRole('region', { name: uk.digests.nextBias.weekly('16.11.2026') })
    await user.type(within(section).getByLabelText(uk.bias.editor.rawTextLabel), 'Тиждень бичачий')
    await user.click(within(section).getByRole('button', { name: uk.bias.editor.save }))
    await waitFor(() => expect(biasPosts).toHaveLength(1))
    expect(biasPosts[0]).toMatchObject({ kind: 'weekly', period_date: '2026-11-16', raw_text: 'Тиждень бичачий' })
    // Still on the digest screen with the review kept.
    expect(screen.getByLabelText(uk.digests.review.what_worked)).toHaveValue('Чекав POI')
  })

  it('opens the existing next-period bias note', async () => {
    serveDigest(fixtureDigest({ next_bias_note_id: 9 }))
    mockApi(http.get('/api/bias/notes/9', () => HttpResponse.json(fixtureBiasNote({ id: 9, kind: 'weekly', period_date: '2026-11-16', raw_text: 'Старий біас' }))))
    render()
    const section = await screen.findByRole('region', { name: uk.digests.nextBias.weekly('16.11.2026') })
    expect(await within(section).findByDisplayValue('Старий біас')).toBeInTheDocument()
  })

  it('regenerates with «Оновити»', async () => {
    serveDigest()
    let posts = 0
    mockApi(
      http.post('/api/digests', () => {
        posts += 1
        return HttpResponse.json(fixtureDigest({ metrics: { ...fixtureDigest().metrics, combined: fixtureBlock({ norm_available: false }) } }))
      }),
      http.get('/api/digests', () => HttpResponse.json({ items: [] })),
      http.get('/api/digests/suggestion', () => HttpResponse.json({ weekly: null, monthly: null })),
    )
    const { user } = render()
    await user.click(await screen.findByRole('button', { name: uk.digests.page.regenerate }))
    expect(await screen.findByText(uk.digests.page.regenerated)).toBeInTheDocument()
    expect(posts).toBe(1)
    const combined = screen.getByRole('article', { name: b.combined })
    expect(within(combined).getByText(b.normUnavailable)).toBeInTheDocument()
  })

  it.each([
    ['mixed_currency', 409],
    ['period_in_future', 422],
  ] as const)('shows the %s error from the on-demand create', async (code, status) => {
    serveCommon()
    mockApi(
      http.get('/api/digests/by-period', notFound),
      http.post('/api/digests', () => HttpResponse.json({ error: { code, message: code } }, { status })),
    )
    render()
    const alert = await screen.findByRole('alert')
    expect(within(alert).getByText(uk.digests.page.loadError)).toBeInTheDocument()
    expect(within(alert).getByText(uk.errors[code])).toBeInTheDocument()
  })

  it('shows the AI summary text when present, with «Оновити підсумок»', async () => {
    serveDigest(fixtureDigest({ ai_summary: 'Три збиткові угоди після 15:00.' }))
    render()
    expect(await screen.findByText('Три збиткові угоди після 15:00.')).toBeInTheDocument()
    const section = aiSection()
    expect(within(section).getByRole('button', { name: uk.digests.ai.refresh })).toBeInTheDocument()
    expect(within(section).queryByRole('button', { name: uk.digests.ai.generate })).not.toBeInTheDocument()
  })

  it('never calls the AI on page load and shows the empty state', async () => {
    let posts = 0
    serveDigest()
    mockApi(
      http.post('/api/digests/:id/ai-summary', () => {
        posts += 1
        return HttpResponse.json(fixtureDigest())
      }),
    )
    render()
    await screen.findByRole('heading', { name: 'Тиждень 9–15 лист. 2026' })
    const section = aiSection()
    expect(within(section).getByText(uk.digests.ai.empty)).toBeInTheDocument()
    expect(within(section).getByRole('button', { name: uk.digests.ai.generate })).toBeEnabled()
    expect(posts).toBe(0)
  })

  it('posts once on «Підсумок від ШІ» and renders the returned summary', async () => {
    const posted: string[] = []
    serveDigest()
    mockApi(
      http.post('/api/digests/:id/ai-summary', ({ params }) => {
        posted.push(String(params.id))
        return HttpResponse.json(fixtureDigest({ ai_summary: 'Рядок 1.\nРядок 2.' }))
      }),
      http.get('/api/digests', () => HttpResponse.json({ items: [] })),
      http.get('/api/digests/suggestion', () => HttpResponse.json({ weekly: null, monthly: null })),
    )
    const { user } = render()
    await user.click(await screen.findByRole('button', { name: uk.digests.ai.generate }))
    const section = aiSection()
    const text = await within(section).findByText(/Рядок 1\./)
    expect(text).toHaveClass('whitespace-pre-line')
    expect(within(section).getByRole('button', { name: uk.digests.ai.refresh })).toBeEnabled()
    expect(within(section).queryByText(uk.digests.ai.empty)).not.toBeInTheDocument()
    expect(posted).toEqual([String(fixtureDigest().id)])
  })

  it.each([
    ['ai_not_configured', 503, undefined, uk.digests.ai.notConfigured],
    ['ai_error', 502, { kind: 'rate_limit' }, uk.errors.ai_error_kinds.rate_limit],
    ['ai_error', 502, undefined, uk.digests.ai.error],
  ] as const)('shows %s inline and as a toast (%#)', async (code, status, details, message) => {
    serveDigest()
    mockApi(
      http.post('/api/digests/:id/ai-summary', () =>
        HttpResponse.json({ error: { code, message: code, details } }, { status }),
      ),
    )
    const { user } = render()
    await user.click(await screen.findByRole('button', { name: uk.digests.ai.generate }))
    const section = aiSection()
    expect(await within(section).findByRole('alert')).toHaveTextContent(message)
    await waitFor(() => expect(screen.getAllByText(message)).toHaveLength(2))
    expect(within(section).getByRole('button', { name: uk.digests.ai.generate })).toBeEnabled()
  })
})
