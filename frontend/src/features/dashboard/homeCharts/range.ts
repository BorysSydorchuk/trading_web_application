/** M8-14 Home charts: range presets (Brussels dates) and the remembered selection. */
import { addDays, brusselsToday, isIsoDate, startOfMonth, startOfWeek } from '@/lib/time'

export const RANGE_PRESETS = ['week', 'month', 'months3', 'year', 'all', 'custom'] as const
export type RangePreset = (typeof RANGE_PRESETS)[number]

export interface ChartSelection {
  preset: RangePreset
  /** Custom range only ("YYYY-MM-DD"). */
  from: string
  to: string
  /** null = all accounts. */
  accountId: number | null
}

export const DEFAULT_SELECTION: ChartSelection = { preset: 'month', from: '', to: '', accountId: null }
/** «Усе»: the app has no trades before this date (first account 2026). */
const ALL_FROM = '2000-01-01'
const STORAGE_KEY = 'tj.home.charts'

function monthsBack(today: string, months: number): string {
  const [y, m, d] = today.split('-').map(Number) as [number, number, number]
  const date = new Date(Date.UTC(y, m - 1 - months, d))
  return addDays(date.toISOString().slice(0, 10), 1)
}

/** from..to for the API, or null while a custom range is incomplete or reversed. */
export function rangeOf(selection: ChartSelection, today: string = brusselsToday()): { from: string; to: string } | null {
  switch (selection.preset) {
    case 'week':
      return { from: startOfWeek(today), to: today }
    case 'month':
      return { from: startOfMonth(today), to: today }
    case 'months3':
      return { from: monthsBack(today, 3), to: today }
    case 'year':
      return { from: monthsBack(today, 12), to: today }
    case 'all':
      return { from: ALL_FROM, to: today }
    case 'custom':
      if (!isIsoDate(selection.from) || !isIsoDate(selection.to) || selection.to < selection.from) return null
      return { from: selection.from, to: selection.to }
  }
}

function isPreset(value: unknown): value is RangePreset {
  return typeof value === 'string' && (RANGE_PRESETS as readonly string[]).includes(value)
}

/** The selection remembered in this browser (storage may be unavailable: defaults then). */
export function loadSelection(): ChartSelection {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (raw === null) return DEFAULT_SELECTION
    const data: unknown = JSON.parse(raw)
    if (typeof data !== 'object' || data === null) return DEFAULT_SELECTION
    const v = data as Record<string, unknown>
    return {
      preset: isPreset(v.preset) ? v.preset : DEFAULT_SELECTION.preset,
      from: typeof v.from === 'string' ? v.from : '',
      to: typeof v.to === 'string' ? v.to : '',
      accountId: typeof v.accountId === 'number' ? v.accountId : null,
    }
  } catch {
    return DEFAULT_SELECTION
  }
}

export function saveSelection(selection: ChartSelection): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(selection))
  } catch {
    // Storage unavailable: the choice lasts until reload.
  }
}
