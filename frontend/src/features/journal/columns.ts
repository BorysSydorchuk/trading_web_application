/** Journal table columns: order, alignment, server sort field, visibility preferences. */
import type { TradeSort } from '@/features/trades/types'

export const COLUMN_KEYS = [
  'close_time',
  'open_time',
  'duration',
  'account',
  'symbol',
  'direction',
  'session',
  'weekday',
  'hour',
  'volume',
  'entry_price',
  'exit_price',
  'initial_sl',
  'last_sl',
  'tp',
  'commission',
  'swap',
  'gross_pnl',
  'net_pnl',
  'pnl_pct',
  'balance_at_open',
  'risk_amount',
  'risk_pct',
  'r_multiple',
  'planned_rr',
  'is_reentry',
  'position_id',
  'status',
  'violations',
] as const
export type ColumnKey = (typeof COLUMN_KEYS)[number]

export const DEFAULT_COLUMNS: readonly ColumnKey[] = [
  'close_time',
  'account',
  'symbol',
  'direction',
  'session',
  'volume',
  'entry_price',
  'exit_price',
  'net_pnl',
  'r_multiple',
  'risk_pct',
  'status',
  'violations',
]

/** Columns the API can sort by (docs/api.md whitelist). */
export const COLUMN_SORT: Partial<Record<ColumnKey, TradeSort>> = {
  open_time: 'open_time',
  close_time: 'close_time',
  symbol: 'symbol',
  session: 'session',
  volume: 'volume',
  net_pnl: 'net_pnl',
  risk_pct: 'risk_pct',
  r_multiple: 'r_multiple',
  status: 'status',
}

export const NUMERIC_COLUMNS: ReadonlySet<ColumnKey> = new Set<ColumnKey>([
  'duration',
  'hour',
  'volume',
  'entry_price',
  'exit_price',
  'initial_sl',
  'last_sl',
  'tp',
  'commission',
  'swap',
  'gross_pnl',
  'net_pnl',
  'pnl_pct',
  'balance_at_open',
  'risk_amount',
  'risk_pct',
  'r_multiple',
  'planned_rr',
  'position_id',
])

const STORAGE_KEY = 'tj.journal.columns'

function isColumnKey(value: unknown): value is ColumnKey {
  return typeof value === 'string' && (COLUMN_KEYS as readonly string[]).includes(value)
}

export function loadColumns(): ColumnKey[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (raw === null) return [...DEFAULT_COLUMNS]
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return [...DEFAULT_COLUMNS]
    const keys = parsed.filter(isColumnKey)
    return keys.length > 0 ? keys : [...DEFAULT_COLUMNS]
  } catch {
    return [...DEFAULT_COLUMNS]
  }
}

export function saveColumns(columns: readonly ColumnKey[]): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(columns))
  } catch {
    // Storage unavailable: the choice lasts until reload.
  }
}
