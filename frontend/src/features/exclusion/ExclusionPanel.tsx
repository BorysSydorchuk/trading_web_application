import { useState } from 'react'
import { Button } from '@/components/ui/button'
import type { TradeDetail } from '@/features/trades/types'
import { uk } from '@/i18n/uk'
import { formatDateTimeBrussels } from '@/lib/time'
import { cn } from '@/lib/utils'
import { ExcludedBadge } from './ExcludedBadge'
import { ExclusionDialog, type ExclusionTarget } from './ExclusionDialog'

const t = uk.exclusion
const NO_HISTORY: TradeDetail['exclusion_history'] = []

/** Describe screen: statistics state of the trade, its history and the exclude / return action. */
export function ExclusionPanel({ trade }: { trade: TradeDetail }) {
  const [target, setTarget] = useState<ExclusionTarget | null>(null)
  const history = trade.exclusion_history ?? NO_HISTORY
  const excluded = trade.excluded_from_stats
  return (
    <section
      aria-label={excluded ? t.panelExcluded : t.panelCounted}
      className={cn(
        'flex flex-wrap items-start gap-x-4 gap-y-2 rounded-lg border px-4 py-3 text-sm',
        excluded && 'border-amber-500/50',
      )}
    >
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        {excluded ? (
          <p className="flex flex-wrap items-center gap-2">
            <ExcludedBadge reason={trade.excluded_reason} />
            <span className="font-medium">{t.panelExcluded}</span>
            {trade.excluded_at && (
              <span className="num text-xs text-muted-foreground">
                {t.since(formatDateTimeBrussels(trade.excluded_at))}
              </span>
            )}
          </p>
        ) : (
          <p className="text-muted-foreground">{t.panelCounted}</p>
        )}
        {excluded && trade.excluded_reason && <p className="break-words">{trade.excluded_reason}</p>}
        {history.length > 0 && (
          <details className="text-xs text-muted-foreground">
            <summary className="cursor-pointer select-none">{t.history}</summary>
            <ul className="mt-1 flex flex-col gap-0.5">
              {history.map((event, index) => (
                <li key={index}>
                  <span className="num">{formatDateTimeBrussels(event.at)}</span>
                  {t.historyTail(t.actions[event.action], event.reason ?? t.noReason)}
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
      <Button type="button" variant="outline" size="sm" onClick={() => setTarget(trade)}>
        {excluded ? t.include : t.exclude}
      </Button>
      <ExclusionDialog trade={target} onClose={() => setTarget(null)} />
    </section>
  )
}
