import { describe, expect, it } from 'vitest'
import { ApiError } from '@/api/client'
import { newLinkRow } from '@/features/describe/chartLinks'
import { uk } from '@/i18n/uk'
import { FIXTURE_SYMBOLS, fixtureBiasNote, fixtureEntry } from './bias.fixture'
import {
  buildEntries,
  clientCardErrors,
  initialDrafts,
  mergeBiasExtraction,
  setDraftValue,
  snapshot,
  type EntryDraft,
} from './formModel'
import { canMarkResult, defaultKind, formatDayHeader, groupByDate, normalizePeriod } from './period'
import { mapBiasSaveError } from './serverErrors'
import type { BiasExtractResult } from './types'

function draftOf(drafts: readonly EntryDraft[], symbol: string): EntryDraft {
  const draft = drafts.find((d) => d.symbol === symbol)
  if (!draft) throw new Error(`no draft ${symbol}`)
  return draft
}

function update(drafts: EntryDraft[], symbol: string, change: (d: EntryDraft) => EntryDraft): EntryDraft[] {
  return drafts.map((d) => (d.symbol === symbol ? change(d) : d))
}

function extraction(entries: BiasExtractResult['entries']): BiasExtractResult {
  return {
    entries,
    dropped: [],
    usage: { model: 'm', fallback_used: false, input_tokens: 1, output_tokens: 1, cost_usd: '0.0100', duration_ms: 1 },
  }
}

describe('bias form model', () => {
  it('has one card per config symbol and keeps a saved entry of a removed symbol last, read-only', () => {
    const note = fixtureBiasNote({
      entries: [fixtureEntry({ symbol: 'NAS100', id: 1 }), fixtureEntry({ symbol: 'XAUUSD', id: 2 })],
    })
    const drafts = initialDrafts(FIXTURE_SYMBOLS, note)
    expect(drafts.map((d) => [d.symbol, d.known])).toEqual([
      ['EURUSD', true],
      ['GBPUSD', true],
      ['XAUUSD', true],
      ['GER40', true],
      ['NAS100', false],
    ])
    expect(draftOf(drafts, 'XAUUSD').values).toEqual({
      direction: 'bullish',
      key_levels: '2650 POI FVG H1',
      narrative: '',
      confidence: 2,
    })
  })

  it('sends only configured cards with a direction, trimmed, with links and still-valid AI markers', () => {
    let drafts = initialDrafts(FIXTURE_SYMBOLS, null)
    drafts = update(drafts, 'GBPUSD', (d) => ({
      ...setDraftValue(setDraftValue(d, 'direction', 'bearish'), 'narrative', '  тиск на 1.30  '),
      links: [newLinkRow('https://www.tradingview.com/x/AbC123/'), newLinkRow('  ')],
      aiFilled: new Set(['direction', 'confidence'] as const),
    }))
    const { entries, sent } = buildEntries(drafts)
    expect(entries).toEqual([
      {
        symbol: 'GBPUSD',
        direction: 'bearish',
        key_levels: null,
        narrative: 'тиск на 1.30',
        confidence: null,
        chart_links: [{ url: 'https://www.tradingview.com/x/AbC123/' }],
        // confidence is marked but has no value, so it is dropped.
        ai_filled_fields: ['direction'],
      },
    ])
    expect(sent).toEqual([{ symbol: 'GBPUSD', linkRows: [draftOf(drafts, 'GBPUSD').links[0]?.rowId] }])
  })

  it('asks for a direction on a filled card without one', () => {
    const drafts = update(initialDrafts(FIXTURE_SYMBOLS, null), 'GER40', (d) => setDraftValue(d, 'key_levels', '19500'))
    expect(clientCardErrors(drafts)).toEqual({
      GER40: { fields: { direction: uk.bias.editor.directionNeeded }, links: {} },
    })
    expect(buildEntries(drafts).entries).toEqual([])
  })

  it('lets the AI fill empty and still-AI fields but keeps the user’s own values', () => {
    let drafts = initialDrafts(FIXTURE_SYMBOLS, null)
    drafts = update(drafts, 'GBPUSD', (d) => setDraftValue(d, 'key_levels', 'мої рівні'))
    const merged = mergeBiasExtraction(
      drafts,
      extraction([
        { symbol: 'EURUSD', fields: { direction: 'bullish', confidence: 3 } },
        { symbol: 'GBPUSD', fields: { key_levels: '1.2900', direction: 'bearish' } },
        { symbol: 'XAUUSD', fields: { direction: 'sideways', confidence: 5 } },
        { symbol: 'NAS100', fields: { direction: 'bullish' } },
      ]),
    )
    expect(merged.applied).toBe(3)
    const eur = draftOf(merged.drafts, 'EURUSD')
    expect(eur.values).toMatchObject({ direction: 'bullish', confidence: 3 })
    expect([...eur.aiFilled]).toEqual(['direction', 'confidence'])
    const gbp = draftOf(merged.drafts, 'GBPUSD')
    expect(gbp.values).toMatchObject({ direction: 'bearish', key_levels: 'мої рівні' })
    expect([...gbp.aiFilled]).toEqual(['direction'])
    expect(draftOf(merged.drafts, 'XAUUSD').values.direction).toBeNull()

    // A second extraction may replace an AI value the user has not touched.
    const again = mergeBiasExtraction(merged.drafts, extraction([{ symbol: 'EURUSD', fields: { direction: 'neutral' } }]))
    expect(draftOf(again.drafts, 'EURUSD').values.direction).toBe('neutral')
  })

  it('changes the snapshot only for user-visible edits', () => {
    const drafts = initialDrafts(FIXTURE_SYMBOLS, null)
    const base = snapshot('pre_ny', '2026-11-06', '', drafts)
    expect(snapshot('pre_ny', '2026-11-06', '  ', drafts)).toBe(base)
    const edited = update(drafts, 'EURUSD', (d) => setDraftValue(d, 'confidence', 1))
    expect(snapshot('pre_ny', '2026-11-06', '', edited)).not.toBe(base)
  })
})

