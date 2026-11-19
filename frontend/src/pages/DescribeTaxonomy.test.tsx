/** M8-04..08 Describe form: show_if, multi «Інше», legacy fields, cleared_hidden, violation details. */
import { screen, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { fieldDomId } from '@/features/describe/formModel'
import { TAXONOMY_FIELDS, emptyTaxonomyJournal } from '@/features/describe/journalFields.fixture'
import { fixtureTrade } from '@/features/describe/trade.fixture'
import type { JournalInput } from '@/features/describe/types'
import type { JournalValue, TradeDetail } from '@/features/trades/types'
import { uk } from '@/i18n/uk'
import { renderWithProviders } from '@/test/render'
import { mockApi } from '@/test/server'
import { DescribePage } from './DescribePage'

const t = uk.describe
const f = t.form

function taxonomyTrade(journal: Record<string, JournalValue> = {}, overrides: Partial<TradeDetail> = {}): TradeDetail {
  return fixtureTrade({ journal: { ...emptyTaxonomyJournal(), ...journal }, ...overrides })
}

/** GET trade + taxonomy fields; PUT records the body and answers with `cleared_hidden`. */
function serve(trade: TradeDetail, clearedHidden: string[] = []) {
  const saved: JournalInput[] = []
  mockApi(
    http.get(`/api/trades/${trade.id}`, () => HttpResponse.json(trade)),
    http.get('/api/journal-fields', () => HttpResponse.json({ fields: TAXONOMY_FIELDS })),
    http.put(`/api/trades/${trade.id}/journal`, async ({ request }) => {
      const body = (await request.json()) as JournalInput
      saved.push(body)
      return HttpResponse.json({ ...trade, status: 'draft', cleared_hidden: clearedHidden })
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

async function control(key: string): Promise<HTMLElement> {
  await screen.findByLabelText(t.input.rawTextLabel)
  const element = document.getElementById(fieldDomId(key))
  if (!element) throw new Error(`no control for ${key}`)
  return element
}

describe('Describe taxonomy (M8-04..08)', () => {
  it('shows a show_if field only while its parent includes the option', async () => {
    serve(taxonomyTrade())
    const { user } = renderPage(taxonomyTrade())
    const poi = await control('poi_types')
    expect(screen.queryByText('Тип FVG H1')).not.toBeInTheDocument()

    await user.click(within(poi).getByRole('checkbox', { name: 'FVG H1' }))
    expect(screen.getByText('Тип FVG H1')).toBeInTheDocument()
    expect(screen.queryByText('Тип FVG H4')).not.toBeInTheDocument()

    await user.click(within(poi).getByRole('checkbox', { name: 'FVG H1' }))
    expect(screen.queryByText('Тип FVG H1')).not.toBeInTheDocument()
  })

  it('warns «Буде очищено» for a hidden field with a value and leaves it out of the save', async () => {
    const trade = taxonomyTrade({ poi_types: ['fvg_h1'], fvg_types_h1: ['fractal_updating'] })
    const saved = serve(trade)
    const { user } = renderPage(trade)
    const poi = await control('poi_types')
    expect(screen.queryByText(f.willBeCleared('Тип FVG H1'))).not.toBeInTheDocument()

    await user.click(within(poi).getByRole('checkbox', { name: 'FVG H1' }))
    await user.click(within(poi).getByRole('checkbox', { name: 'Fractal H1' }))
    // The note stays while the user keeps editing, until the save.
    expect(screen.getByText(f.willBeCleared('Тип FVG H1'))).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: t.save.draft }))
    expect(await screen.findByTestId('inbox-page')).toBeInTheDocument()
    const fields = saved[0]?.fields ?? {}
    expect(fields.poi_types).toEqual(['fractal_h1'])
    expect(fields).not.toHaveProperty('fvg_types_h1')
    expect(fields).not.toHaveProperty('fvg_types_h1_other')
  })

  it('toasts the fields the server cleared (cleared_hidden)', async () => {
    const trade = taxonomyTrade({ poi_types: ['fvg_h4'] })
    serve(trade, ['fvg_types_h4'])
    const { user } = renderPage(trade)
    await control('poi_types')
    await user.click(screen.getByRole('button', { name: t.save.draft }))
    expect(await screen.findByText(t.save.clearedHidden('Тип FVG H4'))).toBeInTheDocument()
  })

  it('asks for the «Інше» text of a multi field and sends it with the list', async () => {
    const trade = taxonomyTrade()
    const saved = serve(trade)
    const { user } = renderPage(trade)
    const poi = await control('poi_types')
    expect(screen.queryByLabelText(new RegExp(f.otherTextLabel))).not.toBeInTheDocument()

    await user.click(within(poi).getByRole('checkbox', { name: 'Інше' }))
    // Completing without the text is refused and the text is listed as missing.
    await user.click(screen.getByRole('button', { name: t.save.complete }))
    expect(await screen.findByText(new RegExp(`POI ${f.otherTextSuffix.replace(/[()]/g, '\\$&')}`))).toBeInTheDocument()
    expect(saved).toHaveLength(0)

    const text = await control('poi_types_other')
    await user.type(text, 'зона попиту')
    await user.click(screen.getByRole('button', { name: t.save.draft }))
    expect(await screen.findByTestId('inbox-page')).toBeInTheDocument()
    expect(saved[0]?.fields).toMatchObject({ poi_types: ['other'], poi_types_other: 'зона попиту' })
  })

  it('shows a legacy value read-only and never sends legacy keys or poi_type', async () => {
    const trade = taxonomyTrade({ setup_context: 'no', poi_type: 'fvg_h4', poi_types: ['fvg_h4'] })
    const saved = serve(trade)
    const { user } = renderPage(trade)
    await control('poi_types')
    expect(screen.getByText(f.legacyValue('ні'))).toBeInTheDocument()
    // Empty legacy field: not shown at all.
    expect(screen.queryByText('Тип FVG (старе)')).not.toBeInTheDocument()
    const legacy = document.getElementById(fieldDomId('setup_context'))
    expect(legacy?.closest('div')?.querySelector('button, input, select')).toBeNull()

    await user.click(screen.getByRole('button', { name: t.save.draft }))
    expect(await screen.findByTestId('inbox-page')).toBeInTheDocument()
    const fields = saved[0]?.fields ?? {}
    for (const key of ['setup_context', 'fvg_kind', 'poi_type', 'poi_type_other']) expect(fields).not.toHaveProperty(key)
  })

  it('shows violation details and deprecated violations only on a trade that has them', async () => {
    const trade = taxonomyTrade(
      { rule_violations: ['daily_stop_loss_pct'] },
      {
        rule_violations: [
          { rule_key: 'daily_risk', source: 'auto', details: 'daily_stop_loss_pct: day P&L reached -3.10% before entry <= limit -3.0%' },
          { rule_key: 'daily_stop_loss_pct', source: 'user', details: null },
        ],
      },
    )
    serve(trade)
    renderPage(trade)
    const summary = await screen.findByRole('complementary', { name: t.summary.label })
    expect(within(summary).getByText('Порушення денного ризику')).toBeInTheDocument()
    expect(within(summary).getByText(/day P&L reached -3\.10%/)).toBeInTheDocument()
    const rules = await control('rule_violations')
    expect(within(rules).getByRole('checkbox', { name: 'вхід після денного стоп-лосу' })).toBeChecked()
    expect(within(rules).getByRole('checkbox', { name: 'Вхід від слабкої POI' })).not.toBeChecked()
  })

  it('does not offer a deprecated violation on a trade without it', async () => {
    serve(taxonomyTrade())
    renderPage(taxonomyTrade())
    const rules = await control('rule_violations')
    expect(within(rules).getByRole('checkbox', { name: 'Вхід від слабкої POI' })).toBeInTheDocument()
    expect(within(rules).queryByRole('checkbox', { name: 'вхід після денного стоп-лосу' })).not.toBeInTheDocument()
  })
})
