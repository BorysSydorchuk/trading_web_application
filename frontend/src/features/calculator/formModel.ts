/** Calculator form state → API body. Values stay strings exactly as typed (trim + comma → dot only). */
import { uk } from '@/i18n/uk'
import type { CalculateInput, Direction } from './types'

const t = uk.calculator.validation

export type SlMode = 'price' | 'points'
export type RiskMode = 'percent' | 'amount'

export interface CalculatorFormState {
  accountId: string
  symbol: string
  direction: Direction
  entry: string
  slMode: SlMode
  slPrice: string
  slPoints: string
  riskMode: RiskMode
  riskPercent: string
  riskAmount: string
}

/** Inputs that can carry an error message next to them. */
export type FieldKey = 'accountId' | 'symbol' | 'entry' | 'sl' | 'risk'
export type FieldErrors = Partial<Record<FieldKey, string>>

export const DEFAULT_RISK_PERCENT = '1.0'

export const INITIAL_FORM: CalculatorFormState = {
  accountId: '',
  symbol: '',
  direction: 'buy',
  entry: '',
  slMode: 'price',
  slPrice: '',
  slPoints: '',
  riskMode: 'percent',
  riskPercent: DEFAULT_RISK_PERCENT,
  riskAmount: '',
}

const POSITIVE_DECIMAL_RE = /^\d+(?:\.\d+)?$/

/** Trim and turn one decimal comma into a dot; nothing else is changed (no float parsing). */
export function toDecimalString(value: string): string {
  return value.trim().replace(',', '.')
}

function decimalError(raw: string): string | null {
  const value = toDecimalString(raw)
  if (value === '') return t.required
  if (!POSITIVE_DECIMAL_RE.test(value) || !/[1-9]/.test(value)) return t.positiveNumber
  return null
}

export function slValue(form: CalculatorFormState): string {
  return form.slMode === 'price' ? form.slPrice : form.slPoints
}

export function riskValue(form: CalculatorFormState): string {
  return form.riskMode === 'percent' ? form.riskPercent : form.riskAmount
}

export function validateForm(form: CalculatorFormState): FieldErrors {
  const errors: FieldErrors = {}
  if (form.accountId === '') errors.accountId = t.account
  if (form.symbol === '') errors.symbol = t.symbol
  const entry = decimalError(form.entry)
  if (entry) errors.entry = entry
  const sl = decimalError(slValue(form))
  if (sl) errors.sl = sl
  const risk = decimalError(riskValue(form))
  if (risk) errors.risk = risk
  return errors
}

/** The body for calculate / margin-requests: exactly one SL field and exactly one risk field. */
export function buildPayload(form: CalculatorFormState): CalculateInput {
  const sl = toDecimalString(slValue(form))
  const risk = toDecimalString(riskValue(form))
  return {
    account_id: Number(form.accountId),
    symbol: form.symbol,
    direction: form.direction,
    entry: toDecimalString(form.entry),
    ...(form.slMode === 'price' ? { sl_price: sl } : { sl_points: sl }),
    ...(form.riskMode === 'percent' ? { risk_percent: risk } : { risk_amount: risk }),
  }
}
