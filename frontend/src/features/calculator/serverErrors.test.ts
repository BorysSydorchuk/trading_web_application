import { describe, expect, it } from 'vitest'
import { ApiError } from '@/api/client'
import { uk } from '@/i18n/uk'
import { INITIAL_FORM, type CalculatorFormState } from './formModel'
import { mapCalculatorError } from './serverErrors'

const e = uk.calculator.errors
const FORM: CalculatorFormState = { ...INITIAL_FORM, accountId: '1', symbol: 'XAUUSD', entry: '2650.5', slPrice: '2645.5' }

function map(code: string, details: Record<string, unknown> | null = null, form = FORM, status = 422) {
  return mapCalculatorError(new ApiError(code, 'msg', status, details), form, 'USD')
}

describe('mapCalculatorError', () => {
  it('puts validation_error fields next to their inputs', () => {
    expect(map('validation_error', { fields: { entry: 'x', sl_points: 'x', risk_amount: 'x' } })).toEqual({
      fields: { entry: e.fieldRejected, sl: e.fieldRejected, risk: e.fieldRejected }, general: null, unexpected: false,
    })
  })

  it('shows the generic validation text when no field can be pointed at', () => {
    expect(map('validation_error', { fields: {} }).general).toBe(uk.errors.validation_error)
    expect(map('validation_error', { fields: { other: 'x' } }).general).toBe(uk.errors.validation_error)
  })

  it('maps off_tick_grid fields (list or object), with a points-specific SL text', () => {
    expect(map('off_tick_grid', { fields: ['entry', 'sl_price'] }).fields).toEqual({ entry: e.offTickGrid, sl: e.offTickGrid })
    expect(map('off_tick_grid', { fields: { sl_price: 'x' } }, { ...FORM, slMode: 'points' }).fields).toEqual({ sl: e.slPointsOffGrid })
    expect(map('off_tick_grid', null).general).toBe(e.offTickGridGeneral)
  })

  it('maps invalid_stop to the SL field by direction', () => {
    expect(map('invalid_stop').fields).toEqual({ sl: e.invalidStopBuy })
    expect(map('invalid_stop', null, { ...FORM, direction: 'sell' }).fields).toEqual({ sl: e.invalidStopSell })
  })

  it('maps not_found to the symbol or the account', () => {
    expect(map('not_found', { symbol: 'XAUUSD' }, FORM, 404).fields).toEqual({ symbol: e.symbolNotFound('XAUUSD') })
    expect(map('not_found', { account_id: 1 }, FORM, 404).fields).toEqual({ accountId: e.accountNotFound })
  })

  it('maps domain errors to readable general texts', () => {
    expect(map('balance_unavailable', null, FORM, 409).general).toBe(e.balanceUnavailable)
    expect(map('specs_incomplete', { missing: ['point', 'tick_value_loss'] }, FORM, 409).general).toBe(e.specsIncomplete('point, tick_value_loss'))
    expect(e.specsIncomplete('point, tick_value_loss')).toContain('Дані символу неповні, потрібна синхронізація')
    expect(map('specs_invalid', null, FORM, 409).general).toBe(e.specsInvalid)
    expect(map('invalid_targets').general).toBe(e.invalidTargets)
  })

  it('explains below_min_volume with the minimum lot and its risk, never suggesting rounding up', () => {
    const text = map('below_min_volume', { volume_min: '0.10000000', min_volume_risk: '1250.5' }).general
    expect(text).toBe(e.belowMinVolume('0.10', '1 250.50', 'USD'))
    expect(text).toContain('Ризику не вистачає на мінімальний лот 0.10')
    expect(text).toContain('ризик мінімального лота 1 250.50 USD')
    expect(text).not.toMatch(/округл/i)
    expect(map('below_min_volume').general).toBe(e.belowMinVolumeShort)
  })

  it('treats network and server errors as unexpected with the generic text', () => {
    expect(map('network_error', null, FORM, 0)).toEqual({ fields: {}, general: uk.errors.network_error, unexpected: true })
    expect(map('internal_error', null, FORM, 500).general).toBe(uk.errors.internal_error)
    expect(mapCalculatorError(new Error('boom'), FORM, 'USD').general).toBe(uk.errors.unknown)
  })
})
