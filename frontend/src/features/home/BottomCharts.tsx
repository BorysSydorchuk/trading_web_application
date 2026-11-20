import { useId, type ReactNode } from 'react'
import { Card } from '@/components/studio/Card'
import type { HomeCharts } from '@/features/dashboard/homeCharts/api'
import { uk } from '@/i18n/uk'
import { decimalSign } from '@/lib/decimal'
import { formatPct, formatR, formatUsd } from '@/lib/displayFormat'
import { cn } from '@/lib/utils'
import { evenIndices, minIndex, scale } from './chartMath'
import { brusselsDayMonth, weekdayOfDay } from './dates'

const VIEW_W = 400
const VIEW_H = 150
/** Bars: every value label up to this many days; above it the best, the worst and the last day. */
const ALL_BAR_LABELS_MAX = 10
const WEEKDAY_LABELS_MAX = 7
const DAY_LABELS = 6
const BAR_MAX_W = 60
const BAR_TOP = 22
const BAR_BOTTOM = 108
const DAY_LABEL_Y = 146
/** The charts API's rolling window (docs/api.md M8-14) until the first answer. */
const DEFAULT_ROLLING_WINDOW = 20
const usd = (v: string) => formatUsd(v, 'overview', { signed: true })

function barLabelIndices(values: readonly number[]): Set<number> {
  if (values.length <= ALL_BAR_LABELS_MAX) return new Set(values.map((_, i) => i))
  const max = values.indexOf(Math.max(...values))
  return new Set([minIndex(values), max, values.length - 1])
}

function dayLabels(days: HomeCharts['daily']): Map<number, string> {
  if (days.length <= WEEKDAY_LABELS_MAX) return new Map(days.map((d, i) => [i, weekdayOfDay(d.day)]))
  return new Map(evenIndices(days.length, DAY_LABELS).map((i) => [i, brusselsDayMonth(`${days[i]?.day ?? ''}T12:00:00Z`)]))
}

