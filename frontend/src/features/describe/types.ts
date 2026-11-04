/** Describe screen API types (docs/api.md "## M2"). */
import type { JournalValue } from '@/features/trades/types'

/** Body of PUT /api/trades/{id}/journal: all five keys are required. */
export interface JournalInput {
  fields: Record<string, JournalValue>
  chart_links: { url: string; kind: string }[]
  raw_text: string | null
  ai_filled_fields: string[]
  complete: boolean
}

export interface ExtractUsage {
  model: string
  fallback_used: boolean
  input_tokens: number
  output_tokens: number
  cost_usd: string | null
  duration_ms: number
}

/** Response of POST /api/trades/{id}/extract (nothing is saved). */
export interface ExtractResult {
  fields: Record<string, JournalValue>
  ai_filled_fields: string[]
  missing_required: string[]
  dropped: { key: string; reason: string }[]
  usage: ExtractUsage
}
