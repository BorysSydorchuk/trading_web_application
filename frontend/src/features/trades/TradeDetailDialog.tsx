import { useState, type ReactNode } from 'react'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { uk } from '@/i18n/uk'
import { errorText } from '@/lib/errors'
import { formatDateTimeBrussels } from '@/lib/time'
import { cn } from '@/lib/utils'
import { useTrade } from './api'
import {
  dealReasonLabel,
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
  slSourceLabel,
  statusLabel,
  violationSourceLabel,
  weekdayLabel,
} from './format'
import type { TradeDetail } from './types'
import { useViolationLabel } from './violations'

const d = uk.tradeDetail
const c = uk.trades.columns
const EMPTY = uk.common.empty

interface TradeDetailDialogProps {
  tradeId: number | null
  onClose: () => void
}

/** Read-only trade view: all auto fields, exit deals, violations (journal form comes in M2). */
export function TradeDetailDialog({ tradeId, onClose }: TradeDetailDialogProps) {
  // Keep the last id while the dialog animates out, so the content does not flash to "loading".
  const [shownId, setShownId] = useState(tradeId)
  if (tradeId !== null && tradeId !== shownId) setShownId(tradeId)

  return (
    <Dialog open={tradeId !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-3xl">
        <TradeDetailContent id={shownId} />
      </DialogContent>
    </Dialog>
  )
}

function TradeDetailContent({ id }: { id: number | null }) {
  const { data, isPending, isError, error, refetch, isFetching } = useTrade(id)

  if (isPending) {
    return (
      <>
        <DialogHeader>
          <DialogTitle>{d.title}</DialogTitle>
          <DialogDescription>{d.loading}</DialogDescription>
        </DialogHeader>
        <div className="flex h-40 items-center justify-center">
          <Loader2 className="size-5 animate-spin text-muted-foreground" aria-hidden />
        </div>
      </>
    )
  }
  if (isError) {
    return (
      <>
        <DialogHeader>
          <DialogTitle>{d.title}</DialogTitle>
          <DialogDescription>{d.loadError}</DialogDescription>
        </DialogHeader>
        <div role="alert" className="flex flex-col items-start gap-3">
          <p className="text-xs text-muted-foreground">{errorText(error)}</p>
          <Button variant="outline" size="sm" onClick={() => void refetch()} disabled={isFetching}>
            {uk.common.retry}
          </Button>
        </div>
      </>
    )
  }
  return <TradeDetailBody trade={data} />
}

function TradeDetailBody({ trade }: { trade: TradeDetail }) {
  return (
    <>
      <DialogHeader>
        <DialogTitle className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="num">{trade.symbol}</span>
          <span className="text-sm font-normal text-muted-foreground">
            {directionLabel(trade.direction)}
            {' · '}
            {trade.account_name}
            {' · '}
            {statusLabel(trade.status)}
          </span>
        </DialogTitle>
        <DialogDescription>{d.timeZoneNote}</DialogDescription>
      </DialogHeader>

      <div className="grid gap-x-8 gap-y-4 sm:grid-cols-2">
        <Section title={d.sections.main}>
          <Row label={c.account}>{trade.account_name}</Row>
          <Row label={c.position_id}>
            <span className="num">{trade.position_id}</span>
          </Row>
          <Row label={c.session}>{sessionLabel(trade.session)}</Row>
          <Row label={c.weekday}>{weekdayLabel(trade.weekday)}</Row>
          <Row label={c.hour}>
            <span className="num">{trade.hour ?? EMPTY}</span>
          </Row>
          <Row label={c.is_reentry}>{trade.is_reentry ? uk.trades.yes : uk.trades.no}</Row>
        </Section>

        <Section title={d.sections.time}>
          <Row label={c.open_time}>
            <span className="num">{formatDateTimeBrussels(trade.open_time)}</span>
          </Row>
          <Row label={c.close_time}>
            <span className="num">{trade.close_time ? formatDateTimeBrussels(trade.close_time) : EMPTY}</span>
          </Row>
          <Row label={c.duration}>
            <span className="num">{formatDuration(trade.duration_seconds)}</span>
          </Row>
        </Section>

        <Section title={d.sections.prices}>
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
            {trade.initial_sl_source && (
              <span className="ml-2 text-xs text-muted-foreground">
                {d.slSourceLabel}
                {': '}
                {slSourceLabel(trade.initial_sl_source)}
              </span>
            )}
          </Row>
          <Row label={c.last_sl}>
            <span className="num">{formatPrice(trade.last_sl)}</span>
          </Row>
          <Row label={c.tp}>
            <span className="num">{formatPrice(trade.tp)}</span>
          </Row>
        </Section>

        <Section title={d.sections.result}>
          <Row label={c.gross_pnl}>
            <span className={cn('num', pnlClass(trade.gross_pnl))}>{formatSignedMoney(trade.gross_pnl)}</span>
          </Row>
          <Row label={c.commission}>
            <span className="num">{formatMoney(trade.commission)}</span>
          </Row>
          <Row label={c.swap}>
            <span className="num">{formatMoney(trade.swap)}</span>
          </Row>
          <Row label={c.net_pnl}>
            <span className={cn('num font-medium', pnlClass(trade.net_pnl))}>
              {formatSignedMoney(trade.net_pnl)}
            </span>
          </Row>
          <Row label={c.pnl_pct}>
            <span className={cn('num', pnlClass(trade.pnl_pct))}>{formatPercent(trade.pnl_pct, true)}</span>
          </Row>
          <Row label={c.balance_at_open}>
            <span className="num">{formatMoney(trade.balance_at_open)}</span>
          </Row>
          <Row label={c.risk_amount}>
            <span className="num">{formatMoney(trade.risk_amount)}</span>
          </Row>
          <Row label={c.risk_pct}>
            <span className="num">{formatPercent(trade.risk_pct)}</span>
          </Row>
          <Row label={c.r_multiple}>
            <span className={cn('num', pnlClass(trade.r_multiple))}>{formatR(trade.r_multiple)}</span>
          </Row>
          <Row label={c.planned_rr}>
            <span className="num">{formatRatio(trade.planned_rr)}</span>
          </Row>
        </Section>
      </div>

      <Section title={d.sections.exitDeals}>
        <ExitDealsTable trade={trade} />
      </Section>

      <Section title={d.sections.violations}>
        <ViolationList trade={trade} />
      </Section>

      <p className="text-xs text-muted-foreground">{d.journalLater}</p>
    </>
  )
}

function ExitDealsTable({ trade }: { trade: TradeDetail }) {
  if (trade.exit_deals.length === 0) {
    return <p className="text-xs text-muted-foreground">{d.noDeals}</p>
  }
  const h = d.deals
  return (
    <div className="overflow-x-auto rounded-md border">
      <table className="w-full text-xs">
        <thead className="bg-muted/40 text-muted-foreground">
          <tr className="[&>th]:px-2 [&>th]:py-1.5 [&>th]:font-medium [&>th]:whitespace-nowrap">
            <th className="text-right">{h.ticket}</th>
            <th className="text-left">{h.time}</th>
            <th className="text-right">{h.price}</th>
            <th className="text-right">{h.volume}</th>
            <th className="text-right">{h.profit}</th>
            <th className="text-right">{h.commission}</th>
            <th className="text-right">{h.swap}</th>
            <th className="text-left">{h.reason}</th>
          </tr>
        </thead>
        <tbody>
          {trade.exit_deals.map((deal) => (
            <tr key={deal.ticket} className="border-t [&>td]:px-2 [&>td]:py-1.5 [&>td]:whitespace-nowrap">
              <td className="num text-right">{deal.ticket}</td>
              <td className="num">{formatDateTimeBrussels(deal.time)}</td>
              <td className="num text-right">{formatPrice(deal.price)}</td>
              <td className="num text-right">{formatVolume(deal.volume)}</td>
              <td className={cn('num text-right', pnlClass(deal.profit))}>{formatSignedMoney(deal.profit)}</td>
              <td className="num text-right">{formatMoney(deal.commission)}</td>
              <td className="num text-right">{formatMoney(deal.swap)}</td>
              <td>{dealReasonLabel(deal.reason)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ViolationList({ trade }: { trade: TradeDetail }) {
  const label = useViolationLabel()
  if (trade.rule_violations.length === 0) {
    return <p className="text-xs text-muted-foreground">{d.noViolations}</p>
  }
  return (
    <ul className="flex flex-col gap-1.5">
      {trade.rule_violations.map((v) => (
        <li key={`${v.rule_key}-${v.source}`} className="flex flex-wrap items-baseline gap-2 text-sm">
          <span className="rounded border border-loss/30 bg-loss/10 px-1.5 py-px text-xs text-loss">
            {label(v.rule_key)}
          </span>
          <span className="text-xs text-muted-foreground">{violationSourceLabel(v.source)}</span>
          {v.details && <span className="text-xs text-muted-foreground">{v.details}</span>}
        </li>
      ))}
    </ul>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-1.5">
      <h3 className="text-xs font-semibold tracking-wide uppercase">{title}</h3>
      <dl className="flex flex-col">{children}</dl>
    </section>
  )
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-border/50 py-1 text-sm last:border-b-0">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-right">{children}</dd>
    </div>
  )
}
