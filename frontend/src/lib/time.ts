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