/** «P&L по днях»: bars around zero with value labels and day labels (Brussels days). */
export function DailyBars({ days }: { days: HomeCharts['daily'] }) {
  const id = useId()
  const values = days.map((d) => Number(d.net_pnl))
  const y = scale(Math.min(0, ...values), Math.max(0, ...values), BAR_BOTTOM, BAR_TOP)
  const slot = VIEW_W / Math.max(days.length, 1)
  const width = Math.min(BAR_MAX_W, slot * 0.65)
  const labelled = barLabelIndices(values)
  const labels = dayLabels(days)
  const summary =
    days.length <= ALL_BAR_LABELS_MAX
      ? uk.home.daily.label(days.map((d, i) => `${labels.get(i) ?? d.day} ${usd(d.net_pnl)}`).join(', '))
      : uk.dashboard.charts.dailySummary(days.length)
  return (
    <svg viewBox={`0 0 ${VIEW_W} ${VIEW_H}`} role="img" aria-label={summary} className="h-[150px] w-full">
      <defs>
        <linearGradient id={`${id}-up`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" style={{ stopColor: 'var(--tj-profit-mid)' }} />
          <stop offset="1" style={{ stopColor: 'var(--tj-profit-light)' }} />
        </linearGradient>
        <linearGradient id={`${id}-down`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" style={{ stopColor: 'var(--tj-loss-light)' }} />
          <stop offset="1" style={{ stopColor: 'var(--tj-loss-mid)' }} />
        </linearGradient>
      </defs>
      <line x1="0" x2={VIEW_W} y1={y(0)} y2={y(0)} className="stroke-line" />
      {days.map((d, i) => {
        const value = values[i] ?? 0
        const sign = decimalSign(d.net_pnl)
        const cx = i * slot + slot / 2
        const barTop = Math.min(y(value), y(0))
        const height = Math.max(1, Math.abs(y(value) - y(0)))
        return (
          <g key={d.day}>
            <rect
              data-testid="daily-bar"
              x={cx - width / 2}
              y={barTop}
              width={width}
              height={height}
              rx={Math.min(8, width / 2)}
              fill={sign < 0 ? `url(#${id}-down)` : `url(#${id}-up)`}
            />
            {labelled.has(i) && (
              <text
                data-testid="daily-value"
                x={cx}
                y={sign < 0 ? barTop + height + 14 : barTop - 7}
                textAnchor="middle"
                fontSize="12"
                className={cn('num font-semibold', sign < 0 ? 'fill-loss' : sign > 0 ? 'fill-profit' : 'fill-ink-muted')}
              >
                {usd(d.net_pnl)}
              </text>
            )}
            {labels.has(i) && (
              <text x={cx} y={DAY_LABEL_Y} textAnchor="middle" fontSize="11" className="fill-ink-muted">
                {labels.get(i)}
              </text>
            )}
          </g>
        )
      })}
    </svg>
  )
}

const LINE_RIGHT = 336
const END_LABEL_GAP = 14

function polyline(values: readonly (number | null)[], y: (v: number) => number): { points: string; last: [number, number] | null } {
  const x = (i: number) => (values.length > 1 ? (i / (values.length - 1)) * LINE_RIGHT : LINE_RIGHT / 2)
  const coords = values.flatMap((v, i) => (v === null ? [] : [[x(i), y(v)] as [number, number]]))
  return { points: coords.map(([px, py]) => `${px.toFixed(1)},${py.toFixed(1)}`).join(' '), last: coords[coords.length - 1] ?? null }
}

/** «Форма · 20 угод»: rolling win rate (upper band) and average R (lower band), each with an end label. */
export function FormChart({ points }: { points: HomeCharts['rolling'] }) {
  const winRates = points.map((p) => Number(p.win_rate))
  const rs = points.map((p) => (p.avg_r === null ? null : Number(p.avg_r)))
  const known = rs.filter((v): v is number => v !== null)
  const wr = polyline(winRates, scale(Math.min(...winRates), Math.max(...winRates), 96, 30))
  const r = polyline(rs, scale(Math.min(...known), Math.max(...known), 128, 70))
  const firstPoint = points[0]
  const lastPoint = points[points.length - 1]
  const firstR = points.find((p) => p.avg_r !== null)?.avg_r ?? null
  const lastR = [...points].reverse().find((p) => p.avg_r !== null)?.avg_r ?? null
  // Keep the two end labels apart when the lines end close to each other.
  const wrLabelY = wr.last ? wr.last[1] + 4 : 0
  const rLabelY = r.last ? Math.max(r.last[1] + 4, wrLabelY + END_LABEL_GAP) : 0
  const label = uk.home.form.label(
    formatPct(firstPoint?.win_rate, 'overview'),
    formatPct(lastPoint?.win_rate, 'overview'),
    formatR(firstR, 'overview'),
    formatR(lastR, 'overview'),
  )
  return (
    <svg viewBox={`0 0 ${VIEW_W} ${VIEW_H}`} role="img" aria-label={label} className="h-[150px] w-full">
      {[40, 80, 120].map((gy) => (
        <line key={gy} x1="0" x2={VIEW_W} y1={gy} y2={gy} className="stroke-divider" />
      ))}
      <polyline data-testid="form-win-rate" points={wr.points} fill="none" strokeWidth={3} strokeLinecap="round" strokeLinejoin="round" className="stroke-lavender-mid" />
      <polyline data-testid="form-avg-r" points={r.points} fill="none" strokeWidth={3} strokeDasharray="6 6" strokeLinecap="round" className="stroke-profit-strong" />
      {wr.last && lastPoint && (
        <>
          <circle cx={wr.last[0]} cy={wr.last[1]} r={5} className="fill-lavender-mid" />
          <text data-testid="form-end-label" x={wr.last[0] + 10} y={wrLabelY} fontSize="12" className="num fill-lavender font-semibold">
            {formatPct(lastPoint.win_rate, 'overview')}
          </text>
        </>
      )}
      {r.last && lastR !== null && (
        <>
          <circle cx={r.last[0]} cy={r.last[1]} r={5} className="fill-profit-strong" />
          <text data-testid="form-end-label" x={r.last[0] + 10} y={rLabelY} fontSize="12" className={cn('num font-semibold', decimalSign(lastR) < 0 ? 'fill-loss' : 'fill-profit')}>
            {formatR(lastR, 'overview')}
          </text>
        </>
      )}
    </svg>
  )
}

function ChartCard({ title, children, legend }: { title: string; children: ReactNode; legend?: ReactNode }) {
  const id = useId()
  return (
    <Card lift aria-labelledby={`${id}-title`} className="px-5 py-[18px]">
      <h2 id={`${id}-title`} className="type-card-title mb-2 text-base">
        {title}
      </h2>
      {children}
      {legend}
    </Card>
  )
}

function Legend() {
  const f = uk.home.form
  return (
    <p className="flex gap-4 text-[11px] text-ink-muted">
      <span className="inline-flex items-center gap-1.5">
        <span aria-hidden className="size-2 rounded-full bg-lavender-mid" />
        {f.legendWinRate}
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span aria-hidden className="size-2 rounded-full bg-profit-strong" />
        {f.legendAvgR}
      </span>
    </p>
  )
}

/** Bottom row: «P&L по днях» and «Форма · 20 угод» for the hero's range and account. */
export function BottomCharts({ charts }: { charts: HomeCharts | undefined }) {
  const days = charts?.daily ?? []
  const rolling = charts?.rolling ?? []
  const empty = (text: string) => <p className="flex h-[150px] items-center justify-center text-sm text-ink-muted">{text}</p>
  return (
    <div className="grid grid-cols-2 gap-4">
      <ChartCard title={uk.home.daily.title}>{days.length === 0 ? empty(uk.home.daily.empty) : <DailyBars days={days} />}</ChartCard>
      <ChartCard title={uk.home.form.title(charts?.rolling_window ?? DEFAULT_ROLLING_WINDOW)} legend={rolling.length > 0 ? <Legend /> : undefined}>
        {rolling.length === 0 ? empty(uk.home.form.empty) : <FormChart points={rolling} />}
      </ChartCard>
    </div>
  )
}
