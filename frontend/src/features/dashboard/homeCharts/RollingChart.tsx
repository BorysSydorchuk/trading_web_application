import { linearScale } from '@/features/digests/charts/scale'
import { formatPercent, formatR } from '@/features/trades/format'
import { uk } from '@/i18n/uk'
import type { HomeCharts } from './api'

const t = uk.dashboard.charts
const WIDTH = 320
const HEIGHT = 120
const PAD = 6

function line(values: (number | null)[], y: (v: number) => number): string {
  const x = (i: number) => PAD + (values.length > 1 ? (i / (values.length - 1)) * (WIDTH - 2 * PAD) : (WIDTH - 2 * PAD) / 2)
  return values
    .map((v, i) => (v === null ? null : `${x(i).toFixed(1)},${y(v).toFixed(1)}`))
    .filter((p): p is string => p !== null)
    .join(' ')
}

/** Rolling win rate (0–100 %) and average R of the last N strategy trades. */
export function RollingChart({ points, window }: { points: HomeCharts['rolling']; window: number }) {
  const last = points[points.length - 1]
  const winRates = points.map((p) => Number(p.win_rate))
  const rs = points.map((p) => (p.avg_r === null ? null : Number(p.avg_r)))
  const known = rs.filter((v): v is number => v !== null)
  const yWin = linearScale(0, 100, HEIGHT - PAD, PAD)
  const yR = linearScale(Math.min(0, ...known), Math.max(0, ...known), HEIGHT - PAD, PAD)
  return (
    <figure className="flex flex-col gap-1">
      <figcaption className="flex flex-wrap items-baseline justify-between gap-2 text-xs">
        <span className="font-medium">{t.rolling(window)}</span>
        {last && (
          <span className="num text-muted-foreground">
            {t.rollingLast(formatPercent(last.win_rate), formatR(last.avg_r))}
          </span>
        )}
      </figcaption>
      <svg role="img" aria-label={t.rollingSummary(points.length)} viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="h-32 w-full rounded-md border bg-muted/10">
        <line x1={PAD} x2={WIDTH - PAD} y1={yR(0)} y2={yR(0)} className="stroke-border" strokeDasharray="3 3" />
        <polyline data-testid="rolling-win-rate" points={line(winRates, yWin)} fill="none" strokeWidth={1.5} className="stroke-primary" />
        <polyline data-testid="rolling-avg-r" points={line(rs, yR)} fill="none" strokeWidth={1.5} className="stroke-muted-foreground" strokeDasharray="4 2" />
      </svg>
      {/* Two scales on one plot: name both (win rate 0–100 %, R from its own min to max). */}
      <p className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1">
          <svg aria-hidden width="16" height="4"><line x1="0" x2="16" y1="2" y2="2" className="stroke-primary" strokeWidth="2" /></svg>
          {t.legendWinRate} ({t.winRateScale})
        </span>
        <span className="inline-flex items-center gap-1">
          <svg aria-hidden width="16" height="4"><line x1="0" x2="16" y1="2" y2="2" className="stroke-muted-foreground" strokeWidth="2" strokeDasharray="4 2" /></svg>
          {t.legendAvgR} ({t.rScale(formatR(String(Math.min(0, ...known))), formatR(String(Math.max(0, ...known))))})
        </span>
      </p>
    </figure>
  )
}
