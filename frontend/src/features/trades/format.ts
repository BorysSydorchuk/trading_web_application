/** Display helpers for trade values. Decimals stay strings; rounding is done on digits. */
import { uk } from '@/i18n/uk'
import { decimalSign, formatDecimal, roundDecimal, trimDecimal } from '@/lib/decimal'

const EMPTY = uk.common.empty
const t = uk.trades

/** Prices: trailing zeros of NUMERIC(20,8) dropped, at least 2 decimals, no grouping. */
export function formatPrice(value: string | null): string {
  return value === null ? EMPTY : trimDecimal(value, 2)
}

export function formatVolume(value: string | null): string {
  return value === null ? EMPTY : trimDecimal(value, 2)
}

export function formatMoney(value: string | null): string {
  return value === null ? EMPTY : formatDecimal(roundDecimal(value, 2))
}

/** Rounded to 2 places; sign taken from the rounded value so 0.004 shows "0.00" with no sign or colour. */
function signedRounded(value: string): string {
  const rounded = roundDecimal(value, 2)
  const text = formatDecimal(rounded)
  return decimalSign(rounded) > 0 ? `+${text}` : text
}

/** Money with an explicit "+" for gains (P&L columns). */
export function formatSignedMoney(value: string | null): string {
  return value === null ? EMPTY : signedRounded(value)
}

export function formatPercent(value: string | null, signed = false): string {
  if (value === null) return EMPTY
  const text = signed ? signedRounded(value) : formatDecimal(roundDecimal(value, 2))
  return `${text}${t.percentSuffix}`
}

export function formatR(value: string | null): string {
  return value === null ? EMPTY : `${signedRounded(value)}${t.rSuffix}`
}

export function formatRatio(value: string | null): string {
  return value === null ? EMPTY : roundDecimal(value, 2)
}

/** Tailwind class for P&L-like values (as displayed, i.e. rounded to 2 places): green gain, red loss. */
export function pnlClass(value: string | null): string {
  if (value === null) return ''
  const sign = decimalSign(roundDecimal(value, 2))
  return sign > 0 ? 'text-profit' : sign < 0 ? 'text-loss' : ''
}

export function formatDuration(seconds: number | null): string {
  if (seconds === null) return EMPTY
  const d = t.duration
  if (seconds < 60) return d.seconds(seconds)
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return d.minutes(minutes)
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${d.hours(hours)} ${d.minutes(minutes % 60)}`
  return `${d.days(Math.floor(hours / 24))} ${d.hours(hours % 24)}`
}

/** Ukrainian label for a known value; unknown values (new broker/back-end codes) show as is. */
function lookup(map: Readonly<Record<string, string>>, key: string | null): string {
  if (key === null) return EMPTY
  return (Object.hasOwn(map, key) ? map[key] : undefined) ?? key
}

export const directionLabel = (value: string) => lookup(t.direction, value)
export const sessionLabel = (value: string | null) => lookup(t.session, value)
export const statusLabel = (value: string) => lookup(t.status, value)
export const slSourceLabel = (value: string | null) => lookup(t.slSource, value)
export const dealReasonLabel = (value: string | null) => lookup(t.dealReason, value)
export const violationSourceLabel = (value: string) => lookup(t.violationSource, value)

export function weekdayLabel(value: number | null): string {
  return value === null ? EMPTY : (t.weekdays[value] ?? String(value))
}
