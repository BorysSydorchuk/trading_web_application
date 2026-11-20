import type { ColumnKey } from '@/features/journal/columns'
import { Pill } from '@/components/studio/Pill'
import type { Tone } from '@/components/studio/tones'
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
import type { ExcursionStatus, TradeRow, TradeStatus } from './types'
import { useViolationLabel } from './violations'

const EMPTY = uk.common.empty

/** Status pills: neutral/accent only (green/red stay for P&L). Work still to do is accent. */
const STATUS_TONE: Record<TradeStatus, Tone> & Partial<Record<string, Tone>> = {
  open: 'accent',
  needs_sl: 'accent',
  needs_description: 'accent',
  draft: 'neutral',
  complete: 'neutral',
}

function Muted() {
  return <span className="text-muted-foreground">{EMPTY}</span>
}

/** One table cell value for a trade column. Numbers use `num` (tabular monospace). */
export function TradeCell({ trade, column, violationLabel }: {
  trade: TradeRow
  column: ColumnKey
  violationLabel?: (key: string) => string
}) {
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
    case 'mae_r':
    case 'mfe_r':
      return <ExcursionR value={trade[column] ?? null} status={trade.excursion_status ?? null} />
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
      return <Pill tone={STATUS_TONE[trade.status] ?? 'neutral'} className="px-2">{statusLabel(trade.status)}</Pill>
    case 'violations':
      return violationLabel
        ? <LabeledViolationBadges keys={trade.violations} label={violationLabel} />
        : <ViolationBadges keys={trade.violations} />
  }
}

/**
 * Rule violations as small named badges (red-tinted: a deviation), e.g. «Потрібен опис». The
 * Journal passes `violationLabel` and gets the compact count pill instead (M8-10c, PM-approved).
 */
export function ViolationBadges({ keys }: { keys: readonly string[] }) {
  const label = useViolationLabel()
  if (keys.length === 0) return <Muted />
  return (
    <span className="inline-flex flex-wrap gap-1" data-testid="violation-names">
      {keys.map((key) => (
        <Pill key={key} tone="loss" title={key}>
          {label(key)}
        </Pill>
      ))}
    </span>
  )
}

/** Screen readers pause between the rule names (M8-10c count pill). */
const LIST_SEPARATOR = ', '

function LabeledViolationBadges({ keys, label }: {
  keys: readonly string[]
  label: (key: string) => string
}) {
  if (keys.length === 0) return <Muted />
  const labels = keys.map(label)
  // M8-10c: one compact count pill per row so the default columns fit at 1440 px and the row keeps
  // its height; the rule names show on hover (title), in the trade details and to screen readers.
  return (
    <span className="inline-flex">
      <Pill tone="loss" mono aria-hidden title={labels.join(', ')}>
        {keys.length}
      </Pill>
      {labels.map((text, index) => (
        <span key={keys[index]} className="sr-only">
          {index > 0 && <span>{LIST_SEPARATOR}</span>}
          <span>{text}</span>
        </span>
      ))}
    </span>
  )
}

/** M8-16 «MAE, R» / «MFE, R»: «поточні» for an open trade, a note when MT5 had no history. */
export function ExcursionR({ value, status }: { value: string | null; status: ExcursionStatus | null }) {
  if (status === 'unavailable') return <span className="text-xs text-muted-foreground">{uk.trades.excursion.unavailable}</span>
  if (value === null) return <Muted />
  return (
    <span className="num">
      {formatR(value)}
      {status === 'running' && <span className="ml-1 text-xs text-muted-foreground">{uk.trades.excursion.running}</span>}
    </span>
  )
}
