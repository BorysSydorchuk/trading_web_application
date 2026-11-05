/** Bias periods (docs/api.md M4): trading day, Monday of the week, 1st of the month. Pure. */
import { addDays, APP_TIME_ZONE, isIsoDate, startOfMonth, startOfWeek } from '@/lib/time'
import type { BiasKind, BiasNote } from './types'

/** pre_ny starts with the premarket (PRD 6.6); before it the morning (London) bias is the one to write. */
const PRE_NY_FROM_HOUR = 11

/** The stored period_date for a picked date (same normalization as the API). */
export function normalizePeriod(kind: BiasKind, isoDate: string): string {
  if (kind === 'weekly') return startOfWeek(isoDate)
  if (kind === 'monthly') return startOfMonth(isoDate)
  return isoDate
}

const hourFormatter = new Intl.DateTimeFormat('en-GB', { timeZone: APP_TIME_ZONE, hour: '2-digit', hour12: false })

/** Kind for a new note without one in the URL: London before 11:00 Brussels, else New York. */
export function defaultKind(now: Date = new Date()): BiasKind {
  const hour = Number(hourFormatter.format(now))
  return hour < PRE_NY_FROM_HOUR ? 'pre_london' : 'pre_ny'
}

/** "2026-11-06" → "06.11.2026" (a calendar date, no time zone involved). */
export function formatIsoDate(isoDate: string): string {
  if (!isIsoDate(isoDate)) return isoDate
  const [y, m, d] = isoDate.split('-')
  return `${d ?? ''}.${m ?? ''}.${y ?? ''}`
}

const weekdayFormatter = new Intl.DateTimeFormat('uk-UA', { timeZone: 'UTC', weekday: 'short' })

/** "2026-11-06" → "06.11.2026, пт" (list group header). */
export function formatDayHeader(isoDate: string): string {
  if (!isIsoDate(isoDate)) return isoDate
  return `${formatIsoDate(isoDate)}, ${weekdayFormatter.format(new Date(`${isoDate}T00:00:00Z`))}`
}

/** "02.11" – "08.11" for a weekly note's Monday. */
export function weekRange(monday: string): [string, string] {
  const short = (iso: string) => formatIsoDate(iso).slice(0, 5)
  return [short(monday), short(addDays(monday, 6))]
}

/** A result can be marked once the period has started (the session may already be over today). */
export function canMarkResult(periodDate: string, today: string): boolean {
  return periodDate <= today
}

/** Notes grouped by period date, keeping the API order (newest period first). */
export function groupByDate(notes: readonly BiasNote[]): { date: string; notes: BiasNote[] }[] {
  const groups: { date: string; notes: BiasNote[] }[] = []
  for (const note of notes) {
    const last = groups.at(-1)
    if (last?.date === note.period_date) last.notes.push(note)
    else groups.push({ date: note.period_date, notes: [note] })
  }
  return groups
}
