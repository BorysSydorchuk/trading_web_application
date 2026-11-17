/** M8-09: journal fields prefilled from MT5 (only exit_reason), marked like AI-filled ones. */
import type { TradeDetail } from '@/features/trades/types'

export type Mt5FillSource = 'mt5_reason' | 'price_match'

const EXIT_REASON_KEY = 'exit_reason'

/** Field key → how MT5 filled it; empty when the owner set it or nothing was prefilled. */
export function initialMt5Filled(trade: TradeDetail): ReadonlyMap<string, Mt5FillSource> {
  const source = trade.exit_reason_source
  const value = trade.journal[EXIT_REASON_KEY]
  if ((source === 'mt5_reason' || source === 'price_match') && value !== null && value !== undefined) {
    return new Map([[EXIT_REASON_KEY, source]])
  }
  return new Map()
}

/** Editing a field removes its MT5 marker (same rule as the AI marker). */
export function withoutMt5Mark(
  filled: ReadonlyMap<string, Mt5FillSource>,
  key: string,
): ReadonlyMap<string, Mt5FillSource> {
  if (!filled.has(key)) return filled
  const next = new Map(filled)
  next.delete(key)
  return next
}
