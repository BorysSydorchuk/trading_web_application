/**
 * Journal view state lives in the URL search params (shareable, reload-safe).
 * Period presets are resolved against "today" in Brussels when the query is built,
 * so a link with `period=week` always means the current week.
 * Dates are sent as ISO dates; the backend treats them as Brussels calendar days.
 */
import { addDays, brusselsToday, isIsoDate, startOfMonth, startOfWeek } from '@/lib/time'
import {
  TRADE_SORT_FIELDS,
  TRADE_STATUSES,
  type SortOrder,
  type TradeQuery,
  type TradeSort,
} from '@/features/trades/types'

export const PERIOD_PRESETS = ['today', 'week', 'month', 'days30', 'all', 'custom'] as const
export type PeriodPreset = (typeof PERIOD_PRESETS)[number]

export const PAGE_SIZES = [25, 50, 100, 200] as const
const DEFAULT_PAGE_SIZE = 50
const DEFAULT_SORT: TradeSort = 'close_time'
const DEFAULT_ORDER: SortOrder = 'desc'
const DEFAULT_PERIOD: PeriodPreset = 'all'
/** Same name and value in the page URL and the API query (docs/api.md M3). */
const MISSING_NEW_FIELDS_PARAM = 'missing_new_fields'
const MISSING_R_PARAM = 'missing_r'

export interface JournalFilters {
  accounts: number[]
  symbols: string[]
  statuses: string[]
  period: PeriodPreset
  /** Only used with period=custom. "YYYY-MM-DD" or "". */
  from: string
  to: string
  /** Only closed trades with required fields added after they closed (`missing_new_fields=true`). */
  missingNewFields: boolean
  /** Only closed trades without R (`missing_r=true`, digest «Сума R» link). */
  missingR: boolean
  sort: TradeSort
  order: SortOrder
  /** 1-based. */
  page: number
  limit: number
  /** Trade shown in the detail dialog. */
  trade: number | null
}

function oneOf<T extends string>(allowed: readonly T[], value: string | null, fallback: T): T {
  return value !== null && (allowed as readonly string[]).includes(value) ? (value as T) : fallback
}

function positiveInt(value: string | null): number | null {
  if (value === null || !/^\d+$/.test(value)) return null
  const n = Number(value)
  return Number.isSafeInteger(n) && n > 0 ? n : null
}

export function parseFilters(params: URLSearchParams): JournalFilters {
  const limit = positiveInt(params.get('limit'))
  return {
    accounts: params
      .getAll('account')
      .map(positiveInt)
      .filter((n): n is number => n !== null),
    symbols: params.getAll('symbol').filter((s) => s !== ''),
    statuses: params.getAll('status').filter((s) => (TRADE_STATUSES as readonly string[]).includes(s)),
    period: oneOf(PERIOD_PRESETS, params.get('period'), DEFAULT_PERIOD),
    from: isIsoDate(params.get('from') ?? '') ? (params.get('from') ?? '') : '',
    to: isIsoDate(params.get('to') ?? '') ? (params.get('to') ?? '') : '',
    missingNewFields: params.get(MISSING_NEW_FIELDS_PARAM) === 'true',
    missingR: params.get(MISSING_R_PARAM) === 'true',
    sort: oneOf(TRADE_SORT_FIELDS, params.get('sort'), DEFAULT_SORT),
    order: oneOf(['asc', 'desc'] as const, params.get('order'), DEFAULT_ORDER),
    page: positiveInt(params.get('page')) ?? 1,
    limit: limit !== null && (PAGE_SIZES as readonly number[]).includes(limit) ? limit : DEFAULT_PAGE_SIZE,
    trade: positiveInt(params.get('trade')),
  }
}

/** Serializes filters, leaving out defaults so URLs stay short. */
export function filtersToParams(f: JournalFilters): URLSearchParams {
  const params = new URLSearchParams()
  for (const id of f.accounts) params.append('account', String(id))
  for (const symbol of f.symbols) params.append('symbol', symbol)
  for (const status of f.statuses) params.append('status', status)
  if (f.period !== DEFAULT_PERIOD) params.set('period', f.period)
  if (f.period === 'custom') {
    if (f.from) params.set('from', f.from)
    if (f.to) params.set('to', f.to)
  }
  if (f.missingNewFields) params.set(MISSING_NEW_FIELDS_PARAM, 'true')
  if (f.missingR) params.set(MISSING_R_PARAM, 'true')
  if (f.sort !== DEFAULT_SORT) params.set('sort', f.sort)
  if (f.order !== DEFAULT_ORDER) params.set('order', f.order)
  if (f.page > 1) params.set('page', String(f.page))
  if (f.limit !== DEFAULT_PAGE_SIZE) params.set('limit', String(f.limit))
  if (f.trade !== null) params.set('trade', String(f.trade))
  return params
}

export function periodRange(f: JournalFilters, today: string = brusselsToday()): { from?: string; to?: string } {
  switch (f.period) {
    case 'today':
      return { from: today, to: today }
    case 'week':
      return { from: startOfWeek(today) }
    case 'month':
      return { from: startOfMonth(today) }
    case 'days30':
      return { from: addDays(today, -29) }
    case 'all':
      return {}
    case 'custom':
      return { from: f.from || undefined, to: f.to || undefined }
  }
}

export function toTradeQuery(f: JournalFilters, today: string = brusselsToday()): TradeQuery {
  return {
    account_id: f.accounts,
    symbol: f.symbols,
    status: f.statuses,
    ...periodRange(f, today),
    ...(f.missingNewFields ? { missing_new_fields: true } : {}),
    ...(f.missingR ? { missing_r: true } : {}),
    sort: f.sort,
    order: f.order,
    limit: f.limit,
    offset: (f.page - 1) * f.limit,
  }
}

export function hasActiveFilters(f: JournalFilters): boolean {
  return (
    f.accounts.length > 0 ||
    f.symbols.length > 0 ||
    f.statuses.length > 0 ||
    f.period !== DEFAULT_PERIOD ||
    f.missingNewFields ||
    f.missingR
  )
}

/** Filters with every filter cleared (sort and page size kept). */
export function clearedFilters(f: JournalFilters): JournalFilters {
  return {
    ...f,
    accounts: [],
    symbols: [],
    statuses: [],
    period: DEFAULT_PERIOD,
    from: '',
    to: '',
    missingNewFields: false,
    missingR: false,
    page: 1,
  }
}
