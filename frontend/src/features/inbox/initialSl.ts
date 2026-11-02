/**
 * Client-side checks for a user-entered initial SL, mirroring the backend
 * (PATCH /api/trades/{id}): positive decimal, ≤ 8 decimal places, NUMERIC(20,8),
 * not equal to the entry, below the entry for a buy, above it for a sell.
 * No float math: decimals are compared as digit strings.
 */
import { isApiError } from '@/api/client'
import type { TradeRow } from '@/features/trades/types'
import { uk } from '@/i18n/uk'
import { errorText } from '@/lib/errors'
import { compareDecimal, isPositiveDecimal, normalizeDecimalInput, parseDecimalParts } from '@/lib/decimal'

const s = uk.inboxPage.sl
const MAX_FRACTION = 8
const MAX_INTEGER = 12

export function validateInitialSl(raw: string, trade: Pick<TradeRow, 'direction' | 'entry_price'>): string | null {
  const value = normalizeDecimalInput(raw)
  if (value === '') return s.required
  if (value.startsWith('-')) return s.positive
  const parts = parseDecimalParts(value)
  if (!parts) return s.decimal
  if (parts.fraction.length > MAX_FRACTION) return s.fraction
  if (parts.integer.length > MAX_INTEGER) return s.decimal
  if (!isPositiveDecimal(parts)) return s.positive
  const vsEntry = compareDecimal(value, trade.entry_price)
  if (vsEntry === 0) return s.equal
  if (trade.direction === 'buy' && vsEntry === 1) return s.buyBelow
  if (trade.direction === 'sell' && vsEntry === -1) return s.sellAbove
  return null
}

/** Inline message for a failed PATCH (the global toast is shown separately). */
export function initialSlServerError(error: unknown): string {
  if (isApiError(error)) {
    if (error.code === 'trade_open') return uk.errors.trade_open
    if (error.code === 'validation_error') return s.serverRejected
  }
  return errorText(error)
}
