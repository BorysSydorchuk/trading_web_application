/** Bias API types (docs/api.md "## M4"). */
import type { ExtractUsage } from '@/features/describe/types'
import type { AudioNote } from '@/features/voice/types'

export const BIAS_KINDS = ['pre_london', 'pre_ny', 'weekly', 'monthly'] as const
export type BiasKind = (typeof BIAS_KINDS)[number]

export interface BiasStatus {
  date: string
  weekday: boolean
  now: string
  sessions: Record<'pre_london' | 'pre_ny', {
    note_id: number | null
    missing: boolean
    remind: boolean
    from: string
    until: string
  }>
  weekly: { note_id: number | null }
  monthly: { note_id: number | null }
}

export const BIAS_DIRECTIONS = ['bullish', 'bearish', 'neutral', 'no_trade'] as const
export type BiasDirection = (typeof BIAS_DIRECTIONS)[number]

/** Fields the AI may fill (ai_filled_fields ⊆ these). */
export const BIAS_AI_FIELDS = ['direction', 'key_levels', 'narrative', 'confidence'] as const
export type BiasAiField = (typeof BIAS_AI_FIELDS)[number]

export const MIN_CONFIDENCE = 1
export const MAX_CONFIDENCE = 3

export interface BiasConfig {
  symbols: { symbol: string; aliases: string[] }[]
  reminders: Record<string, { from: string; until: string }>
  kinds: string[]
}

export interface BiasChartLink {
  id: number
  url: string
  kind: string
  preview_url: string | null
}

export interface BiasEntry {
  id: number
  symbol: string
  direction: BiasDirection
  key_levels: string | null
  narrative: string | null
  confidence: number | null
  chart_links: BiasChartLink[]
  was_correct: boolean | null
  was_correct_source: string | null
  ai_filled_fields: string[]
}

export interface BiasNote {
  id: number
  kind: BiasKind
  period_date: string
  raw_text: string | null
  entries: BiasEntry[]
  audio_notes: AudioNote[]
  created_at: string
  updated_at: string
}

export interface BiasEntryInput {
  symbol: string
  direction: BiasDirection
  key_levels: string | null
  narrative: string | null
  confidence: number | null
  chart_links: { url: string }[]
  ai_filled_fields: BiasAiField[]
}

/** Body of POST /api/bias/notes and PUT /api/bias/notes/{id}. */
export interface BiasNoteInput {
  kind: BiasKind
  period_date: string
  raw_text: string | null
  entries: BiasEntryInput[]
}

export interface BiasExtractEntry {
  symbol: string
  fields: Partial<Record<BiasAiField, unknown>>
}

/** Response of POST /api/bias/notes/extract (nothing is saved). */
export interface BiasExtractResult {
  entries: BiasExtractEntry[]
  dropped: unknown[]
  usage: ExtractUsage
}

export function isBiasKind(value: string | null | undefined): value is BiasKind {
  return value != null && (BIAS_KINDS as readonly string[]).includes(value)
}

export function isBiasDirection(value: unknown): value is BiasDirection {
  return typeof value === 'string' && (BIAS_DIRECTIONS as readonly string[]).includes(value)
}
