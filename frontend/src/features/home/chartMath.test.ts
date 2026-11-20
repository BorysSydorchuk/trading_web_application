import { describe, expect, it } from 'vitest'
import { evenIndices, ladderGeometry, limitBarGeometry, monthBoundaryIndices, niceGrid, sparkPoints, valueLabelIndices } from './chartMath'

describe('valueLabelIndices (hero value labels)', () => {
  it('labels every point up to 8 points (the start point only when it is the minimum, as in the mockup)', () => {
    expect(valueLabelIndices([0, 120, 30, 340, 741])).toEqual([0, 1, 2, 3, 4])
    expect(valueLabelIndices([10, 5, 30])).toEqual([1, 2])
    expect(valueLabelIndices([45, 48, 46, 50, 52, 50, 55, 57])).toEqual([0, 1, 2, 3, 4, 5, 6, 7])
  })

  it('above 8 points labels every 3rd point plus the minimum and the last one', () => {
    // mockup «листопад»: 18 points, minimum −45 at index 2
    const month = [0, -20, -45, 60, 140, 120, 260, 310, 290, 410, 499, 470, 640, 705, 780, 899, 1010, 1241]
    expect(valueLabelIndices(month)).toEqual([2, 3, 6, 9, 12, 15, 17])
  })

  it('a single point is labelled; no points, no labels', () => {
    expect(valueLabelIndices([5])).toEqual([0])
    expect(valueLabelIndices([])).toEqual([])
  })
})

describe('niceGrid', () => {
  it('uses 1/2/2.5/5 steps with at most 4 intervals', () => {
    expect(niceGrid(0, 741)).toEqual({ low: 0, high: 800, step: 200, ticks: [0, 200, 400, 600, 800] })
    expect(niceGrid(-45, 1241).ticks).toEqual([-500, 0, 500, 1000, 1500])
    expect(niceGrid(0.6, 1.3).ticks).toEqual([0.6, 0.8, 1, 1.2, 1.4])
  })

  it('a flat series still gets two lines', () => {
    expect(niceGrid(0, 0).ticks).toHaveLength(2)
  })
})

describe('limitBarGeometry', () => {
  it('puts the loss limit left, the profit limit right, zero between, fill from zero (mockup day bar)', () => {
    const g = limitBarGeometry(2.1, -3, 5)
    expect(g.zero).toBeCloseTo(37.5)
    expect(g.lossZone).toBeCloseTo(37.5)
    expect(g.fillLeft).toBeCloseTo(37.5)
    expect(g.fillWidth).toBeCloseTo(26.25)
    expect(g.clamped).toBe(false)
  })

  it('a loss fills from the value up to zero; beyond the limit it is clamped to the edge', () => {
    const loss = limitBarGeometry(-1.5, -3, 5)
    expect(loss.fillLeft).toBeCloseTo(18.75)
    expect(loss.fillWidth).toBeCloseTo(18.75)
    const beyond = limitBarGeometry(-4, -3, 5)
    expect(beyond.fillLeft).toBe(0)
    expect(beyond.fillWidth).toBeCloseTo(37.5)
    expect(beyond.clamped).toBe(true)
  })

  it('without limits the bar is symmetric around zero and has no loss zone', () => {
    const g = limitBarGeometry(3.1, null, null)
    expect(g.zero).toBe(50)
    expect(g.lossZone).toBe(0)
    expect(g.fillWidth).toBeCloseTo(50)
  })
})

describe('ladderGeometry', () => {
  it('SL (−1R) left, entry at 0R, TP R right; MAE–MFE band and the current price on the same scale', () => {
    const g = ladderGeometry({ tpR: 1.5, rNow: 0.7, maeR: 0.2, mfeR: 0.8 })
    expect(g.entry).toBeCloseTo(40)
    expect(g.now).toBeCloseTo(68)
    expect(g.bandLeft).toBeCloseTo(32)
    expect(g.bandWidth).toBeCloseTo(40)
  })

  it('without TP the right edge is the largest of 1R, MFE and the current R; without a live R no dot', () => {
    const g = ladderGeometry({ tpR: null, rNow: null, maeR: null, mfeR: 2 })
    expect(g.right).toBe(2)
    expect(g.now).toBeNull()
    expect(g.bandLeft).toBeNull()
  })
})

describe('small helpers', () => {
  it('evenIndices spreads labels and keeps both ends', () => {
    expect(evenIndices(18, 4)).toEqual([0, 6, 11, 17])
    expect(evenIndices(3, 4)).toEqual([0, 1, 2])
  })

  it('sparkPoints fits the box', () => {
    expect(sparkPoints([0, 10], 120, 26)).toBe('0.0,24.0 120.0,2.0')
  })
})

describe('monthBoundaryIndices', () => {
  it('labels the first point and each month start', () => {
    expect(monthBoundaryIndices(['8', '9', '9', '10', '10', '11'])).toEqual([0, 1, 3, 5])
  })

  it('drops the first point when the first boundary is too close, and thins to the maximum', () => {
    const keys = Array.from({ length: 120 }, (_, i) => String(Math.floor((i + 1) / 10)))
    // Starts at 9, 19, ..., 119 plus index 0 (gap 9): 13 labels thinned evenly to 6, the last kept.
    const indices = monthBoundaryIndices(keys, 6)
    expect(indices).toHaveLength(6)
    expect(indices[indices.length - 1]).toBe(119)
    expect(monthBoundaryIndices(['8', '9', ...Array.from({ length: 30 }, () => '9')], 6)).toEqual([1])
  })

  it('returns [] for no points and [0] for a single month', () => {
    expect(monthBoundaryIndices([])).toEqual([])
    expect(monthBoundaryIndices(['9', '9', '9'])).toEqual([0])
  })
})
