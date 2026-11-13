import { formatSignedMoney, weekdayLabel } from '@/features/trades/format'
import { uk } from '@/i18n/uk'
import { decimalSign } from '@/lib/decimal'
import type { HeatCell } from '../types'
import { ChartEmpty } from './ChartEmpty'

const c = uk.digests.charts
const CELL = 26
const LEFT = 28
const TOP = 16
/** Mon–Fri always; Sat/Sun rows only when they have trades (docs/api.md "Charts data"). */
const WORKDAYS = [0, 1, 2, 3, 4]
const MIN_OPACITY = 0.15

function cellText(cell: HeatCell): string {
  return c.cell(weekdayLabel(cell.weekday), String(cell.hour).padStart(2, '0'), cell.trades, formatSignedMoney(cell.net_pnl))
}

/** Best and worst cell by P&L (geometry-grade comparison; the texts use the API strings). */
function extremes(cells: readonly HeatCell[]): { best: HeatCell; worst: HeatCell } | null {
  const [first, ...rest] = cells
  if (!first) return null
  let best = first
  let worst = first
  for (const cell of rest) {
    if (Number(cell.net_pnl) > Number(best.net_pnl)) best = cell
    if (Number(cell.net_pnl) < Number(worst.net_pnl)) worst = cell
  }
  return { best, worst }
}

/** Weekday × Brussels hour of open: trade count in the cell, colour by P&L sign and size. */
export function HourHeatmap({ cells }: { cells: readonly HeatCell[] }) {
  const ends = extremes(cells)
  if (!ends) return <ChartEmpty title={c.heatmap} />
  const weekdays = [...new Set([...WORKDAYS, ...cells.map((cell) => cell.weekday)])].sort((a, b) => a - b)
  const hourValues = cells.map((cell) => cell.hour)
  const minHour = Math.min(...hourValues)
  const hours = Array.from({ length: Math.max(...hourValues) - minHour + 1 }, (_, i) => minHour + i)
  const maxAbs = Math.max(...cells.map((cell) => Math.abs(Number(cell.net_pnl)))) || 1
  const width = LEFT + hours.length * CELL
  const height = TOP + weekdays.length * CELL
  return (
    <figure className="flex flex-col gap-1">
      <figcaption className="flex items-baseline justify-between gap-2 text-xs">
        <span className="font-medium">{c.heatmap}</span>
        <span className="text-muted-foreground">{c.timeZoneNote}</span>
      </figcaption>
      <svg role="img" aria-label={c.heatmapSummary(cellText(ends.best), cellText(ends.worst))} viewBox={`0 0 ${width} ${height}`} className="w-full max-w-xl rounded-md border bg-muted/10">
        {hours.map((hour, i) => (
          <text key={hour} x={LEFT + i * CELL + CELL / 2} y={TOP - 4} textAnchor="middle" className="num fill-muted-foreground text-[9px]">
            {String(hour).padStart(2, '0')}
          </text>
        ))}
        {weekdays.map((weekday, row) => (
          <text key={weekday} x={4} y={TOP + row * CELL + CELL / 2 + 3} className="fill-muted-foreground text-[9px]">
            {weekdayLabel(weekday)}
          </text>
        ))}
        {cells.map((cell) => {
          const row = weekdays.indexOf(cell.weekday)
          const col = cell.hour - minHour
          const sign = decimalSign(cell.net_pnl)
          const opacity = MIN_OPACITY + (1 - MIN_OPACITY) * (Math.abs(Number(cell.net_pnl)) / maxAbs)
          return (
            <g key={`${cell.weekday}-${cell.hour}`} data-cell={`${cell.weekday}-${cell.hour}`}>
              <title>{cellText(cell)}</title>
              <rect
                x={LEFT + col * CELL + 1}
                y={TOP + row * CELL + 1}
                width={CELL - 2}
                height={CELL - 2}
                rx={3}
                fillOpacity={opacity}
                className={sign > 0 ? 'fill-profit' : sign < 0 ? 'fill-loss' : 'fill-muted-foreground'}
              />
              <text x={LEFT + col * CELL + CELL / 2} y={TOP + row * CELL + CELL / 2 + 3} textAnchor="middle" className="num fill-foreground text-[10px]">
                {cell.trades}
              </text>
            </g>
          )
        })}
      </svg>
    </figure>
  )
}
