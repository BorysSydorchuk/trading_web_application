/** Ukrainian text of the effective firm rules (docs/api.md "Firm rules from config"). Display rounding only. */
import { uk } from '@/i18n/uk'
import { formatPct } from '@/lib/displayFormat'
import type { FirmRules } from './types'

const t = uk.accounts.firmRules

export interface FirmRulesText {
  title: string
  /** "денний збиток 4% від …; макс. збиток 8% статичний; ціль 8%." */
  summary: string
  /** One «Перевірити: …» line per `to_verify` item. */
  verify: string[]
}

const pct = (value: string) => formatPct(value, 'overview')

function resetText(rules: FirmRules): string | null {
  if (!rules.daily_reset) return null
  if (!rules.reset_timezone || rules.reset_timezone === 'server') return t.resetServer(rules.daily_reset)
  return t.resetZone(rules.daily_reset, rules.reset_timezone)
}

const DEFAULT_BASIS = 'balance'

function basisText(basis: string | null, forms: Record<string, string>): string {
  const key = basis || DEFAULT_BASIS
  return forms[key] ?? key
}

/** Value shown next to a `to_verify` item, when the item has one. */
function verifyValue(rules: FirmRules, item: string): string | null {
  switch (item) {
    case 'daily_basis':
      return basisText(rules.daily_basis, t.basisValue)
    case 'daily_reset':
    case 'reset_timezone':
      return resetText(rules)
    case 'daily_loss_pct':
      return rules.daily_loss_pct === null ? null : pct(rules.daily_loss_pct)
    case 'max_loss_pct':
      return rules.max_loss_pct === null ? null : pct(rules.max_loss_pct)
    case 'max_loss_type':
      return rules.max_loss_type === null ? null : (t.maxLossType[rules.max_loss_type] ?? rules.max_loss_type)
    case 'profit_target_pct':
      return rules.profit_target_pct === null ? null : pct(rules.profit_target_pct)
    default:
      return null
  }
}

/** Label of one `to_verify` item, with its value when known, e.g. "база денного ліміту (баланс на початок дня)". */
export function verifyItemText(rules: FirmRules | null, item: string): string {
  const label = t.fields[item] ?? item
  const value = rules === null ? null : verifyValue(rules, item)
  return value === null ? label : t.withValue(label, value)
}

/** Only `source: firm` (config/firms.yaml) gets a note; `account` / `fallback` keep the current UI. */
export function firmRulesText(rules: FirmRules | null | undefined): FirmRulesText | null {
  if (!rules || rules.source !== 'firm') return null
  const parts: string[] = []
  if (rules.daily_loss_pct !== null) {
    const basis = basisText(rules.daily_basis, t.basis)
    const reset = resetText(rules)
    const daily = pct(rules.daily_loss_pct)
    parts.push(reset === null ? t.dailyNoReset(daily, basis) : t.daily(daily, basis, reset))
  }
  if (rules.max_loss_pct !== null) {
    const type = rules.max_loss_type === null ? '' : (t.maxLossType[rules.max_loss_type] ?? rules.max_loss_type)
    parts.push(t.maxLoss(pct(rules.max_loss_pct), type))
  }
  if (rules.profit_target_pct !== null) parts.push(t.target(pct(rules.profit_target_pct)))
  return {
    title: t.title(rules.firm),
    summary: parts.length > 0 ? `${parts.join('; ')}.` : '',
    verify: (rules.to_verify ?? []).map((item) => t.verify(verifyItemText(rules, item))),
  }
}
