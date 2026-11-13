import { formatSignedMoney } from '@/features/trades/format'
import { uk } from '@/i18n/uk'
import { decimalSign } from '@/lib/decimal'
import { cn } from '@/lib/utils'
import type { EquityPoint } from '../types'
import { ChartEmpty } from './ChartEmpty'
import { linearScale } from './scale'

const c = uk.digests.charts
const WIDTH = 320
const HEIGHT = 120
const PAD = 6

/**
 * Running closed P&L after each trade of the period (plain SVG, DECISIONS: no chart library).
 * Floats are used only for the geometry; the shown total is the API string.
 */
export function EquityChart({ title, points }: { title: string; points: readonly EquityPoint[] }) {
  if (points.length === 0) return <ChartEmpty title={title} />
  const values = [0, ...points.map((p) => Number(p.cum_pnl))]
  const y = linearScale(Math.min(...values), Math.max(...values), HEIGHT - PAD, PAD)
  const x = (i: number) => PAD + (values.length === 1 ? 0 : (i / (values.length - 1)) * (WIDTH - 2 * PAD))
  const path = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')
  const last = points[points.length - 1]?.cum_pnl ?? '0'
  const sign = decimalSign(last)
  return (
    <figure className="flex flex-col gap-1">
      <figcaption className="flex items-baseline justify-between gap-2 text-xs">
        <span className="font-medium">{title}</span>
        <span className="num text-muted-foreground">{c.equityEnd(formatSignedMoney(last))}</span>
      </figcaption>
      <svg role="img" aria-label={title} viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="h-32 w-full rounded-md border bg-muted/10">
        <line x1={PAD} x2={WIDTH - PAD} y1={y(0)} y2={y(0)} className="stroke-border" strokeDasharray="3 3" />
        <polyline
          data-testid="equity-line"
          points={path}
          fill="none"
          strokeWidth={1.5}
          className={cn(sign > 0 ? 'stroke-profit' : sign < 0 ? 'stroke-loss' : 'stroke-muted-foreground')}
        />
      </svg>
    </figure>
  )
}
