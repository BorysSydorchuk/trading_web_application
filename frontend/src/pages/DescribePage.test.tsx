import { screen, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { fieldDomId } from '@/features/describe/formModel'
import { FIXTURE_FIELDS } from '@/features/describe/journalFields.fixture'
import { fixtureTrade } from '@/features/describe/trade.fixture'
import type { JournalInput } from '@/features/describe/types'
import type { TradeDetail } from '@/features/trades/types'
import { uk } from '@/i18n/uk'
import { renderWithProviders } from '@/test/render'
import { mockApi } from '@/test/server'
import { DescribePage } from './DescribePage'

const t = uk.describe
const REQUIRED = FIXTURE_FIELDS.filter((field) => field.required)

function labelOf(key: string): string {
  const label = FIXTURE_FIELDS.find((field) => field.key === key)?.label
  if (!label) throw new Error(`no fixture field ${key}`)
  return label
}

/** The field's label: a <label for> or, for button groups, the group's label span. */
function fieldLabel(key: string): HTMLElement {
  const id = fieldDomId(key)
  const label = document.querySelector<HTMLElement>(`label[for="${id}"], #${id}-label`)
  if (!label) throw new Error(`no label for ${key}`)
  return label
}

/** GET trade + journal fields; PUT journal records its body and answers with the saved trade. */
function serveTrade(trade: TradeDetail) {
  const saved: JournalInput[] = []
  mockApi(
    http.get(`/api/trades/${trade.id}`, () => HttpResponse.json(trade)),
    http.get('/api/journal-fields', () => HttpResponse.json({ fields: FIXTURE_FIELDS })),
    http.put(`/api/trades/${trade.id}/journal`, async ({ request }) => {
      const body = (await request.json()) as JournalInput
      saved.push(body)
      return HttpResponse.json({ ...trade, status: body.complete ? 'complete' : 'draft' })
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

describe('DescribePage', () => {
  it('saves a draft with the typed text and chosen value, then goes to the inbox', async () => {
    const trade = fixtureTrade()
    const saved = serveTrade(trade)
    const { user } = renderPage(trade)

    await user.type(await screen.findByLabelText(t.input.rawTextLabel), 'Вхід від FVG H4')
    const context = document.getElementById(fieldDomId('setup_context'))
    if (!context) throw new Error('no setup_context field')
    await user.click(within(context).getByRole('button', { name: 'yes' }))
    // Not described yet: missing fields are not highlighted before the first save.
    expect(screen.queryByText(t.save.missing)).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: t.save.draft }))

    expect(await screen.findByTestId('inbox-page')).toBeInTheDocument()
    expect(await screen.findByText(t.save.draftSaved)).toBeInTheDocument()
    expect(saved).toHaveLength(1)
    expect(saved[0]).toMatchObject({
      complete: false,
      raw_text: 'Вхід від FVG H4',
      chart_links: [],
      ai_filled_fields: [],
      fields: { setup_context: 'yes', poi_type: null, quality_rating: null },
    })
  })

  it('does not send a complete save with required fields missing and marks them red', async () => {
    const trade = fixtureTrade()
    const saved = serveTrade(trade)
    const { user, router } = renderPage(trade)

    await user.click(await screen.findByRole('button', { name: t.save.complete }))

    expect(await screen.findByText(uk.errors.journal_incomplete)).toBeInTheDocument()
    const summary = screen.getByText(t.save.missing).closest('p')
    for (const field of REQUIRED) expect(summary).toHaveTextContent(field.label)
    expect(fieldLabel('setup_context')).toHaveClass('text-destructive')
    expect(screen.getAllByText(t.form.missing)).toHaveLength(REQUIRED.length)
    // The first missing field gets the focus.
    expect(screen.getByRole('group', { name: labelOf('setup_context') })).toContainElement(
      document.activeElement as HTMLElement,
    )
    expect(saved).toHaveLength(0)
    expect(router.state.location.pathname).toBe(`/trades/${trade.id}/describe`)
  })

  it('highlights missing required fields at once for a saved draft', async () => {
    const trade = fixtureTrade({
      status: 'draft',
      journal: { ...fixtureTrade().journal, setup_context: 'yes' },
      missing_required: REQUIRED.map((field) => field.key).filter((key) => key !== 'setup_context'),
    })
    serveTrade(trade)
    renderPage(trade)

    const summary = (await screen.findByText(t.save.missing)).closest('p')
    expect(summary).not.toHaveTextContent(labelOf('setup_context'))
    expect(summary).toHaveTextContent(labelOf('quality_rating'))
    expect(fieldLabel('setup_context')).not.toHaveClass('text-destructive')
    expect(fieldLabel('quality_rating')).toHaveClass('text-destructive')
  })

  it('lists fields made required after the trade closed as a neutral hint and still saves complete', async () => {
    const newKeys = ['quality_rating', 'chart_links']
    const trade = fixtureTrade({
      status: 'complete',
      journal: {
        ...fixtureTrade().journal,
        setup_context: 'yes',
        poi_type: 'fvg_h4',
        followed_plan: true,
        emotion_before: 'calm',
      },
      missing_required: [],
      missing_new_fields: newKeys,
    })
    const saved = serveTrade(trade)
    const { user } = renderPage(trade)

    const hint = await screen.findByRole('note')
    expect(hint).toHaveTextContent(t.form.newFieldsHint)
    expect(hint).toHaveTextContent(`${labelOf('quality_rating')}, ${labelOf('chart_links')}`)
    expect(hint).not.toHaveClass('text-destructive')
    // Not shown as missing even though the trade is complete (missing fields highlighted at once).
    expect(screen.queryByText(t.save.missing)).not.toBeInTheDocument()
    expect(screen.queryByText(t.form.missing)).not.toBeInTheDocument()
    expect(fieldLabel('quality_rating')).not.toHaveClass('text-destructive')

    await user.click(screen.getByRole('button', { name: t.save.complete }))

    expect(await screen.findByTestId('inbox-page')).toBeInTheDocument()
    expect(saved).toHaveLength(1)
    expect(saved[0]).toMatchObject({ complete: true, fields: { quality_rating: null }, chart_links: [] })
  })

  it('shows the raw key when a new field has no label', async () => {
    const trade = fixtureTrade({ missing_new_fields: ['unknown_key'] })
    serveTrade(trade)
    renderPage(trade)

    expect(await screen.findByRole('note')).toHaveTextContent('unknown_key')
  })

  it('shows a readable error when the trade cannot be loaded', async () => {
    mockApi(
      http.get('/api/trades/7', () =>
        HttpResponse.json({ error: { code: 'db_unavailable', message: 'db down' } }, { status: 503 }),
      ),
      http.get('/api/journal-fields', () => HttpResponse.json({ fields: FIXTURE_FIELDS })),
    )
    renderPage(fixtureTrade())

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(t.page.loadError)
    expect(alert).toHaveTextContent(uk.errors.db_unavailable)
    expect(within(alert).getByRole('button', { name: uk.common.retry })).toBeEnabled()
  })
})
