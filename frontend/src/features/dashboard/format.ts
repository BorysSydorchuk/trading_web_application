/**
 * Dashboard display (docs/api.md "## M6"): percents with 2 decimals as `−0.42%`, money 2 dp with
 * the account currency; the app's U+2212 minus and grouping (same as Journal/Describe).
 * Rounding is ROUND_HALF_UP on the digits of the API string (no float).
 */
import { uk } from '@/i18n/uk'
import { formatDecimal, roundDecimal } from '@/lib/decimal'
import { addDays } from '@/lib/time'

const d = uk.dashboard

/** "-0.4250" → "−0.43%", "0.0000" → "0.00%", "-0.0040" → "0.00%" (no negative zero). */
export function formatPct(value: string): string {
  return `${formatDecimal(roundDecimal(value, 2))}${uk.trades.percentSuffix}`
}

/** A limit in percent, or «вимкнено» when the rule is off (`null`). */
export function formatLimit(value: string | null): string {
  return value === null ? d.limitOff : formatPct(value)
}

/** "-1234.5" + "USD" → "−1 234.50 USD". */
export function formatAccountMoney(value: string, currency: string): string {
  return d.money(formatDecimal(roundDecimal(value, 2)), currency)
}

function dayMonth(isoDate: string): { day: number; month: number } {
  return { day: Number(isoDate.slice(8, 10)), month: Number(isoDate.slice(5, 7)) }
}

/** Monday "2026-11-09" → "9–15 лист."; across months "30 лист. – 6 груд.". */
export function formatWeekRange(periodStart: string): string {
  const start = dayMonth(periodStart)
  const end = dayMonth(addDays(periodStart, 6))
  const months = d.monthsShort
  if (start.month === end.month) return `${start.day}–${end.day} ${months[end.month - 1] ?? ''}`
  return `${start.day} ${months[start.month - 1] ?? ''} – ${end.day} ${months[end.month - 1] ?? ''}`
}

/** "2026-11-01" → "листопад 2026". */
export function formatMonth(periodStart: string): string {
  const { month } = dayMonth(periodStart)
  return `${d.months[month - 1] ?? ''} ${periodStart.slice(0, 4)}`
}

/** `/digests?kind=weekly&date=YYYY-MM-DD` (the Дайджести page opens that period). */
export function digestPath(kind: 'weekly' | 'monthly', periodStart: string): string {
  return `/digests?${new URLSearchParams({ kind, date: periodStart }).toString()}`
}
