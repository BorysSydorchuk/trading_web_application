import { useId, useLayoutEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'
import { type AxisCandidate, type LabelAlign, spacedAxisLabels } from './axisLabels'
import { spacedValueLabels, type ValueLabelKind } from './valueLabels'
import { MAX_LOSS_WARN_PCT, minIndex, niceGrid, scale, valueLabelIndices } from './chartMath'

/** money: P&L curves; rate: win rate; r: average R; max_loss: room to the max-loss floor (the 0 line). */
export type ChartKind = 'money' | 'rate' | 'r' | 'max_loss'

export interface ChartPoint {
  /** Exact API decimal (labels are formatted from it). */
  raw: string
  value: number
}

export interface HeroChartProps {
  points: readonly ChartPoint[]
  /** Date / time label candidates (point index + text); those that fit the rendered width show. */
  xLabels: readonly AxisCandidate[]
  kind: ChartKind
  /** Formats a value label (overview mode). */
  format: (value: string) => string
  ariaLabel: string
  /** Text of the 0 grid line (max_loss: «ліміт»); the 0 line is always on that chart. */
  zeroLabel?: string
}

// Plot box of the mockup (viewBox 700 x 250, stretched to the card width).
const VIEW_W = 700
const VIEW_H = 250
/** Rendered chart height, px (the container's h-[290px]). */
const BOX_H_PX = 290
const X0 = 64
const X1 = 676
const Y_BOTTOM = 210
const Y_TOP = 40
const GRID_RIGHT = 690
const AXIS_LABEL_X = 54

/** Width assumed before the first measurement (and where layout is unavailable, e.g. jsdom). */
const FALLBACK_WIDTH_PX = 1000

const ALIGN_SHIFT: Record<LabelAlign, string> = { start: '0', center: '-50%', end: '-100%' }

/** Rendered width of the element, kept current by a ResizeObserver. */
function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [width, setWidth] = useState(FALLBACK_WIDTH_PX)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const measure = () => {
      const next = el.getBoundingClientRect().width
      if (next > 0) setWidth(next)
    }
    measure()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(measure)
    observer.observe(el)
    return () => observer.disconnect()
  }, [])
  return [ref, width] as const
}

const left = (x: number) => `${((x / VIEW_W) * 100).toFixed(2)}%`
const top = (y: number) => `${((y / VIEW_H) * 100).toFixed(2)}%`

const AREA_COLOR: Record<ChartKind, string> = {
  money: 'var(--tj-profit-mid)',
  rate: 'var(--tj-accent-ring)',
  r: 'var(--tj-accent-ring)',
  max_loss: 'var(--tj-accent-ring)',
}
const LINE_END: Record<ChartKind, string> = {
  money: 'var(--tj-profit-strong)',
  rate: 'var(--tj-accent-text)',
  r: 'var(--tj-accent-text)',
  max_loss: 'var(--tj-accent-text)',
}

/** Colour of a value label: P&L-like values by sign, the win rate in accent (never green/red). */
function labelTone(kind: ChartKind, value: number): string {
  if (kind === 'rate') return 'text-lavender'
  if (kind === 'max_loss') return value <= MAX_LOSS_WARN_PCT ? 'text-loss' : 'text-ink'
  if (value < 0) return 'text-loss'
  if (value > 0) return 'text-profit'
  return 'text-ink'
}

/** The last point's dot: P&L-like values green, max-loss room red near the floor, else accent. */
function lastDot(kind: ChartKind, value: number): string {
  if (kind !== 'max_loss') return 'bg-profit-strong'
  return value <= MAX_LOSS_WARN_PCT ? 'bg-loss-strong' : 'bg-lavender-mid'
}

/**
 * Main «Головна» chart (mockup): grid with axis values, gradient line and area, date labels and
 * value labels (all points <= 8, else every 3rd + min + last); the minimum sits below the line
 * (loss colour when negative), the last value is a pill. Labels are HTML over the stretched SVG so
 * text is not distorted; the SVG carries the accessible summary.
 */
