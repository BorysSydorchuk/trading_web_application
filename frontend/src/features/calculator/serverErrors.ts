/** Maps calculate / margin-request errors (docs/api.md "M5-04c exact shapes") to the form. */
import { isApiError, type ApiErrorDetails } from '@/api/client'
import { uk } from '@/i18n/uk'
import { errorText } from '@/lib/errors'
import { formatMoney, formatVolume } from './format'
import type { FieldErrors, FieldKey, CalculatorFormState } from './formModel'

const t = uk.calculator.errors

export interface CalculatorErrors {
  fields: FieldErrors
  /** Shown above the result area; null when every problem sits next to an input. */
  general: string | null
  /** Not a domain answer (network, 500, …): also toasted. */
  unexpected: boolean
}

/** API body field → form input. */
const API_FIELDS: Readonly<Record<string, FieldKey>> = {
  account_id: 'accountId',
  symbol: 'symbol',
  entry: 'entry',
  sl_price: 'sl',
  sl_points: 'sl',
  risk_percent: 'risk',
  risk_amount: 'risk',
}

function fieldNames(details: ApiErrorDetails): string[] {
  const fields = details?.fields
  if (Array.isArray(fields)) return fields.filter((name): name is string => typeof name === 'string')
  if (typeof fields === 'object' && fields !== null) return Object.keys(fields)
  return []
}

function stringDetail(details: ApiErrorDetails, key: string): string | null {
  const value = details?.[key]
  return typeof value === 'string' ? value : null
}

function fieldErrors(details: ApiErrorDetails, message: (key: FieldKey) => string, fallback: string): CalculatorErrors {
  const fields: FieldErrors = {}
  let unmapped = false
  for (const name of fieldNames(details)) {
    const key = API_FIELDS[name]
    if (key) fields[key] = message(key)
    else unmapped = true
  }
  const general = unmapped || Object.keys(fields).length === 0 ? fallback : null
  return { fields, general, unexpected: false }
}

function notFound(details: ApiErrorDetails): CalculatorErrors {
  const symbol = stringDetail(details, 'symbol')
  if (symbol !== null) return { fields: { symbol: t.symbolNotFound(symbol) }, general: null, unexpected: false }
  return { fields: { accountId: t.accountNotFound }, general: null, unexpected: false }
}

function specsIncomplete(details: ApiErrorDetails): string {
  const missing = details?.missing
  const keys = Array.isArray(missing) ? missing.filter((k): k is string => typeof k === 'string') : []
  return t.specsIncomplete(keys.join(', '))
}

function belowMinVolume(details: ApiErrorDetails, currency: string): string {
  const volumeMin = stringDetail(details, 'volume_min')
  const risk = stringDetail(details, 'min_volume_risk')
  if (volumeMin === null || risk === null) return t.belowMinVolumeShort
  return t.belowMinVolume(formatVolume(volumeMin), formatMoney(risk), currency)
}

function general(text: string): CalculatorErrors {
  return { fields: {}, general: text, unexpected: false }
}

/** `currency` = the account currency (for the minimum-lot risk). */
export function mapCalculatorError(error: unknown, form: CalculatorFormState, currency: string): CalculatorErrors {
  if (!isApiError(error)) return { fields: {}, general: errorText(error), unexpected: true }
  const { details } = error
  switch (error.code) {
    case 'validation_error':
      return fieldErrors(details, () => t.fieldRejected, uk.errors.validation_error)
    case 'off_tick_grid':
      return fieldErrors(details, (key) => (key === 'sl' && form.slMode === 'points' ? t.slPointsOffGrid : t.offTickGrid), t.offTickGridGeneral)
    case 'invalid_stop':
      return { fields: { sl: form.direction === 'buy' ? t.invalidStopBuy : t.invalidStopSell }, general: null, unexpected: false }
    case 'not_found':
      return notFound(details)
    case 'balance_unavailable':
      return general(t.balanceUnavailable)
    case 'specs_incomplete':
      return general(specsIncomplete(details))
    case 'specs_invalid':
      return general(t.specsInvalid)
    case 'below_min_volume':
      return general(belowMinVolume(details, currency))
    case 'invalid_targets':
      return general(t.invalidTargets)
    default:
      return { fields: {}, general: errorText(error), unexpected: true }
  }
}
