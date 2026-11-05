/** Bias note editor state as pure data: one card per symbol, save body, AI merge, dirty snapshot. */
import { filledLinks, linkErrors, newLinkRow, type LinkDraft } from '@/features/describe/chartLinks'
import { uk } from '@/i18n/uk'
import {
  BIAS_AI_FIELDS,
  isBiasDirection,
  MAX_CONFIDENCE,
  MIN_CONFIDENCE,
  type BiasAiField,
  type BiasDirection,
  type BiasEntry,
  type BiasEntryInput,
  type BiasExtractResult,
  type BiasNote,
} from './types'

/** Same limit as the API (text fields ≤ 5000 chars). */
export const MAX_ENTRY_TEXT_LENGTH = 5000
/** Same limit as the trade description (RAW_TEXT_MAX_LENGTH). */
export const MAX_NOTE_TEXT_LENGTH = 20000

export interface EntryValues {
  direction: BiasDirection | null
  key_levels: string
  narrative: string
  confidence: number | null
}

export interface EntryDraft {
  symbol: string
  /** Listed in bias.yaml. A saved entry of a removed symbol is shown but never sent (PUT deletes it). */
  known: boolean
  values: EntryValues
  links: LinkDraft[]
  /** Fields the AI filled that the user has not touched since. */
  aiFilled: ReadonlySet<BiasAiField>
}

export interface CardErrors {
  /** Field → message (client: direction missing; server: 422 per field). */
  fields: Partial<Record<BiasAiField | 'symbol' | 'chart_links', string>>
  /** Link row id → message. */
  links: Readonly<Record<string, string>>
}

/** DOM id key of a card field (unique per symbol; used for labels and focusing errors). */
export function biasFieldKey(symbol: string, field: BiasAiField | 'chart_links'): string {
  return `bias-${symbol}-${field}`
}

const EMPTY_VALUES: EntryValues = { direction: null, key_levels: '', narrative: '', confidence: null }

function isAiField(value: string): value is BiasAiField {
  return (BIAS_AI_FIELDS as readonly string[]).includes(value)
}

function draftFromEntry(entry: BiasEntry, known: boolean): EntryDraft {
  return {
    symbol: entry.symbol,
    known,
    values: {
      direction: entry.direction,
      key_levels: entry.key_levels ?? '',
      narrative: entry.narrative ?? '',
      confidence: entry.confidence,
    },
    links: entry.chart_links.map((link) => newLinkRow(link.url, 'before', link.preview_url)),
    aiFilled: new Set(entry.ai_filled_fields.filter(isAiField)),
  }
}

function emptyDraft(symbol: string): EntryDraft {
  return { symbol, known: true, values: EMPTY_VALUES, links: [], aiFilled: new Set() }
}

/** bias.yaml symbols in config order, then saved entries of symbols no longer configured. */
export function initialDrafts(symbols: readonly string[], note: BiasNote | null): EntryDraft[] {
  const saved = new Map((note?.entries ?? []).map((entry) => [entry.symbol, entry]))
  const configured = symbols.map((symbol) => {
    const entry = saved.get(symbol)
    return entry ? draftFromEntry(entry, true) : emptyDraft(symbol)
  })
  const known = new Set(symbols)
  const removed = (note?.entries ?? []).filter((entry) => !known.has(entry.symbol)).map((e) => draftFromEntry(e, false))
  return [...configured, ...removed]
}

export function isValueEmpty(values: EntryValues, key: BiasAiField): boolean {
  const value = values[key]
  return value === null || (typeof value === 'string' && value.trim() === '')
}

export function isDraftEmpty(draft: EntryDraft): boolean {
  return BIAS_AI_FIELDS.every((key) => isValueEmpty(draft.values, key)) && filledLinks(draft.links).length === 0
}

/** Editing a field removes its AI marker. */
export function setDraftValue<K extends BiasAiField>(draft: EntryDraft, key: K, value: EntryValues[K]): EntryDraft {
  const aiFilled = draft.aiFilled.has(key) ? new Set([...draft.aiFilled].filter((k) => k !== key)) : draft.aiFilled
  return { ...draft, values: { ...draft.values, [key]: value }, aiFilled }
}

export function clearDraft(draft: EntryDraft): EntryDraft {
  return { ...draft, values: EMPTY_VALUES, links: [], aiFilled: new Set() }
}

/** Sent when the symbol is configured and has a direction; everything else is left out. */
function isSent(draft: EntryDraft): boolean {
  return draft.known && draft.values.direction !== null
}

