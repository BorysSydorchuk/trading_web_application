/** All timestamps are UTC in data; the UI shows Europe/Brussels (PRD 6.3). */
export const APP_TIME_ZONE = 'Europe/Brussels'

const timeFormatter = new Intl.DateTimeFormat('uk-UA', {
  timeZone: APP_TIME_ZONE,
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
})

/** Formats an instant as HH:mm:ss in Europe/Brussels. */
export function formatTimeBrussels(value: Date | number): string {
  return timeFormatter.format(value)
}

const hmFormatter = new Intl.DateTimeFormat('uk-UA', {
  timeZone: APP_TIME_ZONE,
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
})

const dayMonthFormatter = new Intl.DateTimeFormat('uk-UA', {
  timeZone: APP_TIME_ZONE,
  day: '2-digit',
  month: '2-digit',
})

const dateKeyFormatter = new Intl.DateTimeFormat('en-CA', {
  timeZone: APP_TIME_ZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
})

/**
 * Short Brussels time of a past UTC instant: "HH:mm" if it is today in Brussels,
 * otherwise "dd.MM HH:mm" so a stale value is not mistaken for a fresh one.
 */
export function formatRecentBrussels(isoUtc: string, now: Date = new Date()): string {
  const date = new Date(isoUtc)
  if (Number.isNaN(date.getTime())) return isoUtc
  const time = hmFormatter.format(date)
  if (dateKeyFormatter.format(date) === dateKeyFormatter.format(now)) return time
  return `${dayMonthFormatter.format(date)} ${time}`
}

const dateTimeFormatter = new Intl.DateTimeFormat('uk-UA', {
  timeZone: APP_TIME_ZONE,
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
})

/** Full Brussels date and time of a UTC instant, e.g. "01.11.2026, 14:32:05". */
export function formatDateTimeBrussels(isoUtc: string): string {
  const date = new Date(isoUtc)
  return Number.isNaN(date.getTime()) ? isoUtc : dateTimeFormatter.format(date)
}

const shortDateTimeFormatter = new Intl.DateTimeFormat('uk-UA', {
  timeZone: APP_TIME_ZONE,
  day: '2-digit',
  month: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
})

/** "dd.MM, HH:mm" in Brussels (tables). */
export function formatShortDateTimeBrussels(isoUtc: string): string {
  const date = new Date(isoUtc)
  return Number.isNaN(date.getTime()) ? isoUtc : shortDateTimeFormatter.format(date)
}

/** Today's Brussels calendar date as "YYYY-MM-DD". */
export function brusselsToday(now: Date = new Date()): string {
  return dateKeyFormatter.format(now)
}

const ISO_DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/

export function isIsoDate(value: string): boolean {
  const match = ISO_DATE_RE.exec(value)
  if (!match) return false
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])))
  return date.toISOString().slice(0, 10) === value
}

function fromIsoDate(value: string): Date {
  const [y, m, d] = value.split('-').map(Number)
  return new Date(Date.UTC(y ?? 1970, (m ?? 1) - 1, d ?? 1))
}

/** Calendar arithmetic on "YYYY-MM-DD" strings (no time zone involved). */
export function addDays(isoDate: string, days: number): string {
  const date = fromIsoDate(isoDate)
  date.setUTCDate(date.getUTCDate() + days)
  return date.toISOString().slice(0, 10)
}

/** Monday of the week containing the date (weeks are Mon–Sun). */
export function startOfWeek(isoDate: string): string {
  const weekday = (fromIsoDate(isoDate).getUTCDay() + 6) % 7
  return addDays(isoDate, -weekday)
}

export function startOfMonth(isoDate: string): string {
  return `${isoDate.slice(0, 8)}01`
}
