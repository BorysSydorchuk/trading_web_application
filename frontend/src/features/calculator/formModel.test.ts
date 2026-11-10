import { describe, expect, it } from 'vitest'
import { uk } from '@/i18n/uk'
import { buildPayload, INITIAL_FORM, toDecimalString, validateForm, type CalculatorFormState } from './formModel'

const v = uk.calculator.validation

function form(overrides: Partial<CalculatorFormState> = {}): CalculatorFormState {
  return { ...INITIAL_FORM, accountId: '1', symbol: 'XAUUSD', entry: '2650.50', slPrice: '2645.5', ...overrides }
}

describe('toDecimalString', () => {
  it('trims and turns a decimal comma into a dot, keeping digits as typed', () => {
    expect(toDecimalString('  2650,50 ')).toBe('2650.50')
    expect(toDecimalString('0.10000')).toBe('0.10000')
  })
})

describe('validateForm', () => {
  it('accepts a complete form', () => {
    expect(validateForm(form())).toEqual({})
  })

  it('requires account, symbol and positive decimals in the active SL and risk fields', () => {
    const errors = validateForm(form({ accountId: '', symbol: '', entry: ' ', slPrice: 'abc', riskPercent: '0' }))
    expect(errors).toEqual({ accountId: v.account, symbol: v.symbol, entry: v.required, sl: v.positiveNumber, risk: v.positiveNumber })
  })

  it('checks only the selected SL and risk mode', () => {
    expect(validateForm(form({ slMode: 'points', slPrice: '', slPoints: '500', riskMode: 'amount', riskAmount: '250,5' }))).toEqual({})
    expect(validateForm(form({ slMode: 'points', slPoints: '' })).sl).toBe(v.required)
  })

  it('rejects negatives, exponents and two separators', () => {
    for (const value of ['-1', '1e3', '1.2.3', '1,2,3']) expect(validateForm(form({ entry: value })).entry).toBe(v.positiveNumber)
  })
})

describe('buildPayload', () => {
  it('sends strings, the SL price and the default risk percent', () => {
    expect(buildPayload(form({ entry: '2650,50' }))).toEqual({
      account_id: 1, symbol: 'XAUUSD', direction: 'buy', entry: '2650.50', sl_price: '2645.5', risk_percent: '1.0',
    })
  })

  it('sends exactly one SL field and one risk field for points + amount', () => {
    const payload = buildPayload(form({ direction: 'sell', slMode: 'points', slPoints: ' 500 ', riskMode: 'amount', riskAmount: '250,75' }))
    expect(payload).toEqual({
      account_id: 1, symbol: 'XAUUSD', direction: 'sell', entry: '2650.50', sl_points: '500', risk_amount: '250.75',
    })
    expect(payload).not.toHaveProperty('sl_price')
    expect(payload).not.toHaveProperty('risk_percent')
  })
})
