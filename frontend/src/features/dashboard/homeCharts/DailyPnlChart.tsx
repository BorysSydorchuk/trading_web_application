import { linearScale } from '@/features/digests/charts/scale'
import { formatPercent, formatSignedMoney } from '@/features/trades/format'
import { uk } from '@/i18n/uk'
import { decimalSign } from '@/lib/decimal'
import { cn } from '@/lib/utils'
import type { HomeCharts } from './api'

const t = uk.dashboard.charts
const WIDTH = 320
const HEIGHT = 120
const PAD = 6

/** P&L by Brussels day as bars around a zero line (plain SVG like the digest charts). */
export function DailyPnlChart({ days, currency }: { days: HomeCharts['daily']; currency: string | null }) {
  const values = days.map((d) => Number(d.net_pnl))
  const y = linearScale(Math.min(0, ...values), Math.max(0, ...values), HEIGHT - PAD, PAD)
  const slot = (WIDTH - 2 * PAD) / Math.max(days.length, 1)
  const width = Math.max(2, slot * 0.7)
  const money = (v: string) => (currency ? uk.dashboard.money(formatSignedMoney(v), currency) : formatSignedMoney(v))
  return (
    <figure className="flex flex-col gap-1">
      <figcaption className="text-xs font-medium">{t.daily}</figcaption>
      <svg role="img" aria-label={t.dailySummary(days.length)} viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="h-32 w-full rounded-md border bg-muted/10">
        <line x1={PAD} x2={WIDTH - PAD} y1={y(0)} y2={y(0)} className="stroke-border" />
        {days.map((d, i) => {
          const value = Number(d.net_pnl)
          const top = Math.min(y(value), y(0))
          const sign = decimalSign(d.net_pnl)
          return (
            <rect
              key={d.day}
              data-testid="daily-bar"
              x={PAD + i * slot + (slot - width) / 2}
              y={top}
              width={width}
              height={Math.max(1, Math.abs(y(value) - y(0)))}
              className={cn(sign > 0 ? 'fill-profit-strong' : sign < 0 ? 'fill-loss-strong' : 'fill-faint')}
            >
              <title>{t.dayTitle(d.day, money(d.net_pnl), d.pct === null ? '' : formatPercent(d.pct, true), d.trades)}</title>
            </rect>
          )
        })}
      </svg>
    </figure>
  )
}
