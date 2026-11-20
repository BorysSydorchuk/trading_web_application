import { afterEach, describe, expect, it } from 'vitest'
import { DEFAULT_SELECTION, loadSelection, rangeOf, saveSelection } from './range'

const TODAY = '2026-11-19' // Thursday

afterEach(() => window.localStorage.clear())

describe('M8-14 range presets', () => {
  it('computes Brussels date ranges, «Свої дати» only when valid', () => {
    expect(rangeOf({ ...DEFAULT_SELECTION, preset: 'week' }, TODAY)).toEqual({ from: '2026-11-16', to: TODAY })
    expect(rangeOf({ ...DEFAULT_SELECTION, preset: 'month' }, TODAY)).toEqual({ from: '2026-11-01', to: TODAY })
    expect(rangeOf({ ...DEFAULT_SELECTION, preset: 'months3' }, TODAY)).toEqual({ from: '2026-08-20', to: TODAY })
    expect(rangeOf({ ...DEFAULT_SELECTION, preset: 'year' }, TODAY)).toEqual({ from: '2025-11-20', to: TODAY })
    // month ends and leap days clamp to the target month (no roll-over into the next one)
    expect(rangeOf({ ...DEFAULT_SELECTION, preset: 'months3' }, '2026-05-31')).toEqual({ from: '2026-03-01', to: '2026-05-31' })
    expect(rangeOf({ ...DEFAULT_SELECTION, preset: 'year' }, '2028-02-29')).toEqual({ from: '2027-03-01', to: '2028-02-29' })
    expect(rangeOf({ ...DEFAULT_SELECTION, preset: 'custom', from: '2026-11-10', to: '2026-11-01' }, TODAY)).toBeNull()
    expect(rangeOf({ ...DEFAULT_SELECTION, preset: 'custom', from: '2026-11-01', to: '2026-11-10' }, TODAY)).toEqual({
      from: '2026-11-01',
      to: '2026-11-10',
    })
  })

  it('remembers the selection per browser; defaults «Місяць», all accounts', () => {
    expect(loadSelection()).toEqual(DEFAULT_SELECTION)
    saveSelection({ preset: 'year', from: '', to: '', accountId: 2 })
    expect(loadSelection()).toEqual({ preset: 'year', from: '', to: '', accountId: 2 })
    window.localStorage.setItem('tj.home.charts', '{broken')
    expect(loadSelection()).toEqual(DEFAULT_SELECTION)
  })
})
