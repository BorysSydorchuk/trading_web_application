import { Link } from 'react-router'
import { formatR, formatSignedMoney, pnlClass } from '@/features/trades/format'
import { describePath } from '@/features/trades/links'
import { uk } from '@/i18n/uk'
import { formatShortDateTimeBrussels } from '@/lib/time'
import { cn } from '@/lib/utils'
import { deviationClass, formatMetric, formatNorm } from './format'
import { METRIC_NAMES, type MetricBlock, type MetricName, type MetricValue, type TradeRef } from './types'

const b = uk.digests.blocks
const TD = 'px-3 py-1 whitespace-nowrap'

interface MetricBlockCardProps {
  title: string
  block: MetricBlock
  /** Snapshot currency, shown next to the money metric labels. */
  currency: string | null
  /** Journal link to this block's trades without R (shown when «Сума R» covers fewer trades). */
  missingRHref?: string
}

const MONEY_LABELS: ReadonlySet<MetricName> = new Set(['net_pnl', 'max_drawdown'])

/**
 * One metric block (combined or one account) with its own norm (docs/api.md "Norm and deviation"):
 * worse than the norm → red, better → green; «замало історії для норми» without a norm.
 */
export function MetricBlockCard({ title, block, currency, missingRHref }: MetricBlockCardProps) {
  const trades = block.metrics.trades?.value
  return (
    <article aria-label={title} className="flex flex-col gap-2 rounded-lg border p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold">{title}</h3>
        {!block.norm_available && <span className="text-xs text-muted-foreground">{b.normUnavailable}</span>}
      </div>
      <table className="w-full text-sm">
        <thead className="sr-only">
          <tr>
            <th scope="col">{b.metric}</th>
            <th scope="col">{b.value}</th>
            <th scope="col">{b.normColumn}</th>
          </tr>
        </thead>
        <tbody>
          {METRIC_NAMES.map((name) => {
            const metric = block.metrics[name]
            if (!metric) return null
            return (
              <MetricRow
                key={name}
                name={name}
                metric={metric}
                currency={currency}
                trades={typeof trades === 'number' ? trades : null}
                missingRHref={missingRHref}
              />
            )
          })}
        </tbody>
      </table>
      <TradeLine label={b.bestTrade} trade={block.best_trade} />
      <TradeLine label={b.worstTrade} trade={block.worst_trade} />
    </article>
  )
}

interface MetricRowProps {
  name: MetricName
  metric: MetricValue
  currency: string | null
  trades: number | null
  missingRHref?: string
}

function MetricRow({ name, metric, currency, trades, missingRHref }: MetricRowProps) {
  const norm = formatNorm(metric)
  const deviationText = metric.deviation === 'worse' ? b.worse : metric.deviation === 'better' ? b.better : null
  return (
    <tr data-metric={name} data-deviation={metric.deviation ?? undefined} className="border-t first:border-t-0">
      <th scope="row" className={cn(TD, 'pl-0 text-left font-normal text-muted-foreground')}>
        {MONEY_LABELS.has(name) ? uk.digests.withCurrency(b.metrics[name], currency) : b.metrics[name]}
        {name === 'total_r' && metric.n !== undefined && trades !== null && (
          <RCoverage n={metric.n} trades={trades} href={missingRHref} />
        )}
      </th>
      <td className={cn(TD, 'num text-right font-medium', deviationClass(metric.deviation))}>
        {formatMetric(name, metric.value)}
        {deviationText && <span className="sr-only"> ({deviationText})</span>}
      </td>
      <td className={cn(TD, 'num pr-0 text-right text-xs text-muted-foreground')}>{norm}</td>
    </tr>
  )
}

/** «за n/N угод»; a link to the trades without R when some are missing. */
function RCoverage({ n, trades, href }: { n: number; trades: number; href?: string }) {
  const text = b.rOf(n, trades)
  if (n >= trades || !href) return <span className="ml-1 text-xs">({text})</span>
  return (
    <span className="ml-1 text-xs">
      (
      <Link to={href} aria-label={b.rMissingLink(trades - n)} className="underline underline-offset-2 hover:text-foreground">
        {text}
      </Link>
      )
    </span>
  )
}

function TradeLine({ label, trade }: { label: string; trade: TradeRef | null }) {
  if (!trade) return null
  return (
    <p className="flex flex-wrap items-baseline gap-x-2 text-xs">
      <span className="text-muted-foreground">{label}:</span>
      <Link to={describePath(trade.trade_id)} className="font-medium underline underline-offset-2 hover:text-foreground">
        {trade.symbol}
      </Link>
      <span className={cn('num', pnlClass(trade.net_pnl))}>{formatSignedMoney(trade.net_pnl)}</span>
      <span className="num">{formatR(trade.r_multiple)}</span>
      <span className="num text-muted-foreground">{formatShortDateTimeBrussels(trade.close_time)}</span>
    </p>
  )
}
