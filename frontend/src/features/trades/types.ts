/** Trades API types (docs/api.md M1 "Trades"). Decimal values are strings. */
import type { AudioNote } from '@/features/voice/types'

export const TRADE_STATUSES = ['open', 'needs_sl', 'needs_description', 'draft', 'complete'] as const
export type TradeStatus = (typeof TRADE_STATUSES)[number]

export const INBOX_STATUSES = ['needs_sl', 'needs_description', 'draft'] as const
export type InboxStatus = (typeof INBOX_STATUSES)[number]

/** Server-side sort whitelist (docs/api.md). */
export const TRADE_SORT_FIELDS = [
  'open_time',
  'close_time',
  'symbol',
  'net_pnl',
  'r_multiple',
  'risk_pct',
  'volume',
  'session',
  'status',
] as const
export type TradeSort = (typeof TRADE_SORT_FIELDS)[number]
export type SortOrder = 'asc' | 'desc'

export type BiasAlignment = 'aligned' | 'counter' | 'neutral_bias' | 'no_bias'

export interface TradeRow {
  id: number
  account_id: number
  account_name: string
  position_id: number
  symbol: string
  direction: string
  status: string
  open_time: string
  close_time: string | null
  duration_seconds: number | null
  entry_price: string
  exit_price: string | null
  volume: string
  initial_sl: string | null
  last_sl: string | null
  tp: string | null
  commission: string
  swap: string
  gross_pnl: string | null
  net_pnl: string | null
  pnl_pct: string | null
  balance_at_open: string | null
  risk_amount: string | null
  risk_pct: string | null
  r_multiple: string | null
  planned_rr: string | null
  session: string | null
  weekday: number | null
  hour: number | null
  is_reentry: boolean
  /** M4: effective daily alignment (manual override wins), and computed period alignments. */
  bias_alignment: BiasAlignment | null
  bias_alignment_weekly: BiasAlignment | null
  bias_alignment_monthly: BiasAlignment | null
  violations: string[]
}

export interface TradeList {
  items: TradeRow[]
  total: number
}

export interface ExitDeal {
  ticket: number
  time: string
  price: string
  volume: string
  profit: string
  commission: string
  swap: string
  reason: string | null
}

export interface RuleViolation {
  rule_key: string
  source: string
  details: string | null
}

/** A saved chart link (docs/api.md M2). `preview_url` is null for /chart links. */
export interface ChartLink {
  id: number
  url: string
  kind: string
  preview_url: string | null
}

/** Journal value as sent by the API: enum/text → string, multi_enum → array, bool, int. */
export type JournalValue = string | number | boolean | string[] | null

/** docs/api.md "TradeDetail in M2". `journal` has every YAML key (fields and text_keys). */
export interface TradeDetail extends TradeRow {
  bias_note_ids: { daily: number | null; weekly: number | null; monthly: number | null }
  initial_sl_source: string | null
  exit_deals: ExitDeal[]
  rule_violations: RuleViolation[]
  journal: Record<string, JournalValue>
  chart_links: ChartLink[]
  raw_text: string | null
  transcript: string | null
  /** M3: voice notes of this trade, oldest first. */
  audio_notes: AudioNote[]
  ai_filled_fields: string[]
  described_at: string | null
  missing_required: string[]
  /**
   * M3: required fields that are empty on this trade and were made required after it closed.
   * Informational only: never in `missing_required`, never blocks `complete`.
   */
  missing_new_fields: string[]
}

export interface TradeQuery {
  account_id?: number[]
  symbol?: string[]
  status?: string[]
  from?: string
  to?: string
  /** M3: only closed trades with a non-empty `missing_new_fields`. Absent = no filter. */
  missing_new_fields?: boolean
  /** Only closed trades without an R multiple (digest «Сума R» n/N link). Absent = no filter. */
  missing_r?: boolean
  sort?: TradeSort
  order?: SortOrder
  limit?: number
  offset?: number
}

export interface JournalFieldOption {
  value: string
  label: string
  deprecated: boolean
}

/** `enum | multi_enum | bool | int | text | links | auto`; kept as string so a new type never crashes the UI. */
export type JournalFieldType = string

/** One field from config/journal_fields.yaml (GET /api/journal-fields). */
export interface JournalField {
  key: string
  label: string
  type: JournalFieldType
  options?: JournalFieldOption[]
  required?: boolean
  analytics?: boolean
  storage?: string
  allow_other_text?: boolean
  text_key?: string
  min?: number
  max?: number
}

export interface JournalFieldList {
  fields: JournalField[]
}
