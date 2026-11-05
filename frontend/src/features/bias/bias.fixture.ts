/** Test fixtures in the docs/api.md M4 shapes. Tests only. */
import type { BiasConfig, BiasEntry, BiasNote } from './types'

export const FIXTURE_SYMBOLS = ['EURUSD', 'GBPUSD', 'XAUUSD', 'GER40'] as const

export const FIXTURE_BIAS_CONFIG: BiasConfig = {
  symbols: FIXTURE_SYMBOLS.map((symbol) => ({ symbol, aliases: [] })),
  reminders: { pre_london: { from: '07:45', until: '11:00' }, pre_ny: { from: '12:30', until: '16:00' } },
  kinds: ['pre_london', 'pre_ny', 'weekly', 'monthly'],
}

export function fixtureEntry(overrides: Partial<BiasEntry> = {}): BiasEntry {
  return {
    id: 7,
    symbol: 'XAUUSD',
    direction: 'bullish',
    key_levels: '2650 POI FVG H1',
    narrative: null,
    confidence: 2,
    chart_links: [],
    was_correct: null,
    was_correct_source: null,
    ai_filled_fields: [],
    ...overrides,
  }
}

export function fixtureBiasNote(overrides: Partial<BiasNote> = {}): BiasNote {
  return {
    id: 3,
    kind: 'pre_ny',
    period_date: '2026-11-02',
    raw_text: null,
    entries: [],
    audio_notes: [],
    created_at: '2026-11-02T11:30:00Z',
    updated_at: '2026-11-02T11:30:00Z',
    ...overrides,
  }
}