describe('bias save errors', () => {
  const sent = [
    { symbol: 'GBPUSD', linkRows: ['link-a', 'link-b'] },
    { symbol: 'XAUUSD', linkRows: [] },
  ]

  it('points entries.<i>.<field> and link paths at the sent cards', () => {
    const error = new ApiError('validation_error', 'bad', 422, {
      fields: {
        'entries.1.key_levels': 'too long',
        'entries.0.chart_links.1.url': 'duplicate',
        'entries.0.symbol': 'unknown',
        period_date: 'bad',
        'entries.5.direction': 'no such entry',
      },
    })
    const mapped = mapBiasSaveError(error, sent)
    expect(mapped.cards).toEqual({
      XAUUSD: { fields: { key_levels: uk.describe.form.serverRejected }, links: {} },
      GBPUSD: {
        fields: { symbol: uk.bias.editor.symbolRejected },
        links: { 'link-b': uk.describe.links.serverRejected },
      },
    })
    expect(mapped.periodDate).toBe(uk.describe.form.serverRejected)
    expect(mapped.general).toBe(true)
  })

  it('reads the existing note id of a 409', () => {
    const error = new ApiError('bias_note_exists', 'exists', 409, { id: 5 })
    expect(mapBiasSaveError(error, sent).existingId).toBe(5)
  })
})

describe('bias periods', () => {
  it('normalizes weekly to Monday and monthly to the 1st', () => {
    expect(normalizePeriod('weekly', '2026-11-08')).toBe('2026-11-02')
    expect(normalizePeriod('monthly', '2026-11-19')).toBe('2026-11-01')
    expect(normalizePeriod('pre_ny', '2026-11-08')).toBe('2026-11-08')
  })

  it('defaults to pre_london before 11:00 Brussels and pre_ny from 11:00', () => {
    expect(defaultKind(new Date('2026-11-05T09:59:00Z'))).toBe('pre_london')
    expect(defaultKind(new Date('2026-11-05T10:00:00Z'))).toBe('pre_ny')
  })

  it('groups notes by date in API order and formats the header', () => {
    const notes = [
      fixtureBiasNote({ id: 1, period_date: '2026-11-06' }),
      fixtureBiasNote({ id: 2, period_date: '2026-11-06', kind: 'pre_london' }),
      fixtureBiasNote({ id: 3, period_date: '2026-11-02', kind: 'weekly' }),
    ]
    expect(groupByDate(notes).map((g) => [g.date, g.notes.map((n) => n.id)])).toEqual([
      ['2026-11-06', [1, 2]],
      ['2026-11-02', [3]],
    ])
    expect(formatDayHeader('2026-11-06')).toBe('06.11.2026, пт')
    expect(canMarkResult('2026-11-06', '2026-11-06')).toBe(true)
    expect(canMarkResult('2026-11-07', '2026-11-06')).toBe(false)
  })
})
