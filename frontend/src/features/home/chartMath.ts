/** Pure geometry for the «Головна» charts and bars (M8-10b, docs/design/home-mockup.html). */

/** Index of the first smallest value (-1 for an empty list). */
export function minIndex(values: readonly number[]): number {
  let best = -1
  values.forEach((value, i) => {
    if (best === -1 || value < (values[best] ?? Infinity)) best = i
  })
  return best
}

/** Up to this many points every point gets a value label; above it every 3rd point. */
export const ALL_LABELS_MAX_POINTS = 8
const LABEL_EVERY = 3

/**
 * Points that get a value label (mockup rule): <= 8 points -> every point; more -> every 3rd point,
 * plus the minimum and the last one. The start point (index 0, the zero of a P&L curve) is labelled
 * only when it is the minimum or the only point.
 */
export function valueLabelIndices(values: readonly number[]): number[] {
  const last = values.length - 1
  if (last < 0) return []
  const min = minIndex(values)
  const every = values.length <= ALL_LABELS_MAX_POINTS ? 1 : LABEL_EVERY
  return values
    .map((_, i) => i)
    .filter((i) => i === last || i === min || (i > 0 && i % every === 0))
}

/** `count` indices spread evenly over `length` points, first and last included. */
export function evenIndices(length: number, count: number): number[] {
  if (length <= 0) return []
  if (length <= count) return Array.from({ length }, (_, i) => i)
  const step = (length - 1) / (count - 1)
  return Array.from({ length: count }, (_, i) => Math.round(i * step))
}

export interface Grid {
  low: number
  high: number
  step: number
  ticks: number[]
}

const STEP_MULTIPLIERS = [1, 2, 2.5, 5] as const
const MAX_GRID_INTERVALS = 4

/** Rounds away float noise from grid values (0.1 + 0.2). */
function clean(value: number): number {
  const rounded = Number(value.toPrecision(12))
  return Object.is(rounded, -0) ? 0 : rounded
}

/** A "nice" grid (1 / 2 / 2.5 / 5 x 10^k) with at most 4 intervals covering low..high. */
export function niceGrid(low: number, high: number): Grid {
  const span = high - low || Math.abs(high) || 1
  let magnitude = 10 ** Math.floor(Math.log10(span / MAX_GRID_INTERVALS))
  for (let guard = 0; guard < 4; guard++) {
    for (const multiplier of STEP_MULTIPLIERS) {
      const step = clean(multiplier * magnitude)
      const from = Math.floor(low / step + 1e-9)
      const to = Math.ceil(high / step - 1e-9)
      if (to - from <= MAX_GRID_INTERVALS) {
        const top = to === from ? from + 1 : to
        const ticks = Array.from({ length: top - from + 1 }, (_, i) => clean((from + i) * step))
        return { low: clean(from * step), high: clean(top * step), step, ticks }
      }
    }
    magnitude *= 10
  }
  return { low, high, step: span, ticks: [low, high] }
}

/** Maps [low, high] onto [from, to]; a flat range maps to the middle. */
export function scale(low: number, high: number, from: number, to: number): (value: number) => number {
  if (high === low) return () => (from + to) / 2
  return (value) => from + ((value - low) / (high - low)) * (to - from)
}

/** Clamped to 0..100 and rounded to 0.01 % (CSS positions; no float noise like 26.249999%). */
const clampPct = (value: number) => Math.round(Math.min(100, Math.max(0, value)) * 100) / 100

export interface LimitBarGeometry {
  /** Left edge of the scale and its right edge (percent values, e.g. -3 and 5). */
  low: number
  high: number
  /** Zero tick position, % of the bar width. */
  zero: number
  /** Hatched loss zone: from the left edge to zero, % width; 0 without a loss limit. */
  lossZone: number
  /** Fill from zero to the current value: left edge and width, %. */
  fillLeft: number
  fillWidth: number
  /** The current value is beyond the drawn scale (clamped to the edge). */
  clamped: boolean
}

/** Fallback half-width when a side has no limit: the larger of the value and the other limit, at least 1 %. */
function fallbackSide(current: number, other: number | null): number {
  return Math.max(Math.abs(current), Math.abs(other ?? 0), 1)
}

/**
 * Limit bar: loss limit on the left edge, profit limit on the right edge, zero tick between them,
 * fill from zero to the current value (clamped to the edges). A missing limit uses a symmetric
 * fallback so the bar still shows the value around zero.
 */
export function limitBarGeometry(current: number, loss: number | null, profit: number | null): LimitBarGeometry {
  const low = loss !== null && loss < 0 ? loss : -fallbackSide(current, profit)
  const high = profit !== null && profit > 0 ? profit : fallbackSide(current, loss)
  const at = (value: number) => clampPct(((value - low) / (high - low)) * 100)
  const zero = at(0)
  const value = at(current)
  return {
    low,
    high,
    zero,
    lossZone: loss !== null && loss < 0 ? zero : 0,
    fillLeft: Math.min(zero, value),
    fillWidth: Math.round(Math.abs(value - zero) * 100) / 100,
    clamped: current < low || current > high,
  }
}

export interface LadderGeometry {
  /** Entry tick (0R), % from the left (SL = −1R is the left edge). */
  entry: number
  /** Right edge in R: the TP R, or the largest of 1R / MFE / current R without a TP. */
  right: number
  /** Current price dot, % (null without a live R). */
  now: number | null
  /** MAE–MFE band, % (null without MAE/MFE). */
  bandLeft: number | null
  bandWidth: number | null
}

/**
 * Price ladder of an open position in R: SL (−1R) on the left edge, entry (0R), TP R on the right
 * edge; the current price and the MAE–MFE band are placed on the same scale (clamped to the edges).
 */
export function ladderGeometry(input: { tpR: number | null; rNow: number | null; maeR: number | null; mfeR: number | null }): LadderGeometry {
  const { tpR, rNow, maeR, mfeR } = input
  const right = tpR !== null && tpR > 0 ? tpR : Math.max(1, mfeR ?? 0, rNow ?? 0)
  const at = (r: number) => clampPct(((r + 1) / (right + 1)) * 100)
  const hasBand = maeR !== null && mfeR !== null
  const bandLeft = hasBand ? at(-Math.abs(maeR)) : null
  const bandRight = hasBand ? at(Math.abs(mfeR)) : null
  return {
    entry: at(0),
    right,
    now: rNow === null ? null : at(rNow),
    bandLeft,
    bandWidth: bandLeft === null || bandRight === null ? null : Math.round((bandRight - bandLeft) * 100) / 100,
  }
}

/** Sparkline polyline points in a `width` x `height` box (2px inset so the stroke is not cut). */
export function sparkPoints(values: readonly number[], width: number, height: number): string {
  if (values.length === 0) return ''
  const inset = 2
  const low = Math.min(...values)
  const high = Math.max(...values)
  const y = scale(low, high, height - inset, inset)
  const x = (i: number) => (values.length === 1 ? width / 2 : (i / (values.length - 1)) * width)
  return values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')
}
