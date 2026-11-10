/** Display rounding for calculator values. Decimal strings only; rounding never feeds back into sizing. */
import { uk } from '@/i18n/uk'
import { formatDecimal, roundDecimal, trimDecimal } from '@/lib/decimal'

const EMPTY = uk.common.empty

/** Volume as returned by the server, trailing zeros dropped (at least 2 places). */
export function formatVolume(value: string | null): string {
  return value === null ? EMPTY : trimDecimal(value, 2)
}

/** Money: 2 places, thousands grouped. */
export function formatMoney(value: string | null): string {
  return value === null ? EMPTY : formatDecimal(roundDecimal(value, 2))
}

export function formatPercent(value: string | null): string {
  return value === null ? EMPTY : `${roundDecimal(value, 2)}${uk.trades.percentSuffix}`
}

/** Price with the symbol's digits; unknown digits → trailing zeros dropped. */
export function formatPriceDigits(value: string | null, digits: number | null): string {
  if (value === null) return EMPTY
  return digits === null ? trimDecimal(value, 2) : roundDecimal(value, digits)
}

/** SL distance in points (may be fractional when the SL was entered as a price). */
export function formatPoints(value: string): string {
  return trimDecimal(value)
}

/** Worker codes that read well after «MT5 не порахував маржу:» (uk.sync.errors). */
const MT5_CODES = ['password_missing', 'terminal_not_found', 'terminal_in_program_files', 'terminal_start_failed', 'login_failed', 'timeout', 'mt5_error'] as const
type Mt5Code = (typeof MT5_CODES)[number]

function isMt5Code(code: string): code is Mt5Code {
  return (MT5_CODES as readonly string[]).includes(code)
}

/** Why the live margin did not come: the worker's error_code when known, else the generic reason. */
export function marginFailureText(reason: 'failed' | 'expired' | 'error', code: string | null): string {
  const r = uk.calculator.result
  if (reason === 'failed' && code !== null) {
    if (code === 'interrupted' || code === 'internal_error') return r.marginErrorCodes[code]
    if (isMt5Code(code)) return r.marginFailedWith(uk.sync.errors[code])
  }
  return r.marginLiveFailed[reason]
}