export function HeroChart({ points, xLabels, kind, format, ariaLabel, zeroLabel }: HeroChartProps) {
  const id = useId()
  const [box, width] = useWidth<HTMLDivElement>()
  const axis = spacedAxisLabels(xLabels, points.length, ((X1 - X0) / VIEW_W) * width)
  const values = points.map((p) => p.value)
  const withZero = kind === 'max_loss'
  const grid = niceGrid(Math.min(...values, ...(withZero ? [0] : [])), Math.max(...values, ...(withZero ? [0] : [])))
  const y = scale(grid.low, grid.high, Y_BOTTOM, Y_TOP)
  const x = (i: number) => (points.length === 1 ? (X0 + X1) / 2 : X0 + (i * (X1 - X0)) / (points.length - 1))
  const xy = points.map((p, i) => [x(i), y(p.value)] as const)
  const line = xy.map(([px, py]) => `${px.toFixed(1)},${py.toFixed(1)}`).join(' ')
  const area = `${x(0).toFixed(1)},${Y_BOTTOM} ${line} ${x(points.length - 1).toFixed(1)},${Y_BOTTOM}`
  const last = points.length - 1
  const min = minIndex(values)
  const kindOf = (i: number): ValueLabelKind => (i === last ? 'last' : i === min ? 'min' : 'point')
  const shown = spacedValueLabels(
    valueLabelIndices(values).flatMap((i) => {
      const point = points[i]
      const at = xy[i]
      if (!point || !at) return []
      return [{ index: i, text: format(point.raw), kind: kindOf(i), x: (at[0] / VIEW_W) * width, y: (at[1] / VIEW_H) * BOX_H_PX }]
    }),
  )
  return (
    <div ref={box} className="relative mt-2.5 h-[290px]">
      <svg viewBox={`0 0 ${VIEW_W} ${VIEW_H}`} preserveAspectRatio="none" role="img" aria-label={ariaLabel} className="absolute inset-0 size-full">
        <defs>
          <linearGradient id={`${id}-area`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" style={{ stopColor: AREA_COLOR[kind], stopOpacity: 0.45 }} />
            <stop offset="1" style={{ stopColor: AREA_COLOR[kind], stopOpacity: 0 }} />
          </linearGradient>
          <linearGradient id={`${id}-line`} x1="0" y1="0" x2="1" y2="0">
            <stop offset="0" style={{ stopColor: 'var(--tj-chart-line-from)' }} />
            <stop offset="1" style={{ stopColor: LINE_END[kind] }} />
          </linearGradient>
        </defs>
        {grid.ticks.map((tick) => (
          <line
            key={tick}
            data-testid="hero-grid"
            x1={X0}
            x2={GRID_RIGHT}
            y1={y(tick)}
            y2={y(tick)}
            className="stroke-line"
            strokeDasharray={tick === 0 ? undefined : '3 6'}
            vectorEffect="non-scaling-stroke"
          />
        ))}
        <polygon points={area} fill={`url(#${id}-area)`} />
        <polyline
          points={line}
          fill="none"
          stroke={`url(#${id}-line)`}
          strokeWidth={3}
          strokeLinejoin="round"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      <div aria-hidden>
        {grid.ticks.map((tick) => (
          <span
            key={tick}
            className="num absolute text-[11px] whitespace-nowrap text-ink-muted"
            style={{ left: left(AXIS_LABEL_X), top: top(y(tick)), transform: 'translate(-100%, -50%)' }}
          >
            {tick === 0 ? (zeroLabel ?? '0') : format(String(tick))}
          </span>
        ))}
        {axis.map((label) => (
          <span
            key={`${label.index}-${label.text}`}
            data-testid="hero-x-label"
            className="num absolute top-[92%] text-[11px] whitespace-nowrap text-ink-muted"
            style={{ left: left(x(label.index)), transform: `translateX(${ALIGN_SHIFT[label.align]})` }}
          >
            {label.text}
          </span>
        ))}
        {shown.map((i) => {
          const point = points[i]
          const at = xy[i]
          if (!point || !at) return null
          const isLast = i === last
          const isMin = i === min && !isLast
          const position = { left: left(at[0]), top: top(at[1]) }
          return (
            <span key={i}>
              <span
                className={cn(
                  'absolute -translate-1/2 rounded-full border-surface',
                  isLast ? 'size-3.5 border-[3px] shadow-[0_0_0_1px_var(--tj-border)]' : 'size-2 border-2',
                  isLast ? lastDot(kind, point.value) : isMin && point.value < 0 ? 'bg-loss-strong' : 'bg-lavender-mid',
                )}
                style={position}
              />
              <span
                data-testid="hero-value-label"
                data-kind={isLast ? 'last' : isMin ? 'min' : 'point'}
                className={cn(
                  'num absolute whitespace-nowrap',
                  isLast
                    ? 'ml-[-10px] rounded-[10px] border border-line bg-surface px-2 py-0.5 text-[13px] font-semibold'
                    : 'rounded-md bg-surface/75 px-1 text-[11px] font-semibold',
                  isLast || (isMin && point.value < 0) ? labelTone(kind, point.value) : 'text-ink',
                )}
                style={{ ...position, transform: `translate(${isLast ? '-100%' : '-50%'}, ${isMin ? '10px' : 'calc(-100% - 10px)'})` }}
              >
                {format(point.raw)}
              </span>
            </span>
          )
        })}
      </div>
    </div>
  )
}
