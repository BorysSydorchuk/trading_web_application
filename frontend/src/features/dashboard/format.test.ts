import { describe, expect, it } from 'vitest'
import { digestPath, formatAccountMoney, formatLimit, formatMonth, formatPct, formatWeekRange } from './format'

describe('dashboard format', () => {
  it('shows percents with 2 decimals, rounding half up on the digits', () => {
    expect(formatPct('-0.4200')).toBe('-0.42%')
    expect(formatPct('0.0000')).toBe('0.00%')
    expect(formatPct('-0.4250')).toBe('-0.43%')
    expect(formatPct('0.4249')).toBe('0.42%')
    expect(formatPct('-0.0049')).toBe('0.00%')
    expect(formatPct('1.0050')).toBe('1.01%')
  })

  it('shows a disabled limit as «вимкнено»', () => {
    expect(formatLimit(null)).toBe('вимкнено')
    expect(formatLimit('-3.0000')).toBe('-3.00%')
  })

  it('shows money with 2 decimals, grouping and the currency', () => {
    expect(formatAccountMoney('-1234.5', 'USD')).toBe('-1 234.50 USD')
    expect(formatAccountMoney('0.00', 'EUR')).toBe('0.00 EUR')
  })

  it('formats the digest periods and link', () => {
    expect(formatWeekRange('2026-11-09')).toBe('9–15 лист.')
    expect(formatWeekRange('2026-11-30')).toBe('30 лист. – 6 груд.')
    expect(formatMonth('2026-11-01')).toBe('листопад 2026')
    expect(digestPath('weekly', '2026-11-09')).toBe('/digests?kind=weekly&date=2026-11-09')
  })
})
