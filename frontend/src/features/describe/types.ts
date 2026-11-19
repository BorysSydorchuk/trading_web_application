/** Describe screen API types (docs/api.md "## M2"). */
import type { JournalValue, TradeDetail } from '@/features/trades/types'

/** Body of PUT /api/trades/{id}/journal: the first five keys are required. */
export interface JournalInput {
  fields: Record<string, JournalValue>
  chart_links: { url: string; kind: string }[]
  raw_text: string | null
  ai_filled_fields: string[]
  complete: boolean
  /** M8-02: the form was built while the trade was open; the server keeps after-trade data. */
  form_open?: boolean
}

/** Response of PUT /api/trades/{id}/journal (M8-04..08: + fields cleared by their show_if). */
export interface JournalSaved extends TradeDetail {
  /** Field keys sent with a value but hidden on save; absent from an older backend. */
  cleared_hidden?: string[]
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
