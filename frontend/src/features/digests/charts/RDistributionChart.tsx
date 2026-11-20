import { uk } from '@/i18n/uk'
import { decimalSign } from '@/lib/decimal'
import { rBucketLabel } from '../format'
import type { RBucket } from '../types'
import { ChartEmpty } from './ChartEmpty'

const c = uk.digests.charts
const BAR = 44
const GAP = 6
const PLOT = 100
const LABEL = 16
const TOP = 14

/** Trades per 0.5 R bucket; the edge buckets fold everything beyond ±3 R («≤ −2.5» / «≥ 3»). */
export function RDistributionChart({ buckets }: { buckets: readonly RBucket[] }) {
  if (buckets.length === 0) return <ChartEmpty title={c.rDistribution} />
  const max = Math.max(1, ...buckets.map((b) => b.count))
  const width = buckets.length * (BAR + GAP) + GAP
  const height = TOP + PLOT + LABEL
  const summary = c.rSummary(buckets.map((b) => c.bucket(rBucketLabel(b), b.count)).join('; '))
  return (
    <figure className="flex flex-col gap-2 rounded-card border border-line bg-card p-4">
      <figcaption className="font-display text-sm font-extrabold text-ink">{c.rDistribution}</figcaption>
      <svg role="img" aria-label={summary} viewBox={`0 0 ${width} ${height}`} className="h-40 w-full">
        {buckets.map((bucket, i) => {
          const label = rBucketLabel(bucket)
          const h = (bucket.count / max) * PLOT
          const x = GAP + i * (BAR + GAP)
          const negative = decimalSign(bucket.lower) < 0
          return (
            <g key={bucket.lower} data-bucket={label}>
              <title>{c.bucket(label, bucket.count)}</title>
              <rect x={x} y={TOP + PLOT - h} width={BAR} height={h} rx={3} className={negative ? 'fill-loss-strong' : 'fill-profit-strong'} />
              <text x={x + BAR / 2} y={TOP + PLOT - h - 3} textAnchor="middle" className="num fill-ink text-[10px] font-semibold">
                {bucket.count}
              </text>
              <text x={x + BAR / 2} y={height - 4} textAnchor="middle" className="num fill-ink-muted text-[9px] font-medium">
                {label}
              </text>
            </g>
          )
        })}
      </svg>
    </figure>
  )
}
