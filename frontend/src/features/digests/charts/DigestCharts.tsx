import { uk } from '@/i18n/uk'
import type { DigestSnapshot } from '../types'
import { EquityChart } from './EquityChart'
import { HourHeatmap } from './HourHeatmap'
import { RDistributionChart } from './RDistributionChart'

const c = uk.digests.charts

/** Equity per account and combined, R distribution, hour heatmap. */
export function DigestCharts({ snapshot }: { snapshot: DigestSnapshot }) {
  const { charts } = snapshot
  const names = new Map(snapshot.by_account.map((block) => [block.account_id, block.account_name]))
  const perAccount = charts.equity.by_account
  return (
    <section aria-labelledby="digest-charts" className="flex flex-col gap-3">
      <h2 id="digest-charts" className="text-sm font-semibold">{c.title}</h2>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        <EquityChart title={c.equityOf(c.equityCombined)} points={charts.equity.combined} currency={snapshot.currency} />
        {perAccount.length > 1 &&
          perAccount.map((curve) => (
            <EquityChart
              key={curve.account_id}
              title={c.equityOf(names.get(curve.account_id) ?? String(curve.account_id))}
              points={curve.points}
              currency={snapshot.currency}
            />
          ))}
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        <RDistributionChart buckets={charts.r_distribution} />
        <HourHeatmap cells={charts.hour_heatmap} />
      </div>
    </section>
  )
}
