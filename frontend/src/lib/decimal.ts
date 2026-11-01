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
