import { formatPercent, formatR } from '@/features/trades/format'
import { uk } from '@/i18n/uk'
import type { ExcursionsBlock } from './types'

const t = uk.digests.excursions

/** M8-16 digest block: how far winners and losers went in my favour (final MFE only). */
export function ExcursionsCard({ block }: { block: ExcursionsBlock }) {
  const empty = block.n_winners === 0 && block.n_losers === 0
  return (
    <section aria-labelledby="digest-excursions" className="flex flex-col gap-2 rounded-card border border-line bg-card p-5">
      <h2 id="digest-excursions" className="type-card-title m-0 text-ink">
        {t.title}
      </h2>
      {empty ? (
        <p className="text-sm text-ink-muted">{t.empty}</p>
      ) : (
        <dl className="grid w-fit grid-cols-[auto_auto] gap-x-8 gap-y-1 text-sm">
          <dt className="text-ink-muted">{t.winners(block.n_winners)}</dt>
          <dd className="num text-right font-medium">{formatR(block.winners_avg_mfe_r)}</dd>
          <dt className="text-ink-muted">{t.losers(block.n_losers)}</dt>
          <dd className="num text-right font-medium">{formatR(block.losers_avg_mfe_r)}</dd>
          <dt className="text-ink-muted">{t.reached}</dt>
          <dd className="num text-right font-medium">
            {block.losers_reached_1r}
            {block.losers_reached_1r_share !== null && ` (${formatPercent(block.losers_reached_1r_share)})`}
          </dd>
        </dl>
      )}
      <p className="text-xs text-ink-muted">{t.hint}</p>
    </section>
  )
}
