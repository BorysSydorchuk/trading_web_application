/**
 * Decimal values travel as strings (docs/api.md) and are never converted to float here.
 * Helpers parse/format the string form only.
 */

const DECIMAL_RE = /^(\d+)(?:\.(\d+))?$/
const GROUP_SEPARATOR = '\u202f' // narrow no-break space

export interface DecimalParts {
  integer: string
  fraction: string
}

/** Normalizes user input: trims, drops spaces, turns a decimal comma into a dot. */
export function normalizeDecimalInput(value: string): string {
  return value.replace(/\s+/g, '').replace(/,/g, '.')
}

/** Splits a non-negative decimal string ("0012.50" → {integer: "12", fraction: "50"}); null if not a decimal. */
export function parseDecimalParts(value: string): DecimalParts | null {
  const match = DECIMAL_RE.exec(value)
  if (!match) return null
  const integer = (match[1] ?? '0').replace(/^0+(?=\d)/, '')
  return { integer, fraction: match[2] ?? '' }
}

/** True when the decimal string is strictly greater than zero. */
export function isPositiveDecimal(parts: DecimalParts): boolean {
  return /[1-9]/.test(parts.integer + parts.fraction)
}

/** Compares a decimal to an integer limit without float conversion. */
export function decimalExceeds(parts: DecimalParts, limit: number): boolean {
  if (parts.integer.length > String(limit).length) return true
  const integer = Number(parts.integer)
  if (integer !== limit) return integer > limit
  return /[1-9]/.test(parts.fraction)
}

/** Formats a decimal string for display: thousands grouped, dot as decimal separator, digits kept as sent. */
export function formatDecimal(value: string): string {
  const negative = value.startsWith('-')
  const parts = parseDecimalParts(negative ? value.slice(1) : value)
  if (!parts) return value
  const grouped = parts.integer.replace(/\B(?=(\d{3})+(?!\d))/g, GROUP_SEPARATOR)
  const sign = negative ? '\u2212' : ''
  return parts.fraction ? `${sign}${grouped}.${parts.fraction}` : `${sign}${grouped}`
}

function splitSign(value: string): { negative: boolean; abs: string } {
  if (value.startsWith('-')) return { negative: true, abs: value.slice(1) }
  if (value.startsWith('+')) return { negative: false, abs: value.slice(1) }
  return { negative: false, abs: value }
}

/** Rounds a decimal string half away from zero to `places` digits, on digits only (no float). */
export function roundDecimal(value: string, places: number): string {
  const { negative, abs } = splitSign(value)
  const parts = parseDecimalParts(abs)
  if (!parts) return value
  const fraction = parts.fraction.padEnd(places + 1, '0')
  const digits = (parts.integer + fraction.slice(0, places)).split('')
  if ((fraction[places] ?? '0') >= '5') {
    let i = digits.length - 1
    while (i >= 0 && digits[i] === '9') {
      digits[i] = '0'
      i--
    }
    if (i < 0) digits.unshift('1')
    else digits[i] = String(Number(digits[i]) + 1)
  }
  const joined = digits.join('')
  const integer = joined.slice(0, joined.length - places).replace(/^0+(?=\d)/, '') || '0'
  const result = places > 0 ? `${integer}.${joined.slice(joined.length - places)}` : integer
  return negative && /[1-9]/.test(result) ? `-${result}` : result
}

/** Drops trailing fraction zeros but keeps at least `minPlaces` ("2650.12000000" → "2650.12"). */
export function trimDecimal(value: string, minPlaces = 0): string {
  const { negative, abs } = splitSign(value)
  const parts = parseDecimalParts(abs)
  if (!parts) return value
  const fraction = parts.fraction.replace(/0+$/, '').padEnd(minPlaces, '0')
  const result = fraction ? `${parts.integer}.${fraction}` : parts.integer
  return negative && /[1-9]/.test(result) ? `-${result}` : result
}

/** -1 / 0 / 1 for two non-negative decimal strings; null if either is not a decimal. */
export function compareDecimal(a: string, b: string): -1 | 0 | 1 | null {
  const pa = parseDecimalParts(a)
  const pb = parseDecimalParts(b)
  if (!pa || !pb) return null
  if (pa.integer.length !== pb.integer.length) return pa.integer.length < pb.integer.length ? -1 : 1
  const width = Math.max(pa.fraction.length, pb.fraction.length)
  const da = pa.integer + pa.fraction.padEnd(width, '0')
  const db = pb.integer + pb.fraction.padEnd(width, '0')
  if (da === db) return 0
  return da < db ? -1 : 1
}

/** Sign of a decimal string: -1, 0 or 1. */
export function decimalSign(value: string): -1 | 0 | 1 {
  const { negative, abs } = splitSign(value)
  if (!/[1-9]/.test(abs)) return 0
  return negative ? -1 : 1
}
