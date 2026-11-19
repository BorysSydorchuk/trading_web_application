import { describe, expect, it } from 'vitest'
import { formatMoney, formatPercent, formatPrice as priceExact, formatR as rExact, formatSignedMoney, formatVolume } from '@/features/trades/format'
import { formatLots, formatPct, formatPrice, formatR, formatUsd, pricePlaces, toDecimalString } from './displayFormat'

const MINUS = '−' // U+2212 minus sign
const NNBSP = ' ' // U+202F narrow no-break space
const EMPTY = '—'

describe('toDecimalString', () => {
  it.each([
    ['12.5', '12.5'],
    [' +3.20 ', '3.20'],
    ['-0.5', '-0.5'],
    [42, '42'],
    [-1.25, '-1.25'],
    [1e-7, '0.00000010000000000000'],
  ])('accepts %j', (input, expected) => {
    expect(toDecimalString(input)).toBe(expected)
  })

  it.each([null, undefined, '', 'abc', '1,5', '1e5', '.5', '1.', '--1', Number.NaN, Number.POSITIVE_INFINITY, 1e21])(
    'rejects %j',
    (input) => {
      expect(toDecimalString(input)).toBeNull()
    },
  )
})

describe('formatUsd overview', () => {
  it.each([
    ['1241.49', '1' + NNBSP + '241'],
    ['0.5', '1'],
    ['2.5', '3'],
    ['-2.5', MINUS + '3'],
    ['-0.49', '0'],
    ['0', '0'],
    ['-0.00', '0'],
    ['999.5', '1' + NNBSP + '000'],
    ['1234567.89', '1' + NNBSP + '234' + NNBSP + '568'],
  ])('unsigned %s -> %s', (input, expected) => {
    expect(formatUsd(input, 'overview')).toBe(expected)
  })

  it('signs positives only when signed, negatives always with U+2212', () => {
    expect(formatUsd('212.4', 'overview', { signed: true })).toBe('+212')
    expect(formatUsd('-90.2', 'overview', { signed: true })).toBe(MINUS + '90')
    expect(formatUsd('-90.2', 'overview')).toBe(MINUS + '90')
    expect(formatUsd('0.4', 'overview', { signed: true })).toBe('0')
  })

  it('rounds on the string beyond float precision', () => {
    // Number('...234.49999999999999999') is 12345678901234.5 and would round up to ...235; the string does not.
    expect(formatUsd('12345678901234.49999999999999999', 'overview')).toBe(['12', '345', '678', '901', '234'].join(NNBSP))
    expect(formatUsd('2.675', 'exact')).toBe('2.68')
  })

  it('accepts numbers', () => {
    expect(formatUsd(1241.5, 'overview', { signed: true })).toBe('+1' + NNBSP + '242')
    expect(formatUsd(-0.5, 'overview')).toBe(MINUS + '1')
  })

  it.each([null, undefined, 'n/a', Number.NaN])('shows «—» for %j', (input) => {
    expect(formatUsd(input, 'overview')).toBe(EMPTY)
    expect(formatUsd(input, 'exact')).toBe(EMPTY)
  })
})

describe('formatPct overview', () => {
  it.each([
    ['2.14', false, '2.1%'],
    ['2.15', false, '2.2%'],
    ['-2.15', false, MINUS + '2.2%'],
    ['57', false, '57.0%'],
    ['2.05', true, '+2.1%'],
    ['-0.04', true, '0.0%'],
    ['0', true, '0.0%'],
    ['1234.56', false, '1' + NNBSP + '234.6%'],
  ])('%s (signed %s) -> %s', (input, signed, expected) => {
    expect(formatPct(input, 'overview', { signed })).toBe(expected)
  })
})

describe('formatR overview', () => {
  it.each([
    ['1.25', '+1.3R'],
    ['-1', MINUS + '1.0R'],
    ['-0.05', MINUS + '0.1R'],
    ['-0.04', '0.0R'],
    ['0', '0.0R'],
    ['0.349', '+0.3R'],
  ])('%s -> %s', (input, expected) => {
    expect(formatR(input, 'overview')).toBe(expected)
  })

  it('shows «—» for null', () => {
    expect(formatR(null, 'overview')).toBe(EMPTY)
  })
})

describe('formatPrice overview by magnitude', () => {
  it.each([
    ['26523.4', '26' + NNBSP + '523'],
    ['26523.5', '26' + NNBSP + '524'],
    ['1000', '1' + NNBSP + '000'],
    ['155.2345', '155.23'],
    ['10', '10.00'],
    ['1.10915', '1.1092'],
    ['1.10914', '1.1091'],
    ['0.65', '0.6500'],
    ['9.99996', '10.00'],
    ['999.996', '1' + NNBSP + '000'],
    ['-1.5', MINUS + '1.5000'],
  ])('%s -> %s', (input, expected) => {
    expect(formatPrice(input, 'overview')).toBe(expected)
  })

  it('picks places from the integer digits', () => {
    expect([pricePlaces('0.5'), pricePlaces('9.9'), pricePlaces('10'), pricePlaces('999.9'), pricePlaces('1000')]).toEqual([4, 4, 2, 2, 0])
  })

  it('never adds a plus sign', () => {
    expect(formatPrice('+1.1', 'overview')).toBe('1.1000')
  })
})

describe('exact mode delegates to the existing formatters', () => {
  it.each(['1234.5', '-0.004', '0', '12.3456', '-98765.4321'])('same output for %s', (value) => {
    expect(formatUsd(value, 'exact')).toBe(formatMoney(value))
    expect(formatUsd(value, 'exact', { signed: true })).toBe(formatSignedMoney(value))
    expect(formatPct(value, 'exact')).toBe(formatPercent(value))
    expect(formatPct(value, 'exact', { signed: true })).toBe(formatPercent(value, true))
    expect(formatR(value, 'exact')).toBe(rExact(value))
    expect(formatPrice(value, 'exact')).toBe(priceExact(value))
  })
})

describe('formatLots', () => {
  it('is always exact', () => {
    expect(formatLots('0.13')).toBe(formatVolume('0.13'))
    expect(formatLots('1.25000000')).toBe('1.25')
    expect(formatLots('0.005')).toBe('0.005')
    expect(formatLots(0.5)).toBe('0.50')
    expect(formatLots(null)).toBe(EMPTY)
  })
})
