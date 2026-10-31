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
