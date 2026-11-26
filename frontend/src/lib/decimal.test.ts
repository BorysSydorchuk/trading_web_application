import { describe, expect, it } from 'vitest'
import { floorDecimal } from './decimal'

describe('floorDecimal', () => {
  it.each([
    ['2.75', 1, '2.7'],
    ['2.7999', 1, '2.7'],
    ['2.70', 1, '2.7'],
    ['3', 1, '3.0'],
    ['0.05', 1, '0.0'],
    ['-0.15', 1, '-0.2'],
    ['-0.10', 1, '-0.1'],
    ['-0.01', 1, '-0.1'],
    ['-9.95', 1, '-10.0'],
    ['-0.00', 1, '0.0'],
    ['2.75', 0, '2'],
    ['-2.75', 0, '-3'],
  ])('%s at %i places -> %s', (value, places, expected) => {
    expect(floorDecimal(value, places)).toBe(expected)
  })

  it('returns a non-decimal input unchanged', () => {
    expect(floorDecimal('abc', 1)).toBe('abc')
  })
})
