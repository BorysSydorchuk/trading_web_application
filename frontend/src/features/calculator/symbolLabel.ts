import { uk } from '@/i18n/uk'
import type { SymbolSpec } from './types'

const t = uk.calculator.form

/** `GER40 (GER30)` when the broker names it differently; needs-sync suffix for an incomplete spec. */
export function symbolLabel(spec: SymbolSpec): string {
  const name = spec.broker_symbol === spec.symbol ? spec.symbol : t.symbolWithBroker(spec.symbol, spec.broker_symbol)
  return spec.point === null || spec.tick_value_loss === null ? t.symbolNeedsSync(name) : name
}
