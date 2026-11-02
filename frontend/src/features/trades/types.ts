/** Trades API types (docs/api.md M1 "Trades"). Decimal values are strings. */

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

export interface TradeDetail extends TradeRow {
  initial_sl_source: string | null
  exit_deals: ExitDeal[]
  rule_violations: RuleViolation[]
}

export interface TradeQuery {
  account_id?: number[]
  symbol?: string[]
  status?: string[]
  from?: string
  to?: string
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

export interface JournalField {
  key: string
  label: string
  type: string
  options?: JournalFieldOption[]
}

export interface JournalFieldList {
  fields: JournalField[]
}
