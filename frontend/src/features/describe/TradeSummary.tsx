import { Link } from 'react-router'
import { BiasAlignmentLabel } from '@/features/trades/BiasAlignmentLabel'
import { Row, Section, ViolationList } from '@/features/trades/DetailParts'
import {
  directionLabel,
  formatDuration,
  formatPercent,
  formatPrice,
  formatR,
  formatRatio,
  formatSignedMoney,
  formatVolume,
  pnlClass,
  sessionLabel,
  statusLabel,
} from '@/features/trades/format'
import type { TradeDetail } from '@/features/trades/types'
import { uk } from '@/i18n/uk'
import { formatDateTimeBrussels } from '@/lib/time'
import { cn } from '@/lib/utils'

const c = uk.trades.columns
const s = uk.describe.summary
const EMPTY = uk.common.empty

/** Left column: auto data from MT5 (read-only), times in Europe/Brussels. */
export function TradeSummary({ trade }: { trade: TradeDetail }) {
  return (
    <aside className="flex flex-col gap-4 rounded-lg border bg-card/40 p-4" aria-label={s.label}>
      <div className="flex flex-col gap-0.5">
        <p className="flex items-baseline gap-2">
          <span className="num text-base font-semibold">{trade.symbol}</span>
          <span className="text-sm">{directionLabel(trade.direction)}</span>
          <span className={cn('num ml-auto text-base font-semibold', pnlClass(trade.net_pnl))}>
            {formatSignedMoney(trade.net_pnl)}
          </span>
        </p>
        <p className="text-xs text-muted-foreground">
          {trade.account_name}
          {' · '}
          {statusLabel(trade.status)}
        </p>
      </div>

      <Section title={s.time}>
        <Row label={c.open_time}>
          <span className="num">{formatDateTimeBrussels(trade.open_time)}</span>
        </Row>
        <Row label={c.close_time}>
          <span className="num">{trade.close_time ? formatDateTimeBrussels(trade.close_time) : EMPTY}</span>
        </Row>
        <Row label={c.duration}>
          <span className="num">{formatDuration(trade.duration_seconds)}</span>
        </Row>
        <Row label={c.session}>{sessionLabel(trade.session)}</Row>
        <Row label={c.is_reentry}>{trade.is_reentry ? uk.trades.yes : uk.trades.no}</Row>
      </Section>

      <Section title={s.prices}>
        <Row label={c.volume}>
          <span className="num">{formatVolume(trade.volume)}</span>
        </Row>
        <Row label={c.entry_price}>
          <span className="num">{formatPrice(trade.entry_price)}</span>
        </Row>
        <Row label={c.exit_price}>
          <span className="num">{formatPrice(trade.exit_price)}</span>
        </Row>
        <Row label={c.initial_sl}>
          <span className="num">{formatPrice(trade.initial_sl)}</span>
        </Row>
        <Row label={c.tp}>
          <span className="num">{formatPrice(trade.tp)}</span>
        </Row>
      </Section>

      <Section title={s.result}>
        <Row label={c.net_pnl}>
          <span className={cn('num font-medium', pnlClass(trade.net_pnl))}>{formatSignedMoney(trade.net_pnl)}</span>
        </Row>
        <Row label={c.r_multiple}>
          <span className={cn('num', pnlClass(trade.r_multiple))}>{formatR(trade.r_multiple)}</span>
        </Row>
        <Row label={c.risk_pct}>
          <span className="num">{formatPercent(trade.risk_pct)}</span>
        </Row>
        <Row label={c.planned_rr}>
          <span className="num">{formatRatio(trade.planned_rr)}</span>
        </Row>
      </Section>

      <Section title={s.violations}>
        <ViolationList trade={trade} />
      </Section>

      <Section title={uk.bias.alignment.title}>
        {(['daily', 'weekly', 'monthly'] as const).map((period) => {
          const key = period === 'daily' ? 'bias_alignment' : `bias_alignment_${period}` as const
          const noteId = trade.bias_note_ids[period]
          return (
            <Row key={period} label={c[key]}>
              <span className="inline-flex flex-wrap items-baseline justify-end gap-x-2 gap-y-1">
                <BiasAlignmentLabel value={trade[key]} />
                {noteId !== null && (
                  <Link to={`/bias/${noteId}`} className="text-xs underline underline-offset-2 hover:text-primary">
                    {uk.bias.alignment.openNote}
                  </Link>
                )}
              </span>
            </Row>
          )
        })}
      </Section>

      <p className="text-[11px] text-muted-foreground">{uk.tradeDetail.timeZoneNote}</p>
    </aside>
  )
}
