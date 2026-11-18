import { formatPercent, formatR } from '@/features/trades/format'
import { uk } from '@/i18n/uk'
import type { ExcursionsBlock } from './types'

const t = uk.digests.excursions

/** M8-16 digest block: how far winners and losers went in my favour (final MFE only). */
export function ExcursionsCard({ block }: { block: ExcursionsBlock }) {
  const empty = block.n_winners === 0 && block.n_losers === 0
  return (
    <section aria-labelledby="digest-excursions" className="flex flex-col gap-2 rounded-lg border p-4">
      <h2 id="digest-excursions" className="text-sm font-semibold">
        {t.title}
      </h2>
      {empty ? (
        <p className="text-sm text-muted-foreground">{t.empty}</p>
      ) : (
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          <dt className="text-muted-foreground">{t.winners(block.n_winners)}</dt>
          <dd className="num">{formatR(block.winners_avg_mfe_r)}</dd>
          <dt className="text-muted-foreground">{t.losers(block.n_losers)}</dt>
          <dd className="num">{formatR(block.losers_avg_mfe_r)}</dd>
          <dt className="text-muted-foreground">{t.reached}</dt>
          <dd className="num">
            {block.losers_reached_1r}
            {block.losers_reached_1r_share !== null && ` (${formatPercent(block.losers_reached_1r_share)})`}
          </dd>
        </dl>
      )}
      <p className="text-xs text-muted-foreground">{t.hint}</p>
    </section>
  )
}