function textOrNull(text: string): string | null {
  const trimmed = text.trim()
  return trimmed === '' ? null : trimmed
}

function entryInput(draft: EntryDraft, direction: BiasDirection): BiasEntryInput {
  const { values } = draft
  return {
    symbol: draft.symbol,
    direction,
    key_levels: textOrNull(values.key_levels),
    narrative: textOrNull(values.narrative),
    confidence: values.confidence,
    chart_links: filledLinks(draft.links).map((link) => ({ url: link.url.trim() })),
    ai_filled_fields: BIAS_AI_FIELDS.filter((key) => draft.aiFilled.has(key) && !isValueEmpty(values, key)),
  }
}

export interface BuiltEntries {
  entries: BiasEntryInput[]
  /** Per sent entry index: its symbol and the row ids of its sent links (maps 422 paths back). */
  sent: { symbol: string; linkRows: string[] }[]
}

export function buildEntries(drafts: readonly EntryDraft[]): BuiltEntries {
  const entries: BiasEntryInput[] = []
  const sent: BuiltEntries['sent'] = []
  for (const draft of drafts) {
    const direction = draft.values.direction
    if (!isSent(draft) || direction === null) continue
    entries.push(entryInput(draft, direction))
    sent.push({ symbol: draft.symbol, linkRows: filledLinks(draft.links).map((link) => link.rowId) })
  }
  return { entries, sent }
}

/** Errors the browser finds before sending: a filled card without direction, bad or repeated links. */
export function clientCardErrors(drafts: readonly EntryDraft[]): Record<string, CardErrors> {
  const result: Record<string, CardErrors> = {}
  for (const draft of drafts) {
    if (!draft.known) continue
    const links = linkErrors(draft.links)
    const needsDirection = draft.values.direction === null && !isDraftEmpty(draft)
    if (!needsDirection && Object.keys(links).length === 0) continue
    result[draft.symbol] = {
      fields: needsDirection ? { direction: uk.bias.editor.directionNeeded } : {},
      links,
    }
  }
  return result
}

/** Converts an extracted value to the card representation; null when it does not fit. */
function toDraftValue(key: BiasAiField, value: unknown): EntryValues[BiasAiField] {
  if (key === 'direction') return isBiasDirection(value) ? value : null
  if (key === 'confidence') {
    const ok = typeof value === 'number' && Number.isInteger(value) && value >= MIN_CONFIDENCE && value <= MAX_CONFIDENCE
    return ok ? value : null
  }
  return typeof value === 'string' && value.trim() !== '' ? value.trim() : null
}

function mergeEntry(draft: EntryDraft, fields: BiasExtractResult['entries'][number]['fields']) {
  let next = draft
  let applied = 0
  for (const key of BIAS_AI_FIELDS) {
    const value = toDraftValue(key, fields[key])
    if (value === null) continue
    if (!isValueEmpty(draft.values, key) && !draft.aiFilled.has(key)) continue
    next = { ...next, values: { ...next.values, [key]: value }, aiFilled: new Set([...next.aiFilled, key]) }
    applied += 1
  }
  return { draft: next, applied }
}

/**
 * Same rule as Describe (aiMerge.ts): the AI writes a field only when it is empty or still
 * marked as AI-filled; the user's own input stays. Symbols not in the cards are ignored.
 */
export function mergeBiasExtraction(drafts: readonly EntryDraft[], result: BiasExtractResult) {
  const bySymbol = new Map(result.entries.map((entry) => [entry.symbol, entry.fields]))
  let applied = 0
  const next = drafts.map((draft) => {
    const fields = draft.known ? bySymbol.get(draft.symbol) : undefined
    if (!fields) return draft
    const merged = mergeEntry(draft, fields)
    applied += merged.applied
    return merged.draft
  })
  return { drafts: next, applied }
}

/** What the user can change; compared with the start state for the unsaved-changes warning. */
export function snapshot(kind: string, periodDate: string, rawText: string, drafts: readonly EntryDraft[]): string {
  return JSON.stringify({
    kind,
    periodDate,
    rawText: rawText.trim(),
    cards: drafts.map((draft) => [
      draft.symbol,
      draft.values.direction,
      draft.values.key_levels.trim(),
      draft.values.narrative.trim(),
      draft.values.confidence,
      filledLinks(draft.links).map((link) => link.url.trim()),
    ]),
  })
}
