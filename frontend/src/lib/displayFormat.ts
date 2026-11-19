/**
 * Display formatter, one module with two modes (DECISIONS 2026-11-20, docs/design/DESIGN_SYSTEM.md).
 *
 * - `overview` (Home, digests, cards, charts, badges): USD whole numbers, % and R one decimal,
 *   prices by magnitude (>= 1000: 0 decimals, >= 10: 2, else 4).
 * - `exact` (calculator, trade details, Describe, Journal table, exports): delegates to today's
 *   formatters in features/trades/format.ts, so exact output does not change.
 *
 * Presentation only: the DB and every calculation keep exact Decimal values.
 *
 * Rounding is half away from zero, done on the decimal string (lib/decimal.ts `roundDecimal`), never
 * through float, so "2.675" -> "2.68" and long API decimals ("12345678901234.56785") keep every digit.
 * A JS number input is first turned into its shortest round-trip string (`String(n)`), then rounded
 * the same way; numbers that need exponent notation are handled below (tiny -> fixed, huge -> «—»).
 *
 * Signs: U+2212 minus for negatives (always), "+" for positives only where the value is signed
 * (P&L, R always). Zero after rounding has no sign. Thousands: U+202F narrow no-break space.
 * null, undefined, NaN/Infinity and anything that is not a plain decimal -> «—».
 */
import {
  formatMoney,
  formatPercent,
  formatPrice as formatPriceExact,
  formatR as formatRExact,
  formatSignedMoney,
  formatVolume,
} from '@/features/trades/format'
import { uk } from '@/i18n/uk'
import { decimalSign, formatDecimal, parseDecimalParts, roundDecimal } from '@/lib/decimal'

export type DisplayMode = 'overview' | 'exact'
export type DisplayValue = string | number | null | undefined

export interface SignOptions {
  /** Prefix "+" on positive values (P&L, deviations). Negatives always get U+2212. */
  signed?: boolean
}

const EMPTY = uk.common.empty
const PERCENT = uk.trades.percentSuffix
const R_SUFFIX = uk.trades.rSuffix
const PLAIN_DECIMAL = /^[+-]?\d+(?:\.\d+)?$/
/** Below this a JS number prints in exponent form; toFixed(20) keeps far more digits than we show. */
const TINY_FIXED_DIGITS = 20

/** Plain decimal string without a leading "+", or null when the value cannot be shown. */
export function toDecimalString(value: DisplayValue): string | null {
  if (value === null || value === undefined) return null
  if (typeof value === 'number') return numberToDecimal(value)
  const trimmed = value.trim()
  if (!PLAIN_DECIMAL.test(trimmed)) return null
  return trimmed.startsWith('+') ? trimmed.slice(1) : trimmed
}

function numberToDecimal(value: number): string | null {
  if (!Number.isFinite(value)) return null
  const text = String(value)
  if (!/e/i.test(text)) return text
  // Exponent form: tiny magnitudes become fixed digits; >= 1e21 is not a trading value.
  return Math.abs(value) < 1 ? value.toFixed(TINY_FIXED_DIGITS) : null
}

/** Rounds, groups thousands, puts U+2212 / "+" from the rounded value (so -0.4 USD shows "0"). */
function roundedText(decimal: string, places: number, signed: boolean): string {
  const rounded = roundDecimal(decimal, places)
  const text = formatDecimal(rounded)
  return signed && decimalSign(rounded) > 0 ? `+${text}` : text
}

/** USD amount. Overview: whole dollars ("+1 241", "−90"). */
export function formatUsd(value: DisplayValue, mode: DisplayMode, { signed = false }: SignOptions = {}): string {
  const decimal = toDecimalString(value)
  if (decimal === null) return EMPTY
  if (mode === 'exact') return signed ? formatSignedMoney(decimal) : formatMoney(decimal)
  return roundedText(decimal, 0, signed)
}

/** Percent with the "%" suffix. Overview: one decimal ("+2.1%", "57.0%"). */
export function formatPct(value: DisplayValue, mode: DisplayMode, { signed = false }: SignOptions = {}): string {
  const decimal = toDecimalString(value)
  if (decimal === null) return EMPTY
  if (mode === 'exact') return formatPercent(decimal, signed)
  return `${roundedText(decimal, 1, signed)}${PERCENT}`
}

/** R multiple, always signed. Overview: one decimal ("+1.3R", "−1.0R"). */
export function formatR(value: DisplayValue, mode: DisplayMode): string {
  const decimal = toDecimalString(value)
  if (decimal === null) return EMPTY
  if (mode === 'exact') return formatRExact(decimal)
  return `${roundedText(decimal, 1, true)}${R_SUFFIX}`
}

/** Decimal places for an overview price by magnitude of |value| (decided on digits, no float). */
export function pricePlaces(decimal: string): number {
  const parts = parseDecimalParts(decimal.replace(/^[+-]/, ''))
  const integerDigits = parts && parts.integer !== '0' ? parts.integer.length : 0
  if (integerDigits >= 4) return 0
  if (integerDigits >= 2) return 2
  return 4
}

/**
 * Instrument price. Overview: GER40 "26 523", USDJPY "155.23", EURUSD "1.1091". When rounding
 * crosses a magnitude step (9.99996 -> 10.0000) the value is re-rounded for the new step ("10.00").
 */
export function formatPrice(value: DisplayValue, mode: DisplayMode): string {
  const decimal = toDecimalString(value)
  if (decimal === null) return EMPTY
  if (mode === 'exact') return formatPriceExact(decimal)
  const places = pricePlaces(decimal)
  const settled = pricePlaces(roundDecimal(decimal, places))
  return roundedText(decimal, Math.min(places, settled), false)
}

/** Lot size: always exact in every mode (DECISIONS 2026-11-20). */
export function formatLots(value: DisplayValue): string {
  const decimal = toDecimalString(value)
  return decimal === null ? EMPTY : formatVolume(decimal)
}
