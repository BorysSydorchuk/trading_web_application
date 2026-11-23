import { uk } from '@/i18n/uk'
import { cn } from '@/lib/utils'
import type { RBucket } from '../types'
import { ChartEmpty } from './ChartEmpty'
import { foldRBuckets } from './rBins'

const c = uk.digests.charts
/** Bars reach this share of the plot, so the count above the tallest bar always fits. */
const MAX_BAR_PCT = 82

/** Trades per R bin: compact, centered, one count above each non-empty bar, R ticks below. */
export function RDistributionChart({ buckets, exactlyMinusOne = 0 }: { buckets: readonly RBucket[]; exactlyMinusOne?: number }) {
  if (buckets.length === 0) return <ChartEmpty title={c.rDistribution} />
  const bins = foldRBuckets(buckets, exactlyMinusOne)
  const max = Math.max(1, ...bins.map((bin) => bin.count))
  const summary = c.rSummary(bins.map((bin) => c.bucket(bin.label, bin.count)).join('; '))
  return (
    <figure className="m-0 flex flex-col gap-3 rounded-card border border-line bg-card p-4">
      <figcaption className="font-display text-sm font-extrabold text-ink">{c.rDistribution}</figcaption>
      <div role="img" aria-label={summary} className="m-auto grid w-full max-w-md grid-cols-6 gap-2">
        {bins.map((bin) => (
          <div key={bin.key} data-bin={bin.key} title={c.bucket(bin.label, bin.count)} className="flex min-w-0 flex-col items-center gap-1">
            <div className="flex h-40 w-full flex-col items-center justify-end gap-1 border-b border-line">
              {bin.count > 0 && <span className="num text-xs leading-none font-semibold text-ink">{bin.count}</span>}
              {bin.count > 0 && (
                <div
                  data-bar
                  style={{ height: `${(bin.count / max) * MAX_BAR_PCT}%` }}
                  className={cn('w-full max-w-11 rounded-t-md', bin.negative ? 'bg-loss-light' : 'bg-profit-light')}
                />
              )}
            </div>
            <span className="num text-[11px] font-medium whitespace-nowrap text-ink-muted">{bin.label}</span>
          </div>
        ))}
      </div>
    </figure>
  )
}
