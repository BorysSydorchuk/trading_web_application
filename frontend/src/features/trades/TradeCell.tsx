import type { ColumnKey } from '@/features/journal/columns'
import { uk } from '@/i18n/uk'
import { formatShortDateTimeBrussels } from '@/lib/time'
import { cn } from '@/lib/utils'
import { BiasAlignmentLabel } from './BiasAlignmentLabel'
import {
  directionLabel,
  formatDuration,
  formatMoney,
  formatPercent,
  formatPrice,
  formatR,
  formatRatio,
  formatSignedMoney,
  formatVolume,
  pnlClass,
  sessionLabel,
  statusLabel,
  weekdayLabel,
} from './format'
import type { TradeRow } from './types'
import { useViolationLabel } from './violations'

const EMPTY = uk.common.empty

function Muted() {
  return <span className="text-muted-foreground/60">{EMPTY}</span>
}

/** One table cell value for a trade column. Numbers use `num` (tabular monospace). */
export function TradeCell({ trade, column }: { trade: TradeRow; column: ColumnKey }) {
  switch (column) {
    case 'close_time':
      return trade.close_time ? (
        <span className="num">{formatShortDateTimeBrussels(trade.close_time)}</span>
      ) : (
        <Muted />
      )
    case 'open_time':
      return <span className="num">{formatShortDateTimeBrussels(trade.open_time)}</span>
    case 'duration':
      return <span className="num">{formatDuration(trade.duration_seconds)}</span>
    case 'account':
      return <>{trade.account_name}</>
    case 'symbol':
      return <span className="num font-medium">{trade.symbol}</span>
    case 'direction':
      return <>{directionLabel(trade.direction)}</>
    case 'session':
      return trade.session ? <>{sessionLabel(trade.session)}</> : <Muted />
    case 'weekday':
      return <>{weekdayLabel(trade.weekday)}</>
    case 'hour':
      return <span className="num">{trade.hour ?? EMPTY}</span>
    case 'volume':
      return <span className="num">{formatVolume(trade.volume)}</span>
    case 'entry_price':
      return <span className="num">{formatPrice(trade.entry_price)}</span>
    case 'exit_price':
      return <span className="num">{formatPrice(trade.exit_price)}</span>
    case 'initial_sl':
      return <span className="num">{formatPrice(trade.initial_sl)}</span>
    case 'last_sl':
      return <span className="num">{formatPrice(trade.last_sl)}</span>
    case 'tp':
      return <span className="num">{formatPrice(trade.tp)}</span>
    case 'commission':
      return <span className="num">{formatMoney(trade.commission)}</span>
    case 'swap':
      return <span className="num">{formatMoney(trade.swap)}</span>
    case 'gross_pnl':
      return <span className={cn('num', pnlClass(trade.gross_pnl))}>{formatSignedMoney(trade.gross_pnl)}</span>
    case 'net_pnl':
      return (
        <span className={cn('num font-medium', pnlClass(trade.net_pnl))}>
          {formatSignedMoney(trade.net_pnl)}
        </span>
      )
    case 'pnl_pct':
      return <span className={cn('num', pnlClass(trade.pnl_pct))}>{formatPercent(trade.pnl_pct, true)}</span>
    case 'balance_at_open':
      return <span className="num">{formatMoney(trade.balance_at_open)}</span>
    case 'risk_amount':
      return <span className="num">{formatMoney(trade.risk_amount)}</span>
    case 'risk_pct':
      return <span className="num">{formatPercent(trade.risk_pct)}</span>
    case 'r_multiple':
      return <span className={cn('num', pnlClass(trade.r_multiple))}>{formatR(trade.r_multiple)}</span>
    case 'planned_rr':
      return <span className="num">{formatRatio(trade.planned_rr)}</span>
    case 'is_reentry':
      return trade.is_reentry ? <>{uk.trades.yes}</> : <Muted />
    case 'bias_alignment':
    case 'bias_alignment_weekly':
    case 'bias_alignment_monthly':
      return <BiasAlignmentLabel value={trade[column]} />
    case 'position_id':
      return <span className="num">{trade.position_id}</span>
    case 'status':
      return <span className="whitespace-nowrap">{statusLabel(trade.status)}</span>
    case 'violations':
      return <ViolationBadges keys={trade.violations} />
  }
}

/** Rule violations as small badges (red-tinted: a deviation). */
export function ViolationBadges({ keys }: { keys: readonly string[] }) {
  const label = useViolationLabel()
  if (keys.length === 0) return <Muted />
  return (
    <span className="flex flex-wrap gap-1">
      {keys.map((key) => (
        <span
          key={key}
          title={key}
          className="rounded border border-loss/30 bg-loss/10 px-1.5 py-px text-xs whitespace-nowrap text-loss"
        >
          {label(key)}
        </span>
      ))}
    </span>
  )
}
