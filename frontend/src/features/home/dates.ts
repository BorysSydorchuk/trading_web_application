/** Brussels date/time labels for «Головна» (all data timestamps are UTC, PRD 6.3). */
import { APP_TIME_ZONE } from '@/lib/time'

const dayMonth = new Intl.DateTimeFormat('uk-UA', { timeZone: APP_TIME_ZONE, day: '2-digit', month: '2-digit' })
const hourMinute = new Intl.DateTimeFormat('uk-UA', { timeZone: APP_TIME_ZONE, hour: '2-digit', minute: '2-digit', hour12: false })
const headerDate = new Intl.DateTimeFormat('uk-UA', { timeZone: APP_TIME_ZONE, weekday: 'short', day: 'numeric', month: 'long' })
const weekdayShort = new Intl.DateTimeFormat('uk-UA', { timeZone: APP_TIME_ZONE, weekday: 'short' })
const monthYear = new Intl.DateTimeFormat('en-CA', { timeZone: APP_TIME_ZONE, year: 'numeric', month: '2-digit' })

function valid(iso: string): Date | null {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? null : date
}

const capitalize = (text: string) => text.charAt(0).toUpperCase() + text.slice(1)

/** "19.11" */
export function brusselsDayMonth(iso: string): string {
  const date = valid(iso)
  return date ? dayMonth.format(date) : iso
}

/** "14:42" */
export function brusselsHourMinute(iso: string): string {
  const date = valid(iso)
  return date ? hourMinute.format(date) : iso
}

/** "Чт, 19 листопада" */
export function brusselsHeaderDate(iso: string): string {
  const date = valid(iso)
  return date ? capitalize(headerDate.format(date)) : iso
}

/** Weekday of a Brussels calendar day "YYYY-MM-DD": "Пн". Noon UTC stays on the same Brussels day. */
export function weekdayOfDay(day: string): string {
  const date = valid(`${day}T12:00:00Z`)
  return date ? capitalize(weekdayShort.format(date)) : day
}

/** Brussels calendar month of an instant: {year, month 1-12}. */
export function brusselsMonth(iso: string): { year: number; month: number } | null {
  const date = valid(iso)
  if (!date) return null
  const [year, month] = monthYear.format(date).split('-').map(Number)
  return year && month ? { year, month } : null
}

const MINUTE_MS = 60_000
const MINUTES_PER_HOUR = 60
const HOURS_PER_DAY = 24

/** Whole minutes from `fromIso` to `toIso` (never negative). */
export function minutesBetween(fromIso: string, toIso: string): number {
  const from = valid(fromIso)
  const to = valid(toIso)
  if (!from || !to) return 0
  return Math.max(0, Math.floor((to.getTime() - from.getTime()) / MINUTE_MS))
}

export function splitDuration(minutes: number): { days: number; hours: number; minutes: number } {
  const days = Math.floor(minutes / (MINUTES_PER_HOUR * HOURS_PER_DAY))
  const hours = Math.floor(minutes / MINUTES_PER_HOUR) % HOURS_PER_DAY
  return { days, hours, minutes: minutes % MINUTES_PER_HOUR }
}
